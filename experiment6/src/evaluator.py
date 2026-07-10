"""
评估模块 — 计算实验六分类指标、评论质量、与实验五对比

核心关注:
  - Specificity (识别 unmerged 的能力)
  - Balanced Accuracy
  - False Positive Rate
  - ROC-AUC 和 PR-AUC
  - Risk Coverage / Actionability Rate / Specificity Rate
"""

import json
import os
import re
import sys
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    EXP5_DATASET_CSV,
    EXP5_LLM_PARSED,
    EXP5_LLM_METRICS,
    EXP5_4X4_METRICS,
    EXP5_4X4_PARSED,
    EVAL_BALANCED_50,
    EVAL_BALANCED_120,
    EVAL_HARD_FP_40,
    EVAL_SAMPLE_STATS,
    RAW_RESPONSES,
    PARSED_PREDICTIONS,
    IMPROVED_4X4_RAW,
    IMPROVED_4X4_PARSED,
    IMPROVED_4X4_METRICS,
    ALL_32_COMBO_METRICS,
    BASELINE_VS_IMPROVED_SUMMARY,
    COMMENT_GENERATION_METRICS,
    METRICS_BALANCED,
    METRICS_HARD_FP,
    COMMENT_QUALITY,
    BASELINE_COMPARISON,
    BEST_METHOD_SUMMARY,
    BASELINE_COMBOS,
    IMPROVED_COMBOS,
    METHOD_COMBOS,
    logger,
)


def load_json_safe(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 分类指标
# ============================================================
def compute_classification_metrics(pred_df: pd.DataFrame, label: str) -> Dict:
    """
    计算完整分类指标。

    必须报告:
      - Accuracy, Precision, Recall, F1
      - ROC-AUC, PR-AUC
      - Specificity, Balanced Accuracy, FPR
      - Confusion Matrix
    """
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score,
        f1_score, roc_auc_score, average_precision_score,
        confusion_matrix,
    )

    all_metrics = {}
    for method_id, group in pred_df.groupby("method_id"):
        group_valid = group[group["parse_success"] == True].copy()
        group_with_prob = group_valid[group_valid["merge_probability"].notna()].copy()

        if group_valid.empty:
            continue

        y_true = group_valid["is_merged"].astype(int).values
        y_pred = (group_valid["merge_prediction"].str.lower() == "merged").astype(int).values

        cm = confusion_matrix(y_true, y_pred)
        if cm.size == 4:
            tn, fp, fn, tp = cm.ravel()
        else:
            tn = fp = fn = tp = 0

        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        balanced_acc = (recall_score(y_true, y_pred, zero_division=0) + specificity) / 2
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        recall_val = recall_score(y_true, y_pred, zero_division=0)

        # ROC-AUC
        auc = None
        if len(group_with_prob) > 0 and len(set(y_true)) > 1:
            try:
                auc = roc_auc_score(
                    group_with_prob[group_valid.index.isin(group_with_prob.index)]["is_merged"].astype(int),
                    group_with_prob["merge_probability"].fillna(0.5),
                )
            except Exception:
                pass

        # PR-AUC
        pr_auc = None
        if len(group_with_prob) > 0 and len(set(y_true)) > 1:
            try:
                pr_auc = average_precision_score(
                    group_with_prob[group_valid.index.isin(group_with_prob.index)]["is_merged"].astype(int),
                    group_with_prob["merge_probability"].fillna(0.5),
                )
            except Exception:
                pass

        # 统计 unmerged 识别
        unmerged_pred_as_unmerged = ((y_true == 0) & (y_pred == 0)).sum()
        unmerged_total = (y_true == 0).sum()

        all_metrics[method_id] = {
            "method_id": method_id,
            "prompt_type": group_valid["prompt_type"].iloc[0],
            "context_type": group_valid["context_type"].iloc[0],
            "n_valid": len(group_valid),
            "n_total": len(group),
            "parse_rate": round(float(len(group_valid) / max(len(group), 1)), 4),
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_val), 4),
            "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
            "roc_auc": round(float(auc), 4) if auc is not None else None,
            "pr_auc": round(float(pr_auc), 4) if pr_auc is not None else None,
            "specificity": round(float(specificity), 4),
            "balanced_accuracy": round(float(balanced_acc), 4),
            "fpr": round(float(fpr), 4),
            "confusion_matrix": cm.tolist(),
            "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
            "unmerged_identified": int(unmerged_pred_as_unmerged),
            "unmerged_total": int(unmerged_total),
            "avg_merge_probability": round(float(group_valid["merge_probability"].mean()), 4)
                if "merge_probability" in group_valid.columns else None,
            "avg_unmerged_risk_score": round(float(group_valid["unmerged_risk_score"].mean()), 4)
                if "unmerged_risk_score" in group_valid.columns else None,
        }

        logger.info(f"  [{label}] {method_id}: Acc={all_metrics[method_id]['accuracy']:.4f}, "
                    f"F1={all_metrics[method_id]['f1']:.4f}, "
                    f"AUC={all_metrics[method_id]['roc_auc']}, "
                    f"Specificity={all_metrics[method_id]['specificity']:.4f}, "
                    f"BalAcc={all_metrics[method_id]['balanced_accuracy']:.4f}, "
                    f"FPR={all_metrics[method_id]['fpr']:.4f}")

    return all_metrics


# ============================================================
# Hard-FP 改判分析
# ============================================================
def compute_hard_fp_correction(pred_df: pd.DataFrame) -> Dict:
    """
    分析 Hard-FP 子集上的改判情况。

    改判: 实验五预测 merged, 实验六预测 not_merged (正确答案)
    """
    # 需要实验五预测来做对比
    corrections = {}
    for method_id, group in pred_df.groupby("method_id"):
        group_valid = group[group["parse_success"] == True].copy()
        if group_valid.empty:
            continue

        y_pred = (group_valid["merge_prediction"].str.lower() == "merged").astype(int).values
        y_true = group_valid["is_merged"].astype(int).values

        # 正确识别 unmerged (TN)
        tn = ((y_true == 0) & (y_pred == 0)).sum()
        total_unmerged = (y_true == 0).sum()

        corrections[method_id] = {
            "method_id": method_id,
            "total_fp_samples": len(group_valid),
            "unmerged_in_sample": int(total_unmerged),
            "correctly_rejected": int(tn),
            "correction_rate": round(float(tn / max(total_unmerged, 1)), 4),
            "still_false_positive": int(total_unmerged - tn),
        }
        logger.info(f"  [Hard-FP] {method_id}: 改判率={corrections[method_id]['correction_rate']:.4f} "
                    f"({tn}/{total_unmerged})")

    return corrections


# ============================================================
# 评论质量指标
# ============================================================
def evaluate_comment_quality(raw_responses_path: str = None) -> Dict:
    """评估评论质量 (Risk Coverage, Actionability, Specificity)"""
    path = raw_responses_path or RAW_RESPONSES
    if not os.path.exists(path):
        logger.warning("raw_responses 不存在，无法评估评论质量")
        return {}

    # 用于计算 BLEU/ROUGE
    ai_df = pd.read_csv(EXP5_DATASET_CSV, encoding="utf-8-sig")
    real_reviews = {}
    for _, row in ai_df.iterrows():
        text = row.get("review_comments_text", "")
        if pd.isna(text) or str(text).strip().lower() in ("", "nan", "none"):
            real_reviews[str(row["pr_id"])] = ""
        else:
            real_reviews[str(row["pr_id"])] = str(text)

    # 关键词定义
    RISK_KEYWORDS = ["test", "edge case", "document", "split", "verify", "api",
                     "compatibility", "fallback", "error handling", "null", "undefined",
                     "race condition", "security", "performance", "breaking", "deprecated"]
    ACTION_KEYWORDS = ["add test", "add unit test", "write test", "clarify", "document",
                       "split pr", "separate", "refactor", "explain", "justify",
                       "benchmark", "measure", "check", "validate", "verify",
                       "consider", "should", "must", "need to", "please"]
    SPECIFICITY_KEYWORDS = ["file", "function", "method", "class", "line", "variable",
                            "api", "interface", "module", "import", "return", "param"]

    results = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            method_id = rec.get("method_id", "unknown")
            parsed = rec.get("parsed_data") or {}
            gen_comments = parsed.get("review_comments", [])
            risk_factors = parsed.get("risk_factors", [])

            if method_id not in results:
                results[method_id] = {
                    "bleu_scores": [], "rouge1": [], "rouge2": [], "rougeL": [],
                    "risk_coverages": [], "actionability_scores": [],
                    "specificity_scores": [], "n_generated": 0, "n_with_real": 0,
                    "total_comments": 0, "blocker_count": 0, "major_count": 0,
                    "minor_count": 0, "nit_count": 0,
                }

            r = results[method_id]

            # 严重程度分布
            for c in gen_comments:
                sev = c.get("severity", "minor")
                r["total_comments"] += 1
                if sev == "blocker":
                    r["blocker_count"] += 1
                elif sev == "major":
                    r["major_count"] += 1
                elif sev == "minor":
                    r["minor_count"] += 1
                else:
                    r["nit_count"] += 1

            # Risk Coverage
            if risk_factors:
                gen_text = " ".join([c.get("comment", "") for c in gen_comments]).lower()
                covered = sum(
                    1 for rf in risk_factors
                    if any(word in gen_text for word in str(rf).lower().split())
                )
                r["risk_coverages"].append(covered / len(risk_factors))

            # Actionability
            if gen_comments:
                gen_text = " ".join([c.get("comment", "") for c in gen_comments]).lower()
                actionable = sum(1 for kw in ACTION_KEYWORDS if kw in gen_text)
                r["actionability_scores"].append(
                    min(1.0, actionable / max(len(gen_comments), 1))
                )

            # Specificity
            if gen_comments:
                gen_text = " ".join([c.get("comment", "") for c in gen_comments]).lower()
                specific = sum(1 for kw in SPECIFICITY_KEYWORDS if kw in gen_text)
                r["specificity_scores"].append(
                    min(1.0, specific / max(len(gen_comments), 1))
                )

            # BLEU/ROUGE
            pr_id = str(rec.get("pr_id", ""))
            real_text = real_reviews.get(pr_id, "")
            if not real_text:
                continue
            r["n_with_real"] += 1
            gen_text = " ".join([c.get("comment", "") for c in gen_comments])
            if not gen_text:
                continue
            r["n_generated"] += 1

            # Simple BLEU-1
            ref_words = real_text.lower().split()
            gen_words = gen_text.lower().split()
            if gen_words:
                matches = sum(1 for t in gen_words if t in ref_words)
                r["bleu_scores"].append(matches / len(gen_words))

                # ROUGE-1
                overlap = len(set(gen_words) & set(ref_words))
                r["rouge1"].append(overlap / len(gen_words))

                # ROUGE-2
                gen_bigrams = set(zip(gen_words, gen_words[1:]))
                ref_bigrams = set(zip(ref_words, ref_words[1:]))
                if gen_bigrams:
                    r["rouge2"].append(len(gen_bigrams & ref_bigrams) / len(gen_bigrams))

                # ROUGE-L
                r["rougeL"].append(_rouge_l(ref_words, gen_words))

    # 聚合
    aggregated = {}
    for method_id, vals in results.items():
        aggregated[method_id] = {
            "method_id": method_id,
            "avg_bleu": round(float(np.mean(vals["bleu_scores"])), 4) if vals["bleu_scores"] else 0.0,
            "avg_rouge1": round(float(np.mean(vals["rouge1"])), 4) if vals["rouge1"] else 0.0,
            "avg_rouge2": round(float(np.mean(vals["rouge2"])), 4) if vals["rouge2"] else 0.0,
            "avg_rougeL": round(float(np.mean(vals["rougeL"])), 4) if vals["rougeL"] else 0.0,
            "avg_risk_coverage": round(float(np.mean(vals["risk_coverages"])), 4) if vals["risk_coverages"] else 0.0,
            "avg_actionability": round(float(np.mean(vals["actionability_scores"])), 4) if vals["actionability_scores"] else 0.0,
            "avg_specificity": round(float(np.mean(vals["specificity_scores"])), 4) if vals["specificity_scores"] else 0.0,
            "n_generated": vals["n_generated"],
            "n_with_real": vals["n_with_real"],
            "total_comments": vals["total_comments"],
            "avg_comments_per_pr": round(float(vals["total_comments"] / max(len(vals["bleu_scores"]) or 1, 1)), 1),
            "severity_distribution": {
                "blocker": vals["blocker_count"],
                "major": vals["major_count"],
                "minor": vals["minor_count"],
                "nit": vals["nit_count"],
            },
            "blocker_major_ratio": round(
                float((vals["blocker_count"] + vals["major_count"]) /
                       max(vals["total_comments"], 1)), 4
            ),
        }

    return aggregated


def _rouge_l(ref_words: List[str], gen_words: List[str]) -> float:
    """ROUGE-L"""
    m, n = len(ref_words), len(gen_words)
    if n == 0:
        return 0.0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            if ref_words[i] == gen_words[j]:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])
    return dp[m][n] / n


# ============================================================
# 与实验五对比
# ============================================================
def compare_with_exp5(exp6_metrics: Dict, sample_stats: Dict) -> Dict:
    """对比实验五基线和实验六结果"""
    comparison = {
        "experiment5_baselines_on_subset": sample_stats.get("baseline_balanced", {}),
        "experiment6_methods": {},
        "improvements": {},
    }

    baseline = sample_stats.get("baseline_balanced", {})
    # 用 P2_C4 作为主基线
    base_key = "P2_C4" if "P2_C4" in baseline else (list(baseline.keys())[0] if baseline else None)

    if base_key and baseline:
        base_metrics = baseline[base_key]
        for method_id, m in exp6_metrics.items():
            comparison["experiment6_methods"][method_id] = m

            improvements = {}
            for metric in ["accuracy", "f1", "roc_auc", "specificity", "balanced_accuracy"]:
                if m.get(metric) is not None and base_metrics.get(metric) is not None:
                    delta = m[metric] - base_metrics[metric]
                    improvements[f"delta_{metric}"] = round(delta, 4)

            improvements["delta_fpr"] = round(
                (base_metrics.get("fpr", 0) or 0) - (m.get("fpr", 0) or 0), 4
            )  # FPR 下降为正

            comparison["improvements"][method_id] = {
                "baseline": base_key,
                **improvements,
            }

            logger.info(f"  对比 {method_id} vs {base_key}: "
                        f"ΔAcc={improvements.get('delta_accuracy', 'N/A'):.4f}, "
                        f"ΔAUC={improvements.get('delta_roc_auc', 'N/A'):.4f}, "
                        f"ΔSpec={improvements.get('delta_specificity', 'N/A'):.4f}")

    return comparison


def find_best_method(exp6_metrics: Dict, hard_fp_corrections: Dict,
                     comment_quality: Dict) -> Dict:
    """找出最佳方法"""
    best = {"overall": None, "by_auc": None, "by_specificity": None, "by_balanced_acc": None}

    if exp6_metrics:
        sorted_by_auc = sorted(
            [(k, v.get("roc_auc") or 0) for k, v in exp6_metrics.items()],
            key=lambda x: x[1], reverse=True
        )
        best["by_auc"] = sorted_by_auc[0][0] if sorted_by_auc else None

        sorted_by_spec = sorted(
            [(k, v.get("specificity") or 0) for k, v in exp6_metrics.items()],
            key=lambda x: x[1], reverse=True
        )
        best["by_specificity"] = sorted_by_spec[0][0] if sorted_by_spec else None

        sorted_by_bal = sorted(
            [(k, v.get("balanced_accuracy") or 0) for k, v in exp6_metrics.items()],
            key=lambda x: x[1], reverse=True
        )
        best["by_balanced_acc"] = sorted_by_bal[0][0] if sorted_by_bal else None

    # 综合最优: 加权 AUC + Specificity + Balanced Accuracy
    if exp6_metrics:
        scores = {}
        for k, v in exp6_metrics.items():
            auc = v.get("roc_auc") or 0
            spec = v.get("specificity") or 0
            bal = v.get("balanced_accuracy") or 0
            f1 = v.get("f1") or 0
            scores[k] = auc * 0.35 + spec * 0.30 + bal * 0.20 + f1 * 0.15

        best["overall"] = max(scores, key=scores.get)
        best["scores"] = {k: round(v, 4) for k, v in scores.items()}

    logger.info(f"最佳方法: overall={best['overall']}, AUC={best['by_auc']}, "
                f"Specificity={best['by_specificity']}")
    return best


# ============================================================
# 32-Combo 对比: B01-B16 vs I01-I16
# ============================================================
def load_exp5_4x4_metrics() -> Dict:
    """加载实验五 B01-B16 基线指标"""
    if not os.path.exists(EXP5_4X4_METRICS):
        logger.warning(f"实验五 4×4 指标不存在: {EXP5_4X4_METRICS}")
        return {}
    metrics = load_json_safe(EXP5_4X4_METRICS)
    logger.info(f"加载实验五 B01-B16 基线: {len(metrics)} 组合")
    return metrics


def compute_32_combo_comparison(exp5_metrics: Dict, exp6_pred_df: pd.DataFrame) -> Dict:
    """
    合并 B01-B16 和 I01-I16 的指标，输出 32 组完整对比。

    返回:
        all_32: 32 组完整指标
        summary: 基线 vs 改进对比摘要
    """
    # 1. 加载 B01-B16 指标
    baseline_metrics = exp5_metrics or load_exp5_4x4_metrics()

    # 2. 计算 I01-I16 指标
    improved_metrics = compute_classification_metrics(exp6_pred_df, "Balanced-50")

    # 3. 合并 32 组
    all_32 = {}

    # B01-B16
    for combo_id, m in baseline_metrics.items():
        all_32[combo_id] = {
            "combo_id": combo_id,
            "group": "baseline",
            "prompt_type": m.get("prompt_type", ""),
            "context_type": m.get("context_type", ""),
            "accuracy": m.get("accuracy"),
            "precision": m.get("precision"),
            "recall": m.get("recall"),
            "f1": m.get("f1"),
            "roc_auc": m.get("roc_auc"),
            "specificity": m.get("specificity"),
            "balanced_accuracy": m.get("balanced_accuracy"),
            "fpr": m.get("fpr"),
            "confusion_matrix": m.get("confusion_matrix"),
        }

    # I01-I16
    for combo_id, m in improved_metrics.items():
        all_32[combo_id] = {
            "combo_id": combo_id,
            "group": "improved",
            "prompt_type": m.get("prompt_type", ""),
            "context_type": m.get("context_type", ""),
            "accuracy": m.get("accuracy"),
            "precision": m.get("precision"),
            "recall": m.get("recall"),
            "f1": m.get("f1"),
            "roc_auc": m.get("roc_auc"),
            "specificity": m.get("specificity"),
            "balanced_accuracy": m.get("balanced_accuracy"),
            "fpr": m.get("fpr"),
            "confusion_matrix": m.get("confusion_matrix"),
        }

    logger.info(f"32 组合指标合并完成: {len(all_32)} 组 (baseline={len(baseline_metrics)}, improved={len(improved_metrics)})")

    # 4. 保存合并 CSV
    csv_rows = []
    for combo_id in sorted(all_32.keys()):
        m = all_32[combo_id]
        cm = m.get("confusion_matrix", [[0, 0], [0, 0]])
        if isinstance(cm, list) and len(cm) == 2 and len(cm[0]) == 2:
            tn, fp = cm[0][0], cm[0][1]
            fn, tp = cm[1][0], cm[1][1]
        else:
            tn = fp = fn = tp = 0

        csv_rows.append({
            "combo_id": combo_id,
            "group": m["group"],
            "prompt_type": m["prompt_type"],
            "context_type": m["context_type"],
            "accuracy": m["accuracy"],
            "precision": m["precision"],
            "recall": m["recall"],
            "f1": m["f1"],
            "roc_auc": m["roc_auc"],
            "specificity": m["specificity"],
            "balanced_accuracy": m["balanced_accuracy"],
            "fpr": m["fpr"],
            "tn": tn, "fp": fp, "fn": fn, "tp": tp,
        })

    csv_df = pd.DataFrame(csv_rows)
    csv_df.to_csv(ALL_32_COMBO_METRICS, index=False, encoding="utf-8-sig")
    logger.info(f"32 组合指标 CSV 已保存: {ALL_32_COMBO_METRICS}")

    # 5. 对比摘要: 找最佳基线和最佳改进
    baseline_f1_best = max(
        [m for m in all_32.values() if m["group"] == "baseline" and m.get("f1") is not None],
        key=lambda x: x["f1"], default=None
    )
    baseline_auc_best = max(
        [m for m in all_32.values() if m["group"] == "baseline" and m.get("roc_auc") is not None],
        key=lambda x: x["roc_auc"], default=None
    )
    baseline_spec_best = max(
        [m for m in all_32.values() if m["group"] == "baseline" and m.get("specificity") is not None],
        key=lambda x: x["specificity"], default=None
    )
    improved_f1_best = max(
        [m for m in all_32.values() if m["group"] == "improved" and m.get("f1") is not None],
        key=lambda x: x["f1"], default=None
    )
    improved_auc_best = max(
        [m for m in all_32.values() if m["group"] == "improved" and m.get("roc_auc") is not None],
        key=lambda x: x["roc_auc"], default=None
    )
    improved_spec_best = max(
        [m for m in all_32.values() if m["group"] == "improved" and m.get("specificity") is not None],
        key=lambda x: x["specificity"], default=None
    )

    def _best_id(m):
        return m["combo_id"] if m else "N/A"

    summary = {
        "baseline_best_f1": {"combo_id": _best_id(baseline_f1_best), "f1": baseline_f1_best["f1"] if baseline_f1_best else None},
        "baseline_best_auc": {"combo_id": _best_id(baseline_auc_best), "roc_auc": baseline_auc_best["roc_auc"] if baseline_auc_best else None},
        "baseline_best_specificity": {"combo_id": _best_id(baseline_spec_best), "specificity": baseline_spec_best["specificity"] if baseline_spec_best else None},
        "improved_best_f1": {"combo_id": _best_id(improved_f1_best), "f1": improved_f1_best["f1"] if improved_f1_best else None},
        "improved_best_auc": {"combo_id": _best_id(improved_auc_best), "roc_auc": improved_auc_best["roc_auc"] if improved_auc_best else None},
        "improved_best_specificity": {"combo_id": _best_id(improved_spec_best), "specificity": improved_spec_best["specificity"] if improved_spec_best else None},
        "comparisons": [],
    }

    # 与实验五最佳基线逐项对比
    target_baselines = ["B14", "B04", "B12"]  # 最佳 F1, AUC, Specificity
    for b_id in target_baselines:
        if b_id not in all_32:
            continue
        base = all_32[b_id]
        for i_id in sorted([k for k in all_32 if all_32[k]["group"] == "improved"]):
            imp = all_32[i_id]
            comparison = {
                "baseline": b_id,
                "improved": i_id,
                "delta_accuracy": round((imp.get("accuracy") or 0) - (base.get("accuracy") or 0), 4),
                "delta_f1": round((imp.get("f1") or 0) - (base.get("f1") or 0), 4),
                "delta_roc_auc": round((imp.get("roc_auc") or 0) - (base.get("roc_auc") or 0), 4),
                "delta_specificity": round((imp.get("specificity") or 0) - (base.get("specificity") or 0), 4),
                "delta_balanced_accuracy": round((imp.get("balanced_accuracy") or 0) - (base.get("balanced_accuracy") or 0), 4),
                "delta_fpr": round((base.get("fpr") or 0) - (imp.get("fpr") or 0), 4),  # 下降为正
            }
            summary["comparisons"].append(comparison)

    # 成功标准检查
    if baseline_f1_best and improved_spec_best:
        b14_spec = all_32.get("B14", {}).get("specificity", 0) or 0
        b14_f1 = all_32.get("B14", {}).get("f1", 0) or 0
        b14_auc = all_32.get("B14", {}).get("roc_auc", 0) or 0

        best_imp_spec = improved_spec_best["specificity"] if improved_spec_best else 0
        best_imp_f1 = improved_f1_best["f1"] if improved_f1_best else 0
        best_imp_auc = improved_auc_best["roc_auc"] if improved_auc_best else 0

        summary["success_criteria"] = {
            "specificity_vs_B14": {
                "target": round(b14_spec + 0.20, 4),
                "achieved": best_imp_spec,
                "passed": best_imp_spec >= b14_spec + 0.20,
            },
            "fpr_vs_B14": {
                "target": "decrease by 0.20",
                "passed": False,  # 需要具体计算
            },
            "balanced_accuracy_vs_B14": {
                "passed": False,  # 需要具体计算
            },
            "roc_auc_vs_B14": {
                "target": f"not below {b14_auc:.4f}",
                "passed": best_imp_auc >= b14_auc - 0.01,
            },
            "f1_vs_B14_85pct": {
                "target": round(b14_f1 * 0.85, 4),
                "achieved": best_imp_f1,
                "passed": best_imp_f1 >= b14_f1 * 0.85,
            },
        }

    with open(BASELINE_VS_IMPROVED_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"基线 vs 改进对比摘要已保存: {BASELINE_VS_IMPROVED_SUMMARY}")

    # 保存 I01-I16 单独指标
    with open(IMPROVED_4X4_METRICS, "w", encoding="utf-8") as f:
        json.dump(improved_metrics, f, ensure_ascii=False, indent=2)
    logger.info(f"改进 4×4 指标已保存: {IMPROVED_4X4_METRICS}")

    return {"all_32": all_32, "summary": summary, "improved_metrics": improved_metrics}


# ============================================================
# 主入口
# ============================================================
def run_evaluation() -> bool:
    """运行全部评估"""
    logger.info("=" * 60)
    logger.info("阶段: 评估")
    logger.info("=" * 60)

    sample_stats = load_json_safe(EVAL_SAMPLE_STATS)

    # ================================================================
    # 主实验: I01-I16 vs B01-B16 (32 组合对比)
    # ================================================================
    if os.path.exists(IMPROVED_4X4_PARSED):
        logger.info("--- 主实验: 32 组合对比 (B01-B16 vs I01-I16) ---")
        exp6_pred_df = pd.read_csv(IMPROVED_4X4_PARSED, encoding="utf-8-sig")
        logger.info(f"加载实验六 I01-I16 预测: {len(exp6_pred_df)} 行, "
                    f"方法: {exp6_pred_df['method_id'].unique().tolist()}")

        exp5_metrics = load_exp5_4x4_metrics()
        comparison_32 = compute_32_combo_comparison(exp5_metrics, exp6_pred_df)

        # 打印关键对比
        summary = comparison_32.get("summary", {})
        logger.info("--- 基线最佳 ---")
        for key in ["baseline_best_f1", "baseline_best_auc", "baseline_best_specificity"]:
            info = summary.get(key, {})
            logger.info(f"  {key}: {info}")
        logger.info("--- 改进最佳 ---")
        for key in ["improved_best_f1", "improved_best_auc", "improved_best_specificity"]:
            info = summary.get(key, {})
            logger.info(f"  {key}: {info}")
        logger.info("--- 成功标准 ---")
        criteria = summary.get("success_criteria", {})
        for k, v in criteria.items():
            status = "PASS" if v.get("passed") else "FAIL"
            logger.info(f"  {k}: {status} (target={v.get('target')}, achieved={v.get('achieved')})")
    else:
        logger.warning(f"实验六 I01-I16 预测不存在: {IMPROVED_4X4_PARSED}")

    # ================================================================
    # M1-M4 on Balanced-120 / Hard-FP (验证)
    # ================================================================
    if os.path.exists(PARSED_PREDICTIONS):
        pred_df = pd.read_csv(PARSED_PREDICTIONS, encoding="utf-8-sig")
        logger.info(f"加载 M1-M4 预测: {len(pred_df)} 行, 方法: {pred_df['method_id'].unique().tolist()}")

        # 1. Balanced-120 指标
        if os.path.exists(EVAL_BALANCED_120):
            balanced_ids = pd.read_csv(EVAL_BALANCED_120, encoding="utf-8-sig")["pr_id"].astype(str).tolist()
            balanced_pred = pred_df[pred_df["pr_id"].astype(str).isin(balanced_ids)]
            logger.info(f"Balanced-120 预测: {len(balanced_pred)} 行")

            metrics_balanced = compute_classification_metrics(balanced_pred, "Balanced-120")
            with open(METRICS_BALANCED, "w", encoding="utf-8") as f:
                json.dump(metrics_balanced, f, ensure_ascii=False, indent=2)
            logger.info(f"Balanced-120 指标已保存: {METRICS_BALANCED}")
        else:
            metrics_balanced = {}

        # 2. Hard-FP 指标
        hardfp_ids = []
        if os.path.exists(EVAL_HARD_FP_40):
            hardfp_ids = pd.read_csv(EVAL_HARD_FP_40, encoding="utf-8-sig")["pr_id"].astype(str).tolist()
            hardfp_pred = pred_df[pred_df["pr_id"].astype(str).isin(hardfp_ids)]
            hard_fp_metrics = compute_classification_metrics(hardfp_pred, "Hard-FP-40")
            hard_fp_corrections = compute_hard_fp_correction(hardfp_pred)
            with open(METRICS_HARD_FP, "w", encoding="utf-8") as f:
                json.dump({
                    "classification": hard_fp_metrics,
                    "corrections": hard_fp_corrections,
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"Hard-FP 指标已保存: {METRICS_HARD_FP}")
        else:
            hard_fp_metrics = {}
            hard_fp_corrections = {}

        # 3. 评论质量
        comment_quality = evaluate_comment_quality()
        with open(COMMENT_QUALITY, "w", encoding="utf-8") as f:
            json.dump(comment_quality, f, ensure_ascii=False, indent=2)
        logger.info(f"评论质量指标已保存: {COMMENT_QUALITY}")

        # 4. 与实验五对比 (M1-M4 vs P2_C4)
        comparison = compare_with_exp5(metrics_balanced, sample_stats)
        with open(BASELINE_COMPARISON, "w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        logger.info(f"基线对比已保存: {BASELINE_COMPARISON}")

        # 5. 最佳方法 (M1-M4)
        best = find_best_method(metrics_balanced, hard_fp_corrections, comment_quality)
        best["all_metrics"] = {
            "balanced_120": metrics_balanced,
            "hard_fp_40": hard_fp_metrics,
            "hard_fp_corrections": hard_fp_corrections,
            "comment_quality": comment_quality,
            "comparison": comparison,
        }
        with open(BEST_METHOD_SUMMARY, "w", encoding="utf-8") as f:
            json.dump(best, f, ensure_ascii=False, indent=2)
        logger.info(f"最佳方法总结已保存: {BEST_METHOD_SUMMARY}")
        logger.info(f"综合最佳: {best['overall']} (scores: {best.get('scores', {})})")

        # 6. I01-I16 评论生成指标
        if os.path.exists(IMPROVED_4X4_RAW):
            logger.info("--- I01-I16 评论生成指标 ---")
            comment_gen_metrics = evaluate_comment_quality(IMPROVED_4X4_RAW)
            with open(COMMENT_GENERATION_METRICS, "w", encoding="utf-8") as f:
                json.dump(comment_gen_metrics, f, ensure_ascii=False, indent=2)
            logger.info(f"评论生成指标已保存: {COMMENT_GENERATION_METRICS}")
    else:
        logger.warning("无 M1-M4 预测数据，跳过验证评估")

    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    run_evaluation()
