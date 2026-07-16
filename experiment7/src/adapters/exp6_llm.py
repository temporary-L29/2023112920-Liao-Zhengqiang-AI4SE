"""
Experiment 6 LLM adapter — optional, requires LLM_API_KEY.

Reuses the P8 "Strict Maintainer" prompt strategy from experiment 6,
adapted for local file/diff input (not historical PR datasets).

When LLM_API_KEY is not set, this adapter reports status=unavailable.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Dict, Any, Optional, List

from src.adapters.base import BaseAdapter
import os

from src.config import (
    LLM_BASE_URL, LLM_MODEL,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT, LLM_MAX_RETRIES,
    logger,
)


def _get_api_key() -> str:
    """Read API key dynamically (not just at import time)."""
    return os.environ.get("LLM_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
from src.schemas import (
    ReviewRequest, ReviewResponse, ModelInfo, ModelStatus,
    MergePrediction, Confidence, Severity,
    InputSummary, TimingInfo, ReviewComment,
)
from src.input_extractors import compute_content_sha256, compute_change_stats


# ═══════════════════════════════════════════════════════════════
# Prompt template (condensed P8 — local risk review)
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are a strict, experienced open-source maintainer performing a pre-merge code review.
Your task is to review the provided code changes (file contents or git diff) and determine
whether this change would likely be ACCEPTED (merged) or REJECTED (not merged) in a
professional open-source project.

CRITICAL RULES:
1. Do NOT default to "merged". Actively search for reasons to reject.
2. Evaluate: missing tests, large scope, breaking API changes, insufficient documentation,
   debug artifacts, code quality issues, security concerns, AI-generated code patterns.
3. Every review comment MUST be specific and actionable — mention file names, line numbers,
   or function names when visible.
4. Assign severity accurately: blocker (must fix before merge), major (should fix),
   minor (nice to fix), nit (style preference).

You MUST respond with ONLY a valid JSON object (no markdown, no extra text):
{
  "merge_prediction": "merged" or "not_merged",
  "merge_probability": <float 0.0-1.0>,
  "confidence": "low" or "medium" or "high",
  "risk_factors": ["<specific risk>", ...],
  "review_comments": [
    {
      "file": "<path or 'general'>",
      "line": <int or null>,
      "severity": "nit|minor|major|blocker",
      "comment": "<actionable review text>"
    }
  ]
}"""


def _build_user_prompt(request: ReviewRequest) -> str:
    """Build the user message from file/diff content."""
    parts = []

    source = request.source
    parts.append(f"## Review Type: {source.kind.value}")

    if source.repo_path:
        parts.append(f"Repository: {source.repo_path}")
    if source.staged:
        parts.append("(Reviewing STAGED changes only)")

    files = request.content.files
    if files:
        parts.append(f"\n### Files ({len(files)}):")
        for f in files:
            parts.append(f"- {f.path}" + (f" ({f.language})" if f.language else ""))

    if request.content.diff:
        diff = request.content.diff
        max_chars = request.options.max_chars
        if len(diff) > max_chars:
            diff = diff[:max_chars] + f"\n... [truncated at {max_chars} chars]"
        parts.append(f"\n### Diff:\n```diff\n{diff}\n```")

    for f in files:
        if f.content:
            content = f.content
            remaining = request.options.max_chars - len("\n".join(parts))
            if remaining < 500:
                parts.append(f"\n### {f.path}:\n[content omitted — context window full]")
                continue
            limit = min(len(content), remaining - 200)
            if limit < len(content):
                content = content[:limit] + f"\n... [truncated, {len(f.content)} chars total]"
            parts.append(f"\n### {f.path}:\n```{f.language or ''}\n{content}\n```")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Adapter
# ═══════════════════════════════════════════════════════════════

class Exp6LLMAdapter(BaseAdapter):
    """LLM-based adapter using experiment 6 prompt strategies."""

    @property
    def model_info(self) -> ModelInfo:
        key = _get_api_key()
        if not key:
            return ModelInfo(
                id="exp6-llm",
                kind="llm",
                version="1",
                status=ModelStatus.unavailable,
                reason="LLM_API_KEY not set",
            )
        return ModelInfo(
            id="exp6-llm",
            kind="llm",
            version="1",
            status=ModelStatus.ready,
        )

    async def review(self, request: ReviewRequest) -> ReviewResponse:
        key = _get_api_key()
        if not key:
            raise ValueError("LLM_API_KEY not set — cannot use exp6-llm adapter")

        t0 = time.perf_counter()

        user_prompt = _build_user_prompt(request)
        t1 = time.perf_counter()
        extract_ms = (t1 - t0) * 1000

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        api_result = await _call_llm_async(messages)
        t2 = time.perf_counter()
        model_ms = (t2 - t1) * 1000

        if not api_result["success"]:
            raise RuntimeError(f"LLM call failed: {api_result['error']}")

        parsed = _parse_json_response(api_result["response_text"])
        if parsed is None:
            raise RuntimeError(
                f"Failed to parse LLM JSON response: {api_result['response_text'][:200]}"
            )

        # Build comments
        comments = []
        for c in parsed.get("review_comments", []):
            try:
                sev = Severity(c.get("severity", "minor"))
            except ValueError:
                sev = Severity.minor
            comments.append(ReviewComment(
                file=c.get("file", "general"),
                line=c.get("line"),
                severity=sev,
                comment=c.get("comment", ""),
            ))

        # Parse prediction
        pred_raw = parsed.get("merge_prediction", "not_merged")
        try:
            merge_prediction = MergePrediction(pred_raw)
        except ValueError:
            merge_prediction = MergePrediction.not_merged

        prob = float(parsed.get("merge_probability", 0.5))
        prob = max(0.0, min(1.0, prob))

        conf_raw = parsed.get("confidence", "medium")
        try:
            confidence = Confidence(conf_raw)
        except ValueError:
            confidence = Confidence.medium

        risk_factors = parsed.get("risk_factors", [])
        if isinstance(risk_factors, str):
            risk_factors = [risk_factors]

        # Risk level from probability
        if prob < 0.3:
            risk_level = "high"
        elif prob < 0.6:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Summary
        additions, deletions = 0, 0
        if request.content.diff:
            additions, deletions = compute_change_stats(request.content.diff)
        changed_files = len(request.content.files)
        raw_for_hash = (request.content.diff or "") + "\n".join(
            (f.content or "") for f in request.content.files
        )
        sha = compute_content_sha256(raw_for_hash)

        import datetime
        suffix = uuid.uuid4().hex[:6]
        history_id = datetime.datetime.now().strftime(f"%Y%m%dT%H%M%S-{suffix}")

        return ReviewResponse(
            request_id=request.request_id,
            status="success",
            model=self.model_info,
            merge_prediction=merge_prediction,
            merge_probability=prob,
            confidence=confidence,
            risk_level=risk_level,
            risk_factors=risk_factors,
            review_comments=comments,
            input_summary=InputSummary(
                changed_files=changed_files,
                additions=additions,
                deletions=deletions,
                content_sha256=sha[:16],
            ),
            timing=TimingInfo(
                extract_ms=round(extract_ms, 2),
                model_ms=round(model_ms, 2),
                total_ms=round((t2 - t0) * 1000, 2),
            ),
            history_id=history_id,
        )


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

async def _call_llm_async(messages: list) -> dict:
    """Async wrapper around OpenAI-compatible chat completion."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return {"success": False, "error": "openai package not installed"}

    client = AsyncOpenAI(
        api_key=_get_api_key(),
        base_url=LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
    )

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            resp = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
            )
            return {
                "success": True,
                "response_text": resp.choices[0].message.content or "",
                "duration_ms": 0,
                "retry_count": attempt,
                "error": "",
            }
        except Exception as e:
            if attempt < LLM_MAX_RETRIES:
                import asyncio
                await asyncio.sleep(2 ** attempt)
            else:
                return {"success": False, "error": str(e), "response_text": ""}

    return {"success": False, "error": "max retries", "response_text": ""}


def _parse_json_response(text: str) -> Optional[dict]:
    """5-level fallback JSON parser (from experiment 6 llm_runner.py)."""
    if not text:
        return None

    # 1. Direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. ```json block
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Outermost {...}
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 4. Fix trailing commas
    try:
        fixed = text.strip()
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 5. First { to last }
    try:
        first = text.find('{')
        last = text.rfind('}')
        if first >= 0 and last > first:
            return json.loads(text[first:last + 1])
    except json.JSONDecodeError:
        pass

    return None
