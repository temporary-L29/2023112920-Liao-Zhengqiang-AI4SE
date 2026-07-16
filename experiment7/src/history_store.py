"""
History store — atomic JSONL append and read.

Design:
  - Each successful or failed review writes one JSON line.
  - By default, source code is NOT stored (privacy).
  - Uses temp-file + os.replace for atomic appends on the same filesystem.
  - Reads are simple line-by-line scans; for up to a few thousand
    entries this is fast enough without a database.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any

from src.config import HISTORY_FILE, MAX_HISTORY_DEFAULT, logger
from src.schemas import HistoryEntry, HistoryListResponse, ReviewResponse


def _ensure_file() -> None:
    """Create the history file if it doesn't exist."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("", encoding="utf-8")


def append(record: dict) -> None:
    """
    Atomically append a single JSON record to the history file.

    Writes to a temp file in the same directory, then os.replace
    (which is atomic on the same filesystem on Windows and Unix).
    """
    _ensure_file()

    line = json.dumps(record, ensure_ascii=False) + "\n"

    # Read existing content, append, write atomically
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            existing = f.read()
    except OSError:
        existing = ""

    new_content = existing + line

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(HISTORY_FILE.parent),
        prefix=".history_tmp_",
        suffix=".jsonl",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, str(HISTORY_FILE))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def list_entries(limit: int = MAX_HISTORY_DEFAULT) -> HistoryListResponse:
    """Return the most recent history entries (summaries only, no source code)."""
    _ensure_file()

    all_entries: List[dict] = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed history line")
                    continue
    except OSError:
        pass

    # Most recent first
    all_entries.reverse()
    all_entries = all_entries[:limit]

    entries = []
    for rec in all_entries:
        entries.append(HistoryEntry(
            history_id=rec.get("history_id", ""),
            timestamp=rec.get("timestamp", ""),
            request_id=rec.get("request_id", ""),
            model_id=rec.get("model_id", ""),
            status=rec.get("status", "unknown"),
            source_kind=rec.get("source_kind", ""),
            merge_prediction=rec.get("merge_prediction"),
            risk_level=rec.get("risk_level"),
            changed_files=rec.get("changed_files", 0),
            additions=rec.get("additions", 0),
            deletions=rec.get("deletions", 0),
            total_ms=rec.get("total_ms", 0.0),
        ))

    return HistoryListResponse(
        entries=entries,
        total=len(all_entries),
        limit=limit,
    )


def get_detail(history_id: str) -> Optional[dict]:
    """Get full detail for a single history entry."""
    _ensure_file()

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("history_id") == history_id:
                    return rec
    except OSError:
        pass

    return None


def build_record_from_response(
    response: ReviewResponse,
    request: Any,
    store_source: bool = False,
) -> dict:
    """Build a history JSON record from a successful review response."""
    record = {
        "history_id": response.history_id,
        "timestamp": response.history_id[:15],  # YYYYmmDDTHHMMSS
        "request_id": response.request_id,
        "model_id": response.model.id,
        "status": response.status,
        "source_kind": request.source.kind.value,
        "merge_prediction": response.merge_prediction.value,
        "merge_probability": response.merge_probability,
        "confidence": response.confidence.value,
        "risk_level": response.risk_level,
        "risk_factors": response.risk_factors,
        "review_comments": [
            {
                "file": c.file,
                "line": c.line,
                "severity": c.severity.value,
                "comment": c.comment,
                "rule_id": c.rule_id,
            }
            for c in response.review_comments
        ],
        "changed_files": response.input_summary.changed_files,
        "additions": response.input_summary.additions,
        "deletions": response.input_summary.deletions,
        "content_sha256": response.input_summary.content_sha256,
        "extract_ms": response.timing.extract_ms,
        "model_ms": response.timing.model_ms,
        "total_ms": response.timing.total_ms,
    }

    if store_source:
        if request.content.diff:
            record["source_diff"] = request.content.diff[:4000]
        for f in request.content.files[:5]:
            if f.content:
                record.setdefault("source_files", {})[f.path] = f.content[:2000]

    return record


def build_error_record(
    request_id: str,
    model_id: str,
    source_kind: str,
    error_message: str,
    changed_files: int = 0,
    additions: int = 0,
    deletions: int = 0,
    total_ms: float = 0.0,
) -> dict:
    """Build a history record for a failed review."""
    import uuid
    import datetime
    suffix = uuid.uuid4().hex[:6]
    history_id = datetime.datetime.now().strftime(f"%Y%m%dT%H%M%S-{suffix}")

    return {
        "history_id": history_id,
        "timestamp": history_id[:15],
        "request_id": request_id,
        "model_id": model_id,
        "status": "failed",
        "source_kind": source_kind,
        "error": error_message[:500],
        "changed_files": changed_files,
        "additions": additions,
        "deletions": deletions,
        "total_ms": total_ms,
    }
