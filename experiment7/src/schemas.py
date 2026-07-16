"""
Pydantic schemas — the single source of truth for the HTTP protocol.

Every request/response flowing between CLI and server MUST validate
against these models.  No other module may duplicate these definitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class SourceKind(str, Enum):
    file = "file"
    git_diff = "git_diff"


class Severity(str, Enum):
    nit = "nit"
    minor = "minor"
    major = "major"
    blocker = "blocker"


class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class MergePrediction(str, Enum):
    merged = "merged"
    not_merged = "not_merged"


class ModelStatus(str, Enum):
    ready = "ready"
    unavailable = "unavailable"
    incompatible = "incompatible"


# ═══════════════════════════════════════════════════════════════
# Request
# ═══════════════════════════════════════════════════════════════

class SourceInfo(BaseModel):
    """Describes where the code under review came from."""
    kind: SourceKind
    repo_path: Optional[str] = None
    base_ref: str = "HEAD"
    staged: bool = False
    files: List[str] = Field(default_factory=list)


class FileEntry(BaseModel):
    """A single file in the review content."""
    path: str
    language: Optional[str] = None
    content: Optional[str] = None


class ContentBlock(BaseModel):
    """The code content to review."""
    diff: Optional[str] = None
    files: List[FileEntry] = Field(default_factory=list)


class ReviewOptions(BaseModel):
    max_chars: int = Field(default=24000, ge=1, le=100000)
    store_source: bool = False


class ReviewRequest(BaseModel):
    """POST /v1/reviews request body."""
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    model_id: str = "rule-based"
    source: SourceInfo
    content: ContentBlock
    options: ReviewOptions = Field(default_factory=ReviewOptions)

    @model_validator(mode="after")
    def validate_content(self) -> "ReviewRequest":
        if self.source.kind == SourceKind.file:
            if not self.content.files or all(
                f.content is None for f in self.content.files
            ):
                raise ValueError("kind=file requires at least one file with content")
        elif self.source.kind == SourceKind.git_diff:
            if not self.content.diff:
                raise ValueError("kind=git_diff requires non-empty diff")
        return self


# ═══════════════════════════════════════════════════════════════
# Response
# ═══════════════════════════════════════════════════════════════

class ModelInfo(BaseModel):
    id: str
    kind: str
    version: str = "1"
    status: ModelStatus = ModelStatus.ready
    reason: str = ""


class ReviewComment(BaseModel):
    file: str
    line: Optional[int] = None
    severity: Severity
    comment: str
    rule_id: Optional[str] = None

    @field_validator("line")
    @classmethod
    def line_must_be_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("line must be positive or null")
        return v


class InputSummary(BaseModel):
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0
    content_sha256: str = ""


class TimingInfo(BaseModel):
    extract_ms: float = 0.0
    model_ms: float = 0.0
    total_ms: float = 0.0


class ReviewResponse(BaseModel):
    """Successful POST /v1/reviews response."""
    request_id: str
    status: str = "success"
    model: ModelInfo
    merge_prediction: MergePrediction
    merge_probability: float = Field(ge=0.0, le=1.0)
    confidence: Confidence
    risk_level: str = "low"          # low | medium | high
    risk_factors: List[str] = Field(default_factory=list)
    review_comments: List[ReviewComment] = Field(default_factory=list)
    input_summary: InputSummary
    timing: TimingInfo
    history_id: str = ""


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str = ""
    status: str = "error"
    error: ErrorDetail


# ═══════════════════════════════════════════════════════════════
# Health / Models / History
# ═══════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "0.1.0"
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    models: List[ModelInfo] = Field(default_factory=list)


class HistoryEntry(BaseModel):
    history_id: str
    timestamp: str
    request_id: str
    model_id: str
    status: str
    source_kind: str
    merge_prediction: Optional[str] = None
    risk_level: Optional[str] = None
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0
    total_ms: float = 0.0
    # Full detail fields (populated on detail endpoint only)
    review_comments: Optional[List[ReviewComment]] = None
    risk_factors: Optional[List[str]] = None
    source_code: Optional[str] = None   # only when store_source=True


class HistoryListResponse(BaseModel):
    entries: List[HistoryEntry] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
