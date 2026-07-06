"""
实验一：构建数据集 — 统计分析
从 CSV 加载数据集，计算描述性统计，输出文本和 JSON 格式的统计报告。
"""

import json

import pandas as pd

import config
from utils import log


# ============================================================
# 统计分析器
# ============================================================
class Analyzer:
    """数据集统计分析器。"""

    FEATURE_COLS = [
        "pr_length", "num_changed_files", "num_reviewers",
        "num_review_comments", "num_labels",
    ]

    def __init__(self, csv_path=None):
        self.csv_path = csv_path or (
            config.PROCESSED_DATA_DIR / "dataset.csv"
        )
        self.df = None

    def load(self):
        """加载 CSV 数据集。"""
        log.info(f"加载数据集: {self.csv_path}")
        self.df = pd.read_csv(self.csv_path)
        log.info(f"加载完成: {len(self.df)} 行 × {len(self.df.columns)} 列")

        # 数据类型修正
        self.df["is_merged"] = self.df["is_merged"].astype(bool)
        self.df["has_ai_reviewer"] = self.df["has_ai_reviewer"].astype(bool)
        self.df["has_ai_generated_code"] = (
            self.df["has_ai_generated_code"].astype(bool)
        )
        return self.df

    # --------------------------------------------------------
    # 总体统计
    # --------------------------------------------------------
    def overall_stats(self):
        """计算总体统计指标。"""
        total = len(self.df)
        merged = self.df["is_merged"].sum()
        unmerged = total - merged
        ai_reviewer = self.df["has_ai_reviewer"].sum()
        ai_code = self.df["has_ai_generated_code"].sum()

        stats = {
            "total_prs": total,
            "merged_count": int(merged),
            "merged_pct": round(100 * merged / total, 2) if total else 0,
            "unmerged_count": int(unmerged),
            "unmerged_pct": round(100 * unmerged / total, 2) if total else 0,
            "ai_reviewer_count": int(ai_reviewer),
            "ai_reviewer_pct": round(100 * ai_reviewer / total, 2) if total else 0,
            "ai_generated_code_count": int(ai_code),
            "ai_generated_code_pct": round(100 * ai_code / total, 2) if total else 0,
        }
        return stats

    # --------------------------------------------------------
    # 数值特征分布
    # --------------------------------------------------------
    def feature_distributions(self):
        """计算数值特征的描述性统计。"""
        dist = {}
        for col in self.FEATURE_COLS:
            if col in self.df.columns:
                series = self.df[col].dropna()
                dist[col] = {
                    "mean": round(series.mean(), 2),
                    "median": round(series.median(), 2),
                    "std": round(series.std(), 2),
                    "min": int(series.min()),
                    "max": int(series.max()),
                    "q25": round(series.quantile(0.25), 2),
                    "q75": round(series.quantile(0.75), 2),
                }
        return dist

    # --------------------------------------------------------
    # 按仓库分组
    # --------------------------------------------------------
    def per_repo_stats(self):
        """按仓库分组的统计指标。"""
        if "repo" not in self.df.columns:
            return []

        records = []
        for repo_name, group in self.df.groupby("repo"):
            total = len(group)
            merged = group["is_merged"].sum()
            records.append({
                "repo": repo_name,
                "prs": total,
                "merged": int(merged),
                "merge_rate": round(100 * merged / total, 1) if total else 0,
                "avg_comments": round(group["num_review_comments"].mean(), 2),
                "avg_reviewers": round(group["num_reviewers"].mean(), 2),
                "avg_length": round(group["pr_length"].mean(), 1),
                "avg_changed_files": round(group["num_changed_files"].mean(), 2),
                "ai_reviewer_count": int(group["has_ai_reviewer"].sum()),
                "ai_code_count": int(group["has_ai_generated_code"].sum()),
            })
        return records

    # --------------------------------------------------------
    # 合并 vs 未合并对比
    # --------------------------------------------------------
    def merge_comparison(self):
        """对比合并与未合并 PR 在各特征上的差异。"""
        comp = {}
        for col in self.FEATURE_COLS:
            if col in self.df.columns:
                merged_mean = self.df[self.df["is_merged"]][col].mean()
                unmerged_mean = self.df[~self.df["is_merged"]][col].mean()
                comp[col] = {
                    "merged_mean": round(merged_mean, 2),
                    "unmerged_mean": round(unmerged_mean, 2),
                }
        return comp

    # --------------------------------------------------------
    # 标签统计
    # --------------------------------------------------------
    def label_stats(self, top_n=15):
        """统计标签频次（Top-N）。"""
        label_counts = {}
        for labels_str in self.df["label_names"].dropna():
            for label in labels_str.split(","):
                label = label.strip()
                if label:
                    label_counts[label] = label_counts.get(label, 0) + 1

        sorted_labels = sorted(
            label_counts.items(), key=lambda x: x[1], reverse=True
        )
        return sorted_labels[:top_n]

    # --------------------------------------------------------
    # 生成报告
    # --------------------------------------------------------
    def generate_report(self):
        """生成完整的统计报告。"""
        if self.df is None:
            self.load()

        log.info("计算统计指标...")

        overall = self.overall_stats()
        distributions = self.feature_distributions()
        per_repo = self.per_repo_stats()
        comparison = self.merge_comparison()
        top_labels = self.label_stats()

        report = {
            "title": "实验一：数据集统计报告",
            "generated_at": pd.Timestamp.now().isoformat(),
            "overall": overall,
            "feature_distributions": distributions,
            "per_repo": per_repo,
            "merge_comparison": comparison,
            "top_labels": [
                {"label": l, "count": c} for l, c in top_labels
            ],
        }

        # 保存 JSON
        json_path = config.PROCESSED_DATA_DIR / "dataset_stats.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log.info(f"统计 JSON 已保存至 {json_path}")

        # 保存文本报告
        txt_path = config.PROCESSED_DATA_DIR / "dataset_stats.txt"
        self._write_text_report(report, txt_path)
        log.info(f"统计文本报告已保存至 {txt_path}")

        # 控制台输出
        self._print_summary(report)

        return report

    # --------------------------------------------------------
    # 文本报告
    # --------------------------------------------------------
    def _write_text_report(self, report, path):
        """生成可读的文本统计报告。"""
        lines = []
        lines.append("=" * 60)
        lines.append("数据集统计报告")
        lines.append("=" * 60)
        lines.append(f"生成时间: {report['generated_at']}")
        lines.append("")

        # 总体
        o = report["overall"]
        lines.append("--- 总体统计 ---")
        lines.append(f"总 PR 数:        {o['total_prs']}")
        lines.append(f"已合并:          {o['merged_count']} ({o['merged_pct']}%)")
        lines.append(f"未合并:          {o['unmerged_count']} ({o['unmerged_pct']}%)")
        lines.append(f"含 AI Reviewer:  {o['ai_reviewer_count']} ({o['ai_reviewer_pct']}%)")
        lines.append(f"含 AI 生成代码:  {o['ai_generated_code_count']} ({o['ai_generated_code_pct']}%)")
        lines.append("")

        # 数值特征分布
        lines.append("--- 数值特征分布 ---")
        for col, stats in report["feature_distributions"].items():
            lines.append(f"{col}:")
            lines.append(f"  mean={stats['mean']}, median={stats['median']}, "
                         f"std={stats['std']}, min={stats['min']}, max={stats['max']}")
            lines.append(f"  Q25={stats['q25']}, Q75={stats['q75']}")
        lines.append("")

        # 按仓库
        lines.append("--- 按仓库统计 ---")
        header = f"{'Repo':<25} {'PRs':>5} {'合并率':>8} {'均评论':>8} {'均审阅人':>8} {'均长度':>8}"
        lines.append(header)
        lines.append("-" * len(header))
        for r in report["per_repo"]:
            lines.append(
                f"{r['repo']:<25} {r['prs']:>5} {r['merge_rate']:>7.1f}% "
                f"{r['avg_comments']:>8.2f} {r['avg_reviewers']:>8.2f} "
                f"{r['avg_length']:>8.1f}"
            )
        lines.append("")

        # 合并对比
        lines.append("--- 合并 vs 未合并特征对比 ---")
        for col, v in report["merge_comparison"].items():
            lines.append(f"{col}: merged_mean={v['merged_mean']}, "
                         f"unmerged_mean={v['unmerged_mean']}")
        lines.append("")

        # 标签
        lines.append("--- Top 标签 ---")
        for item in report["top_labels"]:
            lines.append(f"  {item['label']}: {item['count']}")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # --------------------------------------------------------
    # 控制台摘要
    # --------------------------------------------------------
    def _print_summary(self, report):
        """在控制台打印摘要。"""
        o = report["overall"]
        print("\n" + "=" * 50)
        print("  数据集统计摘要")
        print("=" * 50)
        print(f"总 PR 数: {o['total_prs']}")
        print(f"合并率:   {o['merged_pct']}%")
        print(f"AI Reviewer 占比: {o['ai_reviewer_pct']}%")
        print(f"AI 代码占比:     {o['ai_generated_code_pct']}%")
        print("-" * 50)
        print("按仓库合并率:")
        for r in report["per_repo"]:
            print(f"  {r['repo']:<25}: {r['merge_rate']}%")
        print("=" * 50)


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    analyzer = Analyzer()
    analyzer.load()
    analyzer.generate_report()
