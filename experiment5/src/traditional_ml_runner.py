"""
传统机器学习实验 — 加载实验二模型，在 AI PR 上预测

输入:
  - experiment2/results/models/svm_main.joblib
  - experiment2/results/models/randomforest_main.joblib
  - results/processed/ai_features_main.csv

输出:
  - results/predictions/traditional_ml_predictions.csv
  - results/evaluation/traditional_ml_metrics.json
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, confusion_matrix,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    EXPERIMENT2_DIR,
    RESULTS_PROCESSED_DIR,
    RESULTS_EVALUATION_DIR,
    logger,
)

AI_FEATURES_CSV = os.path.join(RESULTS_PROCESSED_DIR, "ai_features_main.csv")
PREDICTIONS_DIR = os.path.join(os.path.dirname(RESULTS_PROCESSED_DIR), "predictions")
ML_PREDICTIONS_CSV = os.path.join(PREDICTIONS_DIR, "traditional_ml_predictions.csv")
ML_METRICS_JSON = os.path.join(RESULTS_EVALUATION_DIR, "traditional_ml_metrics.json")

SVM_MODEL = os.path.join(EXPERIMENT2_DIR, "results", "models", "svm_main.joblib")
RF_MODEL = os.path.join(EXPERIMENT2_DIR, "results", "models", "randomforest_main.joblib")

os.makedirs(PREDICTIONS_DIR, exist_ok=True)


def compute_metrics(y_true, y_pred, y_prob=None) -> dict:
    """计算分类指标"""
    metrics = {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
    }
    if y_prob is not None:
        try:
            metrics["roc_auc"] = round(float(roc_auc_score(y_true, y_prob)), 4)
        except ValueError:
            metrics["roc_auc"] = None
    cm = confusion_matrix(y_true, y_pred)
    metrics["confusion_matrix"] = cm.tolist()
    metrics["tn"] = int(cm[0, 0]) if cm.shape == (2, 2) else 0
    metrics["fp"] = int(cm[0, 1]) if cm.shape == (2, 2) else 0
    metrics["fn"] = int(cm[1, 0]) if cm.shape == (2, 2) else 0
    metrics["tp"] = int(cm[1, 1]) if cm.shape == (2, 2) else 0
    return metrics


def run_traditional_ml() -> bool:
    """运行传统机器学习实验"""
    logger.info("=" * 60)
    logger.info("阶段: 传统机器学习实验 (SVM / Random Forest)")
    logger.info("=" * 60)

    # 1. 加载特征
    if not os.path.exists(AI_FEATURES_CSV):
        logger.error(f"AI 特征文件未找到: {AI_FEATURES_CSV}")
        logger.error("请先运行: python src/run_all.py --build-features")
        return False

    df = pd.read_csv(AI_FEATURES_CSV, encoding="utf-8-sig")
    y_true = df["is_merged"].values.astype(int)
    logger.info(f"加载 AI 特征: {len(df)} 行, merged={y_true.sum()}/{len(y_true)}")

    # 辅助列
    aux_cols = ["pr_id", "repo", "is_merged", "split"]
    feature_cols = [c for c in df.columns if c not in aux_cols]
    X = df[feature_cols].fillna(0).values

    results = {}

    # 2. SVM
    logger.info("加载 SVM 模型...")
    if not os.path.exists(SVM_MODEL):
        logger.warning(f"SVM 模型未找到: {SVM_MODEL}")
    else:
        svm = joblib.load(SVM_MODEL)
        logger.info(f"  SVM 类型: {type(svm).__name__}")
        t0 = time.time()
        y_pred_svm = svm.predict(X)
        try:
            y_prob_svm = svm.predict_proba(X)[:, 1]
        except Exception:
            y_prob_svm = None
        elapsed = time.time() - t0
        svm_metrics = compute_metrics(y_true, y_pred_svm, y_prob_svm)
        svm_metrics["model"] = "svm_main"
        svm_metrics["inference_time_ms"] = round(elapsed * 1000, 1)
        results["svm"] = svm_metrics
        logger.info(f"  SVM: acc={svm_metrics['accuracy']}, f1={svm_metrics['f1']}, "
                     f"roc_auc={svm_metrics.get('roc_auc')}, time={elapsed:.3f}s")

    # 3. Random Forest
    logger.info("加载 Random Forest 模型...")
    if not os.path.exists(RF_MODEL):
        logger.warning(f"RF 模型未找到: {RF_MODEL}")
    else:
        rf = joblib.load(RF_MODEL)
        logger.info(f"  RF 类型: {type(rf).__name__}")
        t0 = time.time()
        y_pred_rf = rf.predict(X)
        try:
            y_prob_rf = rf.predict_proba(X)[:, 1]
        except Exception:
            y_prob_rf = None
        elapsed = time.time() - t0
        rf_metrics = compute_metrics(y_true, y_pred_rf, y_prob_rf)
        rf_metrics["model"] = "randomforest_main"
        rf_metrics["inference_time_ms"] = round(elapsed * 1000, 1)
        results["randomforest"] = rf_metrics
        logger.info(f"  RF:  acc={rf_metrics['accuracy']}, f1={rf_metrics['f1']}, "
                     f"roc_auc={rf_metrics.get('roc_auc')}, time={elapsed:.3f}s")

    # 4. 保存预测
    pred_df = df[["pr_id", "repo", "is_merged"]].copy()
    if "svm" in results:
        pred_df["svm_prediction"] = y_pred_svm
        if y_prob_svm is not None:
            pred_df["svm_probability"] = y_prob_svm
    if "randomforest" in results:
        pred_df["rf_prediction"] = y_pred_rf
        if y_prob_rf is not None:
            pred_df["rf_probability"] = y_prob_rf

    pred_df.to_csv(ML_PREDICTIONS_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"预测结果已保存: {ML_PREDICTIONS_CSV}")

    # 5. 保存指标
    with open(ML_METRICS_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"指标已保存: {ML_METRICS_JSON}")

    # 6. 摘要
    logger.info("=" * 60)
    logger.info("传统机器学习实验完成")
    for model_name, m in results.items():
        logger.info(f"  {model_name}: acc={m['accuracy']}, prec={m['precision']}, "
                     f"rec={m['recall']}, f1={m['f1']}, auc={m.get('roc_auc')}")
    logger.info("=" * 60)

    return True


if __name__ == "__main__":
    run_traditional_ml()
