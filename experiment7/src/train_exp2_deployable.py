"""Train local-diff-compatible variants of the Experiment 2 ML models.

The original Experiment 2 artifacts are never overwritten.  This script uses
the same PR labels and fixed split, but removes fields unavailable to a local
Git diff before training the deployment variants.
"""

from __future__ import annotations

import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from src.config import EXPERIMENT2_DIR, EXP2_DEPLOYABLE_CONTRACT, EXP2_DEPLOYABLE_METRICS, EXP2_DEPLOYABLE_MODELS_DIR
from src.deployable_features import DEPLOYABLE_FEATURE_NAMES, TrainWinsorizer, build_training_features


def _metrics(y_true, y_pred, y_prob) -> dict:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
    }


def _fitted_pipeline(classifier, X_train, y_train, X_trainval, y_trainval) -> Pipeline:
    preprocessor = Pipeline([
        ("winsorize", TrainWinsorizer(quantile=0.99)),
        ("scale", StandardScaler()),
    ])
    preprocessor.fit(X_train, y_train)
    transformed_trainval = preprocessor.transform(X_trainval)
    classifier.fit(transformed_trainval, y_trainval)
    return Pipeline([("preprocess", preprocessor), ("classifier", classifier)])


def train() -> dict:
    processed = EXPERIMENT2_DIR / "results" / "processed"
    human = pd.read_csv(processed / "human_only_dataset.csv", encoding="utf-8-sig")
    ast = pd.read_csv(processed / "ast_features.csv", encoding="utf-8-sig")
    cfg = pd.read_csv(processed / "cfg_features.csv", encoding="utf-8-sig")
    splits = pd.read_csv(processed / "splits.csv", encoding="utf-8-sig")
    dataset, large_churn_threshold = build_training_features(human, ast, cfg, splits)

    X = dataset[DEPLOYABLE_FEATURE_NAMES].to_numpy(dtype=float)
    y = dataset["is_merged"].astype(int).to_numpy()
    split = dataset["split"].to_numpy()
    train_mask = split == "train"
    val_mask = split == "val"
    test_mask = split == "test"
    X_train, y_train = X[train_mask], y[train_mask]
    X_trainval, y_trainval = X[train_mask | val_mask], y[train_mask | val_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    candidates = {
        "exp2-rf-deployable": RandomForestClassifier(
            n_estimators=500, max_depth=None, max_features="sqrt",
            min_samples_split=2, min_samples_leaf=1, class_weight="balanced",
            random_state=42, n_jobs=-1,
        ),
        "exp2-svm-deployable": SVC(
            C=10, kernel="rbf", gamma="scale", class_weight="balanced",
            probability=True, random_state=42,
        ),
    }
    EXP2_DEPLOYABLE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    paths = {}
    for model_id, classifier in candidates.items():
        started = time.perf_counter()
        pipeline = _fitted_pipeline(classifier, X_train, y_train, X_trainval, y_trainval)
        y_prob = pipeline.predict_proba(X_test)[:, 1]
        y_pred = pipeline.predict(X_test)
        path = EXP2_DEPLOYABLE_MODELS_DIR / f"{model_id}.joblib"
        joblib.dump(pipeline, path)
        paths[model_id] = str(path.resolve())
        results[model_id] = {
            "test_metrics": _metrics(y_test, y_pred, y_prob),
            "training_seconds": round(time.perf_counter() - started, 3),
        }

    contract = {
        "schema_version": 1,
        "description": "Experiment 2 deployable variants trained only on local Git-diff features.",
        "source_dataset": str((processed / "human_only_dataset.csv").resolve()),
        "source_split": str((processed / "splits.csv").resolve()),
        "feature_names": DEPLOYABLE_FEATURE_NAMES,
        "feature_count": len(DEPLOYABLE_FEATURE_NAMES),
        "large_churn_threshold": large_churn_threshold,
        "preprocessor": "TrainWinsorizer(q=0.99) and StandardScaler fit on the original train split; bundled in each model pipeline.",
        "models": paths,
        "limitations": [
            "Only Git-diff input is supported; single-file input has no equivalent patch semantics.",
            "Predictions are for pre-merge assistance and are not merge decisions.",
            "This is a retrained deployment variant, not the original 61-feature PR-level model.",
        ],
    }
    EXP2_DEPLOYABLE_CONTRACT.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    EXP2_DEPLOYABLE_METRICS.write_text(json.dumps({
        "sample_counts": {"train": int(train_mask.sum()), "val": int(val_mask.sum()), "test": int(test_mask.sum())},
        "models": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"contract": contract, "metrics": results}


def main() -> int:
    result = train()
    print(f"Trained {len(result['metrics'])} deployable Experiment 2 models.")
    for model_id, values in result["metrics"].items():
        metrics = values["test_metrics"]
        print(f"  {model_id}: F1={metrics['f1_score']:.4f}, AUC={metrics['roc_auc']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
