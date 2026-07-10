"""
可视化模块 — 生成 8 张实验图表

图表列表:
  1. exp5_baseline_f1_heatmap.png        — 实验五 B01-B16 F1 heatmap
  2. exp5_baseline_specificity_heatmap.png — 实验五 B01-B16 Specificity heatmap
  3. exp6_improved_f1_heatmap.png         — 实验六 I01-I16 F1 heatmap
  4. exp6_improved_specificity_heatmap.png — 实验六 I01-I16 Specificity heatmap
  5. baseline_vs_improved_balacc.png      — B vs I Balanced Accuracy 对比
  6. baseline_vs_improved_fpr.png         — B vs I FPR 对比
  7. best_confusion_matrices.png          — 最佳基线 vs 最佳改进混淆矩阵
  8. comment_severity_distribution.png    — Review Comment severity 分布
"""

import json
import os
import sys
from typing import Dict

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    FIGURES_DIR,
    METRICS_BALANCED,
    METRICS_HARD_FP,
    COMMENT_QUALITY,
    COMMENT_GENERATION_METRICS,
    BASELINE_COMPARISON,
    BASELINE_VS_IMPROVED_SUMMARY,
    BEST_METHOD_SUMMARY,
    EVAL_SAMPLE_STATS,
    ALL_32_COMBO_METRICS,
    IMPROVED_4X4_METRICS,
    EXP5_4X4_METRICS,
    logger,
)

SAVE_KWARGS = dict(dpi=300, bbox_inches="tight", facecolor="white")

# 配色方案
COLORS = {
    "M1": "#4CAF50",
    "M2": "#2196F3",
    "M3": "#FF9800",
    "M4": "#E91E63",
    "baseline": "#9E9E9E",
}


def load_json_safe(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 4×4 Heatmap 辅助函数
# ============================================================
def _build_heatmap_data(metrics: Dict, metric_key: str) -> tuple:
    """从指标字典构建 4×4 heatmap 数据"""
    prompts = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
    contexts = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]

    # 确定使用哪些 prompts/contexts
    used_prompts = set()
    used_contexts = set()
    for combo_id, m in metrics.items():
        pt = m.get("prompt_type", "")
        ct = m.get("context_type", "")
        if pt:
            used_prompts.add(pt)
        if ct:
            used_contexts.add(ct)

    used_prompts = sorted(used_prompts,
                          key=lambda x: prompts.index(x) if x in prompts else 99)
    used_contexts = sorted(used_contexts,
                           key=lambda x: contexts.index(x) if x in contexts else 99)

    if not used_prompts or not used_contexts:
        return None, None, None

    n_rows = len(used_prompts)
    n_cols = len(used_contexts)
    data = np.full((n_rows, n_cols), np.nan)
    annot = np.full((n_rows, n_cols), "", dtype=object)

    for combo_id, m in metrics.items():
        pt = m.get("prompt_type", "")
        ct = m.get("context_type", "")
        if pt in used_prompts and ct in used_contexts:
            r = used_prompts.index(pt)
            c = used_contexts.index(ct)
            val = m.get(metric_key)
            if val is not None:
                data[r, c] = val
                annot[r, c] = f"{val:.3f}"

    return data, used_prompts, used_contexts, annot


def _draw_heatmap(ax, data, row_labels, col_labels, annot, title, cmap="YlOrRd"):
    """在给定 axes 上绘制 heatmap"""
    masked = np.ma.masked_invalid(data)
    im = ax.imshow(masked, cmap=cmap, aspect="auto", vmin=0, vmax=1)

    n_rows, n_cols = data.shape
    for i in range(n_rows):
        for j in range(n_cols):
            if not np.isnan(data[i, j]):
                val = data[i, j]
                text_color = "white" if val < 0.5 else "black"
                ax.text(j, i, f"{val:.3f}", ha="center", va="center",
                        fontsize=9, fontweight="bold", color=text_color)

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(col_labels, fontsize=10)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(row_labels, fontsize=10)
    ax.set_title(title, fontsize=13, fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.85)
    return im


# ============================================================
# 图1: 实验五 B01-B16 F1 Heatmap
# ============================================================
def fig_01_exp5_f1_heatmap():
    logger.info("图1: 实验五 B01-B16 F1 Heatmap")
    metrics = load_json_safe(EXP5_4X4_METRICS)
    if not metrics:
        logger.warning("实验五 4×4 指标不存在，跳过")
        return

    data, prompts, contexts, annot = _build_heatmap_data(metrics, "f1")
    if data is None:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    _draw_heatmap(ax, data, prompts, contexts, annot,
                  "Experiment 5 Baseline: F1 Score (B01-B16)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "exp5_baseline_f1_heatmap.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图2: 实验五 B01-B16 Specificity Heatmap
# ============================================================
def fig_02_exp5_specificity_heatmap():
    logger.info("图2: 实验五 B01-B16 Specificity Heatmap")
    metrics = load_json_safe(EXP5_4X4_METRICS)
    if not metrics:
        return

    data, prompts, contexts, annot = _build_heatmap_data(metrics, "specificity")
    if data is None:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    _draw_heatmap(ax, data, prompts, contexts, annot,
                  "Experiment 5 Baseline: Specificity (B01-B16)", cmap="YlGn")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "exp5_baseline_specificity_heatmap.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图3: 实验六 I01-I16 F1 Heatmap
# ============================================================
def fig_03_exp6_f1_heatmap():
    logger.info("图3: 实验六 I01-I16 F1 Heatmap")
    metrics = load_json_safe(IMPROVED_4X4_METRICS)
    if not metrics:
        logger.warning("实验六 4×4 指标不存在，跳过")
        return

    data, prompts, contexts, annot = _build_heatmap_data(metrics, "f1")
    if data is None:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    _draw_heatmap(ax, data, prompts, contexts, annot,
                  "Experiment 6 Improved: F1 Score (I01-I16)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "exp6_improved_f1_heatmap.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图4: 实验六 I01-I16 Specificity Heatmap
# ============================================================
def fig_04_exp6_specificity_heatmap():
    logger.info("图4: 实验六 I01-I16 Specificity Heatmap")
    metrics = load_json_safe(IMPROVED_4X4_METRICS)
    if not metrics:
        return

    data, prompts, contexts, annot = _build_heatmap_data(metrics, "specificity")
    if data is None:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    _draw_heatmap(ax, data, prompts, contexts, annot,
                  "Experiment 6 Improved: Specificity (I01-I16)", cmap="YlGn")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "exp6_improved_specificity_heatmap.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图5: B vs I Balanced Accuracy 对比
# ============================================================
def fig_05_balacc_comparison():
    logger.info("图5: Baseline vs Improved Balanced Accuracy")
    csv_path = ALL_32_COMBO_METRICS
    if not os.path.exists(csv_path):
        logger.warning("32 组合指标 CSV 不存在，跳过")
        return

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    baseline = df[df["group"] == "baseline"].sort_values("combo_id")
    improved = df[df["group"] == "improved"].sort_values("combo_id")

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(max(len(baseline), len(improved)))
    width = 0.35

    b_ids = baseline["combo_id"].tolist()
    i_ids = improved["combo_id"].tolist()
    b_vals = baseline["balanced_accuracy"].fillna(0).tolist()
    i_vals = improved["balanced_accuracy"].fillna(0).tolist()

    bars1 = ax.bar(x[:len(b_ids)] - width/2, b_vals, width,
                   label="Baseline (B01-B16)", color="#607D8B", alpha=0.85)
    bars2 = ax.bar(x[:len(i_ids)] + width/2, i_vals, width,
                   label="Improved (I01-I16)", color="#4CAF50", alpha=0.85)

    # 标注最佳
    if b_vals:
        best_b_idx = np.argmax(b_vals)
        ax.annotate(f"Best B: {b_ids[best_b_idx]}={b_vals[best_b_idx]:.3f}",
                    xy=(best_b_idx - width/2, b_vals[best_b_idx]),
                    xytext=(best_b_idx - width/2, b_vals[best_b_idx] + 0.05),
                    fontsize=8, color="#607D8B", ha="center",
                    arrowprops=dict(arrowstyle="->", color="#607D8B"))
    if i_vals:
        best_i_idx = np.argmax(i_vals)
        ax.annotate(f"Best I: {i_ids[best_i_idx]}={i_vals[best_i_idx]:.3f}",
                    xy=(best_i_idx + width/2, i_vals[best_i_idx]),
                    xytext=(best_i_idx + width/2, i_vals[best_i_idx] + 0.05),
                    fontsize=8, color="#4CAF50", ha="center",
                    arrowprops=dict(arrowstyle="->", color="#4CAF50"))

    all_ids = sorted(set(b_ids + i_ids))
    ax.set_xticks(range(len(all_ids)))
    ax.set_xticklabels(all_ids, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Balanced Accuracy")
    ax.set_title("Balanced Accuracy: Baseline vs Improved")
    ax.legend(fontsize=9)
    ax.set_ylim(0, 1)

    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "baseline_vs_improved_balacc.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图6: B vs I FPR 对比
# ============================================================
def fig_06_fpr_comparison():
    logger.info("图6: Baseline vs Improved FPR")
    csv_path = ALL_32_COMBO_METRICS
    if not os.path.exists(csv_path):
        return

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    baseline = df[df["group"] == "baseline"].sort_values("combo_id")
    improved = df[df["group"] == "improved"].sort_values("combo_id")

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(max(len(baseline), len(improved)))
    width = 0.35

    b_ids = baseline["combo_id"].tolist()
    i_ids = improved["combo_id"].tolist()
    b_vals = baseline["fpr"].fillna(0).tolist()
    i_vals = improved["fpr"].fillna(0).tolist()

    ax.bar(x[:len(b_ids)] - width/2, b_vals, width,
           label="Baseline (B01-B16)", color="#FF5722", alpha=0.7)
    ax.bar(x[:len(i_ids)] + width/2, i_vals, width,
           label="Improved (I01-I16)", color="#2196F3", alpha=0.85)

    # 标注最佳 (最低 FPR)
    if i_vals:
        best_i_idx = np.argmin(i_vals)
        ax.annotate(f"Lowest FPR: {i_ids[best_i_idx]}={i_vals[best_i_idx]:.3f}",
                    xy=(best_i_idx + width/2, i_vals[best_i_idx]),
                    xytext=(best_i_idx + width/2, i_vals[best_i_idx] + 0.08),
                    fontsize=8, color="#2196F3", ha="center",
                    arrowprops=dict(arrowstyle="->", color="#2196F3"))

    all_ids = sorted(set(b_ids + i_ids))
    ax.set_xticks(range(len(all_ids)))
    ax.set_xticklabels(all_ids, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("False Positive Rate")
    ax.set_title("FPR: Baseline vs Improved (Lower is Better)")
    ax.legend(fontsize=9)
    ax.set_ylim(0, 1.1)

    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "baseline_vs_improved_fpr.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图7: 最佳基线 vs 最佳改进 混淆矩阵
# ============================================================
def fig_07_best_confusion_matrices():
    logger.info("图7: 最佳基线 vs 最佳改进 混淆矩阵")
    summary = load_json_safe(BASELINE_VS_IMPROVED_SUMMARY)
    exp5_metrics = load_json_safe(EXP5_4X4_METRICS)
    exp6_metrics = load_json_safe(IMPROVED_4X4_METRICS)

    if not exp6_metrics:
        logger.warning("缺少实验六数据，跳过混淆矩阵")
        return

    # 选择最佳改进 (按Specificity)
    impr_id = "I16"
    best_spec = -1
    for k, v in exp6_metrics.items():
        if v.get("specificity", 0) and v["specificity"] > best_spec:
            best_spec = v["specificity"]
            impr_id = k

    # 选择最佳基线 (按F1)
    base_id = "B14"
    best_f1 = -1
    for k, v in (exp5_metrics or {}).items():
        if v.get("f1", 0) and v["f1"] > best_f1:
            best_f1 = v["f1"]
            base_id = k

    impr_m = exp6_metrics.get(impr_id, {})
    base_m = exp5_metrics.get(base_id, {}) if exp5_metrics else {}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))

    # Baseline
    if base_m:
        cm = np.array(base_m.get("confusion_matrix", [[0, 0], [0, 0]]))
        if cm.sum() == 0:
            # 从TN/FP/FN/TP重建
            tn = base_m.get("tn", 0)
            fp = base_m.get("fp", 0)
            fn = base_m.get("fn", 0)
            tp = base_m.get("tp", 0)
            cm = np.array([[tn, fp], [fn, tp]])
    else:
        cm = np.array([[0, 0], [0, 0]])

    im = ax1.imshow(cm, cmap="YlOrRd")
    ax1.set_title(f"Best Baseline: {base_id}\nF1={base_m.get('f1','?'):.3f}" if base_m else f"Baseline: {base_id}",
                  color="#607D8B", fontweight="bold", fontsize=12)
    ax1.set_xticks([0, 1]); ax1.set_xticklabels(["Pred Unmerged", "Pred Merged"])
    ax1.set_yticks([0, 1]); ax1.set_yticklabels(["Actual Unmerged", "Actual Merged"])
    for i in range(2):
        for j in range(2):
            val = int(cm[i, j])
            ax1.text(j, i, str(val), ha="center", va="center", fontsize=18,
                    fontweight="bold", color="white" if val > cm.max()/2 else "black")

    # Improved
    cm2 = np.array(impr_m.get("confusion_matrix", [[0, 0], [0, 0]]))
    if cm2.sum() == 0:
        tn2 = impr_m.get("tn", 0); fp2 = impr_m.get("fp", 0)
        fn2 = impr_m.get("fn", 0); tp2 = impr_m.get("tp", 0)
        cm2 = np.array([[tn2, fp2], [fn2, tp2]])

    im2 = ax2.imshow(cm2, cmap="YlOrRd")
    ax2.set_title(f"Best Improved: {impr_id}\nF1={impr_m.get('f1','?'):.3f}",
                  color="#4CAF50", fontweight="bold", fontsize=12)
    ax2.set_xticks([0, 1]); ax2.set_xticklabels(["Pred Unmerged", "Pred Merged"])
    ax2.set_yticks([0, 1]); ax2.set_yticklabels(["Actual Unmerged", "Actual Merged"])
    for i in range(2):
        for j in range(2):
            val = int(cm2[i, j])
            ax2.text(j, i, str(val), ha="center", va="center", fontsize=18,
                    fontweight="bold", color="white" if val > cm2.max()/2 else "black")

    tn2_v, fp2_v = int(cm2[0, 0]), int(cm2[0, 1])
    spec2 = tn2_v / (tn2_v + fp2_v) if (tn2_v + fp2_v) > 0 else 0
    ax2.set_xlabel(f"Specificity: {spec2:.3f} | F1: {impr_m.get('f1', 0):.3f}", fontsize=10)

    fig.suptitle("Confusion Matrices: Best Baseline vs Best Improved", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "best_confusion_matrices.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图8: Review Comment Severity 分布
# ============================================================
def fig_08_comment_severity():
    logger.info("图8: Review Comment Severity 分布")
    quality = load_json_safe(COMMENT_GENERATION_METRICS)
    if not quality:
        quality = load_json_safe(COMMENT_QUALITY)
    if not quality:
        logger.warning("评论质量指标不存在，跳过")
        return

    methods = list(quality.keys())
    blocker_vals = [quality[m].get("severity_distribution", {}).get("blocker", 0) for m in methods]
    major_vals = [quality[m].get("severity_distribution", {}).get("major", 0) for m in methods]
    minor_vals = [quality[m].get("severity_distribution", {}).get("minor", 0) for m in methods]
    nit_vals = [quality[m].get("severity_distribution", {}).get("nit", 0) for m in methods]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # 堆叠柱状图
    x = np.arange(len(methods))
    width = 0.5
    ax1.bar(x, blocker_vals, width, label="Blocker", color="#D32F2F")
    ax1.bar(x, major_vals, width, bottom=blocker_vals, label="Major", color="#FF9800")
    bottom_m = [b + m for b, m in zip(blocker_vals, major_vals)]
    ax1.bar(x, minor_vals, width, bottom=bottom_m, label="Minor", color="#2196F3")
    bottom_all = [b + m + mi for b, m, mi in zip(blocker_vals, major_vals, minor_vals)]
    ax1.bar(x, nit_vals, width, bottom=bottom_all, label="Nit", color="#9E9E9E")
    ax1.set_xticks(x)
    ax1.set_xticklabels(methods, fontsize=8)
    ax1.set_ylabel("Count")
    ax1.set_title("Review Comment Severity Distribution")
    ax1.legend(fontsize=7)

    # Blocker+Major 比例
    bm_ratio = [quality[m].get("blocker_major_ratio", 0) for m in methods]
    colors = ["#4CAF50" if r > 0.3 else "#FF5722" for r in bm_ratio]
    bars = ax2.bar(methods, bm_ratio, color=colors, alpha=0.85)
    ax2.set_ylabel("Blocker+Major Ratio")
    ax2.set_title("High-Severity Comment Ratio")
    ax2.set_ylim(0, 1)
    for bar, v in zip(bars, bm_ratio):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                 f"{v:.1%}", ha="center", fontsize=9)

    fig.suptitle("Review Comment Quality: Severity Analysis", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "comment_severity_distribution.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图1 (旧): 方法核心指标对比
# ============================================================
def fig_01_method_metrics():
    logger.info("图1: 方法指标对比")
    metrics = load_json_safe(METRICS_BALANCED)
    comparison = load_json_safe(BASELINE_COMPARISON)
    if not metrics:
        return

    methods = list(metrics.keys())
    metric_names = ["accuracy", "precision", "recall", "f1", "specificity"]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(methods))
    width = 0.15

    for i, mn in enumerate(metric_names):
        vals = [metrics[m].get(mn, 0) or 0 for m in methods]
        bars = ax.bar(x + i * width, vals, width, label=mn.replace("_", " ").title(),
                      alpha=0.85)
        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                        f"{v:.3f}", ha="center", fontsize=6, rotation=90)

    # 添加实验五基线
    baseline = comparison.get("experiment5_baselines_on_subset", {})
    base_key = "P2_C4" if "P2_C4" in baseline else (list(baseline.keys())[0] if baseline else None)
    if base_key and baseline:
        base = baseline[base_key]
        for i, mn in enumerate(metric_names):
            bv = base.get(mn)
            if bv is not None:
                ax.axhline(y=bv, color="gray", linestyle="--", alpha=0.5,
                          label=f"Exp5 {base_key} {mn}" if i == 0 else "")

    ax.set_xticks(x + width * 2)
    ax.set_xticklabels(methods)
    ax.set_ylabel("Score")
    ax.set_title("Method Metrics Comparison on Balanced-120")
    ax.legend(loc="lower right", fontsize=7)
    ax.set_ylim(0, 1.15)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "01_method_metrics_comparison.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图2: Specificity vs FPR
# ============================================================
def fig_02_specificity_fpr():
    logger.info("图2: Specificity & FPR")
    metrics = load_json_safe(METRICS_BALANCED)
    comparison = load_json_safe(BASELINE_COMPARISON)
    if not metrics:
        return

    methods = list(metrics.keys())
    specifics = [metrics[m].get("specificity", 0) or 0 for m in methods]
    fprs = [metrics[m].get("fpr", 0) or 0 for m in methods]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    colors_list = [COLORS.get(m, "#333") for m in methods]

    # Specificity
    bars1 = ax1.bar(methods, specifics, color=colors_list, alpha=0.85)
    ax1.set_ylabel("Specificity (TN/(TN+FP))")
    ax1.set_title("Specificity — Higher = Better at Identifying Unmerged")
    ax1.set_ylim(0, 1)
    for bar, v in zip(bars1, specifics):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                 f"{v:.3f}", ha="center", fontsize=10)

    # 基线
    baseline = comparison.get("experiment5_baselines_on_subset", {})
    base_key = "P2_C4" if "P2_C4" in baseline else (list(baseline.keys())[0] if baseline else None)
    if base_key and baseline:
        base_spec = baseline[base_key].get("specificity", 0) or 0
        ax1.axhline(y=base_spec, color="gray", linestyle="--", alpha=0.7,
                    label=f"Exp5 {base_key}: {base_spec:.3f}")
        ax1.legend(fontsize=8)

    # FPR
    bars2 = ax2.bar(methods, fprs, color=colors_list, alpha=0.85)
    ax2.set_ylabel("False Positive Rate")
    ax2.set_title("FPR — Lower = Fewer Incorrect Merged Predictions")
    ax2.set_ylim(0, 1)
    for bar, v in zip(bars2, fprs):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                 f"{v:.3f}", ha="center", fontsize=10)

    if base_key and baseline:
        base_fpr = baseline[base_key].get("fpr", 0) or 0
        ax2.axhline(y=base_fpr, color="gray", linestyle="--", alpha=0.7,
                    label=f"Exp5 {base_key}: {base_fpr:.3f}")
        ax2.legend(fontsize=8)

    fig.suptitle("Unmerged PR Identification Ability", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "02_specificity_fpr_comparison.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图3: AUC & Balanced Accuracy
# ============================================================
def fig_03_auc_balanced_acc():
    logger.info("图3: AUC & Balanced Accuracy")
    metrics = load_json_safe(METRICS_BALANCED)
    comparison = load_json_safe(BASELINE_COMPARISON)
    if not metrics:
        return

    methods = list(metrics.keys())
    aucs = [metrics[m].get("roc_auc") or 0 for m in methods]
    bal_accs = [metrics[m].get("balanced_accuracy", 0) or 0 for m in methods]
    pr_aucs = [metrics[m].get("pr_auc") or 0 for m in methods]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    colors_list = [COLORS.get(m, "#333") for m in methods]

    x = np.arange(len(methods))
    width = 0.3

    # AUC + PR-AUC
    bars_auc = ax1.bar(x - width / 2, aucs, width, label="ROC-AUC", color="#2196F3", alpha=0.85)
    bars_pr = ax1.bar(x + width / 2, pr_aucs, width, label="PR-AUC", color="#4CAF50", alpha=0.85)
    ax1.set_xticks(x)
    ax1.set_xticklabels(methods)
    ax1.set_ylabel("AUC Score")
    ax1.set_title("ROC-AUC & PR-AUC")
    ax1.legend(fontsize=8)
    ax1.set_ylim(0, 1)

    # 基线
    baseline = comparison.get("experiment5_baselines_on_subset", {})
    base_key = "P2_C4" if "P2_C4" in baseline else (list(baseline.keys())[0] if baseline else None)
    if base_key and baseline:
        base_auc = baseline[base_key].get("roc_auc") or 0
        ax1.axhline(y=base_auc, color="gray", linestyle="--", alpha=0.7,
                    label=f"Exp5 AUC: {base_auc:.3f}")
        ax1.legend(fontsize=8)

    # Balanced Accuracy
    bars_bal = ax2.bar(methods, bal_accs, color=colors_list, alpha=0.85)
    ax2.set_ylabel("Balanced Accuracy")
    ax2.set_title("Balanced Accuracy = (Recall + Specificity) / 2")
    ax2.set_ylim(0, 1)
    for bar, v in zip(bars_bal, bal_accs):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                 f"{v:.3f}", ha="center", fontsize=10)

    if base_key and baseline:
        base_bal = baseline[base_key].get("balanced_accuracy") or 0
        ax2.axhline(y=base_bal, color="gray", linestyle="--", alpha=0.7,
                    label=f"Exp5 BalAcc: {base_bal:.3f}")
        ax2.legend(fontsize=8)

    fig.suptitle("Discrimination & Balance Metrics", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "03_auc_balanced_accuracy.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图4: Hard-FP 改判率
# ============================================================
def fig_04_hard_fp_correction():
    logger.info("图4: Hard-FP 改判率")
    hardfp = load_json_safe(METRICS_HARD_FP)
    if not hardfp:
        return

    corrections = hardfp.get("corrections", {})
    if not corrections:
        return

    methods = list(corrections.keys())
    correction_rates = [corrections[m].get("correction_rate", 0) for m in methods]
    correctly_rejected = [corrections[m].get("correctly_rejected", 0) for m in methods]
    still_fp = [corrections[m].get("still_false_positive", 0) for m in methods]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    colors_list = [COLORS.get(m, "#333") for m in methods]

    # 改判率
    bars = ax1.bar(methods, correction_rates, color=colors_list, alpha=0.85)
    ax1.set_ylabel("Correction Rate")
    ax1.set_title("Hard-FP Correction Rate\n(Fraction of FP correctly reclassified as not_merged)")
    ax1.set_ylim(0, 1)
    for bar, v in zip(bars, correction_rates):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                 f"{v:.1%}", ha="center", fontsize=10)

    # 改判详细
    x = np.arange(len(methods))
    width = 0.3
    ax2.bar(x - width / 2, correctly_rejected, width, label="Correctly Rejected",
            color="#4CAF50", alpha=0.85)
    ax2.bar(x + width / 2, still_fp, width, label="Still False Positive",
            color="#FF5722", alpha=0.85)
    ax2.set_xticks(x)
    ax2.set_xticklabels(methods)
    ax2.set_ylabel("Count")
    ax2.set_title("Hard-FP Breakdown")
    ax2.legend(fontsize=8)

    fig.suptitle("Improvement on Previously Misclassified PRs", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "04_hard_fp_correction_rate.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图5: 评论质量
# ============================================================
def fig_05_comment_quality():
    logger.info("图5: 评论质量")
    quality = load_json_safe(COMMENT_QUALITY)
    if not quality:
        return

    methods = list(quality.keys())

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    colors_list = [COLORS.get(m, "#333") for m in methods]

    # Risk Coverage & Actionability & Specificity
    ax = axes[0, 0]
    x = np.arange(len(methods))
    width = 0.25
    risk_cov = [quality[m].get("avg_risk_coverage", 0) for m in methods]
    action = [quality[m].get("avg_actionability", 0) for m in methods]
    spec = [quality[m].get("avg_specificity", 0) for m in methods]
    ax.bar(x - width, risk_cov, width, label="Risk Coverage", color="#E91E63", alpha=0.85)
    ax.bar(x, action, width, label="Actionability", color="#2196F3", alpha=0.85)
    ax.bar(x + width, spec, width, label="Specificity", color="#4CAF50", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.set_ylabel("Rate")
    ax.set_title("Comment Quality: Coverage & Actionability")
    ax.legend(fontsize=7)
    ax.set_ylim(0, 1)

    # BLEU/ROUGE
    ax = axes[0, 1]
    x = np.arange(len(methods))
    width = 0.2
    for i, mn in enumerate(["avg_bleu", "avg_rouge1", "avg_rouge2", "avg_rougeL"]):
        vals = [quality[m].get(mn, 0) for m in methods]
        ax.bar(x + i * width, vals, width, label=mn.replace("avg_", "").upper(), alpha=0.85)
    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(methods)
    ax.set_ylabel("Score")
    ax.set_title("Text Overlap Metrics (BLEU/ROUGE)")
    ax.legend(fontsize=7)

    # Severity Distribution
    ax = axes[1, 0]
    blocker_major = [quality[m].get("blocker_major_ratio", 0) for m in methods]
    bars = ax.bar(methods, blocker_major, color=colors_list, alpha=0.85)
    ax.set_ylabel("Blocker+Major Ratio")
    ax.set_title("Severity: Blocker+Major / Total Comments")
    for bar, v in zip(bars, blocker_major):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{v:.1%}", ha="center", fontsize=10)

    # Comments per PR
    ax = axes[1, 1]
    comments_per = [quality[m].get("avg_comments_per_pr", 0) for m in methods]
    bars = ax.bar(methods, comments_per, color=colors_list, alpha=0.85)
    ax.set_ylabel("Avg Comments per PR")
    ax.set_title("Review Comment Volume")
    for bar, v in zip(bars, comments_per):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                f"{v:.1f}", ha="center", fontsize=10)

    fig.suptitle("Review Comment Quality Analysis", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "05_comment_quality_metrics.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图6: 混淆矩阵
# ============================================================
def fig_06_confusion_matrices():
    logger.info("图6: 混淆矩阵")
    metrics = load_json_safe(METRICS_BALANCED)
    if not metrics:
        return

    methods = list(metrics.keys())
    n_methods = len(methods)

    fig, axes = plt.subplots(1, n_methods, figsize=(4 * n_methods, 4))
    if n_methods == 1:
        axes = [axes]

    for idx, method_id in enumerate(methods):
        m = metrics[method_id]
        cm = np.array(m.get("confusion_matrix", [[0, 0], [0, 0]]))
        ax = axes[idx]
        im = ax.imshow(cm, cmap="YlOrRd")
        color = COLORS.get(method_id, "#333")
        ax.set_title(f"{method_id}\n({m.get('prompt_type','')}+{m.get('context_type','')})",
                     color=color, fontweight="bold")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Pred Unmerged", "Pred Merged"])
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["Actual Unmerged", "Actual Merged"])
        for i in range(2):
            for j in range(2):
                val = cm[i, j]
                ax.text(j, i, str(val), ha="center", va="center", fontsize=16,
                        fontweight="bold",
                        color="white" if val > cm.max() / 2 else "black")

        # 标注 Specificity
        tn, fp = cm[0, 0], cm[0, 1]
        spec = tn / (tn + fp) if (tn + fp) > 0 else 0
        ax.set_xlabel(f"Specificity: {spec:.3f}", fontsize=9)

    fig.suptitle("Confusion Matrices on Balanced-120", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "06_confusion_matrices.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图7: 实验五 vs 实验六总结
# ============================================================
def fig_07_exp5_vs_exp6_summary():
    logger.info("图7: 实验五 vs 实验六总结")
    comparison = load_json_safe(BASELINE_COMPARISON)
    if not comparison:
        return

    improvements = comparison.get("improvements", {})
    baseline_info = comparison.get("experiment5_baselines_on_subset", {})
    if not improvements:
        return

    methods = list(improvements.keys())

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))

    # Δ Specificity
    ax = axes[0, 0]
    deltas = [improvements[m].get("delta_specificity", 0) for m in methods]
    colors_list = ["#4CAF50" if d > 0 else "#FF5722" for d in deltas]
    ax.bar(methods, deltas, color=colors_list, alpha=0.85)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title("Δ Specificity (vs Exp5 P2_C4)")
    ax.set_ylabel("Change")
    for i, v in enumerate(deltas):
        ax.text(i, v + (0.02 if v >= 0 else -0.06), f"{v:+.3f}", ha="center", fontsize=9)

    # Δ AUC
    ax = axes[0, 1]
    deltas = [improvements[m].get("delta_roc_auc", 0) for m in methods]
    colors_list = ["#4CAF50" if d > 0 else "#FF5722" for d in deltas]
    ax.bar(methods, deltas, color=colors_list, alpha=0.85)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title("Δ ROC-AUC (vs Exp5 P2_C4)")
    ax.set_ylabel("Change")
    for i, v in enumerate(deltas):
        ax.text(i, v + (0.02 if v >= 0 else -0.06), f"{v:+.3f}", ha="center", fontsize=9)

    # Δ Balanced Accuracy
    ax = axes[0, 2]
    deltas = [improvements[m].get("delta_balanced_accuracy", 0) for m in methods]
    colors_list = ["#4CAF50" if d > 0 else "#FF5722" for d in deltas]
    ax.bar(methods, deltas, color=colors_list, alpha=0.85)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title("Δ Balanced Accuracy (vs Exp5 P2_C4)")
    ax.set_ylabel("Change")
    for i, v in enumerate(deltas):
        ax.text(i, v + (0.02 if v >= 0 else -0.06), f"{v:+.3f}", ha="center", fontsize=9)

    # Δ F1
    ax = axes[1, 0]
    deltas = [improvements[m].get("delta_f1", 0) for m in methods]
    colors_list = ["#4CAF50" if d > 0 else "#FF5722" for d in deltas]
    ax.bar(methods, deltas, color=colors_list, alpha=0.85)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title("Δ F1 (vs Exp5 P2_C4)")
    ax.set_ylabel("Change")
    for i, v in enumerate(deltas):
        ax.text(i, v + (0.02 if v >= 0 else -0.06), f"{v:+.3f}", ha="center", fontsize=9)

    # Δ FPR (下降为正)
    ax = axes[1, 1]
    deltas = [improvements[m].get("delta_fpr", 0) for m in methods]
    colors_list = ["#4CAF50" if d > 0 else "#FF5722" for d in deltas]
    ax.bar(methods, deltas, color=colors_list, alpha=0.85)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title("Δ FPR Reduction (vs Exp5 P2_C4)\nPositive = FPR decreased")
    ax.set_ylabel("Change")
    for i, v in enumerate(deltas):
        ax.text(i, v + (0.02 if v >= 0 else -0.06), f"{v:+.3f}", ha="center", fontsize=9)

    # Radar/Summary
    ax = axes[1, 2]
    ax.axis("off")
    summary_lines = ["Experiment 6 vs Experiment 5", "", "Success Criteria:"]
    criteria = [
        ("ROC-AUC Increase", any(improvements[m].get("delta_roc_auc", 0) or 0 > 0 for m in methods)),
        ("Specificity Increase", any(improvements[m].get("delta_specificity", 0) or 0 > 0 for m in methods)),
        ("FPR Decrease", any(improvements[m].get("delta_fpr", 0) or 0 > 0 for m in methods)),
        ("F1 No Catastrophic Drop", all(improvements[m].get("delta_f1", 0) or 0 > -0.15 for m in methods)),
    ]
    for text, passed in criteria:
        symbol = "✅" if passed else "❌"
        summary_lines.append(f"{symbol} {text}")

    # 最佳方法
    best = load_json_safe(BEST_METHOD_SUMMARY)
    if best.get("overall"):
        summary_lines.append(f"\nBest Method: {best['overall']}")
        if best.get("scores"):
            for m, s in best["scores"].items():
                summary_lines.append(f"  {m}: {s:.4f}")

    ax.text(0.1, 0.9, "\n".join(summary_lines), transform=ax.transAxes,
            fontsize=10, fontfamily="monospace", verticalalignment="top")

    fig.suptitle("Experiment 5 → Experiment 6: Improvement Summary", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "07_exp5_vs_exp6_summary.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 主入口
# ============================================================
def generate_all_figures():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    logger.info("开始生成图表...")

    # 新的 8 张核心图表
    fig_01_exp5_f1_heatmap()
    fig_02_exp5_specificity_heatmap()
    fig_03_exp6_f1_heatmap()
    fig_04_exp6_specificity_heatmap()
    fig_05_balacc_comparison()
    fig_06_fpr_comparison()
    fig_07_best_confusion_matrices()
    fig_08_comment_severity()

    # 保留旧的兼容图表
    try:
        fig_01_method_metrics()
        fig_02_specificity_fpr()
        fig_03_auc_balanced_acc()
        fig_04_hard_fp_correction()
        fig_05_comment_quality()
        fig_06_confusion_matrices()
        fig_07_exp5_vs_exp6_summary()
    except Exception as e:
        logger.warning(f"部分旧图表生成失败 (可能数据不完整): {e}")

    logger.info(f"图表已保存至: {FIGURES_DIR}")


if __name__ == "__main__":
    generate_all_figures()
