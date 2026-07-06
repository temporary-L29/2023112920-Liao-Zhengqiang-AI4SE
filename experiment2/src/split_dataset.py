"""
实验二 步骤二：数据集划分 (train/val/test)
按 repo + is_merged 分层划分 70/15/15，输出 splits.csv
"""
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split

from config import PROCESSED_DIR, RANDOM_SEED, TRAIN_RATIO, VAL_RATIO, TEST_RATIO
from utils import log, write_json


def load_human_dataset(path: Path) -> pd.DataFrame:
    """加载步骤一输出的人类代码数据集。"""
    log.info(f"加载人类代码数据集: {path}")
    df = pd.read_csv(path)
    df["is_merged"] = df["is_merged"].astype(bool)
    log.info(f"加载完成: {len(df)} 条记录")
    return df


def build_stratify_key(df: pd.DataFrame) -> np.ndarray:
    """
    构建分层键：repo + _ + is_merged。

    如果某个分层桶的样本数 < 3，则退化为仅按 is_merged 分层，
    并在该桶使用 repo 分层。
    """
    stratify_cols = ["repo", "is_merged"]
    df = df.copy()
    strat_key = df["repo"].astype(str) + "_" + df["is_merged"].astype(str)

    # 检查每个桶的大小
    bucket_counts = strat_key.value_counts()
    small_buckets = bucket_counts[bucket_counts < 3]
    if len(small_buckets) > 0:
        log.warning(f"以下分层桶样本数 < 3，将退化为仅按 is_merged 分层:")
        for k, v in small_buckets.items():
            log.warning(f"  {k}: {v} 条")
        log.info("使用 is_merged 作为分层键")
        return df["is_merged"].astype(str).values

    return strat_key.values


def split_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    执行 70/15/15 分层划分。

    Returns:
        添加了 'split' 列的 DataFrame
    """
    # 验证比例
    assert abs(TRAIN_RATIO + VAL_RATIO + TEST_RATIO - 1.0) < 1e-10

    total = len(df)
    strat_key = build_stratify_key(df)

    log.info(f"分层键类别数: {len(np.unique(strat_key))}")
    log.info(f"划分比例: train={TRAIN_RATIO}, val={VAL_RATIO}, test={TEST_RATIO}")

    # 第一步：train (70%) vs temp (30%)
    test_val_ratio = TEST_RATIO / (VAL_RATIO + TEST_RATIO)  # 0.5

    df_train, df_temp = train_test_split(
        df, test_size=(1 - TRAIN_RATIO),
        stratify=strat_key,
        random_state=RANDOM_SEED,
    )

    # 第二步：val (15%) vs test (15%) from temp
    temp_strat_key = build_stratify_key(df_temp)

    df_val, df_test = train_test_split(
        df_temp, test_size=test_val_ratio,
        stratify=temp_strat_key,
        random_state=RANDOM_SEED,
    )

    # 标记 split 列
    df_train = df_train.copy()
    df_val = df_val.copy()
    df_test = df_test.copy()

    df_train["split"] = "train"
    df_val["split"] = "val"
    df_test["split"] = "test"

    result = pd.concat([df_train, df_val, df_test], ignore_index=True)

    # 验证
    log.info(f"划分完成: train={len(df_train)} ({100*len(df_train)/total:.1f}%), "
             f"val={len(df_val)} ({100*len(df_val)/total:.1f}%), "
             f"test={len(df_test)} ({100*len(df_test)/total:.1f}%)")

    # 打印各 split 的合并率
    for name, sub_df in [("train", df_train), ("val", df_val), ("test", df_test)]:
        merge_rate = sub_df["is_merged"].mean()
        log.info(f"  {name}: {len(sub_df)} 条, 合并率={merge_rate:.4f}")

    return result


def generate_split_summary(df: pd.DataFrame) -> dict:
    """生成划分摘要。"""
    summary = {"total": len(df), "random_seed": RANDOM_SEED, "splits": {}}
    for split_name in ["train", "val", "test"]:
        sub = df[df["split"] == split_name]
        summary["splits"][split_name] = {
            "count": len(sub),
            "merged": int(sub["is_merged"].sum()),
            "unmerged": int((~sub["is_merged"]).sum()),
            "merge_rate": round(sub["is_merged"].mean(), 4),
            "per_repo": {},
        }
        for repo_name in sorted(sub["repo"].unique()):
            r = sub[sub["repo"] == repo_name]
            summary["splits"][split_name]["per_repo"][repo_name] = {
                "count": len(r),
                "merged": int(r["is_merged"].sum()),
            }
    return summary


def run(input_path: Path = None, output_dir: Path = None):
    if input_path is None:
        input_path = PROCESSED_DIR / "human_only_dataset.csv"
    if output_dir is None:
        output_dir = PROCESSED_DIR

    df = load_human_dataset(input_path)
    df = split_dataset(df)

    # 输出 splits.csv（保留完整列用于后续步骤）
    csv_path = output_dir / "splits.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info(f"划分文件已保存: {csv_path}")

    # 输出摘要
    summary = generate_split_summary(df)
    summary_path = output_dir / "split_summary.json"
    write_json(summary, summary_path)
    log.info(f"划分摘要已保存: {summary_path}")

    return df


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    run()
