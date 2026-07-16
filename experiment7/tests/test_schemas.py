"""Tests for Pydantic schemas — validation and serialization."""

import pytest
from src.schemas import (
    ReviewRequest, ReviewResponse, ReviewComment, SourceInfo, ContentBlock,
    FileEntry, ReviewOptions, SourceKind, Severity, MergePrediction,
    Confidence, ModelInfo, ModelStatus, InputSummary, TimingInfo,
    HealthResponse, HistoryEntry, HistoryListResponse, ErrorResponse, ErrorDetail,
)


class TestReviewRequest:
    def test_valid_file_request(self):
        req = ReviewRequest(
            request_id="test-001",
            model_id="rule-based",
            source=SourceInfo(kind=SourceKind.file, files=["test.py"]),
            content=ContentBlock(
                files=[FileEntry(path="test.py", language="python", content="print('hi')")]
            ),
        )
        assert req.request_id == "test-001"
        assert req.source.kind == SourceKind.file

    def test_valid_diff_request(self):
        req = ReviewRequest(
            request_id="test-002",
            model_id="rule-based",
            source=SourceInfo(kind=SourceKind.git_diff, repo_path="/tmp/repo"),
            content=ContentBlock(diff="diff --git a/test.py b/test.py\n+print('hi')"),
        )
        assert req.content.diff is not None

    def test_file_request_without_content_raises(self):
        with pytest.raises(ValueError, match="kind=file requires"):
            ReviewRequest(
                source=SourceInfo(kind=SourceKind.file),
                content=ContentBlock(files=[]),
            )

    def test_diff_request_without_diff_raises(self):
        with pytest.raises(ValueError, match="kind=git_diff requires"):
            ReviewRequest(
                source=SourceInfo(kind=SourceKind.git_diff),
                content=ContentBlock(diff=None),
            )

    def test_default_request_id(self):
        req = ReviewRequest(
            source=SourceInfo(kind=SourceKind.git_diff),
            content=ContentBlock(diff="test"),
        )
        assert len(req.request_id) == 12


class TestReviewComment:
    def test_valid_comment(self):
        c = ReviewComment(file="test.py", line=42, severity=Severity.major, comment="Fix this")
        assert c.line == 42

    def test_null_line_ok(self):
        c = ReviewComment(file="test.py", line=None, severity=Severity.minor, comment="ok")
        assert c.line is None

    def test_negative_line_raises(self):
        with pytest.raises(ValueError):
            ReviewComment(file="test.py", line=-1, severity=Severity.nit, comment="bad")


class TestReviewResponse:
    def test_minimal_response(self):
        resp = ReviewResponse(
            request_id="r1",
            model=ModelInfo(id="rule-based", kind="rules"),
            merge_prediction=MergePrediction.merged,
            merge_probability=0.85,
            confidence=Confidence.high,
            risk_level="low",
            input_summary=InputSummary(changed_files=1, additions=5, deletions=2, content_sha256="abc"),
            timing=TimingInfo(extract_ms=1.0, model_ms=2.0, total_ms=3.0),
            history_id="20260710T120000-abc123",
        )
        assert resp.merge_probability == 0.85

    def test_probability_clamped(self):
        """merge_probability must be in [0, 1] — 1.5 should be rejected."""
        with pytest.raises(Exception):
            ReviewResponse(
                request_id="r2",
                model=ModelInfo(id="rb", kind="rules"),
                merge_prediction=MergePrediction.not_merged,
                merge_probability=1.5,
                confidence=Confidence.medium,
                risk_level="medium",
                input_summary=InputSummary(),
                timing=TimingInfo(),
                history_id="h",
            )

    def test_probability_out_of_range_raises(self):
        with pytest.raises(Exception):  # ValidationError
            ReviewResponse(
                request_id="r3",
                model=ModelInfo(id="rb", kind="rules"),
                merge_prediction=MergePrediction.merged,
                merge_probability=1.5,  # > 1.0
                confidence=Confidence.low,
                risk_level="low",
                input_summary=InputSummary(),
                timing=TimingInfo(),
                history_id="h",
            )


class TestHealthResponse:
    def test_defaults(self):
        h = HealthResponse()
        assert h.status == "healthy"
        assert h.version == "0.1.0"
        assert len(h.started_at) > 0


class TestSerialization:
    def test_review_response_json_roundtrip(self):
        resp = ReviewResponse(
            request_id="r1",
            model=ModelInfo(id="rule-based", kind="rules"),
            merge_prediction=MergePrediction.merged,
            merge_probability=0.75,
            confidence=Confidence.medium,
            risk_level="low",
            risk_factors=["missing-test"],
            review_comments=[
                ReviewComment(file="a.py", line=10, severity=Severity.major, comment="fix", rule_id="r1")
            ],
            input_summary=InputSummary(changed_files=2, additions=10, deletions=3, content_sha256="ab12"),
            timing=TimingInfo(extract_ms=5.0, model_ms=15.0, total_ms=21.0),
            history_id="20260710T120000-abc123",
        )
        data = resp.model_dump()
        assert data["merge_probability"] == 0.75
        assert data["review_comments"][0]["severity"] == "major"

        # Round-trip
        resp2 = ReviewResponse(**data)
        assert resp2.merge_probability == 0.75
