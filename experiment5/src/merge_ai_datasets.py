"""
合并 Seed 与 Enhanced 数据集

输入:
  - results/processed/ai_generated_dataset_seed.csv  (97条)
  - results/raw/ai_pr_collected.json                  (增强采集结果)

处理:
  1. 以 repo + pr_number 作为唯一键去重
  2. 实验一 seed 样本优先保留
  3. 新采集样本如果字段更完整，可补充 patch/review

输出:
  - results/processed/ai_generated_dataset_enhanced.csv  (seed + 新增)
  - results/processed/ai_generated_dataset.csv           (最终使用版本)
  - results/processed/ai_patch_index.json                (合并后的 patch index)
  - results/evaluation/ai_dataset_stats.json             (统计报告)
"""

import csv
import json
import os
import sys
import copy
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict

# 确保 src 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    AI_DATASET_SEED_CSV,
    AI_DATASET_ENHANCED_CSV,
    AI_DATASET_CSV,
    AI_COLLECTED_JSON,
    AI_PATCH_INDEX_SEED,
    AI_PATCH_INDEX,
    AI_DATASET_STATS_JSON,
    MIN_ENHANCED_FOR_DEFAULT,
    ORIGINAL_REPOS,
    ALL_REPOS,
    logger,
)


def _read_csv_robust(filepath: str) -> List[Dict[str, str]]:
    """鲁棒的 CSV 读取"""
    if not os.path.exists(filepath):
        return []
    rows = []
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        logger.error(f"读取 CSV 失败 {filepath}: {e}")
    return rows


def _make_key(repo: str, pr_number) -> Tuple[str, int]:
    """构建去重键"""
    try:
        num = int(pr_number)
    except (ValueError, TypeError):
        num = 0
    return (repo.strip(), num)


def _load_enhanced_prs() -> List[Dict[str, Any]]:
    """从 collected JSON 加载增强 PR"""
    if not os.path.exists(AI_COLLECTED_JSON):
        logger.warning(f"增强采集结果未找到: {AI_COLLECTED_JSON}")
        return []
    try:
        with open(AI_COLLECTED_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"加载增强数据失败: {e}")
        return []

    # 优先使用 ai_positive_prs（通过 AI 检测的）
    prs = data.get("ai_positive_prs", [])
    if not prs:
        prs = data.get("prs", [])
    return prs


def _pr_to_csv_row(pr: Dict[str, Any], fieldnames: List[str]) -> Dict[str, str]:
    """将 PR 字典转换为 CSV 行（所有值转字符串）"""
    row = {}
    for fn in fieldnames:
        val = pr.get(fn, "")
        if isinstance(val, bool):
            val = str(val)
        elif isinstance(val, (list, dict)):
            val = ""
        elif val is None:
            val = ""
        row[fn] = str(val)
    return row


def _build_merged_patch_index(seed_index: Dict, enhanced_prs: List[Dict]) -> Dict:
    """合并 patch index：seed 优先 + 增强补充"""
    merged = copy.deepcopy(seed_index)

    for pr in enhanced_prs:
        pr_id = str(pr.get("pr_id", ""))
        if not pr_id or pr_id in merged:
            continue

        files_data = pr.get("_files", [])
        if not files_data:
            continue

        merged[pr_id] = {
            "repo": pr.get("repo", ""),
            "pr_number": pr.get("pr_number", ""),
            "files": [
                {
                    "filename": f.get("filename", ""),
                    "status": f.get("status", ""),
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                    "changes": f.get("changes", 0),
                    "patch": f.get("patch", ""),
                }
                for f in files_data
            ],
        }

    return merged


def compute_dataset_stats(
    prs: List[Dict[str, Any]], dataset_type: str, source_desc: str
) -> Dict[str, Any]:
    """计算数据集统计"""
    total = len(prs)
    merged_count = sum(1 for p in prs if _bool_val(p.get("is_merged")))
    unmerged_count = total - merged_count
    merge_rate = merged_count / total if total > 0 else 0.0

    # 仓库分布
    repo_dist = defaultdict(lambda: {"total": 0, "merged": 0, "unmerged": 0, "has_review": 0})
    for p in prs:
        repo = p.get("repo", "unknown")
        repo_dist[repo]["total"] += 1
        if _bool_val(p.get("is_merged")):
            repo_dist[repo]["merged"] += 1
        else:
            repo_dist[repo]["unmerged"] += 1
        if p.get("review_comments_text", "").strip():
            repo_dist[repo]["has_review"] += 1

    has_review = sum(1 for p in prs if p.get("review_comments_text", "").strip())

    return {
        "dataset_type": dataset_type,
        "source": source_desc,
        "total_prs": total,
        "merged_count": merged_count,
        "unmerged_count": unmerged_count,
        "merge_rate": round(merge_rate, 4),
        "review_coverage": round(has_review / total, 4) if total > 0 else 0.0,
        "prs_with_review": has_review,
        "repo_distribution": dict(repo_dist),
        "original_5_repos": {
            repo: dict(repo_dist[repo])
            for repo in ORIGINAL_REPOS
            if repo in repo_dist
        },
    }


def _bool_val(val: Any) -> bool:
    """判断值是否为 True"""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def merge_datasets() -> bool:
    """
    主合并流程。

    返回:
        bool: 成功返回 True
    """
    logger.info("=" * 60)
    logger.info("阶段: 合并数据集")
    logger.info("=" * 60)

    # 1. 加载 seed 数据
    logger.info(f"加载 seed 数据: {AI_DATASET_SEED_CSV}")
    seed_rows = _read_csv_robust(AI_DATASET_SEED_CSV)
    logger.info(f"  Seed 样本数: {len(seed_rows)}")

    if not seed_rows:
        logger.error("Seed 数据为空，无法继续")
        return False

    # 获取 seed 字段名
    seed_fieldnames = list(seed_rows[0].keys())

    # 2. 加载增强数据
    logger.info(f"加载增强数据: {AI_COLLECTED_JSON}")
    enhanced_prs = _load_enhanced_prs()
    logger.info(f"  增强样本数: {len(enhanced_prs)}")

    # 3. 构建 seed 键集
    seed_keys: Set[Tuple[str, int]] = set()
    for row in seed_rows:
        seed_keys.add(_make_key(row.get("repo", ""), row.get("pr_number", 0)))

    # 4. 去重：seed 优先
    new_prs = []
    duplicates = 0
    for pr in enhanced_prs:
        key = _make_key(pr.get("repo", ""), pr.get("pr_number", 0))
        if key in seed_keys:
            duplicates += 1
            continue
        if pr.get("pr_id") in [s.get("pr_id") for s in seed_rows]:
            duplicates += 1
            continue
        new_prs.append(pr)

    logger.info(f"  新增 PR: {len(new_prs)}, 重复: {duplicates}")

    # 5. 构建 enhanced CSV（seed + 新增）
    # 确定字段：使用 seed 的字段 + 增强中可能多的字段
    all_fieldnames = list(seed_fieldnames)

    # 转换增强 PR 为 CSV 行
    enhanced_rows = []
    for pr in new_prs:
        row = _pr_to_csv_row(pr, all_fieldnames)
        enhanced_rows.append(row)

    all_enhanced_rows = seed_rows + enhanced_rows
    logger.info(f"  Enhanced 总样本数: {len(all_enhanced_rows)}")

    # 6. 保存 enhanced CSV
    if all_enhanced_rows:
        with open(AI_DATASET_ENHANCED_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_enhanced_rows)
        logger.info(f"Enhanced 数据集已保存: {AI_DATASET_ENHANCED_CSV}")
        logger.info(f"  {len(all_enhanced_rows)} 行, {len(all_fieldnames)} 列")

    # 7. 版本选择
    enhanced_count = len(all_enhanced_rows)
    if enhanced_count >= MIN_ENHANCED_FOR_DEFAULT:
        final_rows = all_enhanced_rows
        version_note = f"enhanced ({enhanced_count} 样本 >= {MIN_ENHANCED_FOR_DEFAULT})"
    else:
        final_rows = seed_rows
        version_note = (
            f"seed ({enhanced_count} 样本 < {MIN_ENHANCED_FOR_DEFAULT}, "
            f"回退到 seed {len(seed_rows)} 样本)"
        )

    # 8. 保存最终数据集
    if final_rows:
        with open(AI_DATASET_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(final_rows)
        logger.info(f"最终数据集已保存: {AI_DATASET_CSV}")
        logger.info(f"  版本: {version_note}")

    # 9. 合并 patch index
    logger.info("合并 patch index...")
    seed_index = {}
    if os.path.exists(AI_PATCH_INDEX_SEED):
        with open(AI_PATCH_INDEX_SEED, "r", encoding="utf-8") as f:
            seed_index = json.load(f)
        logger.info(f"  Seed patch index: {len(seed_index)} 条目")

    merged_index = _build_merged_patch_index(seed_index, new_prs)
    with open(AI_PATCH_INDEX, "w", encoding="utf-8") as f:
        json.dump(merged_index, f, ensure_ascii=False, indent=2)
    logger.info(f"  合并后 patch index: {len(merged_index)} 条目")
    logger.info(f"  已保存: {AI_PATCH_INDEX}")

    # 10. 生成统计报告
    logger.info("生成统计报告...")
    # 构建用于统计的 PR 字典列表（统一格式）
    final_prs_for_stats = []
    for row in final_rows:
        pr_dict = dict(row)
        final_prs_for_stats.append(pr_dict)

    stats = compute_dataset_stats(
        final_prs_for_stats,
        dataset_type="enhanced" if final_rows is all_enhanced_rows else "seed",
        source_desc=version_note,
    )
    stats["version"] = version_note
    stats["seed_count"] = len(seed_rows)
    stats["enhanced_count"] = enhanced_count
    stats["new_count"] = len(new_prs)
    stats["patch_index_entries"] = len(merged_index)

    # 按仓库分类 enhanced vs seed
    stats["repo_composition"] = {}
    for repo in sorted(set(
        list(stats.get("repo_distribution", {}).keys())
        + list(ORIGINAL_REPOS)
    )):
        seed_count = sum(
            1 for r in seed_rows if r.get("repo") == repo
        )
        new_count = sum(
            1 for p in new_prs if p.get("repo") == repo
        )
        stats["repo_composition"][repo] = {
            "seed": seed_count,
            "new": new_count,
            "total": seed_count + new_count,
        }

    with open(AI_DATASET_STATS_JSON, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    logger.info(f"统计报告已保存: {AI_DATASET_STATS_JSON}")

    # 11. 打印摘要
    logger.info("=" * 60)
    logger.info("数据集合并完成")
    logger.info(f"  Seed 样本:        {len(seed_rows)}")
    logger.info(f"  新增样本:         {len(new_prs)}")
    logger.info(f"  Enhanced 总计:    {enhanced_count}")
    logger.info(f"  最终使用版本:     {version_note}")
    logger.info(f"  最终样本数:       {len(final_rows)}")
    logger.info(f"  Patch index:      {len(merged_index)}")
    logger.info("  仓库组成:")
    for repo, comp in stats.get("repo_composition", {}).items():
        logger.info(
            f"    {repo}: seed={comp['seed']}, new={comp['new']}, "
            f"total={comp['total']}"
        )
    logger.info("=" * 60)

    return True


if __name__ == "__main__":
    success = merge_datasets()
    sys.exit(0 if success else 1)
