"""
Review service — orchestrates extraction, model selection, and history.

Depends ONLY on:
  - BaseAdapter (abstract)
  - schemas (Pydantic models)
  - history_store (record persistence)

Never imports concrete adapters directly — the registry wires them.
"""

from __future__ import annotations

import time
from typing import Optional

from src.schemas import (
    ReviewRequest, ReviewResponse, ErrorResponse, ErrorDetail,
)
from src.model_registry import ModelRegistry
from src.adapters.base import BaseAdapter
from src.history_store import (
    append, build_record_from_response, build_error_record,
)
from src.input_extractors import compute_change_stats, compute_content_sha256
from src.config import logger


_registry: Optional[ModelRegistry] = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


async def execute_review(request: ReviewRequest) -> ReviewResponse:
    """
    Full review pipeline: resolve model → run adapter → save history.

    Raises ValueError for model/input errors (→ HTTP 4xx).
    Raises RuntimeError for model execution failures (→ HTTP 5xx).
    """
    t_start = time.perf_counter()
    registry = get_registry()

    changed_files = len(request.content.files)
    additions, deletions = 0, 0
    if request.content.diff:
        additions, deletions = compute_change_stats(request.content.diff)

    try:
        adapter = registry.resolve(request.model_id)
    except ValueError as e:
        # Save failed history record
        record = build_error_record(
            request_id=request.request_id,
            model_id=request.model_id,
            source_kind=request.source.kind.value,
            error_message=str(e),
            changed_files=changed_files,
            additions=additions,
            deletions=deletions,
            total_ms=(time.perf_counter() - t_start) * 1000,
        )
        append(record)
        raise

    try:
        response = await adapter.review(request)
    except ValueError as e:
        total_ms = (time.perf_counter() - t_start) * 1000
        record = build_error_record(
            request_id=request.request_id,
            model_id=request.model_id,
            source_kind=request.source.kind.value,
            error_message=str(e),
            changed_files=changed_files,
            additions=additions,
            deletions=deletions,
            total_ms=total_ms,
        )
        append(record)
        raise
    except Exception as e:
        total_ms = (time.perf_counter() - t_start) * 1000
        logger.error(f"Model {request.model_id} failed: {e}")
        record = build_error_record(
            request_id=request.request_id,
            model_id=request.model_id,
            source_kind=request.source.kind.value,
            error_message=str(e),
            changed_files=changed_files,
            additions=additions,
            deletions=deletions,
            total_ms=total_ms,
        )
        append(record)
        raise RuntimeError(f"Model execution failed: {e}")

    # Success — save history (without source code by default)
    record = build_record_from_response(
        response, request,
        store_source=request.options.store_source,
    )
    append(record)

    return response
