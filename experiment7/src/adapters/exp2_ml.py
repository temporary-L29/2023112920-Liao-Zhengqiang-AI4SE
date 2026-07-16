"""Experiment 2 ML adapters for Experiment 7.

The original 61-feature PR models remain intentionally disabled for CLI
input.  The deployable IDs load retrained pipelines whose feature contract is
limited to information obtainable from a local Git diff.
"""

from __future__ import annotations

import datetime
import json
import time
import uuid
from pathlib import Path

import joblib

from src.adapters.base import BaseAdapter
from src.config import EXP2_DEPLOYABLE_CONTRACT
from src.deployable_features import DEPLOYABLE_FEATURE_NAMES, build_features_from_diff
from src.input_extractors import compute_change_stats, compute_content_sha256
from src.risk_analyzer import analyze as rule_analyze
from src.schemas import (
    Confidence,
    InputSummary,
    MergePrediction,
    ModelInfo,
    ModelStatus,
    ReviewRequest,
    ReviewResponse,
    SourceKind,
    TimingInfo,
)


ORIGINAL_MODEL_IDS = {"exp2-rf", "exp2-svm"}
DEPLOYABLE_MODEL_IDS = {"exp2-rf-deployable", "exp2-svm-deployable"}


class Exp2MLAdapter(BaseAdapter):
    """Load a deployable Experiment 2 pipeline or report original-model limits."""

    def __init__(self, model_id: str):
        self._model_id = model_id
        self._pipeline = None
        self._large_churn_threshold = 0.0
        self._status = ModelStatus.incompatible
        self._reason = ""
        self._version = "deployable-v1"
        self._load()

    def _load(self) -> None:
        if self._model_id in ORIGINAL_MODEL_IDS:
            self._reason = (
                "Original Experiment 2 model expects 61 PR-level features. "
                "Use exp2-rf-deployable or exp2-svm-deployable for Git diff input."
            )
            self._version = "original-pr-v1"
            return
        if self._model_id not in DEPLOYABLE_MODEL_IDS:
            self._reason = "Unknown Experiment 2 model ID"
            return
        if not EXP2_DEPLOYABLE_CONTRACT.exists():
            self._reason = "Deployable models are not trained. Run python -m src.train_exp2_deployable."
            return
        try:
            contract = json.loads(EXP2_DEPLOYABLE_CONTRACT.read_text(encoding="utf-8"))
            feature_names = contract["feature_names"]
            if feature_names != DEPLOYABLE_FEATURE_NAMES:
                self._reason = "Deployable feature contract does not match this application version"
                return
            model_path = Path(contract["models"][self._model_id])
            self._pipeline = joblib.load(model_path)
            self._large_churn_threshold = float(contract["large_churn_threshold"])
        except (KeyError, OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
            self._reason = f"Unable to load deployable model: {exc}"
            return
        self._status = ModelStatus.ready

    @property
    def model_info(self) -> ModelInfo:
        kind = "ml-rf" if "rf" in self._model_id else "ml-svm"
        return ModelInfo(
            id=self._model_id,
            kind=kind,
            version=self._version,
            status=self._status,
            reason=self._reason,
        )

    async def review(self, request: ReviewRequest) -> ReviewResponse:
        if self._status != ModelStatus.ready:
            raise ValueError(f"Model {self._model_id} is incompatible: {self._reason}")
        if request.source.kind != SourceKind.git_diff or not request.content.diff:
            raise ValueError(f"Model {self._model_id} requires non-empty Git diff input")

        started = time.perf_counter()
        vector = build_features_from_diff(request.content.diff, self._large_churn_threshold)
        extracted = time.perf_counter()
        probabilities = self._pipeline.predict_proba(vector)[0]
        merge_probability = float(probabilities[1])
        predicted = MergePrediction.merged if merge_probability >= 0.5 else MergePrediction.not_merged
        inferred = time.perf_counter()

        files = [{"path": item.path, "language": item.language, "content": item.content} for item in request.content.files]
        rule_result = rule_analyze(files, request.content.diff)
        additions, deletions = compute_change_stats(request.content.diff)
        digest = compute_content_sha256(request.content.diff)[:16]
        if merge_probability < 0.3:
            risk_level, confidence = "high", Confidence.high
        elif merge_probability < 0.6:
            risk_level, confidence = "medium", Confidence.medium
        else:
            risk_level = "low"
            confidence = Confidence.high if merge_probability >= 0.8 else Confidence.medium

        history_id = datetime.datetime.now().strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6]
        return ReviewResponse(
            request_id=request.request_id,
            model=self.model_info,
            merge_prediction=predicted,
            merge_probability=round(merge_probability, 4),
            confidence=confidence,
            risk_level=risk_level,
            risk_factors=rule_result["risk_factors"],
            review_comments=rule_result["review_comments"],
            input_summary=InputSummary(
                changed_files=len(request.content.files),
                additions=additions,
                deletions=deletions,
                content_sha256=digest,
            ),
            timing=TimingInfo(
                extract_ms=round((extracted - started) * 1000, 2),
                model_ms=round((inferred - extracted) * 1000, 2),
                total_ms=round((inferred - started) * 1000, 2),
            ),
            history_id=history_id,
        )
