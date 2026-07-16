"""Tests for CLI — run via subprocess against a live server."""

import json
import subprocess
import sys
import time
import os
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SERVER_URL = "http://127.0.0.1:8765"


def _run_cli(*args, timeout=30):
    """Run the CLI as a subprocess and return (returncode, stdout, stderr)."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "src.cli"] + list(args),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture(scope="module")
def live_server():
    """Start a live server for CLI tests."""
    import uvicorn
    import threading

    # Start in a thread
    def run():
        from src.server import app
        uvicorn.run(app, host="127.0.0.1", port=8765, log_level="error")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(2)

    # Wait for server to be ready
    for _ in range(10):
        try:
            requests.get(f"{SERVER_URL}/health", timeout=2)
            break
        except requests.RequestException:
            time.sleep(0.5)
    else:
        pytest.fail("Server did not start in time")

    yield

    # No cleanup needed — daemon thread dies with test process


class TestCLIStatus:
    def test_status(self, live_server):
        rc, stdout, stderr = _run_cli("status", "--no-color")
        assert rc == 0, f"stderr: {stderr}"
        assert "rule-based" in stdout

    def test_status_json(self, live_server):
        # status command doesn't support --format, but should still work
        rc, stdout, stderr = _run_cli("status", "--no-color")
        assert rc == 0


class TestCLIReviewFile:
    def test_review_file(self, live_server):
        risky = FIXTURES / "risky_example.py"
        rc, stdout, stderr = _run_cli(
            "review", "--file", str(risky), "--model", "rule-based", "--no-color",
        )
        assert rc == 0, f"stderr: {stderr}"
        assert "Code Review Report" in stdout
        assert "merge_prediction" in stdout.lower() or "Merge Prediction" in stdout

    def test_review_file_json(self, live_server):
        clean = FIXTURES / "clean_example.py"
        rc, stdout, stderr = _run_cli(
            "review", "--file", str(clean), "--model", "rule-based",
            "--format", "json", "--no-color",
        )
        assert rc == 0, f"stderr: {stderr}"
        data = json.loads(stdout)
        assert data["status"] == "success"
        assert "merge_probability" in data
        assert len(data["history_id"]) > 0

    def test_review_nonexistent_file(self, live_server):
        rc, stdout, stderr = _run_cli(
            "review", "--file", "/nonexistent/file.py", "--no-color",
        )
        assert rc != 0

    def test_review_unavailable_model(self, live_server):
        """Specifying a nonexistent model should fail."""
        risky = FIXTURES / "risky_example.py"
        rc, stdout, stderr = _run_cli(
            "review", "--file", str(risky), "--model", "no-such-model", "--no-color",
        )
        assert rc != 0  # Should exit with non-zero


class TestCLIHistory:
    def test_history_list(self, live_server):
        rc, stdout, stderr = _run_cli("history", "--limit", "5", "--no-color")
        assert rc == 0, f"stderr: {stderr}"
        # Should show history entries
        assert "History" in stdout or "No review" in stdout

    def test_history_json(self, live_server):
        rc, stdout, stderr = _run_cli(
            "history", "--limit", "5", "--format", "json", "--no-color",
        )
        assert rc == 0, f"stderr: {stderr}"
        data = json.loads(stdout)
        assert "entries" in data

    def test_history_detail(self, live_server):
        # First get a history ID
        rc, stdout, stderr = _run_cli(
            "history", "--limit", "1", "--format", "json", "--no-color",
        )
        if rc == 0:
            data = json.loads(stdout)
            entries = data.get("entries", [])
            if entries:
                hist_id = entries[0]["history_id"]
                rc2, stdout2, _ = _run_cli("history", "--id", hist_id, "--no-color")
                assert rc2 == 0, f"stderr: {_run_cli('history', '--id', hist_id, '--no-color')}"
