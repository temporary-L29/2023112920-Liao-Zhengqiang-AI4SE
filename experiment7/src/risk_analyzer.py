"""
Offline rule-based risk analyzer.

This is the required fallback model.  It inspects file/diff content
and paths against a set of heuristics, and produces a structured
review result WITHOUT any external API call or ML model.

Key rules:
  - missing-test      — code changed without corresponding test changes
  - large-change      — too many files or lines changed at once
  - config-or-dep     — configuration or dependency files modified
  - public-api-change — function/class signature changes in public modules
  - todo-or-placeholder — TODO/FIXME/HACK left in code
  - debug-print       — debug prints (console.log, print(), etc.)

Risk score → merge_probability conversion:
  Each rule contributes a weighted risk penalty.  The risk score R is
  the sum of triggered rule weights, capped at 1.0.  merge_probability
  = max(0.05, 1.0 - R).  This is a HEURISTIC — not a statistical
  estimate — and must not be compared against experiment 5/6 metrics.
"""

from __future__ import annotations

import re
from typing import List, Tuple, Optional

from src.schemas import (
    ReviewComment,
    Severity,
    MergePrediction,
    Confidence,
)


# ═══════════════════════════════════════════════════════════════
# Rule definitions  (id, weight, severity, message template)
# ═══════════════════════════════════════════════════════════════

class Rule:
    __slots__ = ("rule_id", "weight", "severity", "message")

    def __init__(self, rule_id: str, weight: float, severity: Severity, message: str):
        self.rule_id = rule_id
        self.weight = weight
        self.severity = severity
        self.message = message


RULES: List[Rule] = [
    Rule(
        "missing-test", 0.25, Severity.major,
        "Changed code files without corresponding test changes. "
        "Please add or update tests for the modified behaviour."
    ),
    Rule(
        "large-change", 0.20, Severity.major,
        "This change touches {file_count} files with +{additions}/-{deletions} lines. "
        "Consider splitting into smaller, focused PRs."
    ),
    Rule(
        "config-or-dependency-change", 0.15, Severity.major,
        "Configuration or dependency file modified: {files}. "
        "Ensure this change is intentional and reviewed for side effects."
    ),
    Rule(
        "public-api-change", 0.20, Severity.blocker,
        "Public API signature changed in {files}. "
        "Breaking changes require documentation, migration notes, and approval."
    ),
    Rule(
        "todo-or-placeholder", 0.10, Severity.minor,
        "TODO/FIXME/HACK markers found. "
        "Resolve or track these before merging."
    ),
    Rule(
        "debug-print", 0.10, Severity.minor,
        "Debug output (e.g. print(), console.log) found in production paths. "
        "Replace with proper logging or remove."
    ),
]

# Sum of all rule weights = 1.0
_RULE_WEIGHT_SUM = sum(r.weight for r in RULES)


# ═══════════════════════════════════════════════════════════════
# Detection helpers
# ═══════════════════════════════════════════════════════════════

_CONFIG_PATTERNS = [
    r'\.json$', r'\.ya?ml$', r'\.toml$', r'\.ini$', r'\.cfg$',
    r'\.env', r'Dockerfile', r'docker-compose',
    r'requirements.*\.txt$', r'package\.json$', r'Cargo\.toml$',
    r'go\.mod$', r'go\.sum$', r'Gemfile$', r'pom\.xml$',
    r'build\.gradle', r'CMakeLists\.txt$', r'Makefile$',
    r'\.eslintrc', r'\.prettierrc', r'tsconfig\.json$',
]
_CONFIG_RE = re.compile("|".join(_CONFIG_PATTERNS), re.IGNORECASE)

_TEST_PATTERNS = [
    r'test_', r'_test\.', r'tests?/', r'__tests__/', r'spec\.',
    r'\.test\.', r'\.spec\.', r'/test/', r'/tests/',
]
_TEST_RE = re.compile("|".join(_TEST_PATTERNS), re.IGNORECASE)

# Public API changes — function/class def at module level (Python)
_PUBLIC_API_RE = re.compile(
    r'^[+-]\s*(def |class |async def |export |pub fn |pub struct |public )',
    re.MULTILINE,
)

_TODO_RE = re.compile(r'\b(TODO|FIXME|HACK|XXX|WORKAROUND)\b', re.IGNORECASE)

_DEBUG_PRINT_RE = re.compile(
    r'\b(print|console\.log|console\.warn|console\.error|console\.debug'
    r'|System\.out\.println|fmt\.Println|log\.Println'
    r'|println!|dbg!|dump\()',
)


def _is_test_file(path: str) -> bool:
    return bool(_TEST_RE.search(path))


def _is_config_file(path: str) -> bool:
    return bool(_CONFIG_RE.search(path))


# ═══════════════════════════════════════════════════════════════
# Main analysis entry point
# ═══════════════════════════════════════════════════════════════

def analyze(
    files: List[dict],
    diff_text: Optional[str] = None,
) -> dict:
    """
    Run all rules and return a result dictionary with:

        merge_prediction, merge_probability, confidence,
        risk_level, risk_factors, review_comments
    """
    triggered: List[Tuple[Rule, Optional[str], Optional[int]]] = []

    # Collect paths and contents for pattern matching
    file_paths = [f.get("path", "") for f in files]
    code_files = [f for f in files if not _is_test_file(f.get("path", ""))]
    test_files = [f for f in files if _is_test_file(f.get("path", ""))]

    all_content = "\n".join(
        (f.get("content") or "") for f in files
    )
    diff_content = diff_text or ""
    combined = all_content + "\n" + diff_content

    additions, deletions = 0, 0
    if diff_text:
        additions, deletions = _count_diff_stats(diff_text)

    # ── Rule: missing-test ────────────────────────────────────
    if code_files and not test_files:
        triggered.append((RULES[0], None, None))

    # ── Rule: large-change ────────────────────────────────────
    file_count = len(file_paths)
    total_churn = additions + deletions
    if file_count > 5 or total_churn > 200:
        triggered.append((
            RULES[1],
            RULES[1].message.format(
                file_count=file_count, additions=additions, deletions=deletions
            ),
            None,
        ))

    # ── Rule: config-or-dependency-change ──────────────────────
    config_files = [p for p in file_paths if _is_config_file(p)]
    if config_files and len(config_files) <= len(file_paths) * 0.7:
        # Only flag if not ALL files are config (could be a config-only repo)
        triggered.append((
            RULES[2],
            RULES[2].message.format(files=", ".join(config_files[:5])),
            None,
        ))

    # ── Rule: public-api-change ────────────────────────────────
    api_hits = _PUBLIC_API_RE.findall(diff_content)
    if api_hits:
        # Determine which files have API changes
        api_files = set()
        for fpath in file_paths:
            if any(
                re.search(r'^[+-]\s*(def |class |async def )', line)
                for line in diff_content.splitlines()
            ):
                api_files.add(fpath)
        triggered.append((
            RULES[3],
            RULES[3].message.format(
                files=", ".join(sorted(api_files)[:5]) or "modified files"
            ),
            None,
        ))

    # ── Rule: todo-or-placeholder ──────────────────────────────
    todo_matches = list(_TODO_RE.finditer(combined))
    if todo_matches:
        # Find line numbers in the file content
        for f in files:
            fpath = f.get("path", "")
            fcontent = f.get("content") or ""
            for i, line in enumerate(fcontent.splitlines(), start=1):
                if _TODO_RE.search(line):
                    triggered.append((
                        RULES[4],
                        RULES[4].message,
                        i,
                    ))
                    break  # one comment per file

    # ── Rule: debug-print ─────────────────────────────────────
    debug_matches = list(_DEBUG_PRINT_RE.finditer(combined))
    if debug_matches:
        for f in files:
            fpath = f.get("path", "")
            fcontent = f.get("content") or ""
            for i, line in enumerate(fcontent.splitlines(), start=1):
                if _DEBUG_PRINT_RE.search(line):
                    triggered.append((
                        RULES[5],
                        RULES[5].message,
                        i,
                    ))
                    break

    # ── Compute scores ─────────────────────────────────────────
    risk_score = min(1.0, sum(r.weight for r, _, _ in triggered))
    merge_prob = max(0.05, round(1.0 - risk_score, 4))

    if risk_score >= 0.6:
        risk_level = "high"
    elif risk_score >= 0.3:
        risk_level = "medium"
    else:
        risk_level = "low"

    prediction = MergePrediction.not_merged if risk_score >= 0.4 else MergePrediction.merged

    if risk_score >= 0.5:
        confidence = Confidence.high
    elif risk_score >= 0.25:
        confidence = Confidence.medium
    else:
        confidence = Confidence.low

    risk_factors = [
        r.rule_id for r, _, _ in triggered
    ]

    review_comments = []
    seen_files = set()
    for rule, msg, line in triggered:
        # Use the first file path available for the comment
        fpath = "general"
        comment_line = line
        for f in files:
            fp = f.get("path", "")
            if fp and fp not in seen_files:
                fpath = fp
                break
        if fpath == "general" and file_paths:
            fpath = file_paths[0]

        review_comments.append(ReviewComment(
            file=fpath,
            line=comment_line,
            severity=rule.severity,
            comment=msg or rule.message,
            rule_id=rule.rule_id,
        ))

    return {
        "merge_prediction": prediction,
        "merge_probability": merge_prob,
        "confidence": confidence,
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "review_comments": review_comments,
    }


def _count_diff_stats(diff_text: str) -> Tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions
