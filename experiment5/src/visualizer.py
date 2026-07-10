"""
可视化模块 — 生成 8 张实验图表

图表列表:
  1. 01_ai_dataset_distribution.png   AI PR 仓库分布与合并状态
  2. 02_ai_vs_human_distribution.png  人类 vs AI 对比
  3. 03_traditional_ml_ai_performance.png  SVM/RF在AI上指标
  4. 04_llm_ai_performance.png        DeepSeek在AI上指标
  5. 05_human_vs_ai_model_comparison.png  人类vs AI性能变化
  6. 06_confusion_matrices.png        混淆矩阵
  7. 07_comment_generation_metrics.png  BLEU/ROUGE
  8. 08_error_analysis.png           错误分析
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
    AI_DATASET_CSV,
    EXPERIMENT2_DIR,
    EXPERIMENT1_DIR,
    RESULTS_EVALUATION_DIR,
    FIGURES_DIR,
    logger,
)

PREDICTIONS_DIR = os.path.join(os.path.dirname(RESULTS_EVALUATION_DIR), "predictions")
ML_PRED = os.path.join(PREDICTIONS_DIR, "traditional_ml_predictions.csv")
LLM_PARSED = os.path.join(PREDICTIONS_DIR, "llm_parsed_predictions.csv")

SAVE_KWARGS = dict(dpi=300, bbox_inches="tight", facecolor="white")

EXP2_FEATURES = os.path.join(EXPERIMENT2_DIR, "results", "processed", "features_main.csv")
EXP1_DATASET = os.path.join(EXPERIMENT1_DIR, "results", "processed", "dataset.csv")
EXP2_METRICS = os.path.join(EXPERIMENT2_DIR, "results", "evaluation", "metrics_main.json")


def load_json_safe(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 图1: AI PR 仓库分布
# ============================================================
def fig_01_dataset_distribution():
    logger.info("图1: AI PR 仓库分布")
    if not os.path.exists(AI_DATASET_CSV):
        return
    df = pd.read_csv(AI_DATASET_CSV, encoding="utf-8-sig")
    df["is_merged_bool"] = df["is_merged"].apply(
        lambda x: True if str(x).lower() in ("true", "1") else False
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    repos = df["repo"].value_counts()
    merged_by_repo = df[df["is_merged_bool"]]["repo"].value_counts()
    unmerged_by_repo = df[~df["is_merged_bool"]]["repo"].value_counts()

    x = range(len(repos))
    width = 0.6
    ax.bar(x, [merged_by_repo.get(r, 0) for r in repos.index],
           width, label="Merged", color="#4CAF50")
    ax.bar(x, [unmerged_by_repo.get(r, 0) for r in repos.index],
           width, bottom=[merged_by_repo.get(r, 0) for r in repos.index],
           label="Unmerged", color="#FF5722")

    ax.set_xticks(x)
    ax.set_xticklabels([r.split("/")[-1] for r in repos.index], rotation=30, ha="right")
    ax.set_ylabel("PR Count")
    ax.set_title("AI-Generated Code PR Distribution by Repository")
    ax.legend()
    for i, (r, total) in enumerate(zip(repos.index, repos.values)):
        ax.text(i, total + 1, str(total), ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "01_ai_dataset_distribution.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图2: 人类 vs AI 分布对比
# ============================================================
def fig_02_human_vs_ai_distribution():
    logger.info("图2: 人类 vs AI 分布对比")
    human_df = pd.read_csv(EXP1_DATASET, encoding="utf-8-sig") if os.path.exists(EXP1_DATASET) else None
    ai_df = pd.read_csv(AI_DATASET_CSV, encoding="utf-8-sig") if os.path.exists(AI_DATASET_CSV) else None

    if human_df is None or ai_df is None:
        return

    human_merged = human_df["is_merged"].apply(lambda x: str(x).lower() in ("true", "1")).mean()
    ai_merged = ai_df["is_merged"].apply(lambda x: str(x).lower() in ("true", "1")).mean()
    human_review = (human_df["review_comments_text"].fillna("").str.strip() != "").mean()
    ai_review = (ai_df["review_comments_text"].fillna("").str.strip() != "").mean()

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))

    axes[0].bar(["Human (n=1500)", "AI (n={})".format(len(ai_df))],
                [len(human_df), len(ai_df)], color=["#2196F3", "#FF9800"])
    axes[0].set_title("Sample Size")
    axes[0].set_ylabel("PR Count")

    axes[1].bar(["Human", "AI"], [human_merged * 100, ai_merged * 100],
                color=["#2196F3", "#FF9800"])
    axes[1].set_title("Merge Rate (%)")
    axes[1].set_ylabel("%")
    for i, v in enumerate([human_merged * 100, ai_merged * 100]):
        axes[1].text(i, v + 1, f"{v:.1f}%", ha="center")

    axes[2].bar(["Human", "AI"], [human_review * 100, ai_review * 100],
                color=["#2196F3", "#FF9800"])
    axes[2].set_title("Review Coverage (%)")
    axes[2].set_ylabel("%")
    for i, v in enumerate([human_review * 100, ai_review * 100]):
        axes[2].text(i, v + 1, f"{v:.1f}%", ha="center")

    fig.suptitle("Human vs AI-Generated Code: Dataset Comparison", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "02_ai_vs_human_distribution.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图3: 传统 ML 在 AI PR 上的表现
# ============================================================
def fig_03_traditional_ml():
    logger.info("图3: 传统ML AI性能")
    metrics = load_json_safe(os.path.join(RESULTS_EVALUATION_DIR, "traditional_ml_metrics.json"))
    if not metrics:
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    models = list(metrics.keys())
    x = np.arange(len(models))
    width = 0.15

    for i, metric_name in enumerate(["accuracy", "precision", "recall", "f1"]):
        values = [metrics[m].get(metric_name, 0) or 0 for m in models]
        bars = ax.bar(x + i * width, values, width, label=metric_name.capitalize())
        for bar, v in zip(bars, values):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                        f"{v:.3f}", ha="center", fontsize=7, rotation=90)

    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels([m.upper() for m in models])
    ax.set_ylabel("Score")
    ax.set_title("Traditional ML Performance on AI-Generated PRs")
    ax.legend()
    ax.set_ylim(0, 1.1)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "03_traditional_ml_ai_performance.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图4: LLM 在 AI PR 上的表现
# ============================================================
def fig_04_llm_ai_performance():
    logger.info("图4: LLM AI性能")
    metrics = load_json_safe(os.path.join(RESULTS_EVALUATION_DIR, "llm_metrics.json"))
    if not metrics:
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    combos = list(metrics.keys())
    x = np.arange(len(combos))
    width = 0.15

    for i, metric_name in enumerate(["accuracy", "precision", "recall", "f1"]):
        values = [metrics[c].get(metric_name, 0) or 0 for c in combos]
        bars = ax.bar(x + i * width, values, width, label=metric_name.capitalize())
        for bar, v in zip(bars, values):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                        f"{v:.3f}", ha="center", fontsize=7, rotation=90)

    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(combos)
    ax.set_ylabel("Score")
    ax.set_title("DeepSeek Performance on AI-Generated PRs")
    ax.legend()
    ax.set_ylim(0, 1.1)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "04_llm_ai_performance.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图5: 人类 vs AI 模型对比
# ============================================================
def fig_05_human_vs_ai_comparison():
    logger.info("图5: 人类vs AI对比")
    comparison = load_json_safe(os.path.join(RESULTS_EVALUATION_DIR, "human_vs_ai_comparison.json"))
    if not comparison:
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # ML对比
    ml_data = comparison.get("traditional_ml", {})
    if ml_data:
        ax = axes[0]
        models = list(ml_data.keys())
        x = np.arange(len(models))
        width = 0.25
        human_f1 = [ml_data[m].get("human_test", {}).get("f1") or 0 for m in models]
        ai_f1 = [ml_data[m].get("ai_test", {}).get("f1") or 0 for m in models]
        ax.bar(x - width / 2, human_f1, width, label="Human Code", color="#2196F3")
        ax.bar(x + width / 2, ai_f1, width, label="AI Code", color="#FF9800")
        for i, (h, a) in enumerate(zip(human_f1, ai_f1)):
            delta = a - h
            ax.annotate(f"{delta:+.3f}", (x[i], max(h, a) + 0.02), ha="center", fontsize=9,
                        color="red" if delta < 0 else "green")
        ax.set_xticks(x)
        ax.set_xticklabels([m.upper() for m in models])
        ax.set_ylabel("F1 Score")
        ax.set_title("Traditional ML: Human vs AI Code")
        ax.legend()

    # LLM对比
    llm_data = comparison.get("llm", {})
    if llm_data:
        ax = axes[1]
        combos = list(llm_data.keys())
        x = np.arange(len(combos))
        human_f1 = [llm_data[c].get("human_sample_50", {}).get("f1") or 0 for c in combos]
        ai_f1 = [llm_data[c].get("ai_test", {}).get("f1") or 0 for c in combos]
        ax.bar(x - width / 2, human_f1, width, label="Human Code", color="#2196F3")
        ax.bar(x + width / 2, ai_f1, width, label="AI Code", color="#FF9800")
        for i, (h, a) in enumerate(zip(human_f1, ai_f1)):
            delta = a - h
            ax.annotate(f"{delta:+.3f}", (x[i], max(h, a) + 0.02), ha="center", fontsize=9,
                        color="red" if delta < 0 else "green")
        ax.set_xticks(x)
        ax.set_xticklabels(combos)
        ax.set_ylabel("F1 Score")
        ax.set_title("DeepSeek: Human vs AI Code")
        ax.legend()

    fig.suptitle("Cross-Scenario Generalization: Human Code → AI Code", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "05_human_vs_ai_model_comparison.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图6: 混淆矩阵
# ============================================================
def fig_06_confusion_matrices():
    logger.info("图6: 混淆矩阵")
    ml_metrics = load_json_safe(os.path.join(RESULTS_EVALUATION_DIR, "traditional_ml_metrics.json"))
    llm_metrics = load_json_safe(os.path.join(RESULTS_EVALUATION_DIR, "llm_metrics.json"))

    n_plots = len(ml_metrics) + (1 if llm_metrics else 0)
    if n_plots == 0:
        return

    fig, axes = plt.subplots(1, n_plots, figsize=(4 * n_plots, 4))
    if n_plots == 1:
        axes = [axes]

    idx = 0
    for model_name, m in ml_metrics.items():
        cm = np.array(m.get("confusion_matrix", [[0, 0], [0, 0]]))
        ax = axes[idx]
        im = ax.imshow(cm, cmap="Blues")
        ax.set_title(f"{model_name.upper()}")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Pred No", "Pred Yes"])
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["Actual No", "Actual Yes"])
        for i in range(2):
            for j in range(2):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center", fontsize=14)
        idx += 1

    # LLM (取第一个组合)
    if llm_metrics:
        combo = list(llm_metrics.keys())[0]
        cm = np.array(llm_metrics[combo].get("confusion_matrix", [[0, 0], [0, 0]]))
        ax = axes[idx]
        im = ax.imshow(cm, cmap="Oranges")
        ax.set_title(f"DeepSeek {combo}")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Pred No", "Pred Yes"])
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["Actual No", "Actual Yes"])
        for i in range(2):
            for j in range(2):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center", fontsize=14)

    fig.suptitle("Confusion Matrices on AI-Generated PRs", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "06_confusion_matrices.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图7: Comment Generation 指标
# ============================================================
def fig_07_comment_generation():
    logger.info("图7: Comment Generation")
    metrics = load_json_safe(os.path.join(RESULTS_EVALUATION_DIR, "comment_generation_metrics.json"))
    if not metrics:
        return

    combos = list(metrics.keys())
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(combos))
    width = 0.2
    for i, metric_name in enumerate(["avg_bleu", "avg_rouge1", "avg_rouge2", "avg_rougeL"]):
        values = [metrics[c].get(metric_name, 0) or 0 for c in combos]
        ax.bar(x + i * width, values, width, label=metric_name.replace("avg_", "").upper())

    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(combos)
    ax.set_ylabel("Score")
    ax.set_title("Review Comment Generation Metrics on AI PRs")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "07_comment_generation_metrics.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图8: 错误分析
# ============================================================
def fig_08_error_analysis():
    logger.info("图8: 错误分析")
    errors = load_json_safe(os.path.join(RESULTS_EVALUATION_DIR, "error_analysis.json"))
    if not errors:
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # FP/FN 数量
    models = list(errors.keys())
    fp_counts = [errors[m].get("false_positives", 0) for m in models]
    fn_counts = [errors[m].get("false_negatives", 0) for m in models]
    x = np.arange(len(models))
    width = 0.3
    axes[0].bar(x - width / 2, fp_counts, width, label="False Positive", color="#FF5722")
    axes[0].bar(x + width / 2, fn_counts, width, label="False Negative", color="#FF9800")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([m.upper() for m in models])
    axes[0].set_ylabel("Count")
    axes[0].set_title("False Positives vs False Negatives")
    axes[0].legend()

    # 按仓库的 FP/FN
    all_fp_repos = set()
    for m in models:
        all_fp_repos.update(errors[m].get("fp_repos", {}).keys())
        all_fp_repos.update(errors[m].get("fn_repos", {}).keys())
    all_fp_repos = sorted(all_fp_repos)

    if all_fp_repos and models:
        m = models[0]
        fp_repos = errors[m].get("fp_repos", {})
        fn_repos = errors[m].get("fn_repos", {})
        x2 = np.arange(len(all_fp_repos))
        axes[1].bar(x2 - 0.2, [fp_repos.get(r, 0) for r in all_fp_repos],
                    0.4, label="FP", color="#FF5722")
        axes[1].bar(x2 + 0.2, [fn_repos.get(r, 0) for r in all_fp_repos],
                    0.4, label="FN", color="#FF9800")
        axes[1].set_xticks(x2)
        axes[1].set_xticklabels([r.split("/")[-1] for r in all_fp_repos], rotation=30, ha="right")
        axes[1].set_ylabel("Count")
        axes[1].set_title(f"Error Distribution by Repository ({m.upper()})")
        axes[1].legend()

    fig.suptitle("Error Analysis on AI-Generated PRs", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES_DIR, "08_error_analysis.png"), **SAVE_KWARGS)
    plt.close(fig)


# ============================================================
# 图9: 4×4 Prompt×Context 热力图 (2.6.2)
# ============================================================
def fig_09_llm_4x4_heatmap():
    """4×4 Prompt×Context 热力图"""
    logger.info("图9: 4×4 Prompt×Context 热力图")
    metrics_path = os.path.join(RESULTS_EVALUATION_DIR, "llm_4x4_metrics.json")
    if not os.path.exists(metrics_path):
        logger.info("4x4 指标文件不存在，跳过热力图")
        return

    with open(metrics_path, "r", encoding="utf-8") as f:
        metrics = json.load(f)
    if not metrics:
        return

    PROMPT_LABELS = ["P1\nZero-shot", "P2\nFew-shot", "P3\nRole-based", "P4\nCoT"]
    CONTEXT_LABELS = ["C1\nDiff Only", "C2\n+PR Desc", "C3\n+Commit", "C4\nFull"]

    metrics_list = ["f1", "accuracy", "precision", "recall", "roc_auc"]
    matrices = {m: np.full((4, 4), np.nan) for m in metrics_list}

    for combo, vals in metrics.items():
        pt = vals.get("prompt_type", "")
        ct = vals.get("context_type", "")
        if not pt or not ct:
            continue
        p_idx = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(pt, -1)
        c_idx = {"C1": 0, "C2": 1, "C3": 2, "C4": 3}.get(ct, -1)
        if p_idx < 0 or c_idx < 0:
            continue
        for m in metrics_list:
            v = vals.get(m)
            if v is not None and not np.isnan(v):
                matrices[m][p_idx, c_idx] = v

    fig, axes = plt.subplots(2, 3, figsize=(20, 13))
    axes = axes.flatten()

    for i, metric_name in enumerate(metrics_list):
        ax = axes[i]
        data = matrices[metric_name]
        mask = np.isnan(data)

        im = ax.imshow(data, cmap="YlOrRd", vmin=0.0, vmax=1.0, aspect="auto")
        ax.set_xticks(range(4))
        ax.set_xticklabels(CONTEXT_LABELS, fontsize=9)
        ax.set_yticks(range(4))
        ax.set_yticklabels(PROMPT_LABELS, fontsize=9)
        ax.set_title(metric_name.upper(), fontsize=13, fontweight="bold")

        for r in range(4):
            for c in range(4):
                if not mask[r, c]:
                    val = data[r, c]
                    text_color = "white" if val < 0.55 else "black"
                    ax.text(c, r, f"{val:.3f}", ha="center", va="center",
                            fontsize=10, fontweight="bold", color=text_color)

        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    # 第6格: 摘要
    ax = axes[5]
    ax.axis("off")
    best_items = sorted(metrics.items(), key=lambda x: x[1].get("f1", 0) or 0, reverse=True)
    lines = [
        "4×4 Prompt×Context Matrix",
        "on AI-Generated PRs (n=50 sample)",
        "",
        f"Total combos evaluated: {len(metrics)} / 16",
    ]
    if best_items:
        best = best_items[0]
        lines.append(f"Best F1: {best[0]} = {best[1].get('f1', 0):.4f}")
        lines.append(f"Best Acc: {best[0]} = {best[1].get('accuracy', 0):.4f}")
    top3 = best_items[:3]
    lines.append("")
    lines.append("Top-3 by F1:")
    for rank, (combo, vals) in enumerate(top3, 1):
        lines.append(f"  {rank}. {combo} F1={vals.get('f1', 0):.4f} Acc={vals.get('accuracy', 0):.4f}")

    ax.text(0.5, 0.5, "\n".join(lines), transform=ax.transAxes,
            fontsize=12, ha="center", va="center",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
            fontfamily="monospace")

    fig.suptitle("Prompt × Context Full Combination Baseline on AI-Generated PRs (Experiment 5 §2.6.2)",
                 fontsize=16, fontweight="bold")
    fig.tight_layout()
    out_path = os.path.join(FIGURES_DIR, "09_llm_4x4_prompt_context_heatmap.png")
    fig.savefig(out_path, **SAVE_KWARGS)
    plt.close(fig)
    logger.info(f"4×4 热力图已保存: {out_path}")


def generate_all_figures():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    logger.info("开始生成图表...")
    fig_01_dataset_distribution()
    fig_02_human_vs_ai_distribution()
    fig_03_traditional_ml()
    fig_04_llm_ai_performance()
    fig_05_human_vs_ai_comparison()
    fig_06_confusion_matrices()
    fig_07_comment_generation()
    fig_08_error_analysis()
    fig_09_llm_4x4_heatmap()
    logger.info(f"图表已保存至: {FIGURES_DIR}")


if __name__ == "__main__":
    generate_all_figures()
