"""
实验二：全流程编排脚本
按顺序执行：数据筛选 → 划分 → patch索引 → AST → CFG → 特征工程 → 训练 → 评估 → 可视化

用法：
    python src/run_all.py                    # 完整流水线
    python src/run_all.py --from-filter      # 跳过前序（重新运行数据筛选及后续）
    python src/run_all.py --from-features    # 从特征工程开始
    python src/run_all.py --train-only       # 仅训练
    python src/run_all.py --eval-only        # 仅评估与可视化
"""
import sys
import time
import argparse
from pathlib import Path

# 确保 src 目录在路径中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PROCESSED_DIR, MODELS_DIR, EVALUATION_DIR, FIGURES_DIR
from utils import log, setup_logger


def run_full_pipeline():
    """执行完整流水线。"""
    log.info("=" * 60)
    log.info("实验二：基于机器学习的人类编写代码代码审查")
    log.info("完整流水线启动")
    log.info("=" * 60)

    t_start = time.time()

    # ---- 步骤一：数据筛选 ----
    log.info("\n" + "=" * 50)
    log.info("步骤一：数据筛选与清洗")
    log.info("=" * 50)
    from data_filter import run as step1
    step1()

    # ---- 步骤二：数据集划分 ----
    log.info("\n" + "=" * 50)
    log.info("步骤二：数据集划分 (train/val/test)")
    log.info("=" * 50)
    from split_dataset import run as step2
    step2()

    # ---- 步骤三：Patch 索引 ----
    log.info("\n" + "=" * 50)
    log.info("步骤三：Patch 抽取与索引")
    log.info("=" * 50)
    from patch_indexer import run as step3
    step3()

    # ---- 步骤四：AST 提取 ----
    log.info("\n" + "=" * 50)
    log.info("步骤四：AST 提取")
    log.info("=" * 50)
    from ast_extractor import run as step4
    step4()

    # ---- 步骤五：CFG 构建 ----
    log.info("\n" + "=" * 50)
    log.info("步骤五：CFG 构建")
    log.info("=" * 50)
    from cfg_extractor import run as step5
    step5()

    # ---- 步骤六：特征工程 ----
    log.info("\n" + "=" * 50)
    log.info("步骤六：特征工程")
    log.info("=" * 50)
    from feature_extractor import build_features as step6
    step6()

    # ---- 步骤七：模型训练 ----
    log.info("\n" + "=" * 50)
    log.info("步骤七：模型训练")
    log.info("=" * 50)
    from model_trainer import run as step7
    step7()

    # ---- 步骤八：模型评估 ----
    log.info("\n" + "=" * 50)
    log.info("步骤八：模型评估")
    log.info("=" * 50)
    from model_evaluator import run as step8
    step8()

    # ---- 步骤九：可视化 ----
    log.info("\n" + "=" * 50)
    log.info("步骤九：可视化")
    log.info("=" * 50)
    from visualizer import run_all as step9
    step9()

    elapsed = time.time() - t_start
    log.info("\n" + "=" * 60)
    log.info(f"全流程完成! 总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    log.info(f"输出目录: {PROCESSED_DIR.parent}")
    log.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="实验二：基于机器学习的人类编写代码代码审查"
    )
    parser.add_argument("--from-filter", action="store_true",
                        help="从数据筛选开始（重新运行步骤1-9）")
    parser.add_argument("--from-features", action="store_true",
                        help="从特征工程开始（重新运行步骤6-9）")
    parser.add_argument("--train-only", action="store_true",
                        help="仅训练模型（步骤7）")
    parser.add_argument("--eval-only", action="store_true",
                        help="仅评估与可视化（步骤8-9）")
    parser.add_argument("--step", type=str, default=None,
                        help="运行指定模块: filter, split, patch, ast, cfg, features, train, eval, visualize")

    args = parser.parse_args()

    # 设置日志
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    global log
    log = setup_logger("experiment2", log_file)

    if args.step:
        # 单步运行
        step_map = {
            "filter": ("data_filter", "run"),
            "split": ("split_dataset", "run"),
            "patch": ("patch_indexer", "run"),
            "ast": ("ast_extractor", "run"),
            "cfg": ("cfg_extractor", "run"),
            "features": ("feature_extractor", "build_features"),
            "train": ("model_trainer", "run"),
            "eval": ("model_evaluator", "run"),
            "visualize": ("visualizer", "run_all"),
        }
        if args.step in step_map:
            mod_name, func_name = step_map[args.step]
            mod = __import__(mod_name, fromlist=[func_name])
            func = getattr(mod, func_name)
            func()
        else:
            log.error(f"未知步骤: {args.step}")
            log.info(f"可用步骤: {list(step_map.keys())}")
        return

    if args.eval_only:
        log.info("仅运行评估与可视化...")
        from model_evaluator import run as step8
        step8()
        from visualizer import run_all as step9
        step9()
        return

    if args.train_only:
        log.info("仅运行模型训练...")
        from model_trainer import run as step7
        step7()
        return

    if args.from_features:
        log.info("从特征工程开始...")
        from feature_extractor import build_features
        from model_trainer import run as train_models
        from model_evaluator import run as eval_models
        from visualizer import run_all as visualize

        build_features()
        train_models()
        eval_models()
        visualize()
        return

    if args.from_filter:
        log.info("从数据筛选开始...")
        from data_filter import run as f1
        from split_dataset import run as f2
        from patch_indexer import run as f3
        from ast_extractor import run as f4
        from cfg_extractor import run as f5
        from feature_extractor import build_features
        from model_trainer import run as train_models
        from model_evaluator import run as eval_models
        from visualizer import run_all as visualize

        f1(); f2(); f3(); f4(); f5()
        build_features()
        train_models()
        eval_models()
        visualize()
        return

    # 默认：完整流水线
    run_full_pipeline()


if __name__ == "__main__":
    main()
