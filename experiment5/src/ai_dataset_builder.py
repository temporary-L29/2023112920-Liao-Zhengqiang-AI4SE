"""
从实验一数据构建 Seed 数据集

输入:
  - experiment1/results/processed/dataset.csv
  - raw/merged_raw.json

处理:
  1. 筛选 has_ai_generated_code == True
  2. 从 merged_raw.json 抽取 patch / files / commits / reviews / review_comments
  3. 生成 seed 数据统计

输出:
  - results/processed/ai_generated_dataset_seed.csv
  - results/processed/ai_patch_index_seed.json
  - results/evaluation/seed_dataset_stats.json
"""

import csv
import json
import os
import sys
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    EXPERIMENT1_DATASET_CSV,
    EXPERIMENT1_MERGED_RAW,
    AI_DATASET_SEED_CSV,
    AI_PATCH_INDEX_SEED,
    SEED_DATASET_STATS_JSON,
    logger,
)


def read_csv_with_bom(filepath: str) -> List[Dict[str, str]]:
    """读取带 BOM 的 CSV 文件"""
    rows = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_patch_index_from_raw(
    raw_data: List[Dict[str, Any]],
    pr_id_to_entry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    从 merged_raw.json 构建 patch index。

    返回格式:
    {
        "<pr_id>": {
            "repo": "owner/repo",
            "pr_number": 123,
            "files": [
                {
                    "filename": "src/file.py",
                    "status": "modified",
                    "additions": 10,
                    "deletions": 5,
                    "patch": "@@ ..."
                },
                ...
            ]
        }
    }
    """
    patch_index = {}

    for entry in raw_data:
        pr_id = str(entry.get("detail", {}).get("id", ""))
        if pr_id not in pr_id_to_entry:
            continue

        repo = entry.get("repo", "")
        pr_number = entry.get("detail", {}).get("number", "")

        files_data = []
        for f in entry.get("files", []):
            files_data.append(
                {
                    "filename": f.get("filename", ""),
                    "status": f.get("status", ""),
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                    "changes": f.get("changes", 0),
                    "patch": f.get("patch", ""),
                }
            )

        patch_index[pr_id] = {
            "repo": repo,
            "pr_number": pr_number,
            "files": files_data,
        }

    return patch_index


def compute_seed_stats(seed_df: List[Dict[str, str]]) -> Dict[str, Any]:
    """计算 seed 数据集统计"""
    total = len(seed_df)
    merged_count = sum(
        1 for r in seed_df if r.get("is_merged", "").lower() in ("true", "1")
    )
    unmerged_count = total - merged_count
    merge_rate = merged_count / total if total > 0 else 0.0

    # 按仓库分布
    repo_dist = {}
    for r in seed_df:
        repo = r.get("repo", "unknown")
        if repo not in repo_dist:
            repo_dist[repo] = {"total": 0, "merged": 0, "unmerged": 0, "has_review": 0}
        repo_dist[repo]["total"] += 1
        if r.get("is_merged", "").lower() in ("true", "1"):
            repo_dist[repo]["merged"] += 1
        else:
            repo_dist[repo]["unmerged"] += 1
        if r.get("review_comments_text", "").strip():
            repo_dist[repo]["has_review"] += 1

    # 评论覆盖率
    has_review = sum(
        1 for r in seed_df if r.get("review_comments_text", "").strip()
    )

    return {
        "dataset_type": "seed",
        "source": "experiment1",
        "total_prs": total,
        "merged_count": merged_count,
        "unmerged_count": unmerged_count,
        "merge_rate": round(merge_rate, 4),
        "review_coverage": round(has_review / total, 4) if total > 0 else 0.0,
        "prs_with_review": has_review,
        "repo_distribution": repo_dist,
    }


def build_seed_dataset() -> bool:
    """
    构建 seed 数据集。

    返回:
        bool: 成功返回 True
    """
    logger.info("=" * 60)
    logger.info("阶段: 构建 Seed 数据集")
    logger.info("=" * 60)

    # 1. 检查输入文件
    if not os.path.exists(EXPERIMENT1_DATASET_CSV):
        logger.error(f"实验一数据集未找到: {EXPERIMENT1_DATASET_CSV}")
        return False
    if not os.path.exists(EXPERIMENT1_MERGED_RAW):
        logger.error(f"合并原始数据未找到: {EXPERIMENT1_MERGED_RAW}")
        return False

    # 2. 读取实验一数据集
    logger.info(f"读取实验一数据集: {EXPERIMENT1_DATASET_CSV}")
    all_rows = read_csv_with_bom(EXPERIMENT1_DATASET_CSV)
    logger.info(f"  总 PR 数: {len(all_rows)}")

    # 3. 筛选 AI 生成代码 PR
    seed_rows = [
        r
        for r in all_rows
        if r.get("has_ai_generated_code", "").lower() in ("true", "1")
    ]
    logger.info(f"  AI 生成代码 PR: {len(seed_rows)}")

    # 快速统计
    merged_in_seed = sum(
        1 for r in seed_rows if r.get("is_merged", "").lower() in ("true", "1")
    )
    logger.info(f"  合并数: {merged_in_seed}, 合并率: {merged_in_seed / len(seed_rows) * 100:.1f}%")

    # 4. 读取 merged_raw.json 并构建 patch index
    logger.info(f"读取原始数据: {EXPERIMENT1_MERGED_RAW}")
    try:
        with open(EXPERIMENT1_MERGED_RAW, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        logger.info(f"  原始条目数: {len(raw_data)}")
    except (json.JSONDecodeError, MemoryError) as e:
        logger.error(f"读取 merged_raw.json 失败: {e}")
        return False

    # 构建 pr_id → seed 行映射
    pr_id_to_seed = {}
    for row in seed_rows:
        pr_id_to_seed[str(row.get("pr_id", ""))] = row

    # 5. 构建 patch index
    logger.info("构建 patch index...")
    patch_index = build_patch_index_from_raw(raw_data, pr_id_to_seed)
    logger.info(f"  Patch index 条目数: {len(patch_index)}")

    # 6. 补充 patch 覆盖率信息
    prs_with_patch = 0
    for pr_id, pi in patch_index.items():
        total_patch_len = sum(
            len(f.get("patch", "")) for f in pi.get("files", [])
        )
        if total_patch_len > 0:
            prs_with_patch += 1
    logger.info(f"  有 patch 数据的 PR: {prs_with_patch}/{len(patch_index)}")

    # 7. 保存 seed CSV
    logger.info(f"保存 seed 数据集: {AI_DATASET_SEED_CSV}")
    if seed_rows:
        fieldnames = list(seed_rows[0].keys())
        with open(AI_DATASET_SEED_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(seed_rows)
        logger.info(f"  写入 {len(seed_rows)} 行, {len(fieldnames)} 列")
    else:
        logger.warning("  没有 AI 生成代码 PR 可写入")

    # 8. 保存 patch index
    logger.info(f"保存 patch index: {AI_PATCH_INDEX_SEED}")
    with open(AI_PATCH_INDEX_SEED, "w", encoding="utf-8") as f:
        json.dump(patch_index, f, ensure_ascii=False, indent=2)

    # 9. 计算统计
    stats = compute_seed_stats(seed_rows)
    # 添加 patch 覆盖率
    stats["prs_with_patch"] = prs_with_patch
    stats["patch_coverage"] = (
        round(prs_with_patch / len(seed_rows), 4) if seed_rows else 0.0
    )

    logger.info(f"保存 seed 统计: {SEED_DATASET_STATS_JSON}")
    with open(SEED_DATASET_STATS_JSON, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # 10. 打印摘要
    logger.info("=" * 60)
    logger.info("Seed 数据集构建完成")
    logger.info(f"  总 PR 数:     {stats['total_prs']}")
    logger.info(f"  合并数:       {stats['merged_count']}")
    logger.info(f"  合并率:       {stats['merge_rate']:.2%}")
    logger.info(f"  评论覆盖率:   {stats['review_coverage']:.2%}")
    logger.info(f"  Patch 覆盖率: {stats['patch_coverage']:.2%}")
    logger.info("  仓库分布:")
    for repo, dist in stats["repo_distribution"].items():
        logger.info(
            f"    {repo}: {dist['total']} PRs "
            f"(merged={dist['merged']}, unmerged={dist['unmerged']}, "
            f"review={dist['has_review']})"
        )
    logger.info("=" * 60)

    return True


if __name__ == "__main__":
    success = build_seed_dataset()
    sys.exit(0 if success else 1)
