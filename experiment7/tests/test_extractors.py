"""Tests for input extractors."""

import os
import tempfile
from pathlib import Path

import pytest

from src.input_extractors import (
    extract_file,
    extract_git_diff,
    parse_diff_new_lines,
    compute_change_stats,
    compute_content_sha256,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestExtractFile:
    def test_valid_python_file(self):
        fpath = FIXTURES / "risky_example.py"
        content = extract_file(str(fpath))
        assert len(content.files) == 1
        assert content.files[0].language == "python"
        assert "calculate_risk_score" in (content.files[0].content or "")

    def test_valid_clean_file(self):
        fpath = FIXTURES / "clean_example.py"
        content = extract_file(str(fpath))
        assert content.files[0].language == "python"

    def test_nonexistent_file_raises(self):
        with pytest.raises(ValueError, match="File not found"):
            extract_file(str(FIXTURES / "nonexistent.py"))

    def test_empty_file_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("")
            tmp = f.name
        try:
            with pytest.raises(ValueError, match="empty"):
                extract_file(tmp)
        finally:
            os.unlink(tmp)

    def test_binary_file_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".bin", delete=False
        ) as f:
            f.write(b"\x00\x01\x02\x03")
            tmp = f.name
        try:
            with pytest.raises(ValueError, match="binary"):
                extract_file(tmp)
        finally:
            os.unlink(tmp)

    def test_truncation(self):
        # Create a file that passes the size check (< max_chars*2 = 200)
        # but exceeds the char limit (> 100 chars content)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("# " + "x" * 120)  # 122 bytes, passes 200 byte size limit, > 100 char limit
            tmp = f.name
        try:
            content = extract_file(tmp, max_chars=100)
            assert len(content.files[0].content or "") == 100
        finally:
            os.unlink(tmp)


class TestExtractGitDiff:
    def test_non_git_directory_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(ValueError, match="Not a Git repository"):
                extract_git_diff(tmp)

    def test_clean_working_tree_raises(self):
        # Use a temp git repo with no changes
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmp, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=tmp, capture_output=True,
            )
            # Create an initial commit so there's a HEAD
            (Path(tmp) / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True)

            with pytest.raises(ValueError, match="No .*changes"):
                extract_git_diff(tmp)


class TestParseDiff:
    def test_parse_new_lines(self):
        diff = (
            "diff --git a/test.py b/test.py\n"
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -1,0 +1,5 @@\n"
            "+line 1\n"
            "+line 2\n"
            "+line 3\n"
            "@@ -10,5 +15,7 @@\n"
            " unchanged\n"
            "+new line\n"
            "+another new line"
        )
        lines = parse_diff_new_lines(diff, "test.py")
        assert 1 in lines
        assert 15 in lines

    def test_parse_unknown_file(self):
        diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,0 +1,1 @@\n+x"
        lines = parse_diff_new_lines(diff, "nonexistent.py")
        assert lines == []


class TestChangeStats:
    def test_basic_stats(self):
        diff = "+added line\n-another line\n+more\n regular line\n-deleted"
        adds, dels = compute_change_stats(diff)
        assert adds == 2
        assert dels == 2

    def test_empty_diff(self):
        adds, dels = compute_change_stats("")
        assert adds == 0
        assert dels == 0


class TestSHA256:
    def test_deterministic(self):
        a = compute_content_sha256("hello")
        b = compute_content_sha256("hello")
        assert a == b
        assert len(a) == 64

    def test_different(self):
        a = compute_content_sha256("hello")
        b = compute_content_sha256("world")
        assert a != b
