"""
评估模块 — 对比人类代码 vs AI 代码性能

输入:
  - traditional_ml_predictions.csv
  - llm_parsed_predictions.csv
  - experiment2/results/evaluation/metrics_main.json (人类代码指标)
  - experiment4/results/evaluation/metrics_by_prompt_context.json (人类代码DeepSeek指标)

输出:
  - results/evaluation/traditional_ml_metrics.json
  - results/evaluation/llm_metrics.json
  - results/evaluation/human_vs_ai_comparison.json
  - results/evaluation/comment_generation_metrics.json
  - results/evaluation/error_analysis.json
"""

import json
import os
import sys
from typing import Dict, Any

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    EXPERIMENT2_DIR,
    EXPERIMENT4_DIR,
    RESULTS_PROCESSED_DIR,
    RESULTS_EVALUATION_DIR,
    logger,
)

PREDICTIONS_DIR = os.path.join(os.path.dirname(RESULTS_PROCESSED_DIR), "predictions")

ML_PREDICTIONS_CSV = os.path.join(PREDICTIONS_DIR, "traditional_ml_predictions.csv")
LLM_PARSED = os.path.join(PREDICTIONS_DIR, "llm_parsed_predictions.csv")
LLM_RAW = os.path.join(PREDICTIONS_DIR, "llm_raw_responses.jsonl")

EXP2_METRICS = os.path.join(EXPERIMENT2_DIR, "results", "evaluation", "metrics_main.json")
EXP4_METRICS = os.path.join(EXPERIMENT4_DIR, "results", "evaluation", "metrics_by_prompt_context.json")
EXP4_COMMENT = os.path.join(EXPERIMENT4_DIR, "results", "evaluation", "comment_generation_metrics.json")

OUT_ML_METRICS = os.path.join(RESULTS_EVALUATION_DIR, "traditional_ml_metrics.json")
OUT_LLM_METRICS = os.path.join(RESULTS_EVALUATION_DIR, "llm_metrics.json")
OUT_COMPARISON = os.path.join(RESULTS_EVALUATION_DIR, "human_vs_ai_comparison.json")
OUT_COMMENT = os.path.join(RESULTS_EVALUATION_DIR, "comment_generation_metrics.json")
OUT_ERROR = os.path.join(RESULTS_EVALUATION_DIR, "error_analysis.json")
OUT_4X4_METRICS = os.path.join(RESULTS_EVALUATION_DIR, "llm_4x4_metrics.json")


def load_json_safe(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_ml() -> Dict:
    """评估传统 ML 在 AI PR 上的表现"""
    logger.info("评估传统 ML...")
    if not os.path.exists(ML_PREDICTIONS_CSV):
        logger.warning(f"ML 预测文件未找到: {ML_PREDICTIONS_CSV}")
        return {}

    df = pd.read_csv(ML_PREDICTIONS_CSV, encoding="utf-8-sig")
    y_true = df["is_merged"].astype(int).values

    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score,
        f1_score, roc_auc_score, confusion_matrix,
    )

    metrics = {}
    for model_col, prob_col in [("svm_prediction", "svm_probability"),
                                  ("rf_prediction", "rf_probability")]:
        if model_col not in df.columns:
            continue
        model_name = "svm" if "svm" in model_col else "randomforest"
        y_pred = df[model_col].astype(int).values

        try:
            auc = roc_auc_score(y_true, df[prob_col].fillna(0.5))
        except Exception:
            auc = None

        cm = confusion_matrix(y_true, y_pred)
        metrics[model_name] = {
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
            "roc_auc": round(float(auc), 4) if auc else None,
            "confusion_matrix": cm.tolist(),
            "n_samples": len(y_true),
        }

    with open(OUT_ML_METRICS, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    logger.info(f"ML 指标已保存: {OUT_ML_METRICS}")
    return metrics


def evaluate_llm() -> Dict:
    """评估 LLM 在 AI PR 上的表现"""
    logger.info("评估 LLM...")

    # 使用 llm_runner 中的 compute 函数
    from llm_runner import compute_llm_metrics
    metrics = compute_llm_metrics()
    if not metrics:
        logger.warning("无 LLM 指标数据")
    return metrics


def _calculate_bleu(reference: str, candidate: str) -> float:
    """简化 BLEU-1 计算"""
    if not reference or not candidate:
        return 0.0
    ref_tokens = reference.lower().split()
    cand_tokens = candidate.lower().split()
    if not cand_tokens:
        return 0.0
    matches = sum(1 for t in cand_tokens if t in ref_tokens)
    return matches / len(cand_tokens)


def _longest_common_subsequence(a: list, b: list) -> int:
    """LCS 长度"""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            if a[i] == b[j]:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])
    return dp[m][n]


def evaluate_comment_generation() -> Dict:
    """评估 Review Comment Generation"""
    logger.info("评估 Comment Generation...")
    if not os.path.exists(LLM_RAW):
        logger.warning("LLM raw responses 不存在")
        return {}

    # 加载数据
    ai_df = pd.read_csv(
        os.path.join(RESULTS_PROCESSED_DIR, "ai_generated_dataset.csv"),
        encoding="utf-8-sig",
    )
    real_reviews = {}
    for _, row in ai_df.iterrows():
        text = row.get("review_comments_text", "")
        # 过滤 NaN/空/nan 字符串
        if pd.isna(text) or str(text).strip().lower() in ("", "nan", "none"):
            real_reviews[str(row["pr_id"])] = ""
        else:
            real_reviews[str(row["pr_id"])] = str(text)

    results = {}
    with open(LLM_RAW, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            pr_id = str(rec.get("pr_id", ""))
            combo = f"{rec.get('prompt_type', '')}_{rec.get('context_type', '')}"
            parsed = rec.get("parsed_data") or {}
            gen_comments = parsed.get("review_comments", [])

            if combo not in results:
                results[combo] = {"bleu_scores": [], "rouge1": [], "rouge2": [], "rougeL": [],
                                  "n_generated": 0, "n_with_real": 0}

            real_text = real_reviews.get(pr_id, "")
            if not real_text:
                continue

            results[combo]["n_with_real"] += 1
            gen_text = " ".join([c.get("comment", "") for c in gen_comments])
            if not gen_text:
                continue

            results[combo]["bleu_scores"].append(_calculate_bleu(real_text, gen_text))
            results[combo]["n_generated"] += 1

            # ROUGE
            ref_words = real_text.lower().split()
            gen_words = gen_text.lower().split()

            if gen_words and ref_words:
                # ROUGE-1
                overlap_1 = len(set(gen_words) & set(ref_words))
                results[combo]["rouge1"].append(overlap_1 / len(gen_words))

                # ROUGE-2
                gen_bigrams = set(zip(gen_words, gen_words[1:]))
                ref_bigrams = set(zip(ref_words, ref_words[1:]))
                if gen_bigrams:
                    results[combo]["rouge2"].append(len(gen_bigrams & ref_bigrams) / len(gen_bigrams))
                else:
                    results[combo]["rouge2"].append(0.0)

                # ROUGE-L
                lcs = _longest_common_subsequence(ref_words, gen_words)
                results[combo]["rougeL"].append(lcs / len(gen_words) if gen_words else 0.0)

    # 聚合
    aggregated = {}
    for combo, vals in results.items():
        aggregated[combo] = {
            "avg_bleu": round(float(np.mean(vals["bleu_scores"])), 4) if vals["bleu_scores"] else 0.0,
            "avg_rouge1": round(float(np.mean(vals["rouge1"])), 4) if vals["rouge1"] else 0.0,
            "avg_rouge2": round(float(np.mean(vals["rouge2"])), 4) if vals["rouge2"] else 0.0,
            "avg_rougeL": round(float(np.mean(vals["rougeL"])), 4) if vals["rougeL"] else 0.0,
            "n_generated": vals["n_generated"],
            "n_with_real": vals["n_with_real"],
        }

    with open(OUT_COMMENT, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)
    logger.info(f"Comment Generation 指标已保存: {OUT_COMMENT}")
    return aggregated


def compare_human_vs_ai() -> Dict:
    """对比人类代码 vs AI 代码性能"""
    logger.info("对比人类 vs AI 代码...")
    comparison = {
        "traditional_ml": {},
        "llm": {},
        "note": "实验三 (Code2Vec/CodeBERT) 未实现，标记为 N/A",
        "experiment3_status": "N/A (not implemented)",
    }

    # 人类代码指标
    exp2_metrics = load_json_safe(EXP2_METRICS)
    exp4_metrics = load_json_safe(EXP4_METRICS)

    # AI 代码指标
    ml_ai = load_json_safe(OUT_ML_METRICS)
    llm_ai = load_json_safe(OUT_LLM_METRICS)

    # 对比传统 ML — 实验二指标嵌套在 test_metrics 下, key 是 random_forest
    ml_key_map = {"svm": "svm", "randomforest": "random_forest"}
    for model_name, exp2_key in ml_key_map.items():
        exp2_entry = exp2_metrics.get(exp2_key, {})
        human_metrics = exp2_entry.get("test_metrics", {}) if isinstance(exp2_entry, dict) else {}
        human_f1 = human_metrics.get("f1_score", human_metrics.get("f1", 0)) or 0
        human_acc = human_metrics.get("accuracy", 0) or 0
        human_auc = human_metrics.get("roc_auc", 0) or 0
        ai_metrics = ml_ai.get(model_name, {})
        ai_f1 = ai_metrics.get("f1", 0) or 0
        ai_acc = ai_metrics.get("accuracy", 0) or 0
        ai_auc = ai_metrics.get("roc_auc", 0) or 0
        if human_metrics and ai_metrics:
            comparison["traditional_ml"][model_name] = {
                "human_test": {
                    "accuracy": human_acc,
                    "f1": human_f1,
                    "roc_auc": human_auc,
                },
                "ai_test": {
                    "accuracy": ai_acc,
                    "f1": ai_f1,
                    "roc_auc": ai_auc,
                },
                "delta_accuracy": round(ai_acc - human_acc, 4),
                "delta_f1": round(ai_f1 - human_f1, 4),
                "delta_roc_auc": round(ai_auc - human_auc, 4),
            }

    # 对比 LLM (P2_C3)
    for combo in ["P2_C3", "P2_C4"]:
        human_llm = exp4_metrics.get(combo, {})
        ai_llm = llm_ai.get(combo, {})
        if human_llm and ai_llm:
            comparison["llm"][combo] = {
                "human_sample_50": {
                    "accuracy": human_llm.get("accuracy"),
                    "f1": human_llm.get("f1"),
                    "roc_auc": human_llm.get("roc_auc"),
                },
                "ai_test": {
                    "accuracy": ai_llm.get("accuracy"),
                    "f1": ai_llm.get("f1"),
                    "roc_auc": ai_llm.get("roc_auc"),
                },
                "delta_accuracy": round(float(ai_llm.get("accuracy", 0)) -
                                        float(human_llm.get("accuracy", 0)), 4),
                "delta_f1": round(float(ai_llm.get("f1", 0)) -
                                  float(human_llm.get("f1", 0)), 4),
            }

    with open(OUT_COMPARISON, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    logger.info(f"对比报告已保存: {OUT_COMPARISON}")
    return comparison


def analyze_errors() -> Dict:
    """错误分析"""
    logger.info("错误分析...")
    if not os.path.exists(ML_PREDICTIONS_CSV):
        return {}

    df = pd.read_csv(ML_PREDICTIONS_CSV, encoding="utf-8-sig")
    ai_df = pd.read_csv(
        os.path.join(RESULTS_PROCESSED_DIR, "ai_generated_dataset.csv"),
        encoding="utf-8-sig",
    )

    # 合并
    # 统一 pr_id 类型再合并
    df["pr_id_str"] = df["pr_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    ai_df["pr_id_str"] = ai_df["pr_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    merged = df.merge(ai_df[["pr_id_str", "num_changed_files", "total_additions",
                              "total_deletions"]],
                      on="pr_id_str", how="left")

    errors = {}
    for model_col in ["svm_prediction", "rf_prediction"]:
        if model_col not in merged.columns:
            continue
        model_name = "svm" if "svm" in model_col else "randomforest"
        y_true = merged["is_merged"].astype(int)
        y_pred = merged[model_col].astype(int)

        fp_mask = (y_true == 0) & (y_pred == 1)
        fn_mask = (y_true == 1) & (y_pred == 0)

        fp = merged[fp_mask]
        fn = merged[fn_mask]
        all_data = merged

        errors[model_name] = {
            "false_positives": int(fp_mask.sum()),
            "false_negatives": int(fn_mask.sum()),
            "fp_avg_changed_files": round(float(fp["num_changed_files"].mean()), 1) if len(fp) > 0 else 0,
            "fn_avg_changed_files": round(float(fn["num_changed_files"].mean()), 1) if len(fn) > 0 else 0,
            "fp_avg_additions": round(float(fp["total_additions"].mean()), 1) if len(fp) > 0 else 0,
            "fn_avg_additions": round(float(fn["total_additions"].mean()), 1) if len(fn) > 0 else 0,
            "fp_repos": fp["repo"].value_counts().to_dict() if len(fp) > 0 else {},
            "fn_repos": fn["repo"].value_counts().to_dict() if len(fn) > 0 else {},
            "overall_avg_files": round(float(all_data["num_changed_files"].mean()), 1),
            "overall_avg_additions": round(float(all_data["total_additions"].mean()), 1),
        }

    with open(OUT_ERROR, "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)
    logger.info(f"错误分析已保存: {OUT_ERROR}")
    return errors


def run_evaluation() -> bool:
    """运行全部评估"""
    logger.info("=" * 60)
    logger.info("阶段: 评估与对比")
    logger.info("=" * 60)

    evaluate_ml()
    evaluate_llm()
    evaluate_comment_generation()
    compare_human_vs_ai()
    analyze_errors()

    # 2.6.2 4×4 评估
    try:
        from llm_4x4_runner import compute_4x4_metrics, generate_4x4_heatmap
        logger.info("评估 4×4 Prompt×Context 全组合...")
        compute_4x4_metrics()
        generate_4x4_heatmap()
    except ImportError:
        logger.info("4×4 模块不可用，跳过")
    except Exception as e:
        logger.warning(f"4×4 评估失败: {e}")

    logger.info("=" * 60)
    logger.info("评估完成")
    return True


if __name__ == "__main__":
    run_evaluation()
