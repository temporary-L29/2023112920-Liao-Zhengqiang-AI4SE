"""
实验二 步骤九：可视化
生成 10 张图表，风格与实验一保持一致（300 DPI）。
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from sklearn.metrics import roc_curve, auc, ConfusionMatrixDisplay

from config import PROCESSED_DIR, MODELS_DIR, EVALUATION_DIR, FIGURES_DIR
from utils import log, read_json

# 全局样式
plt.rcParams.update({
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
})


def _save(fig, name: str):
    path = FIGURES_DIR / name
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    log.info(f"图表已保存: {path}")


# ============================================================
# Figure 1: 人类代码数据集仓库分布与合并率
# ============================================================
def plot_human_dataset_distribution():
    df = pd.read_csv(PROCESSED_DIR / "human_only_dataset.csv")
    stats = read_json(PROCESSED_DIR / "human_dataset_stats.json")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    repos = [r["repo"] for r in stats["per_repo"]]
    prs = [r["prs"] for r in stats["per_repo"]]
    merge_rates = [r["merge_rate"] for r in stats["per_repo"]]
    short_names = [r.split("/")[-1] for r in repos]

    colors = ["#E74C3C" if m < 60 else "#2ECC71" for m in merge_rates]

    # Left: PR count
    bars = ax1.barh(short_names, prs, color=colors, edgecolor="white", linewidth=0.5)
    ax1.set_xlabel("PR Count")
    ax1.set_title("Human-Written PRs by Repository")
    for bar, val in zip(bars, prs):
        ax1.text(bar.get_width() + 3, bar.get_y() + bar.get_height() / 2,
                 str(val), va="center", fontsize=9)

    # Right: Merge rate
    bars2 = ax2.barh(short_names, merge_rates, color=colors, edgecolor="white", linewidth=0.5)
    ax2.set_xlabel("Merge Rate (%)")
    ax2.set_title("Merge Rate by Repository")
    ax2.axvline(x=stats["overall"]["merged_pct"], color="gray",
                linestyle="--", alpha=0.5, label=f"Overall: {stats['overall']['merged_pct']}%")
    ax2.legend(fontsize=8)
    for bar, val in zip(bars2, merge_rates):
        ax2.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                 f"{val:.1f}%", va="center", fontsize=9)

    fig.suptitle("Human-Written Code Dataset Overview", fontsize=14, fontweight="bold")
    fig.tight_layout()
    _save(fig, "01_human_dataset_distribution.png")


# ============================================================
# Figure 2: 语言分布与 patch 覆盖率
# ============================================================
def plot_language_patch_coverage():
    coverage = read_json(PROCESSED_DIR / "patch_coverage_stats.json")
    ext_dist = coverage["extension_distribution"]

    # Top-15 extensions
    top_exts = dict(sorted(ext_dist.items(), key=lambda x: x[1], reverse=True)[:15])

    fig, ax = plt.subplots(figsize=(10, 6))
    names = list(top_exts.keys())
    names_display = [n if n else "(no ext)" for n in names]
    counts = list(top_exts.values())

    # Color: code vs config vs doc vs other
    code_exts = {".py", ".go", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".rs"}
    doc_exts = {".md", ".rst", ".txt"}
    config_exts = {".json", ".yml", ".yaml", ".toml", ".xml"}

    bar_colors = []
    for n in names:
        if n in code_exts:
            bar_colors.append("#3498DB")
        elif n in doc_exts:
            bar_colors.append("#95A5A6")
        elif n in config_exts:
            bar_colors.append("#F39C12")
        else:
            bar_colors.append("#E74C3C")

    bars = ax.bar(names_display, counts, color=bar_colors, edgecolor="white")
    ax.set_xlabel("File Extension")
    ax.set_ylabel("File Count")
    ax.set_title("File Extension Distribution (Top 15)")

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#3498DB", label="Code"),
        Patch(facecolor="#95A5A6", label="Documentation"),
        Patch(facecolor="#F39C12", label="Config/Data"),
        Patch(facecolor="#E74C3C", label="Other"),
    ]
    ax.legend(handles=legend_elements, fontsize=8)

    # Coverage annotation
    ax.text(0.98, 0.95,
            f"PR patch coverage: {coverage['pr_patch_coverage']}%\n"
            f"File patch coverage: {coverage['file_patch_coverage']}%\n"
            f"Total added lines: {coverage['total_added_lines']:,}",
            transform=ax.transAxes, fontsize=8, va="top", ha="right",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    _save(fig, "02_language_patch_coverage.png")


# ============================================================
# Figure 3: AST/CFG 解析覆盖率
# ============================================================
def plot_ast_cfg_coverage():
    ast_df = pd.read_csv(PROCESSED_DIR / "ast_features.csv")
    cfg_df = pd.read_csv(PROCESSED_DIR / "cfg_features.csv")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))

    # AST parse success rate distribution
    ax1 = axes[0]
    rates = ast_df["ast_parse_success_rate"] * 100
    ax1.hist(rates, bins=20, color="#3498DB", edgecolor="white", alpha=0.8)
    ax1.axvline(x=rates.mean(), color="red", linestyle="--",
                label=f"Mean: {rates.mean():.1f}%")
    ax1.set_xlabel("Parse Success Rate (%)")
    ax1.set_ylabel("PR Count")
    ax1.set_title("AST Parse Success Rate")
    ax1.legend(fontsize=8)

    # AST: tree-sitter vs fallback
    ax2 = axes[1]
    ts_only = (ast_df["ast_files_parsed"] > 0) & (ast_df["ast_files_fallback"] == 0)
    fallback = ast_df["ast_files_fallback"] > 0
    no_ast = ast_df["ast_files_parsed"] == 0
    sizes = [ts_only.sum(), fallback.sum(), no_ast.sum()]
    labels = [f"Tree-sitter only\n({sizes[0]})",
              f"With fallback\n({sizes[1]})",
              f"No AST\n({sizes[2]})"]
    colors_ast = ["#2ECC71", "#F39C12", "#E74C3C"]
    ax2.pie(sizes, labels=labels, colors=colors_ast, autopct="%1.1f%%",
            startangle=90, explode=(0, 0, 0.05))
    ax2.set_title("AST Method Distribution")

    # CFG availability
    ax3 = axes[2]
    cfg_avail = cfg_df["cfg_available"].sum()
    cfg_not = (~cfg_df["cfg_available"]).sum()
    sizes_cfg = [cfg_avail, cfg_not]
    labels_cfg = [f"CFG Available\n({cfg_avail})", f"No CFG\n({cfg_not})"]
    colors_cfg = ["#2ECC71", "#E74C3C"]
    ax3.pie(sizes_cfg, labels=labels_cfg, colors=colors_cfg, autopct="%1.1f%%",
            startangle=90)
    ax3.set_title("CFG Availability")

    fig.suptitle("AST & CFG Coverage Analysis", fontsize=14, fontweight="bold")
    fig.tight_layout()
    _save(fig, "03_ast_cfg_coverage.png")


# ============================================================
# Figure 4: 特征相关性热力图
# ============================================================
def plot_feature_correlation_heatmap():
    fm = pd.read_csv(PROCESSED_DIR / "features_main.csv")
    aux = ["pr_id", "repo", "is_merged", "split"]
    feat_df = fm[[c for c in fm.columns if c not in aux]]

    # Select top features (by variance, or key groups)
    key_features = [
        "num_changed_files", "total_additions", "total_deletions",
        "num_commits", "code_churn", "net_lines",
        "title_len", "body_len", "commit_msg_len",
        "title_word_count", "body_word_count",
        "num_code_files", "num_test_files", "test_file_ratio",
        "ast_total_nodes", "ast_max_depth", "ast_func_def_count",
        "ast_if_count", "ast_loop_count",
        "cfg_total_nodes", "cfg_cyclomatic_complexity",
        "cfg_branch_nodes", "cfg_loop_nodes",
    ]
    # Only keep columns that exist
    key_features = [c for c in key_features if c in feat_df.columns]

    corr = feat_df[key_features].corr()

    fig, ax = plt.subplots(figsize=(14, 12))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap="RdBu_r",
                center=0, vmin=-1, vmax=1, square=True,
                linewidths=0.5, cbar_kws={"shrink": 0.8}, ax=ax)
    ax.set_title("Feature Correlation Heatmap (Key Features)", fontsize=14,
                 fontweight="bold")
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.yticks(fontsize=8)
    fig.tight_layout()
    _save(fig, "04_feature_correlation_heatmap.png")


# ============================================================
# Figure 5: ROC 曲线对比
# ============================================================
def plot_roc_curves():
    import joblib

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    for name, feat_file, ax, title in [
        ("main", "features_main.csv", ax1, "Main Experiment"),
        ("upper_bound", "features_upper_bound.csv", ax2, "Upper Bound"),
    ]:
        fm = pd.read_csv(PROCESSED_DIR / feat_file)
        test_df = fm[fm["split"] == "test"]
        aux = ["pr_id", "repo", "is_merged", "split"]
        feat_cols = [c for c in fm.columns if c not in aux]
        X_test = test_df[feat_cols].values
        y_test = test_df["is_merged"].values.astype(int)

        for mt, color, label in [("svm", "#E74C3C", "SVM"),
                                   ("randomforest", "#3498DB", "Random Forest")]:
            model_path = MODELS_DIR / f"{mt}_{name}.joblib"
            if model_path.exists():
                model = joblib.load(model_path)
                y_prob = model.predict_proba(X_test)[:, 1]
                fpr, tpr, _ = roc_curve(y_test, y_prob)
                roc_auc = auc(fpr, tpr)
                ax.plot(fpr, tpr, color=color, lw=2,
                        label=f"{label} (AUC={roc_auc:.3f})")

        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.3, label="Random")
        ax.set_xlabel("False Positive Rate")
        ax.set_ylabel("True Positive Rate")
        ax.set_title(title)
        ax.legend(fontsize=9, loc="lower right")
        ax.set_xlim([-0.02, 1.02])
        ax.set_ylim([-0.02, 1.02])

    fig.suptitle("ROC Curves: SVM vs Random Forest", fontsize=14, fontweight="bold")
    fig.tight_layout()
    _save(fig, "05_roc_curve_main.png")


# ============================================================
# Figures 6 & 7: 混淆矩阵
# ============================================================
def plot_confusion_matrices():
    import joblib
    fm = pd.read_csv(PROCESSED_DIR / "features_main.csv")
    test_df = fm[fm["split"] == "test"]
    aux = ["pr_id", "repo", "is_merged", "split"]
    feat_cols = [c for c in fm.columns if c not in aux]
    X_test = test_df[feat_cols].values
    y_test = test_df["is_merged"].values.astype(int)

    for mt, figname in [("svm", "06_confusion_matrix_svm"),
                          ("randomforest", "07_confusion_matrix_rf")]:
        model_path = MODELS_DIR / f"{mt}_main.joblib"
        if not model_path.exists():
            continue

        model = joblib.load(model_path)
        y_pred = model.predict(X_test)

        fig, ax = plt.subplots(figsize=(5, 4.5))
        ConfusionMatrixDisplay.from_predictions(
            y_test, y_pred,
            display_labels=["Not Merged", "Merged"],
            cmap="Blues", colorbar=False, ax=ax,
        )
        ax.set_title(f"{'SVM' if mt == 'svm' else 'Random Forest'} "
                     f"Confusion Matrix (Main)")
        fig.tight_layout()
        _save(fig, f"{figname}.png")


# ============================================================
# Figure 8: 特征重要性 Top-20
# ============================================================
def plot_feature_importance():
    fi_path = EVALUATION_DIR / "feature_importance.csv"
    if not fi_path.exists():
        log.warning(f"特征重要性文件不存在: {fi_path}")
        return

    fi_df = pd.read_csv(fi_path)
    top20 = fi_df.head(20).iloc[::-1]  # Reverse for horizontal bar

    fig, ax = plt.subplots(figsize=(10, 7))
    colors = []
    for feat in top20["feature"]:
        if feat.startswith("ast_"):
            colors.append("#2ECC71")
        elif feat.startswith("cfg_"):
            colors.append("#3498DB")
        elif feat.startswith("repo_"):
            colors.append("#9B59B6")
        elif feat in ("ast_missing", "cfg_missing"):
            colors.append("#E74C3C")
        else:
            colors.append("#F39C12")

    ax.barh(range(len(top20)), top20["importance"], color=colors,
            edgecolor="white", linewidth=0.5)
    ax.set_yticks(range(len(top20)))
    ax.set_yticklabels(top20["feature"], fontsize=8)
    ax.set_xlabel("Feature Importance")
    ax.set_title("Random Forest Top-20 Feature Importance (Main)")

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#F39C12", label="Code/Text Stats"),
        Patch(facecolor="#2ECC71", label="AST"),
        Patch(facecolor="#3498DB", label="CFG"),
        Patch(facecolor="#9B59B6", label="Repo One-Hot"),
        Patch(facecolor="#E74C3C", label="Missing Flag"),
    ]
    ax.legend(handles=legend_elements, fontsize=8, loc="lower right")

    fig.tight_layout()
    _save(fig, "08_feature_importance.png")


# ============================================================
# Figure 9: 消融实验对比
# ============================================================
def plot_ablation_comparison():
    ablation_path = EVALUATION_DIR / "ablation_results.json"
    if not ablation_path.exists():
        log.warning(f"消融结果文件不存在: {ablation_path}")
        return

    ablation = read_json(ablation_path)

    fig, ax = plt.subplots(figsize=(10, 6))
    names = [a["feature_set"] for a in ablation]
    accs = [a["accuracy"] for a in ablation]
    f1s = [a["f1_score"] for a in ablation]
    aucs = [a["roc_auc"] for a in ablation]

    x = np.arange(len(names))
    width = 0.25

    bars1 = ax.bar(x - width, accs, width, label="Accuracy",
                   color="#3498DB", edgecolor="white")
    bars2 = ax.bar(x, f1s, width, label="F1-score",
                   color="#2ECC71", edgecolor="white")
    bars3 = ax.bar(x + width, aucs, width, label="ROC-AUC",
                   color="#E74C3C", edgecolor="white")

    ax.set_xticks(x)
    ax.set_xticklabels([n.replace("_", "\n") for n in names], fontsize=9)
    ax.set_ylabel("Score")
    ax.set_title("Ablation Study: Feature Group Contribution (RF)")
    ax.legend(fontsize=9)
    ax.set_ylim(0.5, 0.9)

    # Value labels
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height + 0.005,
                    f"{height:.3f}", ha="center", va="bottom", fontsize=7)

    fig.tight_layout()
    _save(fig, "09_ablation_comparison.png")


# ============================================================
# Figure 10: 分仓库性能对比
# ============================================================
def plot_per_repo_performance():
    eval_path = EVALUATION_DIR / "evaluation_main.json"
    if not eval_path.exists():
        log.warning(f"评估结果文件不存在: {eval_path}")
        return

    eval_data = read_json(eval_path)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    for ax, metric in [(axes[0], "f1_score"), (axes[1], "roc_auc")]:
        for mt, color, marker in [("svm", "#E74C3C", "s"),
                                    ("randomforest", "#3498DB", "o")]:
            if mt not in eval_data:
                continue
            per_repo = eval_data[mt]["per_repo"]
            repos = [r["repo"].split("/")[-1] for r in per_repo]
            scores = [r[metric] for r in per_repo]

            ax.plot(repos, scores, color=color, marker=marker,
                    linewidth=2, markersize=8, label=mt.upper())

        ax.set_ylabel(metric.replace("_", " ").upper())
        ax.set_title(f"Per-Repository {metric.replace('_', ' ').upper()}")
        ax.legend(fontsize=8)
        ax.set_ylim(0.3, 1.05)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)

    fig.suptitle("Per-Repository Performance Comparison", fontsize=14,
                 fontweight="bold")
    fig.tight_layout()
    _save(fig, "10_per_repo_performance.png")


# ============================================================
# 批量生成所有图表
# ============================================================
def run_all():
    """生成全部 10 张图表。"""
    log.info("开始生成可视化图表...")

    plot_functions = [
        ("01: 人类代码数据集分布", plot_human_dataset_distribution),
        ("02: 语言与 patch 覆盖率", plot_language_patch_coverage),
        ("03: AST/CFG 覆盖率", plot_ast_cfg_coverage),
        ("04: 特征相关性热力图", plot_feature_correlation_heatmap),
        ("05: ROC 曲线对比", plot_roc_curves),
        ("06: SVM 混淆矩阵", plot_confusion_matrices),
        ("07: RF 混淆矩阵", lambda: None),  # handled in 06
        ("08: 特征重要性", plot_feature_importance),
        ("09: 消融实验对比", plot_ablation_comparison),
        ("10: 分仓库性能", plot_per_repo_performance),
    ]

    for label, func in plot_functions:
        if func is None:
            continue
        try:
            log.info(f"生成图表 {label}...")
            func()
        except Exception as e:
            log.error(f"图表 {label} 生成失败: {e}")
            import traceback
            traceback.print_exc()

    log.info(f"图表生成完成，输出目录: {FIGURES_DIR}")


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    run_all()
