"""
实验六总调度 — 端到端流水线

命令:
  python run_all.py --prepare          # 构建评估子集
  python run_all.py --build-contexts    # 构建增强上下文
  python run_all.py --dry-run           # 生成任务清单
  python run_all.py --run-llm --suite improved-4x4 --limit 4  # smoke test
  python run_all.py --run-llm --suite improved-4x4  # 主实验 I01-I16
  python run_all.py --run-llm --suite balanced  # M1-M4 on Balanced-120
  python run_all.py --run-llm --suite hard-fp   # Hard-FP
  python run_all.py --run-llm --suite full --allow-full  # Full-343
  python run_all.py --evaluate          # 评估
  python run_all.py --visualize         # 可视化
  python run_all.py --report            # 生成报告
  python run_all.py --all               # 全流程 (不含 API 调用)
"""

import os
import sys
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    logger,
    LLM_API_KEY,
    LLM_MODEL,
    RESULTS_PROCESSED_DIR,
    RESULTS_EVALUATION_DIR,
    FIGURES_DIR,
)


def cmd_prepare():
    """构建评估子集"""
    from sample_builder import prepare_samples
    return prepare_samples()


def cmd_build_contexts():
    """构建增强上下文"""
    from enhanced_context_builder import run_build_contexts
    return run_build_contexts()


def cmd_dry_run():
    """生成任务清单 (不调用 API)"""
    from llm_runner import run_llm_experiment
    return run_llm_experiment(suite="improved-4x4", dry_run=True)


def cmd_run_llm(suite="improved-4x4", limit=0, allow_full=False, methods=None):
    """运行 LLM API 调用"""
    from llm_runner import run_llm_experiment
    return run_llm_experiment(
        suite=suite,
        limit=limit,
        allow_full=allow_full,
        method_ids=methods,
    )


def cmd_evaluate():
    """评估"""
    from evaluator import run_evaluation
    return run_evaluation()


def cmd_visualize():
    """生成图表"""
    from visualizer import generate_all_figures
    generate_all_figures()
    logger.info("可视化完成")
    return True


def cmd_report():
    """生成实验报告摘要"""
    from evaluator import (
        load_json_safe, METRICS_BALANCED, METRICS_HARD_FP,
        COMMENT_QUALITY, BASELINE_COMPARISON, BEST_METHOD_SUMMARY,
    )
    from config import EVAL_SAMPLE_STATS
    from datetime import datetime

    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append("  实验六：改进针对大模型生成代码的代码审查 — 实验报告")
    report_lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("=" * 70)
    report_lines.append("")

    # 样本统计
    stats = load_json_safe(EVAL_SAMPLE_STATS)
    if stats:
        bal = stats.get("balanced_120", {})
        report_lines.append("## 1. 评估样本")
        report_lines.append(f"  Balanced-120: {bal.get('total', '?')} 条 "
                           f"(merged={bal.get('merged', '?')}, unmerged={bal.get('unmerged', '?')})")
        hardfp = stats.get("hard_fp_40", {})
        report_lines.append(f"  Hard-FP-40: {hardfp.get('total', '?')} 条")
        report_lines.append("")

    # 基线
    baseline = stats.get("baseline_balanced", {})
    if baseline:
        report_lines.append("## 2. 实验五基线 (在 Balanced-120 上重算)")
        for key, m in baseline.items():
            report_lines.append(f"  {key}: Acc={m.get('accuracy', 0):.4f}, F1={m.get('f1', 0):.4f}, "
                              f"AUC={m.get('roc_auc', 'N/A')}, "
                              f"Specificity={m.get('specificity', 0):.4f}, "
                              f"FPR={m.get('fpr', 0):.4f}")
        report_lines.append("")

    # 实验六指标
    metrics = load_json_safe(METRICS_BALANCED)
    if metrics:
        report_lines.append("## 3. 实验六方法指标 (Balanced-120)")
        report_lines.append(f"  {'Method':<8} {'Acc':<8} {'F1':<8} {'AUC':<8} {'Spec':<8} {'BalAcc':<8} {'FPR':<8}")
        report_lines.append("  " + "-" * 60)
        for m_id, m in metrics.items():
            report_lines.append(
                f"  {m_id:<8} {m.get('accuracy', 0):.4f}   {m.get('f1', 0):.4f}   "
                f"{str(m.get('roc_auc', 'N/A')):<8} {m.get('specificity', 0):.4f}   "
                f"{m.get('balanced_accuracy', 0):.4f}   {m.get('fpr', 0):.4f}"
            )
        report_lines.append("")

    # 与实验五对比
    comparison = load_json_safe(BASELINE_COMPARISON)
    improvements = comparison.get("improvements", {})
    if improvements:
        report_lines.append("## 4. 与实验五对比 (Δ vs P2_C4)")
        report_lines.append(f"  {'Method':<8} {'ΔAcc':<8} {'ΔF1':<8} {'ΔAUC':<8} {'ΔSpec':<8} {'ΔBalAcc':<8}")
        report_lines.append("  " + "-" * 60)
        for m_id, imp in improvements.items():
            report_lines.append(
                f"  {m_id:<8} {imp.get('delta_accuracy', 0):+.4f}   {imp.get('delta_f1', 0):+.4f}   "
                f"{imp.get('delta_roc_auc', 0):+.4f}   {imp.get('delta_specificity', 0):+.4f}   "
                f"{imp.get('delta_balanced_accuracy', 0):+.4f}"
            )
        report_lines.append("")

    # Hard-FP
    hardfp_metrics = load_json_safe(METRICS_HARD_FP)
    if hardfp_metrics:
        corrections = hardfp_metrics.get("corrections", {})
        if corrections:
            report_lines.append("## 5. Hard-FP 改判率")
            for m_id, c in corrections.items():
                report_lines.append(f"  {m_id}: 改判率={c.get('correction_rate', 0):.1%} "
                                   f"({c.get('correctly_rejected', 0)}/{c.get('unmerged_in_sample', 0)})")
            report_lines.append("")

    # 评论质量
    quality = load_json_safe(COMMENT_QUALITY)
    if quality:
        report_lines.append("## 6. 评论质量")
        for m_id, q in quality.items():
            report_lines.append(f"  {m_id}: RiskCov={q.get('avg_risk_coverage', 0):.3f}, "
                              f"Action={q.get('avg_actionability', 0):.3f}, "
                              f"Spec={q.get('avg_specificity', 0):.3f}, "
                              f"Blocker+Major={q.get('blocker_major_ratio', 0):.1%}")
        report_lines.append("")

    # 最佳方法
    best = load_json_safe(BEST_METHOD_SUMMARY)
    if best.get("overall"):
        report_lines.append("## 7. 最佳方法")
        report_lines.append(f"  Overall Best: {best['overall']}")
        report_lines.append(f"  Best by AUC: {best.get('by_auc', 'N/A')}")
        report_lines.append(f"  Best by Specificity: {best.get('by_specificity', 'N/A')}")
        report_lines.append(f"  Best by Balanced Accuracy: {best.get('by_balanced_acc', 'N/A')}")
        if best.get("scores"):
            report_lines.append("  Scores:")
            for m, s in best["scores"].items():
                report_lines.append(f"    {m}: {s:.4f}")
        report_lines.append("")

    # 成功标准
    report_lines.append("## 8. 成功标准检查")
    success = True
    if improvements:
        any_auc_up = any(imp.get("delta_roc_auc", 0) or 0 > 0 for imp in improvements.values())
        any_spec_up = any(imp.get("delta_specificity", 0) or 0 > 0 for imp in improvements.values())
        any_fpr_down = any(imp.get("delta_fpr", 0) or 0 > 0 for imp in improvements.values())
        f1_ok = all(imp.get("delta_f1", 0) or 0 > -0.15 for imp in improvements.values())

        report_lines.append(f"  {'✅' if any_auc_up else '❌'} ROC-AUC improved")
        report_lines.append(f"  {'✅' if any_spec_up else '❌'} Specificity improved")
        report_lines.append(f"  {'✅' if any_fpr_down else '❌'} FPR decreased")
        report_lines.append(f"  {'✅' if f1_ok else '❌'} F1 no catastrophic drop")

        if not all([any_auc_up, any_spec_up, any_fpr_down, f1_ok]):
            success = False

    report_lines.append("")
    report_lines.append("=" * 70)

    # 保存报告
    report_path = os.path.join(os.path.dirname(RESULTS_EVALUATION_DIR), "experiment_report.txt")
    report_text = "\n".join(report_lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info(f"实验报告已保存: {report_path}")
    print(report_text)

    return success


def main():
    parser = argparse.ArgumentParser(description="实验六：改进代码审查")
    parser.add_argument("--prepare", action="store_true", help="构建评估子集")
    parser.add_argument("--build-contexts", action="store_true", help="构建增强上下文")
    parser.add_argument("--dry-run", action="store_true", help="生成任务清单")
    parser.add_argument("--run-llm", action="store_true", help="调用 LLM API")
    parser.add_argument("--suite", default="improved-4x4",
                        choices=["improved-4x4", "balanced", "hard-fp", "full"],
                        help="评估集 (default: improved-4x4)")
    parser.add_argument("--methods", nargs="+", default=None,
                        help="方法列表 (default: M1 M2 M3 M4)")
    parser.add_argument("--limit", type=int, default=0, help="限制 API 调用次数")
    parser.add_argument("--allow-full", action="store_true",
                        help="确认跑 full-343 (需要显式传入)")
    parser.add_argument("--evaluate", action="store_true", help="评估")
    parser.add_argument("--visualize", action="store_true", help="生成图表")
    parser.add_argument("--report", action="store_true", help="生成报告")
    parser.add_argument("--all", action="store_true",
                        help="全流程 (--prepare --build-contexts --evaluate --visualize --report, "
                             "不自动调用 API)")

    args = parser.parse_args()

    # 全流程 (不含 API)
    if args.all:
        logger.info("=" * 60)
        logger.info("实验六全流程启动 (不含 API 调用)")
        logger.info("=" * 60)
        cmd_prepare()
        cmd_build_contexts()
        cmd_evaluate()
        cmd_visualize()
        cmd_report()
        return

    # 没有参数默认 run all
    if not any([args.prepare, args.build_contexts, args.dry_run,
                args.run_llm, args.evaluate, args.visualize, args.report]):
        logger.info("未指定参数，执行全流程 (--all, 不含 API)")
        cmd_prepare()
        cmd_build_contexts()
        cmd_evaluate()
        cmd_visualize()
        cmd_report()
        return

    # 逐步执行
    if args.prepare:
        cmd_prepare()

    if args.build_contexts:
        cmd_build_contexts()

    if args.dry_run:
        cmd_dry_run()

    if args.run_llm:
        # 设置 API key
        if not LLM_API_KEY:
            logger.warning("=" * 60)
            logger.warning("未设置 DEEPSEEK_API_KEY 环境变量!")
            logger.warning("请先设置: set DEEPSEEK_API_KEY=your-key")
            logger.warning("或在运行前: $env:DEEPSEEK_API_KEY='your-key'")
            logger.warning("=" * 60)
        cmd_run_llm(
            suite=args.suite,
            limit=args.limit,
            allow_full=args.allow_full,
            methods=args.methods,
        )

    if args.evaluate:
        cmd_evaluate()

    if args.visualize:
        cmd_visualize()

    if args.report:
        cmd_report()


if __name__ == "__main__":
    main()
