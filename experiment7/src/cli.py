"""
CLI — pure HTTP client for the code review service.

Commands:
  serve     Start the FastAPI server
  status    Show service health and model status
  review    Review a file or git diff
  history   List or view review history

All commands communicate with the server exclusively via HTTP.
The CLI never imports server internals.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

# Make sure we can import from the project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import requests

from src.config import SERVER_URL, HOST, PORT

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _safe_print(*args, **kwargs):
    """Print with fallback for GBK/Windows encoding issues."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # Replace special chars with ASCII
        safe_args = [str(a).encode('ascii', errors='replace').decode('ascii') for a in args]
        print(*safe_args, **kwargs)


def _check_server() -> None:
    """Verify the server is reachable; exit with code 3 if not."""
    try:
        r = requests.get(f"{SERVER_URL}/health", timeout=5)
        r.raise_for_status()
    except requests.RequestException:
        print(f"Error: Cannot reach server at {SERVER_URL}", file=sys.stderr)
        print("Start the server first: python -m src.cli serve", file=sys.stderr)
        sys.exit(3)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _format_table(headers: list, rows: list, use_color: bool = True) -> str:
    """Simple terminal table with optional ANSI colors."""
    try:
        from rich.console import Console
        from rich.table import Table
        if use_color:
            console = Console()
            table = Table(*headers)
            for row in rows:
                table.add_row(*[str(c) for c in row])
            console.print(table)
            return ""
        else:
            raise ImportError
    except ImportError:
        # Plain text fallback
        col_widths = [max(len(h), max((len(str(r[i])) for r in rows), default=0)) + 2
                      for i, h in enumerate(headers)]
        sep = "+" + "+".join("-" * w for w in col_widths) + "+"
        lines = [sep]
        lines.append("|" + "|".join(h.center(col_widths[i]) for i, h in enumerate(headers)) + "|")
        lines.append(sep)
        for row in rows:
            lines.append("|" + "|".join(
                str(c).ljust(col_widths[i]) for i, c in enumerate(row)
            ) + "|")
        lines.append(sep)
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════

def cmd_serve():
    """Start the FastAPI server (blocking)."""
    from src.server import run_server
    print(f"Starting code review server on {HOST}:{PORT}")
    print(f"API docs: http://{HOST}:{PORT}/docs")
    print("Press Ctrl+C to stop.")
    run_server()


def cmd_status(args):
    """Print service health and model status."""
    _check_server()

    # Health
    r = requests.get(f"{SERVER_URL}/health", timeout=5)
    health = r.json()
    print(f"Service: {health['status']}")
    print(f"Version: {health['version']}")
    print(f"Started:  {health['started_at']}")
    print()

    # Models
    r = requests.get(f"{SERVER_URL}/v1/models", timeout=5)
    models = r.json()["models"]

    rows = []
    for m in models:
        status_icon = {"ready": "[OK]", "unavailable": "[NO]", "incompatible": "[!!]"}.get(
            m["status"], "?"
        )
        rows.append([
            status_icon,
            m["id"],
            m["kind"],
            m["status"],
            m.get("reason", ""),
        ])

    print(_format_table(
        ["", "Model ID", "Kind", "Status", "Reason"],
        rows,
        use_color=not args.no_color,
    ))


def cmd_review(args):
    """Review a file or git diff."""
    _check_server()

    import uuid

    # Build source info
    if args.repo:
        # Git diff mode
        repo_path = str(Path(args.repo).resolve())
        source = {
            "kind": "git_diff",
            "repo_path": repo_path,
            "base_ref": "HEAD",
            "staged": args.staged,
        }

        diff_args = ["diff", "--no-ext-diff", "--unified=3"]
        if args.staged:
            diff_args.append("--cached")

        try:
            result = subprocess.run(
                ["git"] + diff_args,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                print(f"Error: Git diff failed: {result.stderr}", file=sys.stderr)
                sys.exit(2)
            diff_text = result.stdout
        except FileNotFoundError:
            print("Error: Git is not installed or not on PATH", file=sys.stderr)
            sys.exit(2)
        except subprocess.TimeoutExpired:
            print("Error: Git diff timed out", file=sys.stderr)
            sys.exit(2)

        if not diff_text.strip():
            staged_label = "staged " if args.staged else ""
            print(f"Error: No {staged_label}changes in working tree.", file=sys.stderr)
            sys.exit(2)

        content = {
            "diff": diff_text,
            "files": [],
        }
    elif args.file:
        # Single file mode
        fpath = Path(args.file).resolve()
        if not fpath.exists():
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(2)

        try:
            file_content = fpath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"Error: Cannot read {args.file} as UTF-8 text", file=sys.stderr)
            sys.exit(2)

        if not file_content.strip():
            print(f"Error: File is empty: {args.file}", file=sys.stderr)
            sys.exit(2)

        # Truncate if needed
        if len(file_content) > 24000:
            file_content = file_content[:24000]

        ext = fpath.suffix.lower()
        lang_map = {".py": "python", ".js": "javascript", ".ts": "typescript",
                    ".go": "go", ".rs": "rust", ".java": "java", ".c": "c",
                    ".cpp": "cpp", ".sh": "shell", ".yaml": "yaml", ".json": "json"}
        source = {
            "kind": "file",
            "repo_path": None,
            "base_ref": "HEAD",
            "staged": False,
            "files": [str(fpath)],
        }
        content = {
            "diff": None,
            "files": [{
                "path": str(fpath),
                "language": lang_map.get(ext),
                "content": file_content,
            }],
        }
    else:
        print("Error: Specify --file or --repo", file=sys.stderr)
        sys.exit(2)

    request_id = uuid.uuid4().hex[:12]

    payload = {
        "request_id": request_id,
        "model_id": args.model,
        "source": source,
        "content": content,
        "options": {
            "max_chars": 24000,
            "store_source": args.store_source,
        },
    }

    try:
        r = requests.post(
            f"{SERVER_URL}/v1/reviews",
            json=payload,
            timeout=180,
        )
    except requests.RequestException as e:
        print(f"Error: Request failed: {e}", file=sys.stderr)
        sys.exit(3)

    if r.status_code == 400:
        data = r.json()
        print(f"Error: {data.get('error', {}).get('message', data)}", file=sys.stderr)
        sys.exit(4 if "unavailable" in str(data).lower() or "incompatible" in str(data).lower() else 2)
    elif r.status_code == 500:
        data = r.json()
        print(f"Error: {data.get('error', {}).get('message', data)}", file=sys.stderr)
        sys.exit(5)
    elif r.status_code != 200:
        print(f"Error: HTTP {r.status_code}: {r.text}", file=sys.stderr)
        sys.exit(3)

    result = r.json()

    if args.format == "json":
        _print_json(result)
        return

    # ── Human-readable output ──────────────────────────────────
    print()
    print("=" * 60)
    print(f"  Code Review Report")
    print("=" * 60)
    print(f"  Request ID:       {result['request_id']}")
    print(f"  Model:            {result['model']['id']} ({result['model']['kind']})")
    print(f"  Status:           {result['status']}")
    print()

    # Merge prediction with color
    pred = result["merge_prediction"]
    prob = result["merge_probability"]
    risk = result["risk_level"]
    conf = result["confidence"]

    pred_color = ""
    risk_color = ""
    reset = ""
    if not args.no_color:
        pred_color = "\033[92m" if pred == "merged" else "\033[91m"
        risk_color = {"low": "\033[92m", "medium": "\033[93m", "high": "\033[91m"}.get(risk, "")
        reset = "\033[0m"

    print(f"  Merge Prediction:  {pred_color}{pred}{reset}")
    print(f"  Probability:       {prob:.2%}")
    print(f"  Risk Level:        {risk_color}{risk}{reset}")
    print(f"  Confidence:        {conf}")
    print()

    # Risk factors
    if result.get("risk_factors"):
        print("  Risk Factors:")
        for rf in result["risk_factors"]:
            print(f"    - {rf}")
        print()

    # Review comments
    comments = result.get("review_comments", [])
    if comments:
        print(f"  Review Comments ({len(comments)}):")
        print()

        sev_icons = {"blocker": "!!", "major": "**", "minor": "! ", "nit": " -"}
        rows = []
        for c in comments:
            icon = sev_icons.get(c["severity"], "  ")
            rows.append([
                icon,
                c["severity"].upper(),
                c.get("file", "general"),
                str(c.get("line", "-")),
                c.get("rule_id", ""),
                c["comment"][:100],
            ])

        print(_format_table(
            ["", "Severity", "File", "Line", "Rule", "Comment"],
            rows,
            use_color=not args.no_color,
        ))

    print()
    print(f"  Timing:  extract={result['timing']['extract_ms']:.1f}ms  "
          f"model={result['timing']['model_ms']:.1f}ms  "
          f"total={result['timing']['total_ms']:.1f}ms")
    print(f"  History: {result['history_id']}")
    print("=" * 60)


def cmd_history(args):
    """List or view review history."""
    _check_server()

    if args.id:
        r = requests.get(f"{SERVER_URL}/v1/history/{args.id}", timeout=5)
        if r.status_code == 404:
            print(f"Error: History entry not found: {args.id}", file=sys.stderr)
            sys.exit(2)
        data = r.json()
        if args.format == "json":
            _print_json(data)
        else:
            print()
            print(f"  History ID:  {data.get('history_id', '?')}")
            print(f"  Timestamp:   {data.get('timestamp', '?')}")
            print(f"  Model:       {data.get('model_id', '?')}")
            print(f"  Status:      {data.get('status', '?')}")
            print(f"  Source:      {data.get('source_kind', '?')}")
            print(f"  Prediction:  {data.get('merge_prediction', '?')}")
            print(f"  Risk:        {data.get('risk_level', '?')}")
            print(f"  Files:       {data.get('changed_files', 0)}")
            print(f"  Changes:     +{data.get('additions', 0)}/-{data.get('deletions', 0)}")
            print(f"  Time:        {data.get('total_ms', 0):.0f}ms")
            if data.get("review_comments"):
                print(f"\n  Review Comments ({len(data['review_comments'])}):")
                for c in data["review_comments"]:
                    if isinstance(c, dict):
                        print(f"    [{c.get('severity', '?')}] {c.get('file', '?')}:{c.get('line', '-')} — {c.get('comment', '')[:120]}")
            if data.get("risk_factors"):
                print("\n  Risk Factors:")
                for rf in data["risk_factors"]:
                    print(f"    - {rf}")
    else:
        limit = args.limit or 20
        r = requests.get(f"{SERVER_URL}/v1/history?limit={limit}", timeout=5)
        data = r.json()

        if args.format == "json":
            _print_json(data)
        else:
            entries = data.get("entries", [])
            if not entries:
                print("No review history yet.")
                return

            print(f"\n  Review History ({data.get('total', len(entries))} total, showing {len(entries)}):")
            print()

            rows = []
            for e in entries:
                pred = e.get("merge_prediction", "?") or "?"
                rows.append([
                    e.get("history_id", "?"),
                    e.get("timestamp", "?"),
                    e.get("model_id", "?"),
                    e.get("source_kind", "?"),
                    pred,
                    e.get("risk_level", "?") or "?",
                    str(e.get("changed_files", 0)),
                    f"+{e.get('additions', 0)}/-{e.get('deletions', 0)}",
                    f"{e.get('total_ms', 0):.0f}ms",
                ])

            print(_format_table(
                ["History ID", "Time", "Model", "Source", "Prediction", "Risk", "Files", "Changes", "Time"],
                rows,
                use_color=not args.no_color,
            ))


# ═══════════════════════════════════════════════════════════════
# Main parser
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        prog="reviewctl",
        description="CLI Intelligent Code Review Tool",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    sub.add_parser("serve", help="Start the review server")

    # status
    status_p = sub.add_parser("status", help="Show server and model status")
    status_p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")

    # review
    review_p = sub.add_parser("review", help="Review a file or git diff")
    review_p.add_argument("--file", help="Path to a source file to review")
    review_p.add_argument("--repo", help="Path to a Git repository for diff review")
    review_p.add_argument("--staged", action="store_true", help="Review staged changes only")
    review_p.add_argument("--model", default="auto", help="Model ID or 'auto' (default: auto)")
    review_p.add_argument("--format", choices=["table", "json"], default="table",
                          help="Output format (default: table)")
    review_p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    review_p.add_argument("--store-source", action="store_true",
                          help="Store source code in history (warning: may contain sensitive data)")

    # history
    hist_p = sub.add_parser("history", help="View review history")
    hist_p.add_argument("--limit", type=int, default=20, help="Number of entries (default: 20)")
    hist_p.add_argument("--id", help="View a specific history entry by ID")
    hist_p.add_argument("--format", choices=["table", "json"], default="table",
                        help="Output format (default: table)")
    hist_p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve()
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "history":
        cmd_history(args)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
