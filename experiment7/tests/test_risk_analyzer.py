"""Tests for the rule-based risk analyzer."""

from pathlib import Path
import pytest

from src.risk_analyzer import analyze
from src.schemas import MergePrediction


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read_file(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()
    lang = {".py": "python", ".js": "javascript"}.get(ext)
    return {"path": str(path), "language": lang, "content": content}


class TestRiskAnalyzer:
    def test_clean_file_low_risk(self):
        """Clean code should score low risk and predict merged."""
        f = _read_file(FIXTURES / "clean_example.py")
        result = analyze([f])
        assert result["risk_level"] == "low"
        assert result["merge_prediction"] == MergePrediction.merged
        assert result["merge_probability"] > 0.5

    def test_risky_file_high_risk(self):
        """Risky code with TODOs and debug prints should score higher."""
        f = _read_file(FIXTURES / "risky_example.py")
        result = analyze([f])
        # Should have at least some risk factors
        assert len(result["risk_factors"]) > 0
        # TODOs + debug prints should trigger
        assert "todo-or-placeholder" in result["risk_factors"] or \
               "debug-print" in result["risk_factors"]

    def test_missing_test_rule(self):
        """Code files without test files should trigger missing-test."""
        f = _read_file(FIXTURES / "risky_example.py")
        result = analyze([f])
        assert "missing-test" in result["risk_factors"]
        assert any(
            c.rule_id == "missing-test" for c in result["review_comments"]
        )

    def test_with_test_file(self):
        """Having a test file should prevent missing-test rule."""
        code = _read_file(FIXTURES / "risky_example.py")
        test = {
            "path": "tests/test_risky.py",
            "language": "python",
            "content": "def test_something(): pass",
        }
        result = analyze([code, test])
        assert "missing-test" not in result["risk_factors"]

    def test_large_change_rule(self):
        """Many files or large additions should trigger large-change."""
        files = []
        for i in range(10):
            files.append({
                "path": f"src/module_{i}.py",
                "language": "python",
                "content": "# module\n" + "x = 1\n" * 50,
            })
        result = analyze(files, diff_text="+" + "x\n" * 300)
        assert "large-change" in result["risk_factors"]

    def test_config_change_rule(self):
        """Modifying config files should trigger config-or-dependency-change."""
        files = [
            {"path": "src/main.py", "language": "python", "content": "x=1"},
            {"path": "requirements.txt", "language": None, "content": "numpy==1.0"},
        ]
        result = analyze(files)
        assert "config-or-dependency-change" in result["risk_factors"]

    def test_debug_print_rule(self):
        """Print statements should trigger debug-print."""
        f = {
            "path": "app.py",
            "language": "python",
            "content": "def foo():\n    print('debug')\n    return 1",
        }
        result = analyze([f])
        assert "debug-print" in result["risk_factors"]

    def test_score_range(self):
        """merge_probability must be in [0.05, 1.0]."""
        f = _read_file(FIXTURES / "risky_example.py")
        result = analyze([f])
        assert 0.0 <= result["merge_probability"] <= 1.0
        assert isinstance(result["merge_probability"], float)

    def test_empty_input(self):
        """Empty input should produce low risk."""
        result = analyze([])
        assert result["risk_level"] == "low"
        assert result["merge_probability"] >= 0.9
