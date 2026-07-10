"""
样本构建模块 — 从实验五数据构建评估子集

构建:
  0. Balanced-50: 复用实验五 ai_llm_sample_50.csv (主实验样本)
  1. Balanced-120: 60 merged + 60 unmerged, 按仓库分层抽样
  2. Hard-FP-40: 从实验五 False Positive 中抽取
"""

import json
import os
import sys
import shutil
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    EXP5_DATASET_CSV,
    EXP5_PATCH_INDEX,
    EXP5_LLM_PARSED,
    EXP5_LLM_RAW,
    EXP5_LLM_SAMPLE_50,
    EXP5_4X4_PARSED,
    EVAL_BALANCED_50,
    EVAL_BALANCED_120,
    EVAL_HARD_FP_40,
    EVAL_SAMPLE_STATS,
    RANDOM_SEED,
    BALANCED_SIZE,
    HARD_FP_SIZE,
    RESULTS_PROCESSED_DIR,
    logger,
)


def load_exp5_data() -> pd.DataFrame:
    """加载实验五 AI 数据集"""
    if not os.path.exists(EXP5_DATASET_CSV):
        raise FileNotFoundError(f"实验五数据集未找到: {EXP5_DATASET_CSV}")

    df = pd.read_csv(EXP5_DATASET_CSV, encoding="utf-8-sig")
    # 统一 is_merged 为 bool
    df["is_merged_bool"] = df["is_merged"].apply(
        lambda x: True if str(x).lower() in ("true", "1") else False
    )
    # 是否有真实 review comments
    df["has_review"] = df["review_comments_text"].apply(
        lambda x: bool(str(x).strip()) and str(x).strip().lower() not in ("", "nan", "none")
    )
    logger.info(f"加载实验五数据集: {len(df)} 条 PR, merged={df['is_merged_bool'].sum()}, "
                f"unmerged={(~df['is_merged_bool']).sum()}")
    return df


def load_exp5_predictions() -> Optional[pd.DataFrame]:
    """加载实验五 LLM 预测"""
    if not os.path.exists(EXP5_LLM_PARSED):
        logger.warning(f"实验五预测文件未找到: {EXP5_LLM_PARSED}")
        return None
    df = pd.read_csv(EXP5_LLM_PARSED, encoding="utf-8-sig")
    logger.info(f"加载实验五预测: {len(df)} 条")
    return df


def build_balanced_50() -> pd.DataFrame:
    """
    从实验五 ai_llm_sample_50.csv 复制主实验样本。

    校验:
      - 共 50 条
      - merged/unmerged 分布接近平衡
      - 每条 PR 有 repo、pr_number、title/body/diff
    """
    logger.info("=" * 40)
    logger.info("构建 Balanced-50 主实验样本 (复用实验五 ai_llm_sample_50.csv)")

    if not os.path.exists(EXP5_LLM_SAMPLE_50):
        logger.error(f"实验五 50 样本不存在: {EXP5_LLM_SAMPLE_50}")
        logger.error("需要先运行实验五的 4×4 基线实验！")
        raise FileNotFoundError(f"实验五 50 样本不存在: {EXP5_LLM_SAMPLE_50}")

    df = pd.read_csv(EXP5_LLM_SAMPLE_50, encoding="utf-8-sig")
    logger.info(f"加载实验五 50 样本: {len(df)} 条")

    # 统一 is_merged_bool
    if "is_merged_bool" not in df.columns:
        df["is_merged_bool"] = df["is_merged"].apply(
            lambda x: True if str(x).lower() in ("true", "1") else False
        )

    # 校验
    n_total = len(df)
    n_merged = df["is_merged_bool"].sum()
    n_unmerged = (~df["is_merged_bool"]).sum()
    logger.info(f"  总数: {n_total}, merged={n_merged}, unmerged={n_unmerged}")

    if n_total != 50:
        logger.warning(f"  预期 50 条，实际 {n_total} 条")

    # 检查必需字段
    required_fields = ["pr_id", "repo", "title", "body"]
    missing = [f for f in required_fields if f not in df.columns]
    if missing:
        logger.error(f"  缺少必需字段: {missing}")
    else:
        logger.info(f"  必需字段完整: {required_fields}")

    # 校验与实验五 4×4 predictions 中的 PR 一致
    if os.path.exists(EXP5_4X4_PARSED):
        pred_df = pd.read_csv(EXP5_4X4_PARSED, encoding="utf-8-sig")
        pred_pr_ids = set(pred_df["pr_id"].astype(str))
        sample_pr_ids = set(df["pr_id"].astype(str))
        overlap = pred_pr_ids & sample_pr_ids
        logger.info(f"  与实验五 4×4 predictions 重叠 PR: {len(overlap)}/{len(sample_pr_ids)}")
        if len(overlap) < len(sample_pr_ids):
            logger.warning(f"  有 {len(sample_pr_ids) - len(overlap)} 个 PR 不在实验五 4×4 predictions 中")

    # 复制到 experiment6
    df.to_csv(EVAL_BALANCED_50, index=False, encoding="utf-8-sig")
    logger.info(f"Balanced-50 已保存: {EVAL_BALANCED_50}")

    return df


def build_balanced_120(df: pd.DataFrame) -> pd.DataFrame:
    """
    构建 Balanced-120 评估子集。

    策略:
      - 60 merged + 60 unmerged
      - 按仓库分层抽样
      - 优先包含有真实 review comments 的样本
    """
    logger.info("=" * 40)
    logger.info("构建 Balanced-120 评估子集")

    merged = df[df["is_merged_bool"] == True].copy()
    unmerged = df[df["is_merged_bool"] == False].copy()

    logger.info(f"  可用: merged={len(merged)}, unmerged={len(unmerged)}")

    n_per_class = BALANCED_SIZE // 2  # 60 each

    # 按仓库分层抽样
    def stratified_sample(sub_df: pd.DataFrame, n: int, label: str) -> pd.DataFrame:
        """按仓库分层，优先选有 review comments 的"""
        repos = sub_df["repo"].unique()
        n_repos = len(repos)
        per_repo = max(1, n // n_repos)
        remaining = n

        sampled = []
        for repo in repos:
            repo_df = sub_df[sub_df["repo"] == repo].copy()
            # 优先选有 review comments 的
            with_review = repo_df[repo_df["has_review"]]
            without_review = repo_df[~repo_df["has_review"]]

            take = min(per_repo, remaining, len(repo_df))
            # 尽量选有 review 的，但保证总数
            n_review = min(len(with_review), max(1, take * 2 // 3))
            n_no_review = take - n_review
            if n_no_review < 0:
                n_review = take
                n_no_review = 0

            repo_sample = pd.concat([
                with_review.sample(n=min(n_review, len(with_review)),
                                   random_state=RANDOM_SEED),
                without_review.sample(n=min(n_no_review, len(without_review)),
                                      random_state=RANDOM_SEED),
            ])
            sampled.append(repo_sample)
            remaining -= len(repo_sample)

        result = pd.concat(sampled) if sampled else pd.DataFrame()
        # 如果还不够，从剩余中随机补
        if len(result) < n and len(sub_df) > len(result):
            extra = sub_df[~sub_df.index.isin(result.index)].sample(
                n=min(n - len(result), len(sub_df) - len(result)),
                random_state=RANDOM_SEED,
            )
            result = pd.concat([result, extra])

        logger.info(f"  {label}: 目标{n}, 实际{len(result)}, "
                    f"含review={result['has_review'].sum()}")
        return result

    merged_sample = stratified_sample(merged, n_per_class, "merged")
    unmerged_sample = stratified_sample(unmerged, n_per_class, "unmerged")

    balanced = pd.concat([merged_sample, unmerged_sample]).sample(
        frac=1, random_state=RANDOM_SEED
    ).reset_index(drop=True)

    logger.info(f"Balanced-120 构建完成: {len(balanced)} 条, "
                f"merged={balanced['is_merged_bool'].sum()}, "
                f"unmerged={(~balanced['is_merged_bool']).sum()}, "
                f"含review={balanced['has_review'].sum()}")
    return balanced


def build_hard_fp_40(df: pd.DataFrame, pred_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    构建 Hard-FP-40 子集。

    从实验五 P2_C3/P2_C4 的 False Positive 中抽取:
      - 真实 unmerged 但模型预测 merged
    """
    logger.info("=" * 40)
    logger.info("构建 Hard-FP-40 子集")

    if pred_df is None:
        logger.warning("无实验五预测数据，从 unmerged 中随机抽取作为 fallback")
        unmerged = df[df["is_merged_bool"] == False]
        sample = unmerged.sample(n=min(HARD_FP_SIZE, len(unmerged)),
                                 random_state=RANDOM_SEED)
        sample.to_csv(EVAL_HARD_FP_40, index=False, encoding="utf-8-sig")
        return sample

    # 找出 FP: 真实 unmerged, 预测 merged
    fp_candidates = set()
    for _, row in pred_df.iterrows():
        is_merged_true = str(row.get("is_merged", "")).lower() in ("true", "1", "yes")
        pred = str(row.get("merge_prediction", "")).lower()
        if not is_merged_true and pred == "merged":
            fp_candidates.add(str(row["pr_id"]))

    logger.info(f"  实验五 FP 候选: {len(fp_candidates)} 个")

    # 从实验五数据集中筛选这些 FP
    df["pr_id_str"] = df["pr_id"].astype(str)
    fp_df = df[df["pr_id_str"].isin(fp_candidates)].copy()

    if len(fp_df) > HARD_FP_SIZE:
        fp_df = fp_df.sample(n=HARD_FP_SIZE, random_state=RANDOM_SEED)
    elif len(fp_df) < HARD_FP_SIZE:
        logger.warning(f"  只有 {len(fp_df)} 个 FP, 补充 unmerged 样本")
        unmerged = df[(df["is_merged_bool"] == False) & (~df["pr_id_str"].isin(fp_candidates))]
        extra = unmerged.sample(n=min(HARD_FP_SIZE - len(fp_df), len(unmerged)),
                                random_state=RANDOM_SEED)
        fp_df = pd.concat([fp_df, extra])

    logger.info(f"Hard-FP-40 构建完成: {len(fp_df)} 条")
    return fp_df


def compute_sample_stats(df: pd.DataFrame, balanced: pd.DataFrame,
                         hard_fp: pd.DataFrame) -> Dict:
    """计算样本统计"""
    stats = {
        "full_dataset": {
            "total": len(df),
            "merged": int(df["is_merged_bool"].sum()),
            "unmerged": int((~df["is_merged_bool"]).sum()),
            "merge_rate": round(float(df["is_merged_bool"].mean()), 4),
            "with_review": int(df["has_review"].sum()),
            "repos": df["repo"].value_counts().to_dict(),
        },
        "balanced_120": {
            "total": len(balanced),
            "merged": int(balanced["is_merged_bool"].sum()),
            "unmerged": int((~balanced["is_merged_bool"]).sum()),
            "with_review": int(balanced["has_review"].sum()),
            "repos": balanced["repo"].value_counts().to_dict(),
        },
        "hard_fp_40": {
            "total": len(hard_fp),
            "merged": int(hard_fp["is_merged_bool"].sum()),
            "unmerged": int((~hard_fp["is_merged_bool"]).sum()),
            "repos": hard_fp["repo"].value_counts().to_dict(),
        },
    }
    return stats


def compute_baseline_on_subset(eval_df: pd.DataFrame, pred_df: Optional[pd.DataFrame],
                                label: str) -> Dict:
    """
    在评估子集上重新计算实验五基线指标。

    重要：不能在 full-343 上算完直接比较，必须用同一子集。
    """
    if pred_df is None:
        return {}

    eval_ids = set(eval_df["pr_id"].astype(str))
    sub_pred = pred_df[pred_df["pr_id"].astype(str).isin(eval_ids)].copy()

    if sub_pred.empty:
        logger.warning(f"  {label}: 无匹配预测")
        return {}

    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score,
        f1_score, roc_auc_score, confusion_matrix,
    )

    baselines = {}
    for (pt, ct), group in sub_pred.groupby(["prompt_type", "context_type"]):
        group_valid = group[group["parse_success"] == True].copy()
        if group_valid.empty:
            continue

        key = f"{pt}_{ct}"
        y_true = group_valid["is_merged"].astype(int).values
        y_pred = (group_valid["merge_prediction"].str.lower() == "merged").astype(int).values

        try:
            prob = group_valid["merge_probability"].fillna(0.5)
            auc = roc_auc_score(y_true, prob)
        except Exception:
            auc = None

        cm = confusion_matrix(y_true, y_pred)
        tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0

        baselines[key] = {
            "prompt_type": pt,
            "context_type": ct,
            "n_valid": len(group_valid),
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
            "roc_auc": round(float(auc), 4) if auc else None,
            "specificity": round(float(specificity), 4),
            "balanced_accuracy": round(float((recall_score(y_true, y_pred, zero_division=0) + specificity) / 2), 4),
            "fpr": round(float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0, 4),
            "confusion_matrix": cm.tolist(),
        }
        logger.info(f"  {label} 基线 {key}: Acc={baselines[key]['accuracy']:.4f}, "
                    f"F1={baselines[key]['f1']:.4f}, AUC={baselines[key]['roc_auc']}, "
                    f"Specificity={baselines[key]['specificity']:.4f}")

    return baselines


def prepare_samples() -> bool:
    """准备评估样本 (主入口)"""
    logger.info("=" * 60)
    logger.info("阶段: 构建评估子集")
    logger.info("=" * 60)

    # 0. 构建 Balanced-50 (主实验样本，复用实验五)
    balanced_50 = build_balanced_50()

    # 1. 加载数据
    df = load_exp5_data()
    pred_df = load_exp5_predictions()

    # 2. 构建验证子集
    balanced_120 = build_balanced_120(df)
    hard_fp = build_hard_fp_40(df, pred_df)

    # 3. 保存
    balanced_120.to_csv(EVAL_BALANCED_120, index=False, encoding="utf-8-sig")
    logger.info(f"Balanced-120 已保存: {EVAL_BALANCED_120}")

    hard_fp.to_csv(EVAL_HARD_FP_40, index=False, encoding="utf-8-sig")
    logger.info(f"Hard-FP-40 已保存: {EVAL_HARD_FP_40}")

    # 4. 统计
    stats = compute_sample_stats(df, balanced_120, hard_fp)

    # 添加 Balanced-50 统计
    stats["balanced_50"] = {
        "total": len(balanced_50),
        "merged": int(balanced_50["is_merged_bool"].sum()),
        "unmerged": int((~balanced_50["is_merged_bool"]).sum()),
        "repos": balanced_50["repo"].value_counts().to_dict(),
        "source": "experiment5/ai_llm_sample_50.csv",
    }

    # 5. 子集基线
    stats["baseline_balanced_120"] = compute_baseline_on_subset(balanced_120, pred_df, "Balanced-120")
    stats["baseline_hard_fp"] = compute_baseline_on_subset(hard_fp, pred_df, "Hard-FP-40")

    with open(EVAL_SAMPLE_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    logger.info(f"样本统计已保存: {EVAL_SAMPLE_STATS}")

    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    prepare_samples()
