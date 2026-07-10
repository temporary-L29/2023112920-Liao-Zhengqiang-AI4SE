"""
实验五 - 主入口

命令:
  python src/run_all.py --prepare-seed        构建 seed 数据集
  python src/run_all.py --collect-ai          增强采集 (含多线程)
                  [--max-samples 300]         目标样本数
                  [--no-resume]               禁用断点续跑
  python src/run_all.py --merge-ai-data       合并 seed + enhanced
  python src/run_all.py --data-report         生成数据报告
  python src/run_all.py --all-data            运行全部数据准备阶段
"""

import argparse
import os
import sys
import json
import time
from datetime import datetime, timezone

from config import (
    AI_DATASET_SEED_CSV,
    AI_DATASET_ENHANCED_CSV,
    AI_DATASET_CSV,
    AI_CANDIDATES_JSON,
    AI_COLLECTED_JSON,
    AI_DATASET_STATS_JSON,
    AI_DETECTION_STATS_JSON,
    SEED_DATASET_STATS_JSON,
    TARGET_TOTAL_SAMPLES,
    logger,
)


def print_banner(title: str):
    """打印阶段标题"""
    border = "=" * 70
    logger.info(border)
    logger.info(f"  实验五: {title}")
    logger.info(f"  时间: {datetime.now(timezone.utc).isoformat()}")
    logger.info(border)


def cmd_prepare_seed() -> bool:
    """构建 seed 数据集"""
    print_banner("构建 Seed 数据集")
    from ai_dataset_builder import build_seed_dataset
    return build_seed_dataset()


def cmd_collect_ai(max_samples: int, resume: bool, skip_search: bool = False) -> bool:
    """增强采集"""
    print_banner(f"Enhanced 数据采集 (目标: {max_samples} 样本)")
    logger.info(f"断点续跑: {'启用' if resume else '禁用'}")
    if skip_search:
        logger.info("跳过搜索阶段，使用已有候选列表")
    from ai_data_collector import collect_ai_prs
    return collect_ai_prs(max_samples=max_samples, resume=resume, skip_search=skip_search)


def cmd_merge() -> bool:
    """合并数据集"""
    print_banner("合并数据集")
    from merge_ai_datasets import merge_datasets
    return merge_datasets()


def cmd_data_report() -> bool:
    """生成数据报告"""
    print_banner("数据报告")

    report_parts = []

    # 1. Seed 统计
    if os.path.exists(SEED_DATASET_STATS_JSON):
        with open(SEED_DATASET_STATS_JSON, "r", encoding="utf-8") as f:
            seed_stats = json.load(f)
        report_parts.append("### Seed 数据集")
        report_parts.append(f"- 总样本: {seed_stats.get('total_prs', 'N/A')}")
        report_parts.append(f"- 合并率: {seed_stats.get('merge_rate', 'N/A')}")
        report_parts.append(f"- 评论覆盖: {seed_stats.get('review_coverage', 'N/A')}")
        report_parts.append(f"- Patch 覆盖: {seed_stats.get('patch_coverage', 'N/A')}")
        report_parts.append("")
    else:
        report_parts.append("### Seed 数据集: 未找到\n")
        logger.warning(f"未找到: {SEED_DATASET_STATS_JSON}")

    # 2. 增强采集统计
    if os.path.exists(AI_COLLECTED_JSON):
        with open(AI_COLLECTED_JSON, "r", encoding="utf-8") as f:
            collected = json.load(f)
        report_parts.append("### Enhanced 采集")
        report_parts.append(f"- 采集时间: {collected.get('collected_at', 'N/A')}")
        report_parts.append(f"- 搜索候选: {collected.get('total_candidates', 'N/A')}")
        report_parts.append(f"- 成功采集: {collected.get('total_collected', 'N/A')}")
        report_parts.append(f"- AI检测通过: {collected.get('total_ai_positive', 'N/A')}")
        report_parts.append(f"- 失败: {collected.get('total_failed', 'N/A')}")
        report_parts.append("")
    else:
        report_parts.append("### Enhanced 采集: 未找到 (可能未执行采集)\n")
        logger.info(f"未找到: {AI_COLLECTED_JSON}")

    # 3. 最终数据集统计
    if os.path.exists(AI_DATASET_STATS_JSON):
        with open(AI_DATASET_STATS_JSON, "r", encoding="utf-8") as f:
            final_stats = json.load(f)
        report_parts.append("### 最终数据集")
        report_parts.append(f"- 版本: {final_stats.get('version', 'N/A')}")
        report_parts.append(f"- 总样本数: {final_stats.get('total_prs', 'N/A')}")
        report_parts.append(f"- Seed 样本: {final_stats.get('seed_count', 'N/A')}")
        report_parts.append(f"- 新增样本: {final_stats.get('new_count', 'N/A')}")
        report_parts.append(f"- 合并率: {final_stats.get('merge_rate', 'N/A')}")
        report_parts.append(f"- 评论覆盖: {final_stats.get('review_coverage', 'N/A')}")
        report_parts.append("")

        repo_dist = final_stats.get("repo_distribution", {})
        if repo_dist:
            report_parts.append("#### 仓库分布")
            report_parts.append("| 仓库 | 总计 | Merged | Unmerged | 有评论 |")
            report_parts.append("|------|------|--------|----------|--------|")
            for repo, dist in sorted(repo_dist.items(), key=lambda x: -x[1]["total"]):
                report_parts.append(
                    f"| {repo} | {dist['total']} | {dist['merged']} | "
                    f"{dist['unmerged']} | {dist['has_review']} |"
                )
            report_parts.append("")

        repo_comp = final_stats.get("repo_composition", {})
        if repo_comp:
            report_parts.append("#### Seed vs New 组成")
            report_parts.append("| 仓库 | Seed | New | Total |")
            report_parts.append("|------|------|-----|-------|")
            for repo, comp in sorted(repo_comp.items(), key=lambda x: -x[1]["total"]):
                report_parts.append(
                    f"| {repo} | {comp['seed']} | {comp['new']} | {comp['total']} |"
                )
            report_parts.append("")

    elif os.path.exists(SEED_DATASET_STATS_JSON):
        report_parts.append("### 最终数据集: 未合并，仅 seed 可用\n")
    else:
        report_parts.append("### 最终数据集: 未找到（请先运行 --prepare-seed）\n")

    # 4. 检查文件存在性
    report_parts.append("### 文件状态")
    files_status = {
        "Seed CSV": AI_DATASET_SEED_CSV,
        "Enhanced CSV": AI_DATASET_ENHANCED_CSV,
        "最终 CSV": AI_DATASET_CSV,
        "候选 JSON": AI_CANDIDATES_JSON,
        "采集 JSON": AI_COLLECTED_JSON,
        "数据集统计 JSON": AI_DATASET_STATS_JSON,
        "Seed 统计 JSON": SEED_DATASET_STATS_JSON,
    }
    for name, path in files_status.items():
        status = "✓ 存在" if os.path.exists(path) else "✗ 不存在"
        report_parts.append(f"- {name}: {status}")

    report_text = "\n".join(report_parts)
    logger.info("\n" + report_text)

    # 保存报告
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "results", "evaluation", "data_report.md",
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# 实验五 数据报告\n\n")
        f.write(f"生成时间: {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(report_text)
    logger.info(f"报告已保存: {report_path}")

    return True


# ============================================================
# Part 2: 具体实验
# ============================================================
def cmd_build_features() -> bool:
    """构建特征"""
    print_banner("特征构建")
    from feature_builder import build_ai_features
    return build_ai_features()


def cmd_run_ml() -> bool:
    """传统机器学习实验"""
    print_banner("传统机器学习实验")
    from traditional_ml_runner import run_traditional_ml
    return run_traditional_ml()


def cmd_run_llm(dry_run: bool = False, limit: int = 0) -> bool:
    """LLM 实验"""
    print_banner(f"DeepSeek LLM 实验 {'(dry run)' if dry_run else ''}")
    from llm_runner import run_llm_experiment
    return run_llm_experiment(dry_run=dry_run, limit=limit)


def cmd_run_llm_4x4(dry_run: bool = False, limit: int = 0) -> bool:
    """4×4 Prompt×Context 全组合实验 (2.6.2)"""
    print_banner(f"DeepSeek 4×4 Prompt×Context 全组合 {'(dry run)' if dry_run else ''}")
    from llm_4x4_runner import run_llm_4x4_experiment
    return run_llm_4x4_experiment(dry_run=dry_run, limit=limit)


def cmd_evaluate() -> bool:
    """评估"""
    print_banner("评估与对比")
    from evaluator import run_evaluation
    return run_evaluation()


def cmd_visualize() -> bool:
    """生成图表"""
    print_banner("生成图表")
    from visualizer import generate_all_figures
    generate_all_figures()
    return True


def cmd_all_experiments(args) -> bool:
    """运行全部实验"""
    logger.info("开始运行全部实验...")
    start_time = time.time()

    steps = [
        ("特征构建", cmd_build_features),
        ("传统ML实验", cmd_run_ml),
        ("LLM实验 (dry run)", lambda: cmd_run_llm(dry_run=args.dry_run_llm, limit=args.limit_llm)),
        ("评估与对比", cmd_evaluate),
        ("生成图表", cmd_visualize),
    ]

    for name, fn in steps:
        logger.info(f"\n>>> {name}...")
        try:
            fn()
        except Exception as e:
            logger.error(f"{name} 失败: {e}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - start_time
    logger.info(f"全部实验完成，耗时: {elapsed:.1f}s")
    return True


def cmd_all_data(args) -> bool:
    """运行全部数据准备阶段"""
    logger.info("开始运行全部数据准备阶段...")
    start_time = time.time()

    # Step 1: Seed
    if not cmd_prepare_seed():
        logger.error("Seed 构建失败")
        return False

    # Step 2: Enhanced 采集
    if not cmd_collect_ai(max_samples=args.max_samples, resume=not args.no_resume, skip_search=args.skip_search):
        logger.error("增强采集失败")
        # 继续尝试合并

    # Step 3: 合并
    if not cmd_merge():
        logger.error("合并失败")
        return False

    # Step 4: 报告
    if not cmd_data_report():
        logger.error("报告生成失败")

    elapsed = time.time() - start_time
    logger.info(f"全部数据准备阶段完成，耗时: {elapsed:.1f}s")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="实验五：针对大模型生成代码的代码审查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python src/run_all.py --prepare-seed
  python src/run_all.py --collect-ai --max-samples 300
  python src/run_all.py --merge-ai-data
  python src/run_all.py --data-report
  python src/run_all.py --all-data
        """,
    )

    parser.add_argument(
        "--prepare-seed",
        action="store_true",
        help="构建 seed 数据集（从实验一数据）",
    )
    parser.add_argument(
        "--collect-ai",
        action="store_true",
        help="增强采集 AI 生成代码 PR（需要 GitHub Token）",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=TARGET_TOTAL_SAMPLES,
        help=f"增强采集目标样本数 (默认: {TARGET_TOTAL_SAMPLES})",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="禁用断点续跑（重新开始采集）",
    )
    parser.add_argument(
        "--skip-search",
        action="store_true",
        help="跳过搜索阶段，使用已有候选列表和 checkpoint",
    )
    parser.add_argument(
        "--merge-ai-data",
        action="store_true",
        help="合并 seed 与 enhanced 数据集",
    )
    parser.add_argument(
        "--data-report",
        action="store_true",
        help="生成数据报告",
    )
    parser.add_argument(
        "--all-data",
        action="store_true",
        help="运行全部数据准备阶段 (seed → collect → merge → report)",
    )
    # ---- Part 2: 实验 ----
    parser.add_argument(
        "--build-features",
        action="store_true",
        help="构建 AI PR 特征 (对齐实验二70列)",
    )
    parser.add_argument(
        "--run-ml",
        action="store_true",
        help="运行传统 ML 实验 (SVM/RF 在 AI PR 上预测)",
    )
    parser.add_argument(
        "--run-llm",
        action="store_true",
        help="运行 DeepSeek LLM 实验",
    )
    parser.add_argument(
        "--dry-run-llm",
        action="store_true",
        help="LLM 实验 dry run (仅生成任务列表)",
    )
    parser.add_argument(
        "--limit-llm",
        type=int,
        default=0,
        help="限制 LLM API 调用次数 (0=不限制)",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="运行评估与对比分析",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="生成实验图表 (8张)",
    )
    parser.add_argument(
        "--run-llm-4x4",
        action="store_true",
        help="运行 4×4 Prompt×Context 全组合实验 (2.6.2, 800次API调用)",
    )
    parser.add_argument(
        "--dry-run-llm-4x4",
        action="store_true",
        help="4×4 实验 dry run (仅生成任务列表和上下文统计)",
    )
    parser.add_argument(
        "--limit-llm-4x4",
        type=int,
        default=0,
        help="限制 4×4 LLM API 调用次数 (0=全部800次)",
    )
    parser.add_argument(
        "--all-experiments",
        action="store_true",
        help="运行全部实验 (特征→ML→LLM→评估→图表)",
    )

    args = parser.parse_args()

    # 如果没有指定任何参数，默认显示帮助
    if not any([
        args.prepare_seed,
        args.collect_ai,
        args.merge_ai_data,
        args.data_report,
        args.all_data,
        args.build_features,
        args.run_ml,
        args.run_llm,
        args.dry_run_llm,
        args.run_llm_4x4,
        args.dry_run_llm_4x4,
        args.evaluate,
        args.visualize,
        args.all_experiments,
    ]):
        parser.print_help()
        return

    success = True

    if args.all_data:
        success = cmd_all_data(args)
    elif args.all_experiments:
        success = cmd_all_experiments(args)
    else:
        if args.prepare_seed:
            success = cmd_prepare_seed() and success
        if args.collect_ai:
            success = cmd_collect_ai(args.max_samples, not args.no_resume, args.skip_search) and success
        if args.merge_ai_data:
            success = cmd_merge() and success
        if args.data_report:
            success = cmd_data_report() and success
        # Part 2
        if args.build_features:
            success = cmd_build_features() and success
        if args.run_ml:
            success = cmd_run_ml() and success
        if args.run_llm:
            success = cmd_run_llm(dry_run=args.dry_run_llm, limit=args.limit_llm) and success
        if args.dry_run_llm and not args.run_llm:
            success = cmd_run_llm(dry_run=True, limit=args.limit_llm) and success
        # 4x4 全组合实验
        if args.run_llm_4x4:
            success = cmd_run_llm_4x4(dry_run=args.dry_run_llm_4x4, limit=args.limit_llm_4x4) and success
        if args.dry_run_llm_4x4 and not args.run_llm_4x4:
            success = cmd_run_llm_4x4(dry_run=True, limit=args.limit_llm_4x4) and success
        if args.evaluate:
            success = cmd_evaluate() and success
        if args.visualize:
            success = cmd_visualize() and success

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
