"""
实验一：构建数据集 — 可视化
使用 matplotlib + seaborn 生成 6 张分析图表。
"""

import matplotlib
matplotlib.use("Agg")  # 非交互式后端
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from collections import Counter

import config
from utils import log


# ============================================================
# 全局样式
# ============================================================
# 中文字体回退链
plt.rcParams["font.sans-serif"] = [
    "SimHei", "Microsoft YaHei", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

sns.set_theme(style="whitegrid", context="paper", font_scale=1.1)

# 统一配色
PALETTE = "Set2"
FIG_SIZE = (10, 6)
DPI = 300


def save_figure(fig, filename):
    """保存图表到 figures 目录。"""
    path = config.FIGURES_DIR / filename
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    log.info(f"图表已保存: {path}")
    plt.close(fig)


# ============================================================
# 可视化器
# ============================================================
class Visualizer:
    """数据集可视化器。"""

    def __init__(self, csv_path=None):
        self.csv_path = csv_path or (
            config.PROCESSED_DATA_DIR / "dataset.csv"
        )
        self.df = None

    def load(self):
        """加载数据集。"""
        self.df = pd.read_csv(self.csv_path)
        log.info(f"加载 {len(self.df)} 条数据用于可视化")
        return self.df

    # --------------------------------------------------------
    # 图1：合并状态分组柱状图
    # --------------------------------------------------------
    def plot_merge_status_bar(self):
        """每仓库的合并/未合并分组柱状图。"""
        if self.df is None:
            self.load()

        fig, ax = plt.subplots(figsize=FIG_SIZE)

        repos = sorted(self.df["repo"].unique())
        merged_counts = []
        unmerged_counts = []

        for repo in repos:
            subset = self.df[self.df["repo"] == repo]
            merged_counts.append(subset["is_merged"].sum())
            unmerged_counts.append((~subset["is_merged"]).sum())

        x = np.arange(len(repos))
        width = 0.35

        bars1 = ax.bar(x - width/2, merged_counts, width,
                       label="Merged", color=sns.color_palette(PALETTE)[0])
        bars2 = ax.bar(x + width/2, unmerged_counts, width,
                       label="Unmerged", color=sns.color_palette(PALETTE)[1])

        # 柱上标注数值
        for bar in bars1:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., h + 2,
                    str(int(h)), ha="center", va="bottom", fontsize=9)
        for bar in bars2:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., h + 2,
                    str(int(h)), ha="center", va="bottom", fontsize=9)

        ax.set_xlabel("Repository")
        ax.set_ylabel("PR Count")
        ax.set_title("Merge Status by Repository")
        ax.set_xticks(x)
        ax.set_xticklabels(repos, rotation=15, ha="right")
        ax.legend()
        ax.set_ylim(0, max(max(merged_counts), max(unmerged_counts)) * 1.15)

        plt.tight_layout()
        save_figure(fig, "01_merge_status_bar.png")
        return fig, ax

    # --------------------------------------------------------
    # 图2：评论数量分布直方图
    # --------------------------------------------------------
    def plot_comment_distribution_hist(self):
        """审查评论数量的直方图 + KDE。"""
        if self.df is None:
            self.load()

        fig, ax = plt.subplots(figsize=FIG_SIZE)

        data = self.df["num_review_comments"].dropna()
        # 过滤极端异常值便于可视化
        q99 = data.quantile(0.99)
        data_filtered = data[data <= q99]

        sns.histplot(data_filtered, bins=30, kde=True, ax=ax,
                     color=sns.color_palette(PALETTE)[0])

        ax.axvline(data.median(), color="red", linestyle="--",
                   linewidth=1.5, label=f"Median = {data.median():.1f}")
        ax.axvline(data.mean(), color="orange", linestyle="--",
                   linewidth=1.5, label=f"Mean = {data.mean():.1f}")

        ax.set_xlabel("Number of Review Comments")
        ax.set_ylabel("Frequency")
        ax.set_title("Distribution of Review Comment Counts")
        ax.legend()

        plt.tight_layout()
        save_figure(fig, "02_comment_distribution_hist.png")
        return fig, ax

    # --------------------------------------------------------
    # 图3：标签分布饼图
    # --------------------------------------------------------
    def plot_label_distribution_pie(self, top_n=10):
        """Top-N 标签分布饼图。"""
        if self.df is None:
            self.load()

        fig, ax = plt.subplots(figsize=(10, 8))

        # 统计标签频次
        label_counter = Counter()
        for labels_str in self.df["label_names"].dropna():
            for label in labels_str.split(","):
                label = label.strip()
                if label:
                    label_counter[label] += 1

        top_labels = label_counter.most_common(top_n)
        other_count = sum(
            v for k, v in label_counter.items()
            if k not in dict(top_labels)
        )

        labels = [l for l, _ in top_labels]
        sizes = [c for _, c in top_labels]
        if other_count > 0:
            labels.append("Other")
            sizes.append(other_count)

        colors = sns.color_palette(PALETTE, n_colors=len(labels))
        wedges, texts, autotexts = ax.pie(
            sizes, labels=labels, autopct="%1.1f%%",
            colors=colors, startangle=140,
            pctdistance=0.85,
        )

        # 调整文字大小
        for t in autotexts:
            t.set_fontsize(8)
        for t in texts:
            t.set_fontsize(9)

        ax.set_title(
            f"Top {top_n} PR Labels Distribution\n"
            f"(Total unique labels: {len(label_counter)})"
        )

        plt.tight_layout()
        save_figure(fig, "03_label_distribution_pie.png")
        return fig, ax

    # --------------------------------------------------------
    # 图4：Reviewer 数量分布
    # --------------------------------------------------------
    def plot_reviewer_count_distribution(self):
        """每 PR 的 Reviewer 数量分布。"""
        if self.df is None:
            self.load()

        fig, ax = plt.subplots(figsize=FIG_SIZE)

        data = self.df["num_reviewers"].dropna()
        max_val = int(data.max())

        sns.histplot(data, bins=range(0, min(max_val + 2, 16)),
                     discrete=True, ax=ax,
                     color=sns.color_palette(PALETTE)[3])

        ax.axvline(data.mean(), color="red", linestyle="--",
                   linewidth=2, label=f"Mean = {data.mean():.2f}")

        ax.set_xlabel("Number of Reviewers")
        ax.set_ylabel("PR Count")
        ax.set_title("Distribution of Reviewer Count per PR")
        ax.legend()

        plt.tight_layout()
        save_figure(fig, "04_reviewer_count_distribution.png")
        return fig, ax

    # --------------------------------------------------------
    # 图5：PR 长度分布
    # --------------------------------------------------------
    def plot_pr_length_distribution(self):
        """PR 长度（标题+正文字符数）分布。"""
        if self.df is None:
            self.load()

        fig, ax = plt.subplots(figsize=FIG_SIZE)

        data = self.df["pr_length"].dropna()
        # 过滤 99 分位数以避免极端值压缩图像
        q99 = data.quantile(0.99)
        data_filtered = data[data <= q99]

        sns.histplot(data_filtered, bins=40, kde=True, ax=ax,
                     color=sns.color_palette(PALETTE)[4])

        ax.axvline(data.median(), color="red", linestyle="--",
                   linewidth=1.5, label=f"Median = {data.median():.0f}")
        ax.axvline(data.mean(), color="orange", linestyle="--",
                   linewidth=1.5, label=f"Mean = {data.mean():.0f}")

        ax.set_xlabel("PR Length (title + body, characters)")
        ax.set_ylabel("Frequency")
        ax.set_title("Distribution of PR Length")
        ax.legend()

        plt.tight_layout()
        save_figure(fig, "05_pr_length_distribution.png")
        return fig, ax

    # --------------------------------------------------------
    # 图6：AI 相关 PR vs 人类 PR 对比
    # --------------------------------------------------------
    def plot_ai_vs_human_comparison(self):
        """AI 相关 PR 与纯人类 PR 的数量对比。"""
        if self.df is None:
            self.load()

        fig, ax = plt.subplots(figsize=FIG_SIZE)

        # 四种分类
        ai_reviewer = self.df["has_ai_reviewer"]
        ai_code = self.df["has_ai_generated_code"]

        human_only = (~ai_reviewer & ~ai_code).sum()
        ai_review_only = (ai_reviewer & ~ai_code).sum()
        ai_code_only = (~ai_reviewer & ai_code).sum()
        both_ai = (ai_reviewer & ai_code).sum()

        categories = [
            "Human Only",
            "AI Reviewer Only",
            "AI Code Only",
            "Both AI",
        ]
        counts = [human_only, ai_review_only, ai_code_only, both_ai]
        colors = sns.color_palette(PALETTE, n_colors=4)

        bars = ax.bar(categories, counts, color=colors)

        # 标注数值和百分比
        total = len(self.df)
        for bar, count in zip(bars, counts):
            h = bar.get_height()
            pct = 100 * count / total if total else 0
            ax.text(bar.get_x() + bar.get_width()/2., h + 2,
                    f"{count}\n({pct:.1f}%)",
                    ha="center", va="bottom", fontsize=10)

        ax.set_ylabel("PR Count")
        ax.set_title(
            "AI-Related PRs vs Human-Only PRs\n"
            f"(Total: {total})"
        )
        ax.set_ylim(0, max(counts) * 1.2)

        plt.tight_layout()
        save_figure(fig, "06_ai_vs_human_comparison.png")
        return fig, ax

    # --------------------------------------------------------
    # 全部生成
    # --------------------------------------------------------
    def generate_all(self):
        """依次生成全部 6 张图表。"""
        log.info("开始生成可视化图表...")

        self.load()
        log.info(f"生成图1: 合并状态柱状图")
        self.plot_merge_status_bar()

        log.info(f"生成图2: 评论数量分布")
        self.plot_comment_distribution_hist()

        log.info(f"生成图3: 标签分布饼图")
        self.plot_label_distribution_pie()

        log.info(f"生成图4: Reviewer 数量分布")
        self.plot_reviewer_count_distribution()

        log.info(f"生成图5: PR 长度分布")
        self.plot_pr_length_distribution()

        log.info(f"生成图6: AI vs 人类对比")
        self.plot_ai_vs_human_comparison()

        log.info("全部图表生成完成！")


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    viz = Visualizer()
    viz.generate_all()
