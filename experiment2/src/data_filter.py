"""
实验二 步骤一：数据筛选与清洗
从实验一数据集筛选人类编写代码的 PR，输出 human_only_dataset.csv
"""
import pandas as pd
import numpy as np
from pathlib import Path

from config import EXPERIMENT1_DATASET, PROCESSED_DIR, RANDOM_SEED
from utils import log, write_json, safe_str


def load_dataset(path: Path) -> pd.DataFrame:
    """加载实验一数据集，统一布尔字段格式。"""
    log.info(f"加载数据集: {path}")
    df = pd.read_csv(path)

    # 统一布尔字段
    bool_cols = ["is_merged", "has_ai_reviewer", "has_ai_generated_code"]
    for col in bool_cols:
        if col in df.columns:
            # 处理可能的字符串 "True"/"False" 或 1/0
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.strip().str.lower().map({
                    "true": True, "false": False, "1": True, "0": False
                })
            df[col] = df[col].fillna(False).astype(bool)

    log.info(f"数据集加载完成: {len(df)} 条记录")
    return df


def filter_human_code(df: pd.DataFrame) -> pd.DataFrame:
    """
    筛选人类编写代码的 PR。

    规则：
    1. has_ai_generated_code == False
    2. merge_status 为 "merged" 或 "closed_not_merged"
    3. 去除异常值
    """
    n_before = len(df)

    # 1. 过滤 AI 生成代码
    ai_before = df["has_ai_generated_code"].sum()
    df = df[~df["has_ai_generated_code"]].copy()
    log.info(f"过滤 AI 生成代码: {ai_before} → 移除, 剩余 {len(df)} 条")

    # 2. 保留明确的合并状态
    valid_status = {"merged", "closed_not_merged"}
    status_before = len(df)
    df = df[df["merge_status"].isin(valid_status)].copy()
    removed = status_before - len(df)
    if removed > 0:
        log.warning(f"移除 {removed} 条非明确状态记录 (非 merged/closed_not_merged)")

    # 3. 删除异常样本
    df = df.dropna(subset=["pr_id", "repo", "is_merged"])
    abnormal = (
        (df["num_changed_files"] <= 0)
        | (df["total_additions"] < 0)
        | (df["total_deletions"] < 0)
    )
    n_abnormal = abnormal.sum()
    if n_abnormal > 0:
        log.warning(f"移除 {n_abnormal} 条异常样本 (num_changed_files<=0 或负新增/删除)")
        df = df[~abnormal].copy()

    # 4. 将 num_changed_files=0 的少量样本也标记（正常不应该存在）
    # 如果存在有 additions/deletions 但 changed_files=0 的情况，修正
    mask_zero_files = df["num_changed_files"] <= 0
    if mask_zero_files.any():
        log.warning(f"发现 {mask_zero_files.sum()} 条 num_changed_files <= 0, 剔除")
        df = df[~mask_zero_files].copy()

    log.info(f"筛选完成: {n_before} → {len(df)} 条 ({len(df)/max(n_before,1)*100:.1f}%)")
    return df


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """清洗文本和数值字段。"""
    # 文本缺失值填充
    text_cols = ["title", "body", "commit_messages",
                 "review_comments_text", "modified_functions",
                 "changed_files_list", "label_names"]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    # 数值字段确保非负
    for col in ["num_changed_files", "total_additions", "total_deletions",
                "num_commits", "num_reviewers", "num_review_comments",
                "num_inline_comments", "num_labels", "pr_length"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).clip(lower=0)

    return df


def generate_stats(df: pd.DataFrame) -> dict:
    """生成筛选后数据集的统计报告。"""
    total = len(df)
    merged = df["is_merged"].sum()
    unmerged = total - merged

    stats = {
        "title": "实验二：人类代码数据集统计",
        "overall": {
            "total_prs": total,
            "merged_count": int(merged),
            "merged_pct": round(100 * merged / max(total, 1), 2),
            "unmerged_count": int(unmerged),
            "unmerged_pct": round(100 * unmerged / max(total, 1), 2),
            "ai_reviewer_count": int(df["has_ai_reviewer"].sum()),
            "ai_reviewer_pct": round(100 * df["has_ai_reviewer"].sum() / max(total, 1), 2),
        },
        "per_repo": [],
    }

    for repo_name in sorted(df["repo"].unique()):
        repo_df = df[df["repo"] == repo_name]
        repo_total = len(repo_df)
        repo_merged = repo_df["is_merged"].sum()
        stats["per_repo"].append({
            "repo": repo_name,
            "prs": repo_total,
            "merged": int(repo_merged),
            "merge_rate": round(100 * repo_merged / max(repo_total, 1), 2),
            "ai_reviewer_count": int(repo_df["has_ai_reviewer"].sum()),
        })

    return stats


def log_stats(stats: dict):
    """打印统计摘要到日志。"""
    ov = stats["overall"]
    log.info("=" * 55)
    log.info("人类代码数据集统计摘要")
    log.info("=" * 55)
    log.info(f"总 PR 数:           {ov['total_prs']}")
    log.info(f"已合并:             {ov['merged_count']} ({ov['merged_pct']}%)")
    log.info(f"未合并:             {ov['unmerged_count']} ({ov['unmerged_pct']}%)")
    log.info(f"含 AI Reviewer:     {ov['ai_reviewer_count']} ({ov['ai_reviewer_pct']}%)")
    log.info("-" * 55)
    log.info(f"{'仓库':<30} {'PR数':>5} {'合并率':>8}")
    log.info("-" * 55)
    for r in stats["per_repo"]:
        log.info(f"{r['repo']:<30} {r['prs']:>5} {r['merge_rate']:>7.1f}%")
    log.info("=" * 55)


def run(output_dir: Path = None):
    """执行数据筛选与清洗。"""
    if output_dir is None:
        output_dir = PROCESSED_DIR

    # 1. 加载
    df = load_dataset(EXPERIMENT1_DATASET)

    # 2. 筛选
    df = filter_human_code(df)

    # 3. 清洗
    df = clean_dataset(df)

    # 4. 生成统计
    stats = generate_stats(df)
    log_stats(stats)

    # 5. 输出
    csv_path = output_dir / "human_only_dataset.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info(f"数据集已保存: {csv_path}")

    stats_path = output_dir / "human_dataset_stats.json"
    write_json(stats, stats_path)
    log.info(f"统计已保存: {stats_path}")

    return df


if __name__ == "__main__":
    from config import PROCESSED_DIR
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    run(PROCESSED_DIR)
