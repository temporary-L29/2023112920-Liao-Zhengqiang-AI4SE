"""Feature contract for the Experiment 2 deployable ML variants.

The original Experiment 2 models consume PR-level metadata.  This module
defines the smaller, local-diff-only schema used consistently for retraining
and CLI inference.  It deliberately excludes PR title/body, review process
data, commit count, and repository identity.
"""

from __future__ import annotations

import importlib
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin


DEPLOYABLE_FEATURE_NAMES = [
    "num_changed_files", "total_additions", "total_deletions",
    "code_churn", "net_lines", "additions_per_file", "deletions_per_file",
    "large_pr_flag",
    "num_code_files", "num_doc_files", "num_config_files", "num_test_files",
    "test_file_ratio", "code_file_ratio", "doc_file_ratio",
    "has_py", "has_go", "has_js", "has_ts", "has_rs",
    "ast_total_nodes", "ast_max_depth", "ast_files_parsed",
    "ast_files_attempted", "ast_parse_success_rate", "ast_error_node_count",
    "ast_func_def_count", "ast_class_def_count", "ast_if_count",
    "ast_loop_count", "ast_try_count", "ast_return_count",
    "ast_assignment_count",
    "cfg_total_nodes", "cfg_total_edges", "cfg_branch_nodes",
    "cfg_loop_nodes", "cfg_exit_nodes", "cfg_cyclomatic_complexity",
    "cfg_max_branch_depth", "cfg_avg_out_degree", "cfg_files_processed",
    "cfg_files_with_cfg", "ast_missing", "cfg_missing",
]

CODE_EXTENSIONS = {
    ".py", ".go", ".js", ".jsx", ".ts", ".tsx", ".java", ".c",
    ".cpp", ".h", ".hpp", ".rs",
}
CONFIG_EXTENSIONS = {".json", ".yml", ".yaml", ".toml", ".xml"}
DOC_EXTENSIONS = {".md", ".rst", ".txt"}


class TrainWinsorizer(BaseEstimator, TransformerMixin):
    """Clip each feature at its training-set upper quantile."""

    def __init__(self, quantile: float = 0.99):
        self.quantile = quantile

    def fit(self, X, y=None):
        values = np.asarray(X, dtype=float)
        self.upper_bounds_ = np.quantile(values, self.quantile, axis=0)
        return self

    def transform(self, X):
        values = np.asarray(X, dtype=float)
        return np.minimum(values, self.upper_bounds_)


def build_training_features(
    human: pd.DataFrame,
    ast: pd.DataFrame,
    cfg: pd.DataFrame,
    splits: pd.DataFrame,
) -> Tuple[pd.DataFrame, float]:
    """Build the deployable feature table from Experiment 2 source outputs."""
    df = human.merge(splits[["pr_id", "split"]], on="pr_id", how="inner")
    df = df.merge(ast, on=["pr_id", "repo"], how="left")
    df = df.merge(cfg, on=["pr_id", "repo"], how="left")

    _fill_structural_missing(df)
    _add_change_features(df)
    _add_file_type_features(df)

    train_churn = df.loc[df["split"] == "train", "code_churn"]
    large_churn_threshold = float(train_churn.quantile(0.75))
    df["large_pr_flag"] = (df["code_churn"] > large_churn_threshold).astype(int)
    df["ast_missing"] = (df["ast_files_parsed"] == 0).astype(int)
    df["cfg_missing"] = (~df["cfg_available"].astype(bool)).astype(int)

    return df[["pr_id", "is_merged", "split"] + DEPLOYABLE_FEATURE_NAMES].copy(), large_churn_threshold


def build_features_from_diff(diff_text: str, large_churn_threshold: float) -> np.ndarray:
    """Create one raw deployable feature vector from a unified Git diff."""
    file_changes = _parse_diff_changes(diff_text)
    if not file_changes:
        raise ValueError("No changed files could be parsed from the Git diff")

    paths = list(file_changes)
    additions, deletions = _change_stats(diff_text)
    counts = _file_type_counts(paths)
    changed_files = len(paths)

    pr_record = {
        "pr_id": "local-diff",
        "repo": "local",
        "files": [
            {
                "filename": path,
                "ext": Path(path).suffix.lower(),
                "file_type": "code" if Path(path).suffix.lower() in CODE_EXTENSIONS else "other",
                "has_patch": bool(change["added_lines"]),
                "added_lines": "\n".join(change["added_lines"]),
            }
            for path, change in file_changes.items()
        ],
    }
    ast_features, cfg_features = _extract_structural_features(pr_record)

    raw: Dict[str, float] = {
        "num_changed_files": float(changed_files),
        "total_additions": float(additions),
        "total_deletions": float(deletions),
        "code_churn": float(additions + deletions),
        "net_lines": float(additions - deletions),
        "additions_per_file": additions / max(changed_files, 1),
        "deletions_per_file": deletions / max(changed_files, 1),
        "large_pr_flag": float(additions + deletions > large_churn_threshold),
        **counts,
        **ast_features,
        **cfg_features,
    }
    raw["ast_missing"] = float(raw["ast_files_parsed"] == 0)
    raw["cfg_missing"] = float(not bool(pr_record.get("cfg_available", False)))
    raw["cfg_missing"] = float(raw["cfg_files_with_cfg"] == 0)

    return np.asarray([[raw[name] for name in DEPLOYABLE_FEATURE_NAMES]], dtype=float)


def _fill_structural_missing(df: pd.DataFrame) -> None:
    ast_columns = [name for name in DEPLOYABLE_FEATURE_NAMES if name.startswith("ast_")]
    cfg_columns = [name for name in DEPLOYABLE_FEATURE_NAMES if name.startswith("cfg_")]
    for column in ast_columns + cfg_columns:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    if "cfg_available" not in df:
        df["cfg_available"] = False
    df["cfg_available"] = df["cfg_available"].fillna(False)


def _add_change_features(df: pd.DataFrame) -> None:
    for column in ["num_changed_files", "total_additions", "total_deletions"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["code_churn"] = df["total_additions"] + df["total_deletions"]
    df["net_lines"] = df["total_additions"] - df["total_deletions"]
    files = df["num_changed_files"].clip(lower=1)
    df["additions_per_file"] = df["total_additions"] / files
    df["deletions_per_file"] = df["total_deletions"] / files


def _add_file_type_features(df: pd.DataFrame) -> None:
    feature_rows = df["changed_files_list"].apply(_file_type_counts).apply(pd.Series)
    for column in feature_rows:
        df[column] = feature_rows[column]


def _file_type_counts(paths: Iterable[str] | str) -> Dict[str, float]:
    if isinstance(paths, str):
        paths = [part.strip() for part in paths.split(",") if part.strip()]
    paths = list(paths)
    counts = {
        "num_code_files": 0.0, "num_doc_files": 0.0, "num_config_files": 0.0,
        "num_test_files": 0.0, "num_other_files": 0.0,
        "has_py": 0.0, "has_go": 0.0, "has_js": 0.0, "has_ts": 0.0, "has_rs": 0.0,
    }
    for path in paths:
        candidate = Path(path)
        ext = candidate.suffix.lower()
        lowered = path.lower()
        if ext in CODE_EXTENSIONS:
            counts["num_code_files"] += 1
        elif ext in CONFIG_EXTENSIONS:
            counts["num_config_files"] += 1
        elif ext in DOC_EXTENSIONS:
            counts["num_doc_files"] += 1
        else:
            counts["num_other_files"] += 1
        if any(token in candidate.name.lower() for token in ("test_", "_test", "test.", "spec.", ".spec.")) or any(
            part.lower() in {"test", "tests", "spec", "__tests__", "testing"} for part in candidate.parts
        ):
            counts["num_test_files"] += 1
        if ext == ".py":
            counts["has_py"] = 1
        elif ext == ".go":
            counts["has_go"] = 1
        elif ext in {".js", ".jsx"}:
            counts["has_js"] = 1
        elif ext in {".ts", ".tsx"}:
            counts["has_ts"] = 1
        elif ext == ".rs":
            counts["has_rs"] = 1
    total = max(len(paths), 1)
    counts["test_file_ratio"] = counts["num_test_files"] / total
    counts["code_file_ratio"] = counts["num_code_files"] / total
    counts["doc_file_ratio"] = counts["num_doc_files"] / total
    return counts


def _parse_diff_changes(diff_text: str) -> Dict[str, Dict[str, List[str]]]:
    changes: Dict[str, Dict[str, List[str]]] = {}
    current_path = None
    for line in diff_text.splitlines():
        match = re.match(r"^diff --git a/(.+) b/(.+)$", line)
        if match:
            current_path = match.group(2)
            changes.setdefault(current_path, {"added_lines": []})
            continue
        if line.startswith("+++ b/"):
            current_path = line[6:]
            changes.setdefault(current_path, {"added_lines": []})
            continue
        if current_path and line.startswith("+") and not line.startswith("+++"):
            changes[current_path]["added_lines"].append(line[1:])
    return changes


def _change_stats(diff_text: str) -> Tuple[int, int]:
    additions = deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions


@lru_cache(maxsize=1)
def _experiment2_extractors():
    experiment2_src = Path(__file__).resolve().parents[2] / "experiment2" / "src"
    sys.path.insert(0, str(experiment2_src))
    ast_module = importlib.import_module("ast_extractor")
    cfg_module = importlib.import_module("cfg_extractor")
    ast_module._init_tree_sitter()
    return ast_module.extract_pr_ast, cfg_module.extract_pr_cfg


def _extract_structural_features(pr_record: dict) -> Tuple[Dict[str, float], Dict[str, float]]:
    extract_ast, extract_cfg = _experiment2_extractors()
    ast_record = extract_ast(pr_record)
    cfg_record = extract_cfg(pr_record)
    pr_record["cfg_available"] = cfg_record.get("cfg_available", False)
    ast_features = {name: float(ast_record.get(name, 0)) for name in DEPLOYABLE_FEATURE_NAMES if name.startswith("ast_") and name != "ast_missing"}
    cfg_features = {name: float(cfg_record.get(name, 0)) for name in DEPLOYABLE_FEATURE_NAMES if name.startswith("cfg_") and name != "cfg_missing"}
    return ast_features, cfg_features
