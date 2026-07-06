"""
实验二 步骤六：特征工程
合并所有数据源，构建 features_main.csv 和 features_upper_bound.csv。
"""
import re
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.preprocessing import StandardScaler

from config import PROCESSED_DIR, RANDOM_SEED, WINSORIZE_Q
from utils import log, write_json


# ============================================================
# 派生特征构建
# ============================================================
def _build_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """从基础字段构建派生特征。"""
    df = df.copy()

    # --- 代码修改派生特征 ---
    df["code_churn"] = df["total_additions"] + df["total_deletions"]
    df["net_lines"] = df["total_additions"] - df["total_deletions"]

    # 每文件指标（避免除以零）
    safe_files = df["num_changed_files"].clip(lower=1)
    df["additions_per_file"] = df["total_additions"] / safe_files
    df["deletions_per_file"] = df["total_deletions"] / safe_files
    df["commits_per_file"] = df["num_commits"] / safe_files

    # --- 文本特征 ---
    df["title_len"] = df["title"].fillna("").astype(str).str.len()
    df["body_len"] = df["body"].fillna("").astype(str).str.len()
    df["commit_msg_len"] = df["commit_messages"].fillna("").astype(str).str.len()

    df["title_word_count"] = df["title"].fillna("").astype(str).apply(
        lambda x: len(x.split()))
    df["body_word_count"] = df["body"].fillna("").astype(str).apply(
        lambda x: len(x.split()))
    df["commit_msg_word_count"] = df["commit_messages"].fillna("").astype(str).apply(
        lambda x: len(x.split()))

    # 是否包含 issue/workitem 链接
    issue_pattern = re.compile(r'(#\d+|issues?/\d+|pull/\d+|bugs?/\d+)', re.IGNORECASE)
    df["has_issue_link"] = df["body"].fillna("").astype(str).apply(
        lambda x: int(bool(issue_pattern.search(x))))

    # 是否包含 release note
    release_pattern = re.compile(r'release.?note|changelog|breaking.?change',
                                 re.IGNORECASE)
    df["has_release_note"] = df["body"].fillna("").astype(str).apply(
        lambda x: int(bool(release_pattern.search(x))))

    # body 是否为空
    df["body_empty_flag"] = (df["body"].fillna("").astype(str).str.strip() == "").astype(int)

    return df


def _build_file_type_features(df: pd.DataFrame) -> pd.DataFrame:
    """从 changed_files_list 构建文件类型特征。"""
    df = df.copy()
    from config import CODE_EXTENSIONS, CONFIG_EXTENSIONS, DOC_EXTENSIONS

    def classify_files(changed_files_str):
        if not changed_files_str or not isinstance(changed_files_str, str):
            return {"num_code_files": 0, "num_doc_files": 0,
                    "num_config_files": 0, "num_test_files": 0,
                    "num_other_files": 0, "has_py": 0, "has_go": 0,
                    "has_js": 0, "has_ts": 0, "has_rs": 0}

        files = [f.strip() for f in changed_files_str.split(",") if f.strip()]
        counts = {"num_code_files": 0, "num_doc_files": 0,
                  "num_config_files": 0, "num_test_files": 0,
                  "num_other_files": 0}
        lang_flags = {"has_py": 0, "has_go": 0, "has_js": 0, "has_ts": 0, "has_rs": 0}

        for f in files:
            ext = Path(f).suffix.lower()
            fname = Path(f).name.lower()

            if ext in CODE_EXTENSIONS:
                counts["num_code_files"] += 1
            elif ext in CONFIG_EXTENSIONS:
                counts["num_config_files"] += 1
            elif ext in DOC_EXTENSIONS:
                counts["num_doc_files"] += 1
            else:
                counts["num_other_files"] += 1

            # 测试文件检测
            test_markers = ["test_", "_test", "test.", "spec.", ".spec."]
            if any(m in fname for m in test_markers) or \
               any(p.lower() in ("test", "tests", "spec", "__tests__", "testing")
                   for p in Path(f).parts):
                counts["num_test_files"] += 1

            # 主要语言标记
            if ext == ".py":
                lang_flags["has_py"] = 1
            elif ext == ".go":
                lang_flags["has_go"] = 1
            elif ext in (".js", ".jsx"):
                lang_flags["has_js"] = 1
            elif ext in (".ts", ".tsx"):
                lang_flags["has_ts"] = 1
            elif ext == ".rs":
                lang_flags["has_rs"] = 1

        return {**counts, **lang_flags}

    file_features = df["changed_files_list"].apply(classify_files).apply(pd.Series)
    df = pd.concat([df, file_features], axis=1)

    # 比例特征
    total_files = df["num_changed_files"].clip(lower=1)
    df["test_file_ratio"] = df["num_test_files"] / total_files
    df["code_file_ratio"] = df["num_code_files"] / total_files
    df["doc_file_ratio"] = df["num_doc_files"] / total_files

    return df


def _build_review_features(df: pd.DataFrame) -> pd.DataFrame:
    """构建审查相关特征（仅用于 upper_bound）。"""
    df = df.copy()

    # review_decision One-Hot
    rd_dummies = pd.get_dummies(df["review_decision"].fillna("NONE"),
                                 prefix="review_decision")
    df = pd.concat([df, rd_dummies], axis=1)

    # 审查强度
    safe_files = df["num_changed_files"].clip(lower=1)
    df["review_intensity"] = (df["num_review_comments"].fillna(0) +
                              df["num_inline_comments"].fillna(0)) / safe_files

    return df


def _winsorize(series: pd.Series, q: float = WINSORIZE_Q) -> pd.Series:
    """极端值截断：用分位数截断。"""
    upper = series.quantile(q)
    return series.clip(upper=upper)


# ============================================================
# 特征矩阵构建
# ============================================================
def build_features(human_path: Path = None, splits_path: Path = None,
                   ast_path: Path = None, cfg_path: Path = None,
                   output_dir: Path = None):
    """构建主实验和上界实验特征矩阵。"""
    if human_path is None:
        human_path = PROCESSED_DIR / "human_only_dataset.csv"
    if splits_path is None:
        splits_path = PROCESSED_DIR / "splits.csv"
    if ast_path is None:
        ast_path = PROCESSED_DIR / "ast_features.csv"
    if cfg_path is None:
        cfg_path = PROCESSED_DIR / "cfg_features.csv"
    if output_dir is None:
        output_dir = PROCESSED_DIR

    # 1. 加载所有数据源
    log.info("加载数据源...")
    human = pd.read_csv(human_path)
    splits = pd.read_csv(splits_path)[["pr_id", "split"]]
    ast = pd.read_csv(ast_path)
    cfg = pd.read_csv(cfg_path)

    log.info(f"human={len(human)}, splits={len(splits)}, "
             f"ast={len(ast)}, cfg={len(cfg)}")

    # 2. 合并
    df = human.merge(splits, on="pr_id", how="inner")
    df = df.merge(ast, on="pr_id", how="left", suffixes=("", "_ast"))
    df = df.merge(cfg, on="pr_id", how="left", suffixes=("", "_cfg"))

    # 填充 AST/CFG 缺失值
    ast_cols = [c for c in ast.columns if c not in ("pr_id", "repo")]
    cfg_cols = [c for c in cfg.columns if c not in ("pr_id", "repo")]
    for col in ast_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    for col in cfg_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    log.info(f"合并后数据集: {len(df)} 行")

    # 3. 构建派生特征
    df = _build_derived_features(df)
    df = _build_file_type_features(df)

    # 4. large_pr_flag（基于训练集分位数，防止泄漏）
    train_mask = df["split"] == "train"
    churn_75 = df.loc[train_mask, "code_churn"].quantile(0.75)
    df["large_pr_flag"] = (df["code_churn"] > churn_75).astype(int)
    log.info(f"large_pr_flag 阈值 (code_churn Q75): {churn_75:.1f}")

    # 5. Repo One-Hot
    repo_dummies = pd.get_dummies(df["repo"], prefix="repo")
    df = pd.concat([df, repo_dummies], axis=1)

    # 6. 定义特征集
    # A. 代码修改特征
    code_change_features = [
        "num_changed_files", "total_additions", "total_deletions",
        "num_commits", "code_churn", "net_lines",
        "additions_per_file", "deletions_per_file", "commits_per_file",
        "large_pr_flag",
    ]

    # B. 文本特征
    text_features = [
        "title_len", "body_len", "commit_msg_len",
        "title_word_count", "body_word_count", "commit_msg_word_count",
        "has_issue_link", "has_release_note", "body_empty_flag",
    ]

    # C. 文件类型特征
    file_type_features = [
        "num_code_files", "num_doc_files", "num_config_files",
        "num_test_files", "test_file_ratio", "code_file_ratio",
        "doc_file_ratio",
        "has_py", "has_go", "has_js", "has_ts", "has_rs",
    ]

    # D. AST 特征
    ast_feature_cols = [
        "ast_total_nodes", "ast_max_depth",
        "ast_files_parsed", "ast_files_attempted",
        "ast_parse_success_rate", "ast_error_node_count",
        "ast_func_def_count", "ast_class_def_count",
        "ast_if_count", "ast_loop_count", "ast_try_count",
        "ast_return_count", "ast_assignment_count",
    ]

    # E. CFG 特征
    cfg_feature_cols = [
        "cfg_total_nodes", "cfg_total_edges",
        "cfg_branch_nodes", "cfg_loop_nodes", "cfg_exit_nodes",
        "cfg_cyclomatic_complexity", "cfg_max_branch_depth",
        "cfg_avg_out_degree",
        "cfg_files_processed", "cfg_files_with_cfg",
    ]

    # F. Repo one-hot 列
    repo_cols = [c for c in repo_dummies.columns]

    # 主实验特征（无审查信息）
    main_feature_cols = (
        code_change_features + text_features + file_type_features +
        ast_feature_cols + cfg_feature_cols + repo_cols
    )

    # 7. 审查过程特征（仅 upper_bound）
    df = _build_review_features(df)
    review_feature_cols = [
        "num_reviewers", "num_review_comments", "num_inline_comments",
        "num_labels", "review_intensity", "has_ai_reviewer",
    ]
    review_decision_cols = [c for c in df.columns
                            if c.startswith("review_decision_")]

    upper_bound_feature_cols = main_feature_cols + review_feature_cols + \
                               review_decision_cols

    # 8. 确保所有特征列存在
    for feat_list, name in [(main_feature_cols, "main"),
                              (upper_bound_feature_cols, "upper_bound")]:
        missing = [c for c in feat_list if c not in df.columns]
        if missing:
            log.warning(f"{name} 缺失列 ({len(missing)}): {missing[:10]}...")
            for c in missing:
                df[c] = 0

    # 只保留存在的列
    main_feature_cols = [c for c in main_feature_cols if c in df.columns]
    upper_bound_feature_cols = [c for c in upper_bound_feature_cols
                                 if c in df.columns]

    log.info(f"主实验特征: {len(main_feature_cols)} 个")
    log.info(f"上界实验特征: {len(upper_bound_feature_cols)} 个")

    # 9. 数值特征预处理：winsorize + StandardScaler（仅在 train 上 fit）
    numeric_main = [c for c in main_feature_cols
                    if c not in repo_cols and df[c].dtype in ('float64', 'int64', 'int32', 'float32')]

    # Winsorize
    for col in numeric_main:
        if col in df.columns:
            df[col] = _winsorize(df[col], WINSORIZE_Q)

    # StandardScaler (fit on train only)
    scaler = StandardScaler()
    train_idx = df["split"] == "train"
    df_scaled = df.copy()

    # 只对数值特征做标准化（不包括 one-hot 列）
    numeric_for_scale = [c for c in numeric_main if c in df.columns]
    df_scaled.loc[train_idx, numeric_for_scale] = \
        scaler.fit_transform(df.loc[train_idx, numeric_for_scale])
    val_idx = df["split"] == "val"
    test_idx = df["split"] == "test"
    df_scaled.loc[val_idx, numeric_for_scale] = \
        scaler.transform(df.loc[val_idx, numeric_for_scale])
    df_scaled.loc[test_idx, numeric_for_scale] = \
        scaler.transform(df.loc[test_idx, numeric_for_scale])

    # 10. 构建输出
    # 辅助列
    aux_cols = ["pr_id", "repo", "is_merged", "split"]

    # 缺失标记（AST/CFG 是否可用）
    df_scaled["ast_missing"] = (df_scaled["ast_files_parsed"] == 0).astype(int)
    df_scaled["cfg_missing"] = (~df_scaled.get("cfg_available", True)).astype(int)

    main_feature_cols_with_flag = main_feature_cols + ["ast_missing", "cfg_missing"]
    upper_bound_feature_cols_with_flag = upper_bound_feature_cols + \
                                          ["ast_missing", "cfg_missing"]

    # 构建 DataFrame
    features_main = df_scaled[aux_cols + main_feature_cols_with_flag].copy()
    features_upper = df_scaled[aux_cols + upper_bound_feature_cols_with_flag].copy()

    # 确认没有 NaN
    for name, fdf in [("main", features_main), ("upper_bound", features_upper)]:
        nan_count = fdf.isnull().sum().sum()
        if nan_count > 0:
            log.warning(f"{name} 含 {nan_count} 个 NaN，填充为 0")
            fdf.fillna(0, inplace=True)

    # 11. 保存
    main_path = output_dir / "features_main.csv"
    features_main.to_csv(main_path, index=False, encoding="utf-8-sig")
    log.info(f"主实验特征已保存: {main_path} ({len(features_main)} 行 × {len(features_main.columns)} 列)")

    upper_path = output_dir / "features_upper_bound.csv"
    features_upper.to_csv(upper_path, index=False, encoding="utf-8-sig")
    log.info(f"上界实验特征已保存: {upper_path} ({len(features_upper)} 行 × {len(features_upper.columns)} 列)")

    # 特征统计
    feature_stats = {
        "total_samples": len(df),
        "train_samples": int((df["split"] == "train").sum()),
        "val_samples": int((df["split"] == "val").sum()),
        "test_samples": int((df["split"] == "test").sum()),
        "main_feature_count": len(main_feature_cols_with_flag),
        "upper_bound_feature_count": len(upper_bound_feature_cols_with_flag),
        "feature_groups": {
            "code_change": len(code_change_features),
            "text": len(text_features),
            "file_type": len(file_type_features),
            "ast": len(ast_feature_cols),
            "cfg": len(cfg_feature_cols),
            "repo_onehot": len(repo_cols),
            "review": len(review_feature_cols) + len(review_decision_cols),
        },
        "main_feature_names": main_feature_cols_with_flag,
    }
    stats_path = output_dir / "feature_stats.json"
    write_json(feature_stats, stats_path)

    return features_main, features_upper


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    build_features()
