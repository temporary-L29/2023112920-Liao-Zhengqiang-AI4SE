"""
实验一：构建数据集 — 流水线编排器
按依赖顺序串联全部步骤，支持分步执行。

Usage:
    python run_all.py                 # 完整流水线
    python run_all.py --collect       # 仅采集数据
    python run_all.py --extract       # 仅提取特征
    python run_all.py --analyze       # 仅分析
    python run_all.py --visualize     # 仅可视化
    python run_all.py --from-extract  # 跳过采集，从提取开始
"""

import sys
import time

import config
from utils import log


def step_collect():
    """步骤 1：数据采集。"""
    log.info("=" * 50)
    log.info("步骤 1/4: 数据采集")
    log.info("=" * 50)
    if not config.validate_token():
        log.error("缺少 GitHub Token，无法进行数据采集。")
        return False
    from collector import PRCollector
    collector = PRCollector()
    collector.collect_all()
    return True


def step_extract():
    """步骤 2：特征提取。"""
    log.info("=" * 50)
    log.info("步骤 2/4: 特征提取")
    log.info("=" * 50)
    from feature_extractor import FeatureExtractor
    extractor = FeatureExtractor()
    extractor.extract_all()
    return True


def step_analyze():
    """步骤 3：统计分析。"""
    log.info("=" * 50)
    log.info("步骤 3/4: 统计分析")
    log.info("=" * 50)
    from analyzer import Analyzer
    analyzer = Analyzer()
    analyzer.load()
    analyzer.generate_report()
    return True


def step_visualize():
    """步骤 4：可视化。"""
    log.info("=" * 50)
    log.info("步骤 4/4: 可视化")
    log.info("=" * 50)
    from visualizer import Visualizer
    viz = Visualizer()
    viz.generate_all()
    return True


def run_full():
    """完整流水线。"""
    start = time.time()
    log.info("实验一：构建数据集 — 流水线开始")

    steps = [
        ("数据采集", step_collect),
        ("特征提取", step_extract),
        ("统计分析", step_analyze),
        ("可视化", step_visualize),
    ]

    for name, func in steps:
        step_start = time.time()
        try:
            success = func()
            elapsed = time.time() - step_start
            if success:
                log.info(f"[{name}] 完成，耗时 {elapsed:.1f} 秒")
            else:
                log.error(f"[{name}] 失败")
        except Exception as e:
            log.error(f"[{name}] 异常: {e}", exc_info=True)

    total = time.time() - start
    log.info(f"流水线全部完成，总耗时 {total:.1f} 秒 ({total/60:.1f} 分钟)")

    # 打印产物清单
    log.info("\n产出物清单:")
    for p in [
        config.RAW_DATA_DIR,
        config.PROCESSED_DATA_DIR,
        config.FIGURES_DIR,
    ]:
        log.info(f"  {p}")
        for f in sorted(p.glob("*")):
            if f.is_file():
                size_kb = f.stat().st_size / 1024
                log.info(f"    {f.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        run_full()
    elif "--collect" in args:
        step_collect()
    elif "--extract" in args:
        step_extract()
    elif "--analyze" in args:
        step_analyze()
    elif "--visualize" in args:
        step_visualize()
    elif "--from-extract" in args:
        for func in [step_extract, step_analyze, step_visualize]:
            try:
                func()
            except Exception as e:
                log.error(f"步骤失败: {e}")
    else:
        print(__doc__)
