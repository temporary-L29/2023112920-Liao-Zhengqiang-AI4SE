"""
Rule-based adapter — the mandatory offline fallback model.

Always ready; requires no API key or trained model files.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Any

from src.adapters.base import BaseAdapter
from src.schemas import (
    ReviewRequest, ReviewResponse, ModelInfo, ModelStatus,
    MergePrediction, Confidence, InputSummary, TimingInfo, ReviewComment,
)
from src.risk_analyzer import analyze
from src.input_extractors import compute_content_sha256, compute_change_stats


class RuleBasedAdapter(BaseAdapter):
    """Offline heuristic code-review adapter."""

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(
            id="rule-based",
            kind="rules",
            version="1",
            status=ModelStatus.ready,
        )

    async def review(self, request: ReviewRequest) -> ReviewResponse:
        t0 = time.perf_counter()

        # Build a flat file list for the rule engine
        files = [
            {"path": f.path, "language": f.language, "content": f.content}
            for f in request.content.files
        ]
        diff_text = request.content.diff

        t1 = time.perf_counter()
        extract_ms = (t1 - t0) * 1000

        result = analyze(files, diff_text)

        t2 = time.perf_counter()
        model_ms = (t2 - t1) * 1000

        # Input summary
        additions, deletions = 0, 0
        if diff_text:
            additions, deletions = compute_change_stats(diff_text)
        changed_files = len(files)

        raw_for_hash = (diff_text or "") + "\n".join(
            (f.content or "") for f in request.content.files
        )
        sha = compute_content_sha256(raw_for_hash)

        history_id = _make_history_id()

        return ReviewResponse(
            request_id=request.request_id,
            status="success",
            model=self.model_info,
            merge_prediction=result["merge_prediction"],
            merge_probability=result["merge_probability"],
            confidence=result["confidence"],
            risk_level=result["risk_level"],
            risk_factors=result["risk_factors"],
            review_comments=result["review_comments"],
            input_summary=InputSummary(
                changed_files=changed_files,
                additions=additions,
                deletions=deletions,
                content_sha256=sha[:16],
            ),
            timing=TimingInfo(
                extract_ms=round(extract_ms, 2),
                model_ms=round(model_ms, 2),
                total_ms=round((t2 - t0) * 1000, 2),
            ),
            history_id=history_id,
        )


def _make_history_id() -> str:
    import datetime
    now = datetime.datetime.now()
    suffix = uuid.uuid4().hex[:6]
    return now.strftime(f"%Y%m%dT%H%M%S-{suffix}")
