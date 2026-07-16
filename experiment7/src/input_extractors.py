"""
Input extractors — read file content or Git diff for review.

Supports:
  - Single-file UTF-8 read with safety checks
  - Git working-tree / staged diff via subprocess
  - Unified-diff parsing to locate changed files and new line numbers
"""

from __future__ import annotations

import hashlib
import subprocess
import re
from pathlib import Path
from typing import List, Optional, Tuple

from src.config import MAX_CONTENT_CHARS, MAX_FILE_COUNT, GIT_DIFF_CONTEXT_LINES, logger
from src.schemas import FileEntry, SourceInfo, ContentBlock


# ═══════════════════════════════════════════════════════════════
# File extraction
# ═══════════════════════════════════════════════════════════════

def _guess_language(path: str) -> Optional[str]:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "javascript", ".tsx": "typescript", ".go": "go",
        ".rs": "rust", ".java": "java", ".c": "c", ".cpp": "cpp",
        ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby",
        ".php": "php", ".swift": "swift", ".kt": "kotlin",
        ".scala": "scala", ".sql": "sql", ".sh": "shell",
        ".yaml": "yaml", ".yml": "yaml", ".json": "json",
        ".xml": "xml", ".toml": "toml", ".md": "markdown",
        ".css": "css", ".html": "html", ".vue": "vue",
    }
    suffix = Path(path).suffix.lower()
    return ext_map.get(suffix)


def _is_text_file(path: Path) -> bool:
    """Heuristic: check first 1024 bytes for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
        return b"\x00" not in chunk
    except OSError:
        return False


def extract_file(file_path: str, max_chars: int = MAX_CONTENT_CHARS) -> ContentBlock:
    """
    Read a single UTF-8 source file.

    Raises ValueError for binary files, decode errors, or empty content.
    """
    path = Path(file_path).resolve()

    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    if path.stat().st_size == 0:
        raise ValueError(f"File is empty: {file_path}")

    if path.stat().st_size > max_chars * 2:
        raise ValueError(
            f"File too large: {path.stat().st_size} bytes "
            f"(max ~{max_chars * 2} bytes)"
        )

    if not _is_text_file(path):
        raise ValueError(f"File appears to be binary: {file_path}")

    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"UTF-8 decode failed for {file_path}: {e}")

    if not raw.strip():
        raise ValueError(f"File has no meaningful content: {file_path}")

    if len(raw) > max_chars:
        truncated_len = len(raw)
        raw = raw[:max_chars]
        logger.info(f"Content truncated from {truncated_len} to {max_chars} chars")

    lang = _guess_language(file_path)

    return ContentBlock(
        diff=None,
        files=[FileEntry(
            path=str(path),
            language=lang,
            content=raw,
        )],
    )


# ═══════════════════════════════════════════════════════════════
# Git diff extraction
# ═══════════════════════════════════════════════════════════════

def _run_git(repo_path: str, args: List[str], timeout: int = 15) -> str:
    """Run a git command and return stdout, raising on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise ValueError("Git is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise ValueError(f"Git command timed out after {timeout}s")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise ValueError(f"Git error: {stderr or 'exit code ' + str(result.returncode)}")

    return result.stdout


def extract_git_diff(
    repo_path: str,
    staged: bool = False,
    max_chars: int = MAX_CONTENT_CHARS,
) -> ContentBlock:
    """
    Get the working-tree (or staged) diff from a Git repository.

    Raises ValueError if the directory is not a Git repo, or if there
    are no changes.
    """
    rp = Path(repo_path).resolve()
    if not (rp / ".git").exists():
        raise ValueError(f"Not a Git repository: {repo_path}")

    # Verify it's a valid git repo
    try:
        _run_git(str(rp), ["rev-parse", "--git-dir"])
    except ValueError:
        raise ValueError(f"Not a valid Git repository: {repo_path}")

    diff_args = ["diff", "--no-ext-diff", f"--unified={GIT_DIFF_CONTEXT_LINES}"]
    if staged:
        diff_args.append("--cached")

    diff_text = _run_git(str(rp), diff_args)

    if not diff_text.strip():
        staged_label = "staged " if staged else ""
        raise ValueError(
            f"No {staged_label}changes in working tree. "
            f"Make some changes or use --staged to review staged changes."
        )

    original_len = len(diff_text)
    if original_len > max_chars:
        diff_text = diff_text[:max_chars]
        logger.info(f"Diff truncated from {original_len} to {max_chars} chars")

    files = _parse_diff_files(diff_text)

    return ContentBlock(
        diff=diff_text,
        files=files,
    )


# ═══════════════════════════════════════════════════════════════
# Diff parsing utilities
# ═══════════════════════════════════════════════════════════════

_DIFF_FILE_RE = re.compile(r'^\+\+\+ b/(.+)$', re.MULTILINE)
_HUNK_HEADER_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', re.MULTILINE)


def _parse_diff_files(diff_text: str) -> List[FileEntry]:
    """Extract file paths from a unified diff."""
    files = []
    for m in _DIFF_FILE_RE.finditer(diff_text):
        fpath = m.group(1)
        if fpath and fpath != "/dev/null":
            files.append(FileEntry(
                path=fpath,
                language=_guess_language(fpath),
            ))
    return files


def parse_diff_new_lines(diff_text: str, target_file: str) -> List[int]:
    """
    Map a unified-diff hunk to *new-file* line numbers for a target file.

    Returns the first line number of each addition hunk.  Returns an
    empty list when the mapping is unreliable (e.g. new-file mode).
    """
    # Split into per-file sections
    sections = re.split(r'^diff --git ', diff_text, flags=re.MULTILINE)
    for section in sections:
        if not section.strip():
            continue
        # Prepend the marker we split on for the regex to work
        section = "diff --git " + section if not section.startswith("diff --git") else section

        file_m = re.search(r'^\+\+\+ b/(.+)$', section, re.MULTILINE)
        if not file_m:
            continue
        if file_m.group(1) != target_file:
            continue

        lines: List[int] = []
        for hunk_m in _HUNK_HEADER_RE.finditer(section):
            start = int(hunk_m.group(1))
            lines.append(start)
        return lines

    return []


def compute_change_stats(diff_text: str) -> Tuple[int, int]:
    """Count total additions (+) and deletions (-) in a unified diff."""
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions


def compute_content_sha256(content: str) -> str:
    """SHA-256 hex digest of content for integrity tracking."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def build_source_info(
    kind: str,
    repo_path: Optional[str] = None,
    staged: bool = False,
    files: Optional[List[str]] = None,
) -> SourceInfo:
    """Build a SourceInfo from extraction parameters."""
    from src.schemas import SourceKind
    return SourceInfo(
        kind=SourceKind(kind),
        repo_path=repo_path,
        staged=staged,
        files=files or [],
    )
