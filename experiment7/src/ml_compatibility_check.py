"""
ML Compatibility Check — determines whether experiment 2 models can be
safely used with local file/diff input.

Outputs: results/compatibility/ml_feature_contract.json

Rules:
  - Only features that can be computed WITHOUT PR metadata (title, body,
    review comments, merge status, repo label) may be marked "supported".
  - Features that can be approximated from local diff are "derived".
  - Features that require PR/post-review data are "unavailable".
  - A model is "ready" ONLY when all required features have a valid
    mapping and the feature vector dimension matches the scaler.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.config import (
    COMPAT_DIR, EXP2_SVM_MODEL, EXP2_RF_MODEL, EXP2_SCALER,
    EXP2_FEATURES_CSV, EXPERIMENT2_DIR, logger,
)


# Features and their local computability
# "supported"    — can compute directly from local file/diff
# "derived"      — can approximate (e.g. title from first diff line)
# "unavailable"  — needs PR metadata not available locally
FEATURE_STATUS = {
    "num_changed_files": "supported",
    "total_additions": "supported",
    "total_deletions": "supported",
    "num_commits": "unavailable",
    "code_churn": "supported",
    "net_lines": "supported",
    "additions_per_file": "supported",
    "deletions_per_file": "supported",
    "commits_per_file": "unavailable",
    "large_pr_flag": "derived",
    "title_len": "unavailable",
    "body_len": "unavailable",
    "commit_msg_len": "unavailable",
    "title_word_count": "unavailable",
    "body_word_count": "unavailable",
    "commit_msg_word_count": "unavailable",
    "has_issue_link": "unavailable",
    "has_release_note": "unavailable",
    "body_empty_flag": "unavailable",
    "num_code_files": "supported",
    "num_doc_files": "supported",
    "num_config_files": "supported",
    "num_test_files": "supported",
    "test_file_ratio": "supported",
    "code_file_ratio": "supported",
    "doc_file_ratio": "supported",
    "has_py": "supported",
    "has_go": "supported",
    "has_js": "supported",
    "has_ts": "supported",
    "has_rs": "supported",
    "ast_total_nodes": "derived",
    "ast_max_depth": "derived",
    "ast_files_parsed": "derived",
    "ast_files_attempted": "derived",
    "ast_parse_success_rate": "derived",
    "ast_error_node_count": "derived",
    "ast_func_def_count": "derived",
    "ast_class_def_count": "derived",
    "ast_if_count": "derived",
    "ast_loop_count": "derived",
    "ast_try_count": "derived",
    "ast_return_count": "derived",
    "ast_assignment_count": "derived",
    "cfg_total_nodes": "derived",
    "cfg_total_edges": "derived",
    "cfg_branch_nodes": "derived",
    "cfg_loop_nodes": "derived",
    "cfg_exit_nodes": "derived",
    "cfg_cyclomatic_complexity": "derived",
    "cfg_max_branch_depth": "derived",
    "cfg_avg_out_degree": "derived",
    "cfg_files_processed": "derived",
    "cfg_files_with_cfg": "derived",
    "repo_facebook/react": "unavailable",
    "repo_huggingface/transformers": "unavailable",
    "repo_kubernetes/kubernetes": "unavailable",
    "repo_microsoft/vscode": "unavailable",
    "repo_pandas-dev/pandas": "unavailable",
    "ast_missing": "derived",
    "cfg_missing": "derived",
}


def run_check() -> dict:
    """Run the full compatibility check and return the contract."""
    now = datetime.now().isoformat()

    contract = {
        "generated_at": now,
        "experiment2_dir": str(EXPERIMENT2_DIR.resolve()),
        "feature_csv": str(EXP2_FEATURES_CSV.resolve()) if EXP2_FEATURES_CSV.exists() else None,
        "feature_status": FEATURE_STATUS,
        "model_paths": {
            "svm": str(EXP2_SVM_MODEL.resolve()),
            "randomforest": str(EXP2_RF_MODEL.resolve()),
            "scaler": str(EXP2_SCALER.resolve()),
        },
        "models": {},
    }

    # Get expected feature names from CSV
    expected_features = _get_feature_names()
    contract["feature_names"] = expected_features
    contract["feature_count"] = len(expected_features)

    # Count feature availability
    supported = sum(1 for f in expected_features if FEATURE_STATUS.get(f) == "supported")
    derived = sum(1 for f in expected_features if FEATURE_STATUS.get(f) == "derived")
    unavailable = sum(1 for f in expected_features if FEATURE_STATUS.get(f) == "unavailable")
    unknown = len(expected_features) - supported - derived - unavailable

    contract["feature_summary"] = {
        "total": len(expected_features),
        "supported": supported,
        "derived": derived,
        "unavailable": unavailable,
        "unknown": unknown,
    }

    # Check each model
    for model_name, model_path, model_key in [
        ("Random Forest", EXP2_RF_MODEL, "exp2-rf"),
        ("SVM", EXP2_SVM_MODEL, "exp2-svm"),
    ]:
        model_status = _check_model(model_path, EXP2_SCALER, expected_features)
        contract["models"][model_key] = model_status

    # Determine global compatibility
    any_ready = any(
        m.get("status") == "ready" for m in contract["models"].values()
    )
    contract["global_status"] = "ready" if any_ready else "incompatible"
    if not any_ready:
        contract["global_reason"] = (
            "Experiment 2 models were trained on PR-level features including "
            "AST/CFG/repo metadata that cannot be computed from local file/diff "
            "input without data leakage. ML models are marked incompatible for "
            "local review. Use rule-based or LLM models instead."
        )

    return contract


def _get_feature_names() -> List[str]:
    """Read feature names from the training CSV."""
    if not EXP2_FEATURES_CSV.exists():
        logger.warning(f"Feature CSV not found: {EXP2_FEATURES_CSV}")
        return []

    try:
        import pandas as pd
        df = pd.read_csv(EXP2_FEATURES_CSV, nrows=0, encoding="utf-8-sig")
        # Drop label columns if present
        cols = [c for c in df.columns if c not in (
            "is_merged", "is_merged_bool", "pr_id", "repo", "merge_status", "split"
        )]
        return cols
    except Exception as e:
        logger.warning(f"Failed to read feature CSV: {e}")
        return []


def _check_model(
    model_path: Path,
    scaler_path: Path,
    expected_features: List[str],
) -> dict:
    """Check one model file for compatibility."""
    if not model_path.exists():
        return {
            "status": "incompatible",
            "reason": f"Model file not found: {model_path}",
            "path": str(model_path),
        }

    if not scaler_path.exists():
        return {
            "status": "incompatible",
            "reason": f"Scaler file not found: {scaler_path}",
            "path": str(model_path),
        }

    try:
        import joblib
        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
    except Exception as e:
        return {
            "status": "incompatible",
            "reason": f"Failed to load model: {e}",
            "path": str(model_path),
        }

    # Check feature count
    try:
        n_features = model.n_features_in_
    except AttributeError:
        try:
            n_features = model.n_features_in_
        except Exception:
            n_features = None

    scaler_features = getattr(scaler, "n_features_in_", None)

    if n_features is not None and n_features != len(expected_features):
        return {
            "status": "incompatible",
            "reason": (
                f"Feature count mismatch: model expects {n_features}, "
                f"CSV has {len(expected_features)} columns"
            ),
            "n_features_in": n_features,
            "expected_features": len(expected_features),
            "path": str(model_path),
        }

    # The original artifacts are PR-level research models.  Even when a local
    # diff can derive AST/CFG, PR metadata has no equivalent value; zero-fill
    # would create a misleading feature vector.
    unavailable_count = sum(
        1 for f in expected_features
        if FEATURE_STATUS.get(f, "unavailable") == "unavailable"
    )
    unavailable_ratio = unavailable_count / max(len(expected_features), 1)

    return {
        "status": "incompatible",
        "reason": (
            f"Original PR-level model requires {unavailable_count}/{len(expected_features)} "
            "non-local PR metadata features. AST/CFG can be derived from Git diff, "
            "but missing PR metadata must not be zero-filled. Use the deployable retrained model."
        ),
        "n_features_in": n_features,
        "unavailable_count": unavailable_count,
        "unavailable_ratio": round(unavailable_ratio, 3),
        "path": str(model_path),
    }


def main():
    """CLI entry point: run check and write JSON."""
    print("Running ML compatibility check...")
    contract = run_check()

    COMPAT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = COMPAT_DIR / "ml_feature_contract.json"
    output_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Contract written to: {output_path}")
    print(f"Global status: {contract['global_status']}")
    for key, model in contract["models"].items():
        print(f"  {key}: {model['status']} — {model.get('reason', '')[:120]}")

    # If all incompatible, still exit 0 (this is a valid result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
