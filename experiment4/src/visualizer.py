"""
实验三 步骤六：可视化
生成至少 8 张图。
"""
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path

from config import (
    FIGURES_DIR, FIGURE_DPI, FIGURE_FORMAT,
    PROMPT_TYPES, CONTEXT_TYPES, CONTEXT_CONFIG, PROMPT_CONFIG,
    PARSED_PREDICTIONS_CSV, METRICS_BY_PROMPT_CONTEXT_JSON,
    COMMENT_GENERATION_METRICS_JSON, EVALUATION_DIR,
    PROCESSED_DIR,
)
from utils import log, read_json, write_json


# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def save_figure(fig, name: str):
    """保存图表。"""
    path = FIGURES_DIR / f"{name}.{FIGURE_FORMAT}"
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches='tight')
    plt.close(fig)
    log.info(f"  保存: {path}")


# ============================================================
# 图 1: 50 条样本仓库与 merge 分布
# ============================================================
def plot_sample_distribution(sample_df: pd.DataFrame):
    log.info("图 1: 样本分布")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 左图：各仓库样本数
    ax = axes[0]
    repo_counts = sample_df.groupby("repo").size()
    colors = ['#2196F3', '#4CAF50', '#FF9800', '#E91E63', '#9C27B0']
    bars = ax.bar(range(len(repo_counts)), repo_counts.values, color=colors)
    ax.set_xticks(range(len(repo_counts)))
    ax.set_xticklabels([r.split('/')[-1] for r in repo_counts.index],
                       rotation=20, ha='right', fontsize=9)
    ax.set_ylabel("Number of PRs")
    ax.set_title("Sample Distribution by Repository")
    for bar, val in zip(bars, repo_counts.values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                str(val), ha='center', fontsize=10)

    # 右图：merged/unmerged 分布
    ax = axes[1]
    repo_merged = sample_df.groupby("repo")["is_merged"].agg(['sum', 'count'])
    repos_short = [r.split('/')[-1] for r in repo_merged.index]
    x = np.arange(len(repos_short))
    width = 0.35
    ax.bar(x - width/2, repo_merged['sum'], width, label='Merged',
           color='#4CAF50')
    ax.bar(x + width/2, repo_merged['count'] - repo_merged['sum'], width,
           label='Not Merged', color='#F44336')
    ax.set_xticks(x)
    ax.set_xticklabels(repos_short, rotation=20, ha='right', fontsize=9)
    ax.set_ylabel("Number of PRs")
    ax.set_title("Merge Status by Repository")
    ax.legend(fontsize=8)

    plt.tight_layout()
    save_figure(fig, "01_sample_distribution")


# ============================================================
# 图 2: 4 种上下文长度与截断率
# ============================================================
def plot_context_lengths(pred_df: pd.DataFrame):
    log.info("图 2: 上下文长度与截断率")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 左图：上下文长度箱线图
    ax = axes[0]
    data_by_ctx = []
    labels = []
    for ctx in CONTEXT_TYPES:
        lengths = pred_df[pred_df["context_type"] == ctx]["context_length"].dropna()
        if len(lengths) > 0:
            data_by_ctx.append(lengths.values)
            labels.append(ctx)

    bp = ax.boxplot(data_by_ctx, labels=labels, patch_artist=True)
    colors = ['#E3F2FD', '#BBDEFB', '#90CAF9', '#42A5F5']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
    ax.set_ylabel("Context Length (chars)")
    ax.set_title("Context Length Distribution by Type")

    # 右图：截断率
    ax = axes[1]
    threshold = 10000  # ~2500 tokens
    truncation_rates = []
    for ctx in CONTEXT_TYPES:
        ctx_data = pred_df[pred_df["context_type"] == ctx]["context_length"].dropna()
        if len(ctx_data) > 0:
            rate = (ctx_data > threshold).mean() * 100
            truncation_rates.append(rate)
        else:
            truncation_rates.append(0)

    ax.bar(CONTEXT_TYPES, truncation_rates, color=colors)
    ax.set_ylabel("Truncation Rate (%)")
    ax.set_title(f"Truncation Rate (> {threshold} chars)")
    for i, rate in enumerate(truncation_rates):
        ax.text(i, rate + 1, f"{rate:.1f}%", ha='center', fontsize=10)

    plt.tight_layout()
    save_figure(fig, "02_context_lengths")


# ============================================================
# 图 3: Prompt × Context Accuracy 热力图
# ============================================================
def plot_heatmap(metrics: dict, metric_key: str, title: str, filename: str):
    """通用热力图绘制函数。"""
    # metrics: {f"{prompt}_{context}": {...}}
    matrix = np.zeros((len(PROMPT_TYPES), len(CONTEXT_TYPES)))
    annot = np.empty((len(PROMPT_TYPES), len(CONTEXT_TYPES)), dtype=object)

    for i, pt in enumerate(PROMPT_TYPES):
        for j, ct in enumerate(CONTEXT_TYPES):
            key = f"{pt}_{ct}"
            if key in metrics:
                val = metrics[key].get(metric_key, np.nan)
                matrix[i][j] = val if val is not None and not np.isnan(val) else np.nan
                annot[i][j] = f"{val:.3f}" if val is not None and not np.isnan(val) else "N/A"
            else:
                matrix[i][j] = np.nan
                annot[i][j] = "N/A"

    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto', vmin=0, vmax=1)

    for i in range(len(PROMPT_TYPES)):
        for j in range(len(CONTEXT_TYPES)):
            if not np.isnan(matrix[i][j]):
                text_color = 'white' if matrix[i][j] > 0.6 else 'black'
                ax.text(j, i, annot[i][j], ha='center', va='center',
                       color=text_color, fontsize=11, fontweight='bold')

    ax.set_xticks(range(len(CONTEXT_TYPES)))
    ax.set_xticklabels([f"{c}\n({CONTEXT_CONFIG[c]['name']})" for c in CONTEXT_TYPES],
                       fontsize=8)
    ax.set_yticks(range(len(PROMPT_TYPES)))
    ax.set_yticklabels([f"{p}\n({PROMPT_CONFIG[p]['name']})" for p in PROMPT_TYPES],
                       fontsize=8)
    ax.set_title(title, fontsize=13, fontweight='bold')
    plt.colorbar(im, ax=ax, shrink=0.8)

    plt.tight_layout()
    save_figure(fig, filename)


def plot_all_heatmaps(metrics: dict):
    log.info("图 3: Accuracy 热力图")
    plot_heatmap(metrics, "accuracy",
                 "Prompt × Context: Accuracy", "03_accuracy_heatmap")

    log.info("图 4: F1 热力图")
    plot_heatmap(metrics, "f1",
                 "Prompt × Context: F1 Score", "04_f1_heatmap")

    log.info("图 5: ROC-AUC 热力图")
    plot_heatmap(metrics, "roc_auc",
                 "Prompt × Context: ROC-AUC", "05_roc_auc_heatmap")


# ============================================================
# 图 6: BLEU / ROUGE 对比图
# ============================================================
def plot_bleu_rouge(comment_metrics: dict):
    log.info("图 6: BLEU/ROUGE 对比图")

    per_combo = comment_metrics.get("per_combination", {})

    fig, ax = plt.subplots(figsize=(12, 6))

    x_labels = []
    bleu_vals = []
    rouge1_vals = []
    rougeL_vals = []

    for pt in PROMPT_TYPES:
        for ct in CONTEXT_TYPES:
            key = f"{pt}_{ct}"
            if key in per_combo:
                m = per_combo[key]
                x_labels.append(f"{pt}/{ct}")
                bleu_vals.append(m.get("avg_bleu", 0))
                rouge1_vals.append(m.get("avg_rouge1", 0))
                rougeL_vals.append(m.get("avg_rougeL", 0))

    x = np.arange(len(x_labels))
    width = 0.25

    ax.bar(x - width, bleu_vals, width, label='BLEU', color='#2196F3')
    ax.bar(x, rouge1_vals, width, label='ROUGE-1', color='#4CAF50')
    ax.bar(x + width, rougeL_vals, width, label='ROUGE-L', color='#FF9800')

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel("Score")
    ax.set_title("BLEU / ROUGE Scores by Prompt × Context")
    ax.legend(fontsize=9)
    ax.set_ylim(0, max(max(bleu_vals), max(rouge1_vals), max(rougeL_vals)) * 1.2)

    plt.tight_layout()
    save_figure(fig, "06_bleu_rouge_comparison")


# ============================================================
# 图 7: 推理时间对比图
# ============================================================
def plot_inference_time(pred_df: pd.DataFrame):
    log.info("图 7: 推理时间对比图")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 左图：按 Prompt 类型
    ax = axes[0]
    data_by_prompt = []
    for pt in PROMPT_TYPES:
        times = pred_df[pred_df["prompt_type"] == pt]["duration_ms"].dropna()
        if len(times) > 0:
            data_by_prompt.append(times.values)
    bp = ax.boxplot(data_by_prompt, labels=PROMPT_TYPES, patch_artist=True)
    colors = ['#E3F2FD', '#BBDEFB', '#90CAF9', '#42A5F5']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
    ax.set_ylabel("Duration (ms)")
    ax.set_title("Inference Time by Prompt Type")

    # 右图：按 Context 类型
    ax = axes[1]
    data_by_ctx = []
    for ct in CONTEXT_TYPES:
        times = pred_df[pred_df["context_type"] == ct]["duration_ms"].dropna()
        if len(times) > 0:
            data_by_ctx.append(times.values)
    bp = ax.boxplot(data_by_ctx, labels=CONTEXT_TYPES, patch_artist=True)
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
    ax.set_ylabel("Duration (ms)")
    ax.set_title("Inference Time by Context Type")

    plt.tight_layout()
    save_figure(fig, "07_inference_time")


# ============================================================
# 图 8: 最佳 LLM 组合与实验二模型对比
# ============================================================
def plot_model_comparison(merge_metrics: dict):
    log.info("图 8: 模型对比")

    # 尝试加载实验二的结果
    exp2_metrics_path = (
        Path(__file__).resolve().parent.parent.parent /
        "experiment2" / "results" / "evaluation" / "metrics_main.json"
    )

    exp2_data = {}
    if exp2_metrics_path.exists():
        exp2_data = read_json(exp2_metrics_path)
        log.info(f"  加载实验二指标: {exp2_metrics_path}")
    else:
        log.warning(f"  未找到实验二指标文件: {exp2_metrics_path}")

    # 找最佳 LLM 组合（按 F1）
    best_combo = None
    best_f1 = 0
    for key, m in merge_metrics.items():
        f1 = m.get("f1", 0)
        if f1 and f1 > best_f1:
            best_f1 = f1
            best_combo = m

    fig, ax = plt.subplots(figsize=(8, 6))

    models = []
    acc_values = []
    f1_values = []

    # 最佳 LLM
    if best_combo:
        models.append(f"LLM\n{best_combo['prompt_type']}"
                      f"/{best_combo['context_type']}")
        acc_values.append(best_combo.get("accuracy", 0))
        f1_values.append(best_combo.get("f1", 0))

    # 实验二模型 — 数据在 test_metrics 嵌套中
    if exp2_data:
        # 实验二 JSON 结构: {"svm": {"test_metrics": {"accuracy": ..., "f1_score": ...}}, ...}
        for model_name in ["svm", "random_forest"]:
            if model_name in exp2_data:
                tm = exp2_data[model_name].get("test_metrics", {})
                short_name = "SVM" if model_name == "svm" else "RF"
                models.append(short_name)
                acc_values.append(tm.get("accuracy", 0))
                f1_values.append(tm.get("f1_score", 0))

    x = np.arange(len(models))
    width = 0.35

    bars1 = ax.bar(x - width/2, acc_values, width, label='Accuracy',
                   color='#42A5F5')
    bars2 = ax.bar(x + width/2, f1_values, width, label='F1 Score',
                   color='#FF7043')

    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=10)
    ax.set_ylabel("Score")
    ax.set_title("Best LLM vs Experiment 2 Models (Main)")
    ax.legend()
    ax.set_ylim(0, 1)

    for bar, val in zip(bars1, acc_values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                    f"{val:.3f}", ha='center', fontsize=9)
    for bar, val in zip(bars2, f1_values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                    f"{val:.3f}", ha='center', fontsize=9)

    plt.tight_layout()
    save_figure(fig, "08_model_comparison")


# ============================================================
# 额外图表：JSON 解析失败率
# ============================================================
def plot_parse_fail_rate(metrics: dict):
    log.info("额外图: JSON 解析失败率")

    fig, ax = plt.subplots(figsize=(8, 5))

    matrix = np.zeros((len(PROMPT_TYPES), len(CONTEXT_TYPES)))
    for i, pt in enumerate(PROMPT_TYPES):
        for j, ct in enumerate(CONTEXT_TYPES):
            key = f"{pt}_{ct}"
            if key in metrics:
                matrix[i][j] = metrics[key].get("parse_fail_rate", 0) * 100

    im = ax.imshow(matrix, cmap='Reds', aspect='auto')

    for i in range(len(PROMPT_TYPES)):
        for j in range(len(CONTEXT_TYPES)):
            text_color = 'white' if matrix[i][j] > 50 else 'black'
            ax.text(j, i, f"{matrix[i][j]:.1f}%", ha='center', va='center',
                   color=text_color, fontsize=11, fontweight='bold')

    ax.set_xticks(range(len(CONTEXT_TYPES)))
    ax.set_xticklabels(CONTEXT_TYPES, fontsize=9)
    ax.set_yticks(range(len(PROMPT_TYPES)))
    ax.set_yticklabels(PROMPT_TYPES, fontsize=9)
    ax.set_title("JSON Parse Failure Rate (%)", fontsize=13, fontweight='bold')
    plt.colorbar(im, ax=ax, shrink=0.8)

    plt.tight_layout()
    save_figure(fig, "09_parse_fail_rate")


def run(sample_df: pd.DataFrame = None, pred_df: pd.DataFrame = None):
    """主入口：生成所有图表。"""
    log.info("=" * 60)
    log.info("步骤六：可视化")
    log.info("=" * 60)

    # 加载数据
    if sample_df is None:
        sample_df = pd.read_csv(PROCESSED_DIR / "llm_sample_50.csv")

    if pred_df is None:
        try:
            pred_df = pd.read_csv(PARSED_PREDICTIONS_CSV)
        except FileNotFoundError:
            log.warning("未找到解析后的预测文件，跳过需要 API 结果的图表")
            pred_df = None

    merge_metrics = {}
    try:
        merge_metrics = read_json(METRICS_BY_PROMPT_CONTEXT_JSON)
    except FileNotFoundError:
        pass

    comment_metrics = {}
    try:
        comment_metrics = read_json(COMMENT_GENERATION_METRICS_JSON)
    except FileNotFoundError:
        pass

    # 图 1：样本分布（总是可以画）
    plot_sample_distribution(sample_df)

    if pred_df is not None and len(pred_df) > 0:
        # 图 2：上下文长度
        plot_context_lengths(pred_df)

        # 图 7：推理时间
        plot_inference_time(pred_df)

    if merge_metrics:
        # 图 3-5：热力图
        plot_all_heatmaps(merge_metrics)

        # 额外图：解析失败率
        plot_parse_fail_rate(merge_metrics)

        # 图 8：模型对比
        plot_model_comparison(merge_metrics)

    if comment_metrics and comment_metrics.get("per_combination"):
        # 图 6：BLEU/ROUGE
        plot_bleu_rouge(comment_metrics)

    log.info("所有图表生成完毕")


if __name__ == "__main__":
    from utils import setup_logger
    log = setup_logger("experiment3", FIGURES_DIR.parent / "results" / "pipeline.log")
    run()
