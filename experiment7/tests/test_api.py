"""Tests for the FastAPI server using TestClient."""

import pytest
from fastapi.testclient import TestClient

from src.server import app
from src.schemas import SourceKind

client = TestClient(app)


class TestHealth:
    def test_health_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert len(data["models"]) >= 1

    def test_models_endpoint(self):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        model_ids = [m["id"] for m in data["models"]]
        assert "rule-based" in model_ids


class TestReviews:
    def test_file_review_rule_based(self):
        payload = {
            "request_id": "test-file-001",
            "model_id": "rule-based",
            "source": {
                "kind": "file",
                "files": ["test.py"],
            },
            "content": {
                "diff": None,
                "files": [{
                    "path": "test.py",
                    "language": "python",
                    "content": "def foo():\n    print('hello')\n    return 1",
                }],
            },
            "options": {"max_chars": 24000, "store_source": False},
        }
        resp = client.post("/v1/reviews", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["model"]["id"] == "rule-based"
        assert data["merge_prediction"] in ("merged", "not_merged")
        assert 0.0 <= data["merge_probability"] <= 1.0
        assert len(data["history_id"]) > 0
        assert data["timing"]["total_ms"] >= 0

    def test_diff_review_rule_based(self):
        payload = {
            "request_id": "test-diff-001",
            "model_id": "rule-based",
            "source": {
                "kind": "git_diff",
                "repo_path": "/tmp/test",
            },
            "content": {
                "diff": "diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n@@ -1,0 +1,10 @@\n+def new_feature():\n+    # TODO: implement\n+    print('debug')\n+    pass",
                "files": [{"path": "main.py", "language": "python"}],
            },
            "options": {"max_chars": 24000, "store_source": False},
        }
        resp = client.post("/v1/reviews", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_file_review_without_content(self):
        payload = {
            "request_id": "bad-1",
            "model_id": "rule-based",
            "source": {"kind": "file", "files": ["test.py"]},
            "content": {"files": []},
        }
        resp = client.post("/v1/reviews", json=payload)
        assert resp.status_code in (400, 422)  # Pydantic validation → 422

    def test_diff_review_without_diff(self):
        payload = {
            "request_id": "bad-2",
            "model_id": "rule-based",
            "source": {"kind": "git_diff", "repo_path": "/tmp"},
            "content": {"diff": None},
        }
        resp = client.post("/v1/reviews", json=payload)
        assert resp.status_code in (400, 422)  # Pydantic validation → 422

    def test_unknown_model(self):
        payload = {
            "request_id": "bad-3",
            "model_id": "nonexistent-model",
            "source": {"kind": "git_diff"},
            "content": {"diff": "some diff"},
        }
        resp = client.post("/v1/reviews", json=payload)
        assert resp.status_code == 400

    def test_unavailable_llm_model(self, monkeypatch):
        """exp6-llm should be unavailable without API key."""
        # Ensure no key is set for this test
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        # Force the module-level cache to re-read
        import src.adapters.exp6_llm as llm_mod
        monkeypatch.setattr(llm_mod, "_get_api_key", lambda: "")

        payload = {
            "request_id": "test-llm-1",
            "model_id": "exp6-llm",
            "source": {"kind": "git_diff"},
            "content": {"diff": "some diff"},
        }
        resp = client.post("/v1/reviews", json=payload)
        assert resp.status_code in (400, 500)


class TestHistory:
    def test_list_history(self):
        # First create a review to populate history
        payload = {
            "request_id": "hist-test-1",
            "model_id": "rule-based",
            "source": {"kind": "file", "files": ["x.py"]},
            "content": {
                "files": [{"path": "x.py", "language": "python", "content": "x=1"}],
            },
        }
        client.post("/v1/reviews", json=payload)

        resp = client.get("/v1/history?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_get_history_detail(self):
        # Create a review
        payload = {
            "request_id": "hist-detail-1",
            "model_id": "rule-based",
            "source": {"kind": "file", "files": ["y.py"]},
            "content": {
                "files": [{"path": "y.py", "language": "python", "content": "y=2"}],
            },
        }
        resp = client.post("/v1/reviews", json=payload)
        history_id = resp.json()["history_id"]

        resp2 = client.get(f"/v1/history/{history_id}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["history_id"] == history_id

    def test_history_not_found(self):
        resp = client.get("/v1/history/nonexistent-id-12345")
        assert resp.status_code == 404
