"""
特征构建模块 — 对齐实验二 features_main.csv 结构

流程:
  1. 从实验一原始数据构建实验二训练集的 unscaled 特征
  2. 拟合 StandardScaler 并保存
  3. 为 AI PR 构建相同特征
  4. 输出 ai_features_main.csv

特征分组（共65列，不含辅助列）:
  A. 代码修改 (10): num_changed_files, total_additions, total_deletions,
     num_commits, code_churn, net_lines, additions_per_file,
     deletions_per_file, commits_per_file, large_pr_flag
  B. 文本 (9): title_len, body_len, commit_msg_len, title_word_count,
     body_word_count, commit_msg_word_count, has_issue_link,
     has_release_note, body_empty_flag
  C. 文件类型 (12): num_code_files, num_doc_files, num_config_files,
     num_test_files, test_file_ratio, code_file_ratio, doc_file_ratio,
     has_py, has_go, has_js, has_ts, has_rs
  D. AST (13): ast_total_nodes ... ast_assignment_count
  E. CFG (10): cfg_total_nodes ... cfg_files_with_cfg
  F. 仓库 (5): repo_facebook/react, repo_huggingface/transformers,
     repo_kubernetes/kubernetes, repo_microsoft/vscode, repo_pandas-dev/pandas
  G. 标记 (2): ast_missing, cfg_missing
  辅助列: pr_id, repo, is_merged, split
"""

import csv
import json
import os
import re
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    EXPERIMENT1_DATASET_CSV,
    EXPERIMENT2_DIR,
    AI_DATASET_CSV,
    AI_PATCH_INDEX,
    RESULTS_PROCESSED_DIR,
    RESULTS_EVALUATION_DIR,
    RANDOM_SEED,
    logger,
)

EXPERIMENT2_SPLITS = os.path.join(EXPERIMENT2_DIR, "results", "processed", "splits.csv")
EXPERIMENT2_FEATURES_MAIN = os.path.join(EXPERIMENT2_DIR, "results", "processed", "features_main.csv")
EXPERIMENT2_AST = os.path.join(EXPERIMENT2_DIR, "results", "processed", "ast_features.csv")
EXPERIMENT2_CFG = os.path.join(EXPERIMENT2_DIR, "results", "processed", "cfg_features.csv")
EXPERIMENT2_HUMAN_ONLY = os.path.join(EXPERIMENT2_DIR, "results", "processed", "human_only_dataset.csv")

SCALER_PATH = os.path.join(RESULTS_PROCESSED_DIR, "..", "models")
AI_FEATURES_CSV = os.path.join(RESULTS_PROCESSED_DIR, "ai_features_main.csv")
FEATURE_STATS_JSON = os.path.join(RESULTS_EVALUATION_DIR, "ai_feature_stats.json")

os.makedirs(SCALER_PATH, exist_ok=True)
SCALER_FILE = os.path.join(SCALER_PATH, "scaler_main.joblib")

ORIGINAL_5_REPOS = [
    "facebook/react", "huggingface/transformers",
    "kubernetes/kubernetes", "microsoft/vscode", "pandas-dev/pandas",
]
WINSORIZE_Q = 0.99

# ============================================================
# 辅助函数
# ============================================================
def _read_csv(filepath: str) -> pd.DataFrame:
    return pd.read_csv(filepath, encoding="utf-8-sig")


def _winsorize(series: pd.Series, q: float = WINSORIZE_Q) -> pd.Series:
    upper = series.quantile(q)
    return series.clip(upper=upper)


def _classify_files(changed_files_str: str):
    """根据文件名字符串分类文件类型"""
    if not changed_files_str or not isinstance(changed_files_str, str):
        return 0, 0, 0, 0
    files = [f.strip() for f in changed_files_str.split(",") if f.strip()]
    code_files = doc_files = config_files = test_files = 0
    doc_exts = {".md", ".rst", ".txt", ".doc", ".pdf"}
    config_exts = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".lock"}
    test_patterns = ["test", "spec", "__test__", "__tests__"]
    code_exts = {".py", ".go", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp",
                 ".h", ".hpp", ".rs", ".rb", ".swift", ".kt", ".scala", ".css",
                 ".scss", ".less", ".html", ".vue", ".svelte", ".sh", ".bash"}
    for fname in files:
        ext = os.path.splitext(fname)[1].lower()
        base = os.path.basename(fname).lower()
        if any(p in base or p in fname.lower() for p in test_patterns):
            test_files += 1
        elif ext in doc_exts:
            doc_files += 1
        elif ext in config_exts:
            config_files += 1
        elif ext in code_exts or ext:
            code_files += 1
    return code_files, doc_files, config_files, test_files


def _has_language(changed_files_str: str, exts: List[str]) -> int:
    if not changed_files_str or not isinstance(changed_files_str, str):
        return 0
    files = [f.strip().lower() for f in changed_files_str.split(",")]
    for fname in files:
        for ext in exts:
            if fname.endswith(ext):
                return 1
    return 0


# ============================================================
# 特征构建
# ============================================================
def build_raw_features(df: pd.DataFrame) -> pd.DataFrame:
    """构建原始特征（未缩放）"""
    df = df.copy()

    # --- A. 代码修改特征 ---
    df["code_churn"] = df["total_additions"] + df["total_deletions"]
    df["net_lines"] = df["total_additions"] - df["total_deletions"]
    safe_files = df["num_changed_files"].clip(lower=1)
    df["additions_per_file"] = df["total_additions"] / safe_files
    df["deletions_per_file"] = df["total_deletions"] / safe_files
    df["commits_per_file"] = df["num_commits"] / safe_files

    # large_pr_flag 基于训练数据分位数（稍后处理，先设0）
    df["large_pr_flag"] = 0

    # --- B. 文本特征 ---
    df["title_len"] = df["title"].fillna("").astype(str).str.len()
    df["body_len"] = df["body"].fillna("").astype(str).str.len()
    df["commit_msg_len"] = df["commit_messages"].fillna("").astype(str).str.len()
    df["title_word_count"] = df["title"].fillna("").astype(str).apply(lambda x: len(x.split()))
    df["body_word_count"] = df["body"].fillna("").astype(str).apply(lambda x: len(x.split()))
    df["commit_msg_word_count"] = df["commit_messages"].fillna("").astype(str).apply(lambda x: len(x.split()))

    issue_pat = re.compile(r'(#\d+|issues?/\d+|pull/\d+|bugs?/\d+)', re.IGNORECASE)
    df["has_issue_link"] = df["body"].fillna("").astype(str).apply(lambda x: int(bool(issue_pat.search(x))))
    release_pat = re.compile(r'release.?note|changelog|breaking.?change', re.IGNORECASE)
    df["has_release_note"] = df["body"].fillna("").astype(str).apply(lambda x: int(bool(release_pat.search(x))))
    df["body_empty_flag"] = df["body"].fillna("").astype(str).apply(lambda x: int(len(x.strip()) == 0))

    # --- C. 文件类型特征 ---
    file_class = df["changed_files_list"].apply(_classify_files)
    df["num_code_files"] = file_class.apply(lambda x: x[0])
    df["num_doc_files"] = file_class.apply(lambda x: x[1])
    df["num_config_files"] = file_class.apply(lambda x: x[2])
    df["num_test_files"] = file_class.apply(lambda x: x[3])
    total_files = df["num_changed_files"].clip(lower=1)
    df["test_file_ratio"] = df["num_test_files"] / total_files
    df["code_file_ratio"] = df["num_code_files"] / total_files
    df["doc_file_ratio"] = df["num_doc_files"] / total_files
    df["has_py"] = df["changed_files_list"].apply(lambda x: _has_language(x, [".py"]))
    df["has_go"] = df["changed_files_list"].apply(lambda x: _has_language(x, [".go"]))
    df["has_js"] = df["changed_files_list"].apply(lambda x: _has_language(x, [".js", ".jsx"]))
    df["has_ts"] = df["changed_files_list"].apply(lambda x: _has_language(x, [".ts", ".tsx"]))
    df["has_rs"] = df["changed_files_list"].apply(lambda x: _has_language(x, [".rs"]))

    # --- D. AST 特征 (默认0，标记为缺失) ---
    ast_cols = [
        "ast_total_nodes", "ast_max_depth", "ast_files_parsed", "ast_files_attempted",
        "ast_parse_success_rate", "ast_error_node_count",
        "ast_func_def_count", "ast_class_def_count",
        "ast_if_count", "ast_loop_count", "ast_try_count",
        "ast_return_count", "ast_assignment_count",
    ]
    for c in ast_cols:
        if c not in df.columns:
            df[c] = 0.0

    # --- E. CFG 特征 (默认0，标记为缺失) ---
    cfg_cols = [
        "cfg_total_nodes", "cfg_total_edges",
        "cfg_branch_nodes", "cfg_loop_nodes", "cfg_exit_nodes",
        "cfg_cyclomatic_complexity", "cfg_max_branch_depth", "cfg_avg_out_degree",
        "cfg_files_processed", "cfg_files_with_cfg",
    ]
    for c in cfg_cols:
        if c not in df.columns:
            df[c] = 0.0

    # --- F. 仓库 one-hot ---
    for repo in ORIGINAL_5_REPOS:
        col_name = f"repo_{repo.replace('/', '_').replace('-', '_')}"
        df[col_name] = (df["repo"] == repo).astype(int)

    return df


def _load_exp2_training_data() -> pd.DataFrame:
    """加载实验二训练集原始数据"""
    # 加载实验一原始数据
    exp1_df = _read_csv(EXPERIMENT1_DATASET_CSV)
    # 加载实验二 split 分配
    splits_df = _read_csv(EXPERIMENT2_SPLITS)
    # 合并
    df = exp1_df.merge(splits_df[["pr_id", "split"]], on="pr_id", how="inner")
    logger.info(f"实验二数据: {len(df)} 行 (split: {df['split'].value_counts().to_dict()})")

    # 尝试加载 AST/CFG 特征
    if os.path.exists(EXPERIMENT2_AST):
        ast_df = _read_csv(EXPERIMENT2_AST)
        ast_cols_merge = ["pr_id"] + [c for c in ast_df.columns if c.startswith("ast_") and c in [
            "ast_total_nodes", "ast_max_depth", "ast_files_parsed", "ast_files_attempted",
            "ast_parse_success_rate", "ast_error_node_count",
            "ast_func_def_count", "ast_class_def_count",
            "ast_if_count", "ast_loop_count", "ast_try_count",
            "ast_return_count", "ast_assignment_count",
        ]]
        if len(ast_cols_merge) > 1:
            df = df.merge(ast_df[ast_cols_merge], on="pr_id", how="left")

    if os.path.exists(EXPERIMENT2_CFG):
        cfg_df = _read_csv(EXPERIMENT2_CFG)
        cfg_cols_merge = ["pr_id"] + [c for c in cfg_df.columns if c.startswith("cfg_") and c in [
            "cfg_total_nodes", "cfg_total_edges",
            "cfg_branch_nodes", "cfg_loop_nodes", "cfg_exit_nodes",
            "cfg_cyclomatic_complexity", "cfg_max_branch_depth", "cfg_avg_out_degree",
            "cfg_files_processed", "cfg_files_with_cfg",
        ]]
        if len(cfg_cols_merge) > 1:
            df = df.merge(cfg_df[cfg_cols_merge], on="pr_id", how="left")

    return df


def fit_scaler(df: pd.DataFrame, train_mask) -> StandardScaler:
    """在训练数据上拟合 StandardScaler (排除 ID/元数据/one-hot)"""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    exclude = [c for c in numeric_cols if c.startswith("repo_") or c in (
        "is_merged", "split", "has_ai_generated_code", "has_ai_reviewer",
        "pr_id", "pr_number",
    )]
    numeric_for_scale = [c for c in numeric_cols if c not in exclude]

    train_df = df[train_mask].copy()
    scaler = StandardScaler()
    scaler.fit(train_df[numeric_for_scale].fillna(0))
    logger.info(f"Scaler fit on {len(train_df)} rows, {len(numeric_for_scale)} features")
    return scaler


def build_ai_features() -> bool:
    """主函数：构建 AI PR 特征"""
    logger.info("=" * 60)
    logger.info("阶段: 特征构建")
    logger.info("=" * 60)

    # 1. 加载实验二训练数据并拟合 scaler
    logger.info("1. 拟合 StandardScaler (from 实验二训练数据)...")
    exp2_df = _load_exp2_training_data()
    train_mask = exp2_df["split"] == "train"

    # 处理数值列类型
    for col in exp2_df.columns:
        if col.startswith("ast_") or col.startswith("cfg_"):
            exp2_df[col] = pd.to_numeric(exp2_df[col], errors="coerce").fillna(0)

    exp2_raw = build_raw_features(exp2_df)
    exp2_raw["ast_missing"] = exp2_raw["ast_total_nodes"].apply(lambda x: 1 if x == 0 else 0)
    exp2_raw["cfg_missing"] = exp2_raw["cfg_total_nodes"].apply(lambda x: 1 if x == 0 else 0)

    # 保存 scaler 拟合时使用的特征列顺序 (排除 ID 和元数据列)
    exp2_numeric_cols = exp2_raw.select_dtypes(include=[np.number]).columns.tolist()
    exp2_exclude = [c for c in exp2_numeric_cols if c.startswith("repo_") or c in (
        "is_merged", "has_ai_generated_code", "has_ai_reviewer",
        "pr_id", "pr_number", "split",
    )]
    scaler_feature_order = [c for c in exp2_numeric_cols if c not in exp2_exclude]

    scaler = fit_scaler(exp2_raw, train_mask)
    scaler_data = {"scaler": scaler, "feature_order": scaler_feature_order}
    joblib.dump(scaler_data, SCALER_FILE)
    logger.info(f"Scaler saved: {SCALER_FILE} ({len(scaler_feature_order)} features)")

    # 2. 加载 AI PR 数据
    logger.info("2. 加载 AI PR 数据...")
    if not os.path.exists(AI_DATASET_CSV):
        logger.error(f"AI 数据集未找到: {AI_DATASET_CSV}")
        return False
    ai_df = _read_csv(AI_DATASET_CSV)
    logger.info(f"  AI PRs: {len(ai_df)}")

    # 3. 构建原始特征
    logger.info("3. 构建特征...")
    for col in ai_df.columns:
        if col.startswith("ast_") or col.startswith("cfg_"):
            ai_df[col] = pd.to_numeric(ai_df[col], errors="coerce").fillna(0)

    ai_raw = build_raw_features(ai_df)
    ai_raw["ast_missing"] = ai_raw["ast_total_nodes"].apply(lambda x: 1 if pd.isna(x) or x == 0 else 0)
    ai_raw["cfg_missing"] = ai_raw["cfg_total_nodes"].apply(lambda x: 1 if pd.isna(x) or x == 0 else 0)

    # 4. Winsorize + StandardScaler
    logger.info("4. 标准化...")
    for col in scaler_feature_order:
        if col in ai_raw.columns:
            ai_raw[col] = _winsorize(ai_raw[col], WINSORIZE_Q)

    # 应用 scaler — 使用拟合时的列顺序
    ai_scaled = ai_raw.copy()
    valid_num = [c for c in scaler_feature_order if c in ai_scaled.columns]
    ai_scaled[valid_num] = scaler.transform(ai_scaled[valid_num].fillna(0))

    # 保留元数据列原始值（不被 scaler 污染）
    for col in ["pr_id", "pr_number", "repo"]:
        if col in ai_raw.columns:
            ai_scaled[col] = ai_raw[col]
    # 确保 pr_id 为整数字符串
    if "pr_id" in ai_scaled.columns:
        ai_scaled["pr_id"] = ai_scaled["pr_id"].apply(
            lambda x: str(int(float(x))) if pd.notna(x) else ""
        )

    # 5. 确定输出列（与实验二 features_main.csv 一致）
    logger.info("5. 对齐列结构...")
    output_cols = [
        "pr_id", "repo", "is_merged", "split",
        "num_changed_files", "total_additions", "total_deletions", "num_commits",
        "code_churn", "net_lines", "additions_per_file", "deletions_per_file",
        "commits_per_file", "large_pr_flag",
        "title_len", "body_len", "commit_msg_len",
        "title_word_count", "body_word_count", "commit_msg_word_count",
        "has_issue_link", "has_release_note", "body_empty_flag",
        "num_code_files", "num_doc_files", "num_config_files", "num_test_files",
        "test_file_ratio", "code_file_ratio", "doc_file_ratio",
        "has_py", "has_go", "has_js", "has_ts", "has_rs",
        "ast_total_nodes", "ast_max_depth", "ast_files_parsed", "ast_files_attempted",
        "ast_parse_success_rate", "ast_error_node_count",
        "ast_func_def_count", "ast_class_def_count",
        "ast_if_count", "ast_loop_count", "ast_try_count",
        "ast_return_count", "ast_assignment_count",
        "cfg_total_nodes", "cfg_total_edges",
        "cfg_branch_nodes", "cfg_loop_nodes", "cfg_exit_nodes",
        "cfg_cyclomatic_complexity", "cfg_max_branch_depth", "cfg_avg_out_degree",
        "cfg_files_processed", "cfg_files_with_cfg",
        "repo_facebook_react", "repo_huggingface_transformers",
        "repo_kubernetes_kubernetes", "repo_microsoft_vscode", "repo_pandas_dev_pandas",
        "ast_missing", "cfg_missing",
    ]

    # 检查缺失列并补充
    for col in output_cols:
        if col not in ai_scaled.columns:
            ai_scaled[col] = 0.0 if col not in ("pr_id", "repo", "split") else ""

    # 确保 is_merged 是数值 (用于模型评估)
    ai_scaled["is_merged"] = ai_scaled["is_merged"].apply(
        lambda x: 1 if str(x).lower() in ("true", "1", "yes") else 0
    )
    ai_scaled["split"] = "ai_test"

    # 选择输出列
    ai_out = ai_scaled[output_cols]

    # 6. 保存
    ai_out.to_csv(AI_FEATURES_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"AI 特征已保存: {AI_FEATURES_CSV}")
    logger.info(f"  {len(ai_out)} 行 × {len(output_cols)} 列")

    # 7. 统计
    merged_count = ai_out["is_merged"].sum()
    stats = {
        "total_prs": len(ai_out),
        "merged_count": int(merged_count),
        "unmerged_count": len(ai_out) - int(merged_count),
        "merge_rate": float(merged_count / len(ai_out)),
        "feature_columns": len(output_cols),
        "ast_missing_rate": float(ai_out["ast_missing"].mean()),
        "cfg_missing_rate": float(ai_out["cfg_missing"].mean()),
    }
    with open(FEATURE_STATS_JSON, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    logger.info(f"特征统计: {FEATURE_STATS_JSON}")
    logger.info(f"  AST缺失率: {stats['ast_missing_rate']:.2%}")
    logger.info(f"  CFG缺失率: {stats['cfg_missing_rate']:.2%}")
    logger.info("=" * 60)

    return True


if __name__ == "__main__":
    build_ai_features()
