"""
实验二 步骤七：模型训练
训练 SVM 和 Random Forest 进行 Merge Prediction。
额外训练 Dummy 和 LogisticRegression 作为 sanity check。
"""
import json
import time
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.model_selection import GridSearchCV
from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                              f1_score, roc_auc_score, classification_report)

from config import (
    PROCESSED_DIR, MODELS_DIR, EVALUATION_DIR,
    SVM_PARAM_GRID, RF_PARAM_GRID, RANDOM_SEED,
)
from utils import log, write_json


def prepare_data(features_path: Path):
    """从特征 CSV 加载并分离 train/val/test。"""
    df = pd.read_csv(features_path)
    log.info(f"加载特征: {features_path.name} ({len(df)} 行 × {len(df.columns)} 列)")

    # 分离辅助列和特征列
    aux_cols = ["pr_id", "repo", "is_merged", "split"]
    feature_cols = [c for c in df.columns if c not in aux_cols]

    # 按 split 分组
    train_df = df[df["split"] == "train"]
    val_df = df[df["split"] == "val"]
    test_df = df[df["split"] == "test"]

    X_train = train_df[feature_cols].values
    y_train = train_df["is_merged"].values.astype(int)
    X_val = val_df[feature_cols].values
    y_val = val_df["is_merged"].values.astype(int)
    X_test = test_df[feature_cols].values
    y_test = test_df["is_merged"].values.astype(int)

    log.info(f"Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")
    log.info(f"特征维度: {len(feature_cols)}")

    # 合并 train+val 用于最终模型训练（在 test 上评估）
    X_trainval = np.vstack([X_train, X_val])
    y_trainval = np.hstack([y_train, y_val])

    return {
        "X_train": X_train, "y_train": y_train,
        "X_val": X_val, "y_val": y_val,
        "X_test": X_test, "y_test": y_test,
        "X_trainval": X_trainval, "y_trainval": y_trainval,
        "feature_names": feature_cols,
    }


def train_dummy(data: dict) -> dict:
    """训练 Dummy 基线模型。"""
    log.info("训练 DummyClassifier (most_frequent)...")
    clf = DummyClassifier(strategy="most_frequent", random_state=RANDOM_SEED)
    clf.fit(data["X_train"], data["y_train"])

    y_pred = clf.predict(data["X_test"])
    y_prob = clf.predict_proba(data["X_test"])[:, 1]

    return {
        "model": clf,
        "type": "DummyClassifier",
        "test_metrics": _compute_metrics(data["y_test"], y_pred, y_prob),
    }


def train_logistic(data: dict) -> dict:
    """训练 LogisticRegression sanity check。"""
    log.info("训练 LogisticRegression (balanced)...")
    clf = LogisticRegression(
        class_weight="balanced", max_iter=2000,
        random_state=RANDOM_SEED, n_jobs=-1,
    )
    clf.fit(data["X_train"], data["y_train"])

    y_pred = clf.predict(data["X_test"])
    y_prob = clf.predict_proba(data["X_test"])[:, 1]

    return {
        "model": clf,
        "type": "LogisticRegression",
        "test_metrics": _compute_metrics(data["y_test"], y_pred, y_prob),
    }


def train_svm(data: dict) -> dict:
    """训练 SVM（GridSearchCV，val 做超参选择）。"""
    log.info("训练 SVM (GridSearchCV)...")
    svm = SVC(class_weight="balanced", random_state=RANDOM_SEED, probability=True)

    grid = GridSearchCV(
        svm, SVM_PARAM_GRID,
        cv=5, scoring="roc_auc", n_jobs=-1, verbose=0,
    )
    t0 = time.time()
    grid.fit(data["X_trainval"], data["y_trainval"])
    train_time = time.time() - t0

    log.info(f"SVM 最佳参数: {grid.best_params_}")
    log.info(f"SVM 最佳 CV ROC-AUC: {grid.best_score_:.4f}")
    log.info(f"训练时间: {train_time:.1f}s")

    best_model = grid.best_estimator_
    y_pred = best_model.predict(data["X_test"])
    y_prob = best_model.predict_proba(data["X_test"])[:, 1]

    return {
        "model": best_model,
        "type": "SVM",
        "best_params": grid.best_params_,
        "best_cv_score": grid.best_score_,
        "train_time_s": round(train_time, 1),
        "test_metrics": _compute_metrics(data["y_test"], y_pred, y_prob),
    }


def train_rf(data: dict) -> dict:
    """训练 Random Forest（GridSearchCV，val 做超参选择）。"""
    log.info("训练 Random Forest (GridSearchCV)...")
    rf = RandomForestClassifier(
        class_weight="balanced", random_state=RANDOM_SEED, n_jobs=-1,
    )

    grid = GridSearchCV(
        rf, RF_PARAM_GRID,
        cv=5, scoring="roc_auc", n_jobs=-1, verbose=0,
    )
    t0 = time.time()
    grid.fit(data["X_trainval"], data["y_trainval"])
    train_time = time.time() - t0

    log.info(f"RF 最佳参数: {grid.best_params_}")
    log.info(f"RF 最佳 CV ROC-AUC: {grid.best_score_:.4f}")
    log.info(f"训练时间: {train_time:.1f}s")

    best_model = grid.best_estimator_
    y_pred = best_model.predict(data["X_test"])
    y_prob = best_model.predict_proba(data["X_test"])[:, 1]

    return {
        "model": best_model,
        "type": "RandomForest",
        "best_params": grid.best_params_,
        "best_cv_score": grid.best_score_,
        "train_time_s": round(train_time, 1),
        "test_metrics": _compute_metrics(data["y_test"], y_pred, y_prob),
        "feature_importances": dict(
            zip(data["feature_names"],
                best_model.feature_importances_.tolist())
        ),
    }


def _compute_metrics(y_true, y_pred, y_prob) -> dict:
    """计算分类评估指标。"""
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
    }


# ============================================================
# 消融实验
# ============================================================
def run_ablation(data: dict, result_dir: Path):
    """特征组消融实验：考察各组特征的贡献。"""
    log.info("开始消融实验...")

    # 特征组定义
    feature_sets = {
        "stats_text": [i for i, name in enumerate(data["feature_names"])
                       if not name.startswith("ast_") and not name.startswith("cfg_")
                       and name not in ("ast_missing", "cfg_missing")],
        "stats_text_ast": [i for i, name in enumerate(data["feature_names"])
                           if not name.startswith("cfg_")
                           and name not in ("cfg_missing",)],
        "stats_text_cfg": [i for i, name in enumerate(data["feature_names"])
                           if not name.startswith("ast_")
                           and name not in ("ast_missing",)],
        "main_all": list(range(len(data["feature_names"]))),
    }

    ablation_results = []

    for name, feat_indices in feature_sets.items():
        X_tr = data["X_trainval"][:, feat_indices]
        X_te = data["X_test"][:, feat_indices]

        # Random Forest
        rf = RandomForestClassifier(
            n_estimators=200, max_depth=16,
            class_weight="balanced", random_state=RANDOM_SEED, n_jobs=-1,
        )
        rf.fit(X_tr, data["y_trainval"])
        y_pred = rf.predict(X_te)
        y_prob = rf.predict_proba(X_te)[:, 1]
        metrics = _compute_metrics(data["y_test"], y_pred, y_prob)

        result = {"feature_set": name, "n_features": len(feat_indices),
                  **metrics}
        ablation_results.append(result)
        log.info(f"  消融 {name} ({len(feat_indices)} 特征): "
                 f"Acc={metrics['accuracy']:.4f}, F1={metrics['f1_score']:.4f}, "
                 f"AUC={metrics['roc_auc']:.4f}")

    # 保存
    ablation_path = result_dir / "ablation_results.json"
    write_json(ablation_results, ablation_path)

    return ablation_results


# ============================================================
# 主入口
# ============================================================
def run(features_main_path: Path = None,
        features_upper_path: Path = None,
        models_dir: Path = None,
        eval_dir: Path = None):
    """完整训练流程。"""
    if features_main_path is None:
        features_main_path = PROCESSED_DIR / "features_main.csv"
    if features_upper_path is None:
        features_upper_path = PROCESSED_DIR / "features_upper_bound.csv"
    if models_dir is None:
        models_dir = MODELS_DIR
    if eval_dir is None:
        eval_dir = EVALUATION_DIR

    results = {}

    for name, feat_path in [("main", features_main_path),
                              ("upper_bound", features_upper_path)]:
        log.info(f"\n{'='*55}")
        log.info(f"训练 {name} 实验模型")
        log.info(f"{'='*55}")

        data = prepare_data(feat_path)

        # Sanity checks
        dummy_result = train_dummy(data)
        logit_result = train_logistic(data)

        # 主模型
        svm_result = train_svm(data)
        rf_result = train_rf(data)

        # 保存模型
        for res in [svm_result, rf_result]:
            model_type = res["type"]
            model_path = models_dir / f"{model_type.lower()}_{name}.joblib"
            joblib.dump(res["model"], model_path)
            log.info(f"模型已保存: {model_path}")

        # 汇总结果
        exp_results = {
            "dummy": {k: v for k, v in dummy_result.items() if k != "model"},
            "logistic_regression": {k: v for k, v in logit_result.items() if k != "model"},
            "svm": {k: v for k, v in svm_result.items() if k != "model"},
            "random_forest": {k: v for k, v in rf_result.items() if k != "model"},
        }
        results[name] = exp_results

        # 打印汇总
        log.info(f"\n{'='*40}")
        log.info(f"{name} 实验测试集结果汇总:")
        log.info(f"{'='*40}")
        for model_name in ["dummy", "logistic_regression", "svm", "random_forest"]:
            m = exp_results[model_name]["test_metrics"]
            log.info(f"  {model_name}: Acc={m['accuracy']:.4f}, "
                     f"F1={m['f1_score']:.4f}, AUC={m['roc_auc']:.4f}")

        # 保存指标
        metrics_path = eval_dir / f"metrics_{name}.json"
        write_json(exp_results, metrics_path)

        # 消融实验（仅对主实验做）
        if name == "main":
            ablation = run_ablation(data, eval_dir)

            # 保存特征重要性
            fi = rf_result.get("feature_importances", {})
            if fi:
                fi_sorted = sorted(fi.items(), key=lambda x: x[1], reverse=True)
                fi_path = eval_dir / "feature_importance.csv"
                import csv
                with open(fi_path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["feature", "importance"])
                    writer.writerows(fi_sorted)
                log.info(f"特征重要性已保存: {fi_path}")

                # Top-20
                log.info("\nTop-20 特征重要性:")
                for rank, (feat, imp) in enumerate(fi_sorted[:20], 1):
                    log.info(f"  {rank:2d}. {feat}: {imp:.4f}")

    # 保存汇总训练日志
    training_log = {
        "random_seed": RANDOM_SEED,
        "main": results["main"],
        "upper_bound": results["upper_bound"],
    }
    log_path = eval_dir / "training_log.json"
    write_json(training_log, log_path)
    log.info(f"\n训练日志已保存: {log_path}")

    return results


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    run()
