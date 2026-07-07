"""
实验三：基于大语言模型的人类编写代码代码审查 — 主入口
用法：
  python src/run_all.py --prepare       # 准备数据（抽样+上下文+prompt）
  python src/run_all.py --dry-run       # Dry-run 检查
  python src/run_all.py --run-llm       # 调用 LLM API（需设置 LLM_API_KEY）
  python src/run_all.py --run-llm --limit 3  # Smoke test
  python src/run_all.py --evaluate      # 计算指标
  python src/run_all.py --visualize     # 生成图表
  python src/run_all.py --report        # 生成报告
  python src/run_all.py --all           # 完整流程（除 API 调用外）
"""
import sys
import argparse
from pathlib import Path

# 确保 src 目录在 Python 路径中
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import (
    EXPERIMENT3_DIR, PROCESSED_DIR, RESPONSES_DIR,
    EVALUATION_DIR, FIGURES_DIR,
)
from utils import log, setup_logger, read_json, write_json


def cmd_prepare():
    """准备数据：抽样 + 上下文构建 + 生成任务列表。"""
    import pandas as pd
    from sampler import run as run_sampler
    from context_builder import build_all_contexts

    log.info("=" * 60)
    log.info("PREPARE: 数据准备")
    log.info("=" * 60)

    # 1. 抽样
    sample_df, few_shot_examples = run_sampler()

    # 2. 构建上下文
    log.info("\n构建上下文...")
    contexts = build_all_contexts(sample_df)

    # 保存上下文（方便后续复用）
    # 注意：上下文可能很大，使用紧凑格式
    contexts_serializable = {
        str(pr_id): ctx_dict
        for pr_id, ctx_dict in contexts.items()
    }
    contexts_path = PROCESSED_DIR / "all_contexts.json"
    write_json(contexts_serializable, contexts_path)
    log.info(f"上下文已保存: {contexts_path}")

    log.info("\nPREPARE 完成！")
    log.info(f"  样本: {PROCESSED_DIR / 'llm_sample_50.csv'}")
    log.info(f"  Few-shot 示例: {PROCESSED_DIR / 'few_shot_examples.json'}")
    log.info(f"  上下文: {contexts_path}")


def cmd_dry_run():
    """Dry-run：检查数据质量。"""
    import pandas as pd
    from sampler import run as run_sampler
    from context_builder import build_all_contexts
    from api_caller import build_task_list

    log.info("=" * 60)
    log.info("DRY RUN: 数据质量检查")
    log.info("=" * 60)

    # 1. 抽样
    sample_df, few_shot_examples = run_sampler()

    # 检查
    errors = []
    if len(sample_df) != 50:
        errors.append(f"样本数不是 50, 实际 {len(sample_df)}")
    for repo in sample_df["repo"].unique():
        count = (sample_df["repo"] == repo).sum()
        if count != 10:
            errors.append(f"{repo}: {count} 条 (期望 10 条)")

    # 检查 review_comments_text 覆盖
    has_text = (
        sample_df["review_comments_text"].notna() &
        (sample_df["review_comments_text"].astype(str).str.strip() != "")
    ).sum()
    log.info(f"有 review text 的样本: {has_text}/50 (需要 ≥ 25)")

    # 2. 构建上下文
    contexts = build_all_contexts(sample_df)

    # 3. 构建任务列表
    tasks = build_task_list(sample_df, few_shot_examples, contexts)
    log.info(f"任务数: {len(tasks)} (期望 800)")

    # 4. 检查每个任务 —— 重点查数据字段名泄露
    # 这些是明确的数据字段名，出现在上下文中一定表示泄露
    forbidden_fields = [
        "is_merged", "merge_status", "review_decision",
        "num_reviewers", "num_review_comments", "num_inline_comments",
        "review_comments_text",
    ]
    # 这些词语可能作为自然语言出现在 PR body/模板中（如 "approved KEP"），
    # 仅作为 data-field 模式（后跟冒号或等号）时才标记
    suspicious_patterns = [
        "review_decision:", "review_decision=",
        "num_reviewers:", "num_reviewers=",
        "num_review_comments:", "num_review_comments=",
        "merge_status:", "merge_status=",
    ]

    for task in tasks:
        ctx = task.get("context_text", "")
        ctx_lower = ctx.lower()

        is_ok = True
        for field in forbidden_fields:
            if field in ctx_lower:
                errors.append(
                    f"pr_id={task['pr_id']}, {task['prompt_type']}/"
                    f"{task['context_type']}: 上下文发现数据字段 '{field}'"
                )
                is_ok = False

        for pattern in suspicious_patterns:
            if pattern in ctx_lower:
                errors.append(
                    f"pr_id={task['pr_id']}, {task['prompt_type']}/"
                    f"{task['context_type']}: 上下文发现可疑模式 '{pattern}'"
                )
                is_ok = False

    # 报告
    log.info(f"\n检查结果: {len(errors)} 个错误")
    for e in errors:
        log.error(f"  [FAIL] {e}")

    if not errors:
        log.info("  [OK] 所有检查通过！未发现数据泄露。")

    log.info("\nDRY RUN 完成！")


def cmd_run_llm(limit: int = None):
    """调用 LLM API。"""
    import pandas as pd
    from api_caller import run as run_api

    # 加载准备好的数据
    sample_path = PROCESSED_DIR / "llm_sample_50.csv"
    if not sample_path.exists():
        log.error("请先运行 --prepare 准备数据")
        return

    sample_df = pd.read_csv(sample_path)
    few_shot = read_json(PROCESSED_DIR / "few_shot_examples.json")
    contexts = read_json(PROCESSED_DIR / "all_contexts.json")

    # 转换 pr_id key 类型
    contexts = {int(k): v for k, v in contexts.items()}

    run_api(sample_df, few_shot, contexts, dry_run=False, limit=limit)


def cmd_evaluate():
    """计算评估指标。"""
    from evaluator import run as run_eval

    try:
        pred_df = __import__('pandas').read_csv(
            PROCESSED_DIR.parent / "responses" / "parsed_predictions.csv"
        )
    except Exception:
        pred_df = None

    run_eval(pred_df)


def cmd_visualize():
    """生成图表。"""
    import pandas as pd
    from visualizer import run as run_viz

    sample_df = None
    try:
        sample_df = pd.read_csv(PROCESSED_DIR / "llm_sample_50.csv")
    except FileNotFoundError:
        log.warning("未找到样本文件")

    pred_df = None
    try:
        from config import PARSED_PREDICTIONS_CSV
        pred_df = pd.read_csv(PARSED_PREDICTIONS_CSV)
    except FileNotFoundError:
        log.warning("未找到预测文件")

    run_viz(sample_df, pred_df)


def cmd_report():
    """编译 LaTeX 报告。"""
    import subprocess

    log.info("=" * 60)
    log.info("REPORT: 编译 LaTeX 报告")
    log.info("=" * 60)

    docs_dir = EXPERIMENT3_DIR / "docs"
    tex_file = docs_dir / "main.tex"

    if not tex_file.exists():
        log.error(f"未找到 LaTeX 文件: {tex_file}")
        return

    # 尝试 xelatex（支持中文）
    for compiler in ["xelatex", "pdflatex", "lualatex"]:
        try:
            result = subprocess.run(
                [compiler, "-interaction=nonstopmode", "main.tex"],
                cwd=str(docs_dir),
                capture_output=True, text=True, timeout=60,
            )
            pdf_file = docs_dir / "main.pdf"
            if pdf_file.exists():
                log.info(f"PDF 报告已生成: {pdf_file} ({pdf_file.stat().st_size} bytes)")
                # 也复制到 report 目录
                import shutil
                dest = EXPERIMENT3_DIR / "report" / "experiment3_report.pdf"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(pdf_file, dest)
                log.info(f"已复制到: {dest}")
                return
        except Exception as e:
            log.warning(f"{compiler} 编译失败: {e}")

    log.error("所有 LaTeX 编译器均失败，请手动编译 docs/main.tex")


def main():
    parser = argparse.ArgumentParser(
        description="实验三：LLM 代码审查"
    )
    parser.add_argument("--prepare", action="store_true",
                        help="准备数据（抽样+上下文）")
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry-run 数据质量检查")
    parser.add_argument("--run-llm", action="store_true",
                        help="调用 LLM API（需设置 LLM_API_KEY）")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制 API 调用数量（用于 smoke test）")
    parser.add_argument("--evaluate", action="store_true",
                        help="计算评估指标")
    parser.add_argument("--visualize", action="store_true",
                        help="生成图表")
    parser.add_argument("--report", action="store_true",
                        help="生成 LaTeX 报告")
    parser.add_argument("--all", action="store_true",
                        help="运行完整流程（除 API 调用外）")

    args = parser.parse_args()

    # 设置日志
    log_file = EXPERIMENT3_DIR / "results" / "pipeline.log"
    global log
    log = setup_logger("experiment3", log_file)

    # 如果没有指定任何参数，默认显示帮助
    if not any(vars(args).values()):
        parser.print_help()
        return

    # --all: 运行除 API 调用外的所有步骤
    if args.all:
        args.prepare = True
        args.dry_run = True
        args.evaluate = True
        args.visualize = True
        args.report = True

    if args.prepare:
        cmd_prepare()

    if args.dry_run:
        cmd_dry_run()

    if args.run_llm:
        cmd_run_llm(limit=args.limit)

    if args.evaluate:
        cmd_evaluate()

    if args.visualize:
        cmd_visualize()

    if args.report:
        cmd_report()


if __name__ == "__main__":
    main()
