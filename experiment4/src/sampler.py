"""
实验三 步骤一：数据抽样
从实验二 test split 中抽取 50 条 PR（每仓库 10 条），
保持 merged/unmerged 比例接近测试集整体分布。
"""
import pandas as pd
import json
import random
from pathlib import Path

from config import (
    SPLITS_CSV, HUMAN_DATASET_CSV, PATCH_INDEX_JSON,
    AST_FEATURES_CSV, CFG_FEATURES_CSV,
    SAMPLE_SIZE, PER_REPO, REPOS, MIN_WITH_REVIEW_COMMENTS,
    RANDOM_SEED, LLM_SAMPLE_CSV, FEW_SHOT_EXAMPLES_JSON,
    PROCESSED_DIR,
)
from utils import log, read_json, write_json


def load_datasets():
    """加载实验二所有相关数据。"""
    log.info("加载数据集...")

    # 加载 human_only_dataset（包含原始文本字段）
    human_df = pd.read_csv(HUMAN_DATASET_CSV)
    log.info(f"  人类代码数据集: {len(human_df)} 条")

    # 加载 splits（包含 split 列）
    splits_df = pd.read_csv(SPLITS_CSV)
    log.info(f"  Splits: {len(splits_df)} 条")

    # 合并 split 信息到 human_df
    df = human_df.merge(
        splits_df[["pr_id", "split"]], on="pr_id", how="inner"
    )
    log.info(f"  合并后: {len(df)} 条")

    # 加载 AST 特征
    ast_df = pd.read_csv(AST_FEATURES_CSV)
    df = df.merge(ast_df, on=["pr_id", "repo"], how="left")

    # 加载 CFG 特征
    cfg_df = pd.read_csv(CFG_FEATURES_CSV)
    df = df.merge(cfg_df, on=["pr_id", "repo"], how="left")

    # 加载 patch index
    patch_index = read_json(PATCH_INDEX_JSON)
    patch_map = {p["pr_id"]: p for p in patch_index}
    log.info(f"  Patch 索引: {len(patch_index)} 条")

    return df, patch_map


def sample_test_prs(df: pd.DataFrame, patch_map: dict, seed: int = RANDOM_SEED):
    """
    从 test split 中抽样 50 条 PR。

    规则：
    - 每仓库 10 条
    - 尽量保持 merged/unmerged 比例接近测试集整体分布
    - 优先保证至少 25 条有非空 review_comments_text
    """
    random.seed(seed)

    test_df = df[df["split"] == "test"].copy()
    log.info(f"测试集总数: {len(test_df)}")

    # 测试集整体 merged 比例
    test_merge_rate = test_df["is_merged"].mean()
    log.info(f"测试集 merge rate: {test_merge_rate:.4f}")

    # 检查 review_comments_text 非空情况
    test_df["has_review_text"] = test_df["review_comments_text"].notna() & (
        test_df["review_comments_text"].astype(str).str.strip() != ""
    )
    has_review_count = test_df["has_review_text"].sum()
    log.info(f"测试集中有 review_comments_text 的: {has_review_count}/{len(test_df)}")

    # 优先选择有 review_comments_text 的辅助函数
    def select_with_review_priority(pool, n, seed_val):
        """从 pool 中选 n 条，优先选有 review text 的。"""
        if pool is None or len(pool) == 0:
            return pd.DataFrame()
        if len(pool) <= n:
            return pool
        with_review = pool[pool["has_review_text"]]
        without_review = pool[~pool["has_review_text"]]
        selected = []
        # 先尽量选有 review text 的
        n_from_review = min(n, len(with_review))
        if n_from_review > 0:
            selected.extend(with_review.sample(
                n_from_review, random_state=seed_val
            ).to_dict("records"))
        # 不够再补
        remaining = n - len(selected)
        if remaining > 0 and len(without_review) > 0:
            selected.extend(without_review.sample(
                min(remaining, len(without_review)), random_state=seed_val
            ).to_dict("records"))
        return pd.DataFrame(selected)

    sampled = []
    for repo in REPOS:
        repo_test = test_df[test_df["repo"] == repo].copy()
        log.info(f"\n{repo}: test 集 {len(repo_test)} 条")

        if len(repo_test) < PER_REPO:
            log.warning(f"  {repo} test 集不足 {PER_REPO} 条，全取")
            sampled.append(repo_test)
            continue

        # 按测试集整体 merge 比例计算目标数量
        target_merged = round(PER_REPO * test_merge_rate)
        target_unmerged = PER_REPO - target_merged

        merged_pool = repo_test[repo_test["is_merged"] == True]
        unmerged_pool = repo_test[repo_test["is_merged"] == False]

        # 处理某一类不足的情况：从另一类补充
        actual_merged = min(target_merged, len(merged_pool))
        actual_unmerged = min(target_unmerged, len(unmerged_pool))
        shortage = PER_REPO - actual_merged - actual_unmerged
        if shortage > 0:
            # 从充足的类别补充
            if len(merged_pool) > actual_merged:
                extra = min(shortage, len(merged_pool) - actual_merged)
                actual_merged += extra
                shortage -= extra
            if shortage > 0 and len(unmerged_pool) > actual_unmerged:
                extra = min(shortage, len(unmerged_pool) - actual_unmerged)
                actual_unmerged += extra

        merged_selected = select_with_review_priority(
            merged_pool, actual_merged, seed
        )
        unmerged_selected = select_with_review_priority(
            unmerged_pool, actual_unmerged, seed
        )

        repo_sample = pd.concat([merged_selected, unmerged_selected], ignore_index=True)
        sampled.append(repo_sample)

        log.info(f"  选中: merged={len(merged_selected)}, unmerged={len(unmerged_selected)}")

    result = pd.concat(sampled, ignore_index=True)

    # 检查 review_comments_text 覆盖
    result["has_review_text"] = result["review_comments_text"].notna() & (
        result["review_comments_text"].astype(str).str.strip() != ""
    )
    review_count = result["has_review_text"].sum()
    log.info(f"\n抽样结果: {len(result)} 条, merged={result['is_merged'].sum()}, "
             f"有 review text: {review_count}")

    # 重抽样直到满足 review text 要求
    attempts = 0
    while review_count < MIN_WITH_REVIEW_COMMENTS and attempts < 10:
        log.info(f"  有 review text 的样本不足 ({review_count} < {MIN_WITH_REVIEW_COMMENTS})，重新抽样...")
        attempts += 1
        retry_sampled = []
        for repo in REPOS:
            repo_test = test_df[test_df["repo"] == repo]
            retry_sampled.append(select_with_review_priority(
                repo_test, PER_REPO, seed + attempts
            ))
        result = pd.concat(retry_sampled, ignore_index=True)
        result["has_review_text"] = result["review_comments_text"].notna() & (
            result["review_comments_text"].astype(str).str.strip() != ""
        )
        review_count = result["has_review_text"].sum()

    log.info(f"最终抽样: {len(result)} 条, merged={result['is_merged'].sum()}, "
             f"merge_rate={result['is_merged'].mean():.4f}, "
             f"有 review text: {review_count}")

    # 按 pr_id 排序
    result = result.sort_values("pr_id").reset_index(drop=True)

    return result


def create_few_shot_examples(df: pd.DataFrame, seed: int = RANDOM_SEED):
    """
    从 validation split 中选择 few-shot 示例。
    2 个 merged + 2 个 not merged。
    不得来自 test split。
    """
    random.seed(seed)

    val_df = df[df["split"] == "val"].copy()
    log.info(f"从 validation 集 ({len(val_df)} 条) 选择 few-shot 示例")

    merged_val = val_df[val_df["is_merged"] == True]
    unmerged_val = val_df[val_df["is_merged"] == False]

    merged_examples = merged_val.sample(
        min(2, len(merged_val)), random_state=seed
    ).to_dict("records")
    unmerged_examples = unmerged_val.sample(
        min(2, len(unmerged_val)), random_state=seed
    ).to_dict("records")

    examples = []
    for i, row in enumerate(merged_examples):
        examples.append({
            "id": f"fewshot_merged_{i+1}",
            "type": "merged",
            "pr_id": row["pr_id"],
            "repo": row["repo"],
            "title": row.get("title", ""),
            "body": str(row.get("body", ""))[:500],
        })
    for i, row in enumerate(unmerged_examples):
        examples.append({
            "id": f"fewshot_unmerged_{i+1}",
            "type": "not_merged",
            "pr_id": row["pr_id"],
            "repo": row["repo"],
            "title": row.get("title", ""),
            "body": str(row.get("body", ""))[:500],
        })

    log.info(f"生成 {len(examples)} 个 few-shot 示例")
    return examples


def run(output_dir: Path = None):
    if output_dir is None:
        output_dir = PROCESSED_DIR

    log.info("=" * 60)
    log.info("步骤一：数据抽样")
    log.info("=" * 60)

    df, patch_map = load_datasets()

    # 抽样
    sample_df = sample_test_prs(df, patch_map)

    # 保存抽样结果
    sample_path = output_dir / "llm_sample_50.csv"
    sample_df.to_csv(sample_path, index=False)
    log.info(f"抽样结果已保存: {sample_path}")

    # 生成 few-shot 示例
    few_shot_examples = create_few_shot_examples(df)
    examples_path = output_dir / "few_shot_examples.json"
    write_json(few_shot_examples, examples_path)
    log.info(f"Few-shot 示例已保存: {examples_path}")

    # 打印抽样统计
    log.info(f"\n抽样统计:")
    log.info(f"  总样本数: {len(sample_df)}")
    log.info(f"  Merged: {sample_df['is_merged'].sum()}")
    log.info(f"  Merge rate: {sample_df['is_merged'].mean():.4f}")
    for repo in REPOS:
        repo_data = sample_df[sample_df["repo"] == repo]
        log.info(f"  {repo}: {len(repo_data)} 条, "
                 f"merged={repo_data['is_merged'].sum()}")

    return sample_df, few_shot_examples


if __name__ == "__main__":
    from utils import setup_logger
    log = setup_logger("experiment3", PROCESSED_DIR.parent / "pipeline.log")
    run()
