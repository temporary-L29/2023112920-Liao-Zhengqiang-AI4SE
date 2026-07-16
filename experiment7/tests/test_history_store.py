"""Tests for history store — append and read."""

import json
import tempfile
from pathlib import Path

import pytest

# Use a temporary history file for tests
import src.config as config_module


@pytest.fixture(autouse=True)
def temp_history(monkeypatch, tmp_path):
    """Redirect history to a temp file."""
    hist_file = tmp_path / "reviews.jsonl"
    monkeypatch.setattr(config_module, "HISTORY_FILE", hist_file)
    # Ensure history_store imports see the patched value
    import src.history_store as hs
    monkeypatch.setattr(hs, "HISTORY_FILE", hist_file)
    yield hist_file


class TestHistoryStore:
    def test_append_and_list(self):
        from src.history_store import append, list_entries

        append({
            "history_id": "20260710T120000-abc001",
            "timestamp": "20260710T120000",
            "request_id": "req-1",
            "model_id": "rule-based",
            "status": "success",
            "source_kind": "file",
            "merge_prediction": "merged",
            "risk_level": "low",
            "changed_files": 1,
            "additions": 5,
            "deletions": 2,
            "total_ms": 25.0,
        })

        result = list_entries(limit=10)
        assert result.total == 1
        assert len(result.entries) == 1
        assert result.entries[0].model_id == "rule-based"
        assert result.entries[0].merge_prediction == "merged"

    def test_append_and_get_detail(self):
        from src.history_store import append, get_detail

        rec = {
            "history_id": "20260710T130000-def002",
            "timestamp": "20260710T130000",
            "request_id": "req-2",
            "model_id": "exp6-llm",
            "status": "success",
            "source_kind": "git_diff",
            "merge_prediction": "not_merged",
            "risk_level": "high",
            "changed_files": 3,
            "additions": 50,
            "deletions": 10,
            "total_ms": 120.0,
            "review_comments": [
                {"file": "a.py", "line": 10, "severity": "major", "comment": "fix"}
            ],
        }
        append(rec)

        detail = get_detail("20260710T130000-def002")
        assert detail is not None
        assert detail["model_id"] == "exp6-llm"
        assert len(detail["review_comments"]) == 1

    def test_get_nonexistent_detail(self):
        from src.history_store import get_detail
        assert get_detail("nonexistent-id") is None

    def test_multiple_entries_order(self):
        from src.history_store import append, list_entries

        for i in range(5):
            append({
                "history_id": f"id-{i:03d}",
                "timestamp": f"20260710T1200{i:02d}",
                "request_id": f"req-{i}",
                "model_id": "rule-based",
                "status": "success",
                "source_kind": "file",
                "merge_prediction": "merged",
                "risk_level": "low",
                "changed_files": 1,
                "additions": i,
                "deletions": 0,
                "total_ms": 10.0,
            })

        result = list_entries(limit=3)
        assert len(result.entries) == 3
        # Most recent first
        assert result.entries[0].history_id == "id-004"

    def test_malformed_lines_skipped(self, tmp_path):
        """Malformed JSON lines should be skipped gracefully."""
        from src.history_store import append, list_entries

        # Write malformed data directly
        hist_file = tmp_path / "reviews.jsonl"
        hist_file.write_text(
            '{"history_id": "good", "timestamp": "t", "request_id": "r", '
            '"model_id": "m", "status": "s", "source_kind": "f", '
            '"merge_prediction": "merged", "risk_level": "l", '
            '"changed_files": 1, "additions": 0, "deletions": 0, "total_ms": 1}\n'
            'this is not json\n'
            '{"history_id": "good2", "timestamp": "t2", "request_id": "r2", '
            '"model_id": "m", "status": "s", "source_kind": "f", '
            '"merge_prediction": "not_merged", "risk_level": "h", '
            '"changed_files": 2, "additions": 5, "deletions": 3, "total_ms": 2}\n',
            encoding="utf-8",
        )
        import src.history_store as hs
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(hs, "HISTORY_FILE", hist_file)

        result = hs.list_entries(limit=10)
        assert result.total == 2  # malformed line skipped
