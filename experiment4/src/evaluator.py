"""
实验三 步骤五：评估
计算 Merge Prediction 和 Review Comment Generation 指标。
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

from config import (
    PARSED_PREDICTIONS_CSV, RAW_RESPONSES_JSONL,
    METRICS_BY_PROMPT_CONTEXT_JSON, COMMENT_GENERATION_METRICS_JSON,
    EVALUATION_DIR, PROMPT_TYPES, CONTEXT_TYPES,
)
from utils import log, read_jsonl, write_json


def load_data():
    """加载解析后的预测和原始数据。"""
    pred_df = pd.read_csv(PARSED_PREDICTIONS_CSV)
    log.info(f"加载预测数据: {len(pred_df)} 条")

    # 加载原始响应（包含完整的 parsed_data 用于 review comments）
    responses = read_jsonl(RAW_RESPONSES_JSONL)
    log.info(f"加载原始响应: {len(responses)} 条")

    return pred_df, responses


# ============================================================
# Merge Prediction 指标
# ============================================================
def safe_float(val, default=np.nan):
    """安全转换为 float。"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def compute_merge_metrics(y_true: np.ndarray, y_pred: np.ndarray,
                          y_prob: np.ndarray = None) -> dict:
    """计算合并预测指标。"""
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        roc_auc_score, confusion_matrix,
    )

    metrics = {}

    # 基本指标
    metrics["accuracy"] = float(accuracy_score(y_true, y_pred))
    metrics["precision"] = float(precision_score(y_true, y_pred, zero_division=0))
    metrics["recall"] = float(recall_score(y_true, y_pred, zero_division=0))
    metrics["f1"] = float(f1_score(y_true, y_pred, zero_division=0))

    # ROC-AUC
    if y_prob is not None and len(set(y_true)) > 1:
        try:
            metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
        except Exception:
            metrics["roc_auc"] = None
    else:
        metrics["roc_auc"] = None

    # 混淆矩阵
    cm = confusion_matrix(y_true, y_pred)
    metrics["confusion_matrix"] = cm.tolist()
    metrics["tn"] = int(cm[0][0]) if cm.shape == (2, 2) else 0
    metrics["fp"] = int(cm[0][1]) if cm.shape == (2, 2) else 0
    metrics["fn"] = int(cm[1][0]) if cm.shape == (2, 2) else 0
    metrics["tp"] = int(cm[1][1]) if cm.shape == (2, 2) else 0

    return metrics


def evaluate_merge_prediction(pred_df: pd.DataFrame) -> dict:
    """对 16 个 Prompt × Context 组合分别计算 Merge Prediction 指标。"""
    log.info("=" * 40)
    log.info("Merge Prediction 评估")
    log.info("=" * 40)

    # 过滤出解析成功的行
    valid_df = pred_df[pred_df["parse_success"] == True].copy()

    # 转换预测值
    valid_df["pred_binary"] = valid_df["merge_prediction"].apply(
        lambda x: 1 if str(x).lower() in ("merged", "1", "true") else 0
    )
    valid_df["y_true"] = valid_df["is_merged"].astype(int)

    results = {}
    all_combinations = []

    for prompt_type in PROMPT_TYPES:
        for context_type in CONTEXT_TYPES:
            subset = valid_df[
                (valid_df["prompt_type"] == prompt_type) &
                (valid_df["context_type"] == context_type)
            ]

            n = len(subset)
            if n == 0:
                log.warning(f"  {prompt_type}/{context_type}: 无有效数据")
                continue

            y_true = subset["y_true"].values
            y_pred = subset["pred_binary"].values
            y_prob = subset["merge_probability"].apply(
                lambda x: safe_float(x)
            ).values

            metrics = compute_merge_metrics(y_true, y_pred, y_prob)

            # 额外统计
            avg_prob = np.nanmean([
                safe_float(p) for p in subset["merge_probability"]
            ])
            avg_duration = subset["duration_ms"].mean() if "duration_ms" in subset else 0
            parse_fail = pred_df[
                (pred_df["prompt_type"] == prompt_type) &
                (pred_df["context_type"] == context_type) &
                (pred_df["parse_success"] != True)
            ]
            parse_fail_rate = len(parse_fail) / max(n + len(parse_fail), 1)

            combo_result = {
                "prompt_type": prompt_type,
                "context_type": context_type,
                "n_valid": n,
                "n_total": n + len(parse_fail),
                "parse_fail_rate": round(parse_fail_rate, 4),
                "avg_probability": round(avg_prob, 4),
                "avg_duration_ms": round(avg_duration, 0),
                **metrics,
            }

            all_combinations.append(combo_result)
            key = f"{prompt_type}_{context_type}"
            results[key] = combo_result

            log.info(f"  {prompt_type}/{context_type}: "
                     f"acc={metrics['accuracy']:.4f}, "
                     f"f1={metrics['f1']:.4f}, "
                     f"auc={metrics.get('roc_auc')}, "
                     f"n={n}")

    # 找出最佳组合
    best = max(all_combinations, key=lambda x: x.get("f1", 0))
    log.info(f"\n最佳 F1: {best['prompt_type']}/{best['context_type']} "
             f"(F1={best['f1']:.4f})")

    if any(c.get("roc_auc") is not None for c in all_combinations):
        best_auc = max(
            (c for c in all_combinations if c.get("roc_auc") is not None),
            key=lambda x: x.get("roc_auc", 0)
        )
        log.info(f"最佳 ROC-AUC: {best_auc['prompt_type']}/{best_auc['context_type']} "
                 f"(AUC={best_auc['roc_auc']:.4f})")

    return results


# ============================================================
# Review Comment Generation 指标
# ============================================================
def safe_str_val(val) -> str:
    """安全转换为字符串。"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    return str(val)


def extract_review_comments(parsed_data: dict) -> list:
    """从解析后的数据中提取 review comments 列表。"""
    if parsed_data is None:
        return []
    comments = parsed_data.get("review_comments", [])
    if isinstance(comments, list):
        return comments
    return []


def compute_bleu(reference: str, candidate: str) -> float:
    """计算 BLEU 分数（简化的独立实现）。"""
    ref_words = reference.lower().split()
    cand_words = candidate.lower().split()
    if not cand_words or not ref_words:
        return 0.0

    # 简化 BLEU: 1-gram 到 4-gram 的几何平均
    max_n = min(4, len(cand_words), len(ref_words))
    scores = []
    for n in range(1, max_n + 1):
        ref_ngrams = _get_ngrams(ref_words, n)
        cand_ngrams = _get_ngrams(cand_words, n)
        if not cand_ngrams:
            scores.append(0)
            continue
        matches = sum(1 for ng in cand_ngrams if ng in ref_ngrams)
        scores.append(matches / len(cand_ngrams))

    if not scores:
        return 0.0
    # 几何平均
    import math
    bleu = math.exp(sum(math.log(max(s, 1e-10)) for s in scores) / len(scores))
    # 长度惩罚
    if len(cand_words) < len(ref_words):
        bleu *= math.exp(1 - len(ref_words) / max(len(cand_words), 1))
    return round(float(bleu), 4)


def _get_ngrams(words: list, n: int) -> list:
    """提取 n-grams。"""
    return [tuple(words[i:i+n]) for i in range(len(words) - n + 1)]


def compute_rouge(reference: str, candidate: str) -> dict:
    """计算 ROUGE 分数（简化实现）。"""
    ref_words = reference.lower().split()
    cand_words = candidate.lower().split()

    if not ref_words or not cand_words:
        return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}

    # ROUGE-1: unigram overlap
    ref_unigrams = set(ref_words)
    cand_unigrams = set(cand_words)
    overlap_1 = len(ref_unigrams & cand_unigrams)
    rouge1_r = overlap_1 / len(ref_unigrams) if ref_unigrams else 0
    rouge1_p = overlap_1 / len(cand_unigrams) if cand_unigrams else 0
    rouge1 = 2 * rouge1_r * rouge1_p / (rouge1_r + rouge1_p) if (rouge1_r + rouge1_p) > 0 else 0

    # ROUGE-2: bigram overlap
    ref_bigrams = set(zip(ref_words, ref_words[1:]))
    cand_bigrams = set(zip(cand_words, cand_words[1:]))
    overlap_2 = len(ref_bigrams & cand_bigrams)
    rouge2_r = overlap_2 / len(ref_bigrams) if ref_bigrams else 0
    rouge2_p = overlap_2 / len(cand_bigrams) if cand_bigrams else 0
    rouge2 = 2 * rouge2_r * rouge2_p / (rouge2_r + rouge2_p) if (rouge2_r + rouge2_p) > 0 else 0

    # ROUGE-L: longest common subsequence
    lcs_len = _lcs_length(ref_words, cand_words)
    rougeL_r = lcs_len / len(ref_words) if ref_words else 0
    rougeL_p = lcs_len / len(cand_words) if cand_words else 0
    rougeL = 2 * rougeL_r * rougeL_p / (rougeL_r + rougeL_p) if (rougeL_r + rougeL_p) > 0 else 0

    return {
        "rouge1": round(float(rouge1), 4),
        "rouge2": round(float(rouge2), 4),
        "rougeL": round(float(rougeL), 4),
    }


def _lcs_length(a: list, b: list) -> int:
    """最长公共子序列长度（DP）。"""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    # 使用 O(min(m,n)) 空间
    if m < n:
        a, b = b, a
        m, n = n, m
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, prev
    return prev[n]


def evaluate_comment_generation(pred_df: pd.DataFrame, responses: list) -> dict:
    """
    评价 Review Comment Generation。
    只在真实 review_comments_text 非空的样本上计算。
    """
    log.info("=" * 40)
    log.info("Review Comment Generation 评估")
    log.info("=" * 40)

    # 需要原始数据集来获取真实 review_comments_text
    from config import PROCESSED_DIR
    human_df = pd.read_csv(PROCESSED_DIR / "llm_sample_50.csv")

    # 建立 pr_id → 真实 review text 的映射
    pr_to_real_review = {}
    for _, row in human_df.iterrows():
        text = safe_str_val(row.get("review_comments_text"))
        if text.strip():
            pr_to_real_review[row["pr_id"]] = text

    log.info(f"有真实 review text 的 PR: {len(pr_to_real_review)}")

    # 为每个组合计算指标
    results = {}
    all_bleu_rouge = []

    for prompt_type in PROMPT_TYPES:
        for context_type in CONTEXT_TYPES:
            combo_responses = [
                r for r in responses
                if r["prompt_type"] == prompt_type and
                   r["context_type"] == context_type and
                   r.get("parse_success") and
                   str(r["pr_id"]) in {
                       str(pid) for pid in pr_to_real_review
                   }
            ]

            if not combo_responses:
                continue

            bleu_scores = []
            rouge1_scores = []
            rouge2_scores = []
            rougeL_scores = []
            total_generated = 0
            severity_dist = defaultdict(int)

            for r in combo_responses:
                pr_id = r["pr_id"]
                real_review = pr_to_real_review.get(pr_id)
                if not real_review:
                    continue

                parsed = r.get("parsed_data") or {}
                comments = extract_review_comments(parsed)

                # 将所有生成的评论合并为一个文本用于 BLEU/ROUGE
                generated_text = " ".join(
                    c.get("comment", "") for c in comments
                )

                if generated_text.strip():
                    bleu = compute_bleu(real_review, generated_text)
                    rouge = compute_rouge(real_review, generated_text)
                    bleu_scores.append(bleu)
                    rouge1_scores.append(rouge["rouge1"])
                    rouge2_scores.append(rouge["rouge2"])
                    rougeL_scores.append(rouge["rougeL"])

                total_generated += len(comments)
                for c in comments:
                    severity_dist[c.get("severity", "unknown")] += 1

            key = f"{prompt_type}_{context_type}"
            combo_metrics = {
                "prompt_type": prompt_type,
                "context_type": context_type,
                "n_samples": len(combo_responses),
                "avg_bleu": round(np.mean(bleu_scores), 4) if bleu_scores else 0,
                "avg_rouge1": round(np.mean(rouge1_scores), 4) if rouge1_scores else 0,
                "avg_rouge2": round(np.mean(rouge2_scores), 4) if rouge2_scores else 0,
                "avg_rougeL": round(np.mean(rougeL_scores), 4) if rougeL_scores else 0,
                "avg_generated_comments": round(
                    total_generated / max(len(combo_responses), 1), 2
                ),
                "severity_distribution": dict(severity_dist),
            }
            results[key] = combo_metrics
            all_bleu_rouge.append(combo_metrics)

            log.info(f"  {prompt_type}/{context_type}: "
                     f"BLEU={combo_metrics['avg_bleu']:.4f}, "
                     f"ROUGE-L={combo_metrics['avg_rougeL']:.4f}, "
                     f"avg_comments={combo_metrics['avg_generated_comments']}")

    # 额外统计
    extra_stats = _compute_extra_comment_stats(responses, pr_to_real_review)

    return {
        "per_combination": results,
        "extra_statistics": extra_stats,
    }


def _compute_extra_comment_stats(responses: list,
                                  pr_to_real_review: dict) -> dict:
    """计算评论生成的额外统计。"""
    # 统计空参考样本是否仍生成评论
    pr_with_review = set(pr_to_real_review.keys())
    all_pr_ids = set(r["pr_id"] for r in responses)

    empty_ref_prs = all_pr_ids - pr_with_review
    generated_on_empty = 0
    total_on_empty = 0
    for r in responses:
        if r["pr_id"] in empty_ref_prs and r.get("parse_success"):
            total_on_empty += 1
            parsed = r.get("parsed_data") or {}
            comments = extract_review_comments(parsed)
            if comments:
                generated_on_empty += 1

    # 总体 severity 分布
    severity_total = defaultdict(int)
    total_comments = 0
    for r in responses:
        if r.get("parse_success"):
            parsed = r.get("parsed_data") or {}
            comments = extract_review_comments(parsed)
            for c in comments:
                severity_total[c.get("severity", "unknown")] += 1
                total_comments += 1

    return {
        "total_pr_with_real_review": len(pr_with_review),
        "empty_ref_prs_generated_comments": generated_on_empty,
        "empty_ref_prs_total": total_on_empty,
        "overall_severity_distribution": dict(severity_total),
        "overall_total_comments": total_comments,
        "avg_comments_per_response": round(
            total_comments / max(len([r for r in responses if r.get("parse_success")]), 1), 2
        ),
    }


def find_best_examples(responses: list, pr_to_real_review: dict,
                       n: int = 3) -> list:
    """找出最佳生成样例（BLEU 最高）。"""
    scored = []
    for r in responses:
        if not r.get("parse_success"):
            continue
        pr_id = r["pr_id"]
        real = pr_to_real_review.get(pr_id)
        if not real:
            continue
        parsed = r.get("parsed_data") or {}
        comments = extract_review_comments(parsed)
        generated = " ".join(c.get("comment", "") for c in comments)
        if generated.strip():
            bleu = compute_bleu(real, generated)
            scored.append({
                "pr_id": pr_id,
                "prompt_type": r["prompt_type"],
                "context_type": r["context_type"],
                "bleu": round(bleu, 4),
                "real_review": real[:500],
                "generated_review": generated[:500],
            })

    scored.sort(key=lambda x: x["bleu"], reverse=True)
    return scored[:n]


def run(pred_df: pd.DataFrame = None, responses: list = None):
    """主入口：运行所有评估。"""
    log.info("=" * 60)
    log.info("步骤五：评估")
    log.info("=" * 60)

    if pred_df is None:
        pred_df, responses = load_data()
    elif responses is None:
        _, responses = load_data()

    # 1. Merge Prediction 指标
    merge_metrics = evaluate_merge_prediction(pred_df)
    merge_path = METRICS_BY_PROMPT_CONTEXT_JSON
    write_json(merge_metrics, merge_path)
    log.info(f"Merge 指标已保存: {merge_path}")

    # 2. Review Comment Generation 指标
    comment_metrics = evaluate_comment_generation(pred_df, responses)
    comment_path = COMMENT_GENERATION_METRICS_JSON
    write_json(comment_metrics, comment_path)
    log.info(f"评论生成指标已保存: {comment_path}")

    # 3. 找最佳生成样例
    from config import PROCESSED_DIR
    human_df = pd.read_csv(PROCESSED_DIR / "llm_sample_50.csv")
    pr_to_real_review = {}
    for _, row in human_df.iterrows():
        text = safe_str_val(row.get("review_comments_text"))
        if text.strip():
            pr_to_real_review[row["pr_id"]] = text

    best_examples = find_best_examples(responses, pr_to_real_review, n=3)
    examples_path = EVALUATION_DIR / "best_generated_examples.json"
    write_json(best_examples, examples_path)
    log.info(f"最佳生成样例已保存: {examples_path}")

    return merge_metrics, comment_metrics


if __name__ == "__main__":
    from utils import setup_logger
    log = setup_logger("experiment3", EVALUATION_DIR.parent / "pipeline.log")
    run()
