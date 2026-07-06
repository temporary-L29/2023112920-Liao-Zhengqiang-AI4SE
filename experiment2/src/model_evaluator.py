"""
实验二 步骤八：模型评估
在测试集上评估所有模型，输出指标、混淆矩阵、分仓库性能、特征重要性。
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, classification_report,
    average_precision_score,
)

from config import PROCESSED_DIR, MODELS_DIR, EVALUATION_DIR
from utils import log, read_json, write_json


def load_test_data(features_path: Path):
    """加载测试集数据和特征名。"""
    df = pd.read_csv(features_path)
    test_df = df[df["split"] == "test"].copy()

    aux_cols = ["pr_id", "repo", "is_merged", "split"]
    feature_cols = [c for c in df.columns if c not in aux_cols]

    X_test = test_df[feature_cols].values
    y_test = test_df["is_merged"].values.astype(int)

    return {
        "X_test": X_test, "y_test": y_test,
        "pr_ids": test_df["pr_id"].values,
        "repos": test_df["repo"].values,
        "feature_names": feature_cols,
    }


def compute_detailed_metrics(y_true, y_pred, y_prob) -> dict:
    """计算详细评估指标。"""
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)

    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "pr_auc": round(float(average_precision_score(y_true, y_prob)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp),
                              "fn": int(fn), "tp": int(tp)},
        "specificity": round(float(tn / max(tn + fp, 1)), 4),
        "npv": round(float(tn / max(tn + fn, 1)), 4),
    }


def per_repo_metrics(y_true, y_pred, y_prob, repos) -> list:
    """按仓库计算指标。"""
    results = []
    for repo_name in sorted(set(repos)):
        mask = repos == repo_name
        if mask.sum() == 0:
            continue
        yt = y_true[mask]
        yp = y_pred[mask]
        ypr = y_prob[mask]
        metrics = compute_detailed_metrics(yt, yp, ypr)
        metrics["repo"] = repo_name
        metrics["n_samples"] = int(mask.sum())
        results.append(metrics)
    return results


def evaluate_model(model, model_type: str, data: dict) -> dict:
    """评估单个模型。"""
    y_pred = model.predict(data["X_test"])
    y_prob = model.predict_proba(data["X_test"])[:, 1]

    overall = compute_detailed_metrics(data["y_test"], y_pred, y_prob)
    per_repo = per_repo_metrics(data["y_test"], y_pred, y_prob, data["repos"])

    # 分类报告（字符串形式）
    report_str = classification_report(
        data["y_test"], y_pred,
        target_names=["not_merged", "merged"],
        zero_division=0,
    )

    return {
        "model_type": model_type,
        "overall": overall,
        "per_repo": per_repo,
        "classification_report": report_str,
        "predictions": y_pred.tolist(),
        "probabilities": y_prob.tolist(),
    }


def run(features_main_path: Path = None,
        features_upper_path: Path = None,
        models_dir: Path = None,
        eval_dir: Path = None):
    """完整评估流程。"""
    import joblib

    if features_main_path is None:
        features_main_path = PROCESSED_DIR / "features_main.csv"
    if features_upper_path is None:
        features_upper_path = PROCESSED_DIR / "features_upper_bound.csv"
    if models_dir is None:
        models_dir = MODELS_DIR
    if eval_dir is None:
        eval_dir = EVALUATION_DIR

    all_results = {}

    for name, feat_path in [("main", features_main_path),
                              ("upper_bound", features_upper_path)]:
        log.info(f"\n{'='*55}")
        log.info(f"评估 {name} 实验")
        log.info(f"{'='*55}")

        data = load_test_data(feat_path)
        log.info(f"测试集: {len(data['y_test'])} 样本, "
                 f"正类率={data['y_test'].mean():.4f}")

        exp_results = {}

        for model_type in ["svm", "randomforest"]:
            model_path = models_dir / f"{model_type}_{name}.joblib"
            if not model_path.exists():
                log.warning(f"模型不存在: {model_path}")
                continue

            model = joblib.load(model_path)
            log.info(f"加载模型: {model_path}")

            result = evaluate_model(model, model_type, data)
            exp_results[model_type] = result

            # 打印结果
            ov = result["overall"]
            log.info(f"\n{model_type} 测试集结果:")
            log.info(f"  Accuracy:     {ov['accuracy']:.4f}")
            log.info(f"  Precision:    {ov['precision']:.4f}")
            log.info(f"  Recall:       {ov['recall']:.4f}")
            log.info(f"  F1-score:     {ov['f1_score']:.4f}")
            log.info(f"  ROC-AUC:      {ov['roc_auc']:.4f}")
            log.info(f"  PR-AUC:       {ov['pr_auc']:.4f}")
            log.info(f"  Confusion:    TN={ov['confusion_matrix']['tn']}, "
                     f"FP={ov['confusion_matrix']['fp']}, "
                     f"FN={ov['confusion_matrix']['fn']}, "
                     f"TP={ov['confusion_matrix']['tp']}")

            # 分仓库
            log.info(f"\n  分仓库性能:")
            for r in result["per_repo"]:
                log.info(f"    {r['repo']}: n={r['n_samples']}, "
                         f"Acc={r['accuracy']:.4f}, F1={r['f1_score']:.4f}, "
                         f"AUC={r['roc_auc']:.4f}")

        all_results[name] = exp_results

        # 保存评估结果
        metrics_path = eval_dir / f"evaluation_{name}.json"
        # 移除 predictions 使 JSON 更小
        eval_save = {}
        for mt, res in exp_results.items():
            eval_save[mt] = {
                "overall": res["overall"],
                "per_repo": res["per_repo"],
                "classification_report": res["classification_report"],
            }
        write_json(eval_save, metrics_path)
        log.info(f"评估结果已保存: {metrics_path}")

    # 汇总报告（简化为 Markdown 格式）
    report_path = eval_dir / "evaluation_report.md"
    write_evaluation_report(all_results, report_path)
    log.info(f"评估报告已保存: {report_path}")

    return all_results


def write_evaluation_report(all_results: dict, output_path: Path):
    """生成 Markdown 格式评估报告。"""
    lines = [
        "# 实验二：模型评估报告",
        "",
        f"测试集: 210 样本 (来自 1397 条人类代码 PR 的 15%)",
        "",
        "## 1. 主实验 (Main) — 无审查过程特征",
        "",
    ]

    for name in ["main", "upper_bound"]:
        if name == "upper_bound":
            lines.extend([
                "## 2. 上界扩展实验 (Upper Bound) — 含审查过程特征",
                "",
                "> ⚠️ 此实验包含审查过程信息，仅作为性能上界参考，不作为主结论。",
                "",
            ])

        results = all_results.get(name, {})
        if not results:
            continue

        lines.extend(["| 模型 | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC |",
                       "|------|----------|-----------|--------|----|---------|--------|"])

        for mt in ["svm", "randomforest"]:
            if mt not in results:
                continue
            ov = results[mt]["overall"]
            lines.append(
                f"| {mt} | {ov['accuracy']:.4f} | {ov['precision']:.4f} | "
                f"{ov['recall']:.4f} | {ov['f1_score']:.4f} | "
                f"{ov['roc_auc']:.4f} | {ov['pr_auc']:.4f} |"
            )

        # 分仓库表
        if results:
            first_model = list(results.keys())[0]
            per_repo = results[first_model]["per_repo"]
            if per_repo:
                lines.extend([
                    "",
                    f"### {'Main' if name == 'main' else 'Upper Bound'} — 分仓库性能 (RF)",
                    "",
                    "| 仓库 | 样本数 | Accuracy | F1 | ROC-AUC |",
                    "|------|--------|----------|----|---------|",
                ])
                rf_per_repo = results.get("randomforest", {}).get("per_repo", per_repo)
                for r in rf_per_repo:
                    lines.append(
                        f"| {r['repo']} | {r['n_samples']} | "
                        f"{r['accuracy']:.4f} | {r['f1_score']:.4f} | "
                        f"{r['roc_auc']:.4f} |"
                    )

        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    run()
