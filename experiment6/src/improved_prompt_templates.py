"""
改进 Prompt 模板 — P5/P6/P7/P8

针对实验五"模型过度乐观"的问题，每个 prompt 显式要求:
  1. 不要默认预测 merged
  2. 主动寻找不会合并的信号
  3. 对 unmerged 风险给出具体证据
  4. 生成更有操作性的审查意见
"""

from typing import Dict, List


# ============================================================
# 统一输出格式
# ============================================================
OUTPUT_FORMAT_V2 = """## Output Format
You MUST respond with ONLY a valid JSON object (no markdown, no extra text):

```json
{
  "merge_prediction": "merged" or "not_merged",
  "merge_probability": <float 0.0-1.0>,
  "unmerged_risk_score": <float 0.0-1.0, higher = more likely to NOT be merged>,
  "confidence": "low" or "medium" or "high",
  "risk_factors": ["<specific risk 1>", "<specific risk 2>", ...],
  "evidence_summary": "<one sentence summarizing key reasoning>",
  "review_comments": [
    {
      "file": "<path or 'general'>",
      "line": null,
      "severity": "nit|minor|major|blocker",
      "comment": "<actionable review text — be specific about what to fix>"
    }
  ]
}
```

IMPORTANT:
- Do NOT default to predicting "merged". Many PRs — especially AI-generated ones — are legitimately not merged.
- Look for SPECIFIC reasons a PR might be rejected: missing tests, large scope, breaking changes, insufficient description, AI artifacts.
- Your review_comments should be ACTIONABLE: mention specific files, functions, or behaviors.
- If risk_factors is empty, explain why in evidence_summary."""


# ============================================================
# Few-shot 示例 (更新版，包含 balanced cases)
# ============================================================
FEW_SHOT_EXAMPLES_V2 = """## Examples of Balanced Analysis

### Example 1: Merged — Clean, Well-Tested Change
**Title**: Fix copilot inline suggestion flickering
**Body**: Fixes race condition in suggestion provider. Root cause: debounce timer not reset on fast typing. Added unit test covering the race condition.
**Changed Files**: 2 files (1 source, 1 test)
**Risk Checklist**: ✓ Has test, ✓ Small scope (+15/-3), ✓ Clear description
**Analysis**: Low-risk bugfix with test coverage. High confidence merge.
**merge_prediction**: merged, **merge_probability**: 0.92, **unmerged_risk_score**: 0.08
**Risk Factors**: []

### Example 2: NOT Merged — Large Untested AI-Generated Change
**Title**: WIP: refactor scheduler using GPT-generated code
**Body**: I used ChatGPT to generate a new scheduler implementation. Still needs testing.
**Changed Files**: 12 files, +850/-120 lines
**Risk Checklist**: ⚠ MISSING_TESTS, ⚠ LARGE_SCOPE (12 files), ⚠ LARGE_ADDITIONS (+850), ⚠ AI_TOOL_TRACES: gpt, ⚠ CORE_MODULE, ⚠ SHORT_DESCRIPTION
**Analysis**: Large untested refactor touching core scheduler code. AI generation explicitly stated. Missing tests and unclear motivation. High risk of rejection.
**merge_prediction**: not_merged, **merge_probability**: 0.15, **unmerged_risk_score**: 0.85
**Risk Factors**: ["Missing tests for large refactor", "AI-generated code touches core module", "No migration plan or benchmarks", "PR description lacks justification"]

### Example 3: Merged — Mechanical Type Annotations
**Title**: Add type hints to DataFrame.groupby (generated with Copilot)
**Body**: Used GitHub Copilot to add missing type hints across the groupby module. All existing tests pass. No behavioral changes.
**Changed Files**: 3 files, +45/-12 lines
**Risk Checklist**: ✓ Has existing test suite, ✓ Small scope, • AI_TOOL_TRACES: copilot (but mechanical change)
**Analysis**: Mechanical type hint additions — low semantic risk despite AI tool usage. Existing tests provide coverage.
**merge_prediction**: merged, **merge_probability**: 0.85, **unmerged_risk_score**: 0.15
**Risk Factors**: ["AI tool used but change is mechanical and well-tested"]

### Example 4: NOT Merged — Breaking API Change Without Documentation
**Title**: Add new attention mechanism (Claude-assisted implementation)
**Body**: Claude helped implement a novel attention mechanism. Breaking change to existing API.
**Changed Files**: 8 files, +420/-80 lines
**Risk Checklist**: ⚠ MISSING_TESTS, ⚠ CORE_MODULE, ⚠ API_CHANGE_NO_DOCS, ⚠ AI_TOOL_TRACES: claude
**Analysis**: Breaking API change without migration plan. No benchmarks or tests. AI-assisted implementation of novel algorithm — needs careful review.
**merge_prediction**: not_merged, **merge_probability**: 0.20, **unmerged_risk_score**: 0.80
**Risk Factors**: ["Breaking API change with no migration guide", "Missing benchmarks for new algorithm", "AI-generated novel implementation — correctness uncertain", "No documentation updates"]"""


# ============================================================
# P5: AI-Risk-Aware Prompt
# ============================================================
P5_SYSTEM = """You are an experienced code reviewer specializing in AI-generated code review.

Your PRIMARY task is to identify risks in AI-generated pull requests that might cause them to NOT be merged.

Key principles:
1. AI-generated code often has subtle issues: hallucinated APIs, missing edge cases, over-engineered solutions.
2. Look for structural problems: missing tests, large scope, breaking changes, insufficient documentation.
3. Many AI-generated PRs are legitimately rejected — do NOT default to predicting "merged".
4. Your review comments must be ACTIONABLE — cite specific files, functions, or patterns.
5. The risk checklist provided is guidance, not a label. Form your own judgment."""

P5_USER_TEMPLATE = """You are reviewing a pull request that may contain AI-generated code.

{few_shot}

---

Now analyze the following pull request:

{context}

---

{output_format}

REMEMBER: Look for reasons this PR might NOT be merged. Be specific and evidence-based."""


# ============================================================
# P6: Contrastive Prompt
# ============================================================
P6_SYSTEM = """You are an experienced code reviewer performing a balanced, evidence-based review.

CRITICAL: You MUST explicitly list evidence BOTH for and against merging, then make a judgment.
Do NOT default to "merged" just because the change looks small or simple.

Process:
1. List evidence FOR merging (merge_evidence)
2. List evidence AGAINST merging (reject_evidence)
3. Weigh both sides
4. If the evidence is balanced or uncertain, lean toward lower merge_probability
5. Output your final assessment"""

P6_USER_TEMPLATE = """Perform a CONTRASTIVE review of this pull request.

{few_shot}

---

## Current Pull Request

{context}

---

{output_format}

BEFORE writing your JSON, mentally list:
- **Merge Evidence** (reasons to accept): ...
- **Reject Evidence** (reasons to reject): ...

If reject evidence is substantial, your merge_probability MUST be low and unmerged_risk_score MUST be high.
Small changes alone are NOT sufficient reason to predict merged — check for tests, scope, and AI artifacts."""


# ============================================================
# P7: Self-Reflection Prompt
# ============================================================
P7_SYSTEM = """You are an experienced code reviewer who practices self-reflection.

Your review process:
1. Make an initial prediction about whether the PR will be merged
2. CRITICALLY EXAMINE your own prediction: Are you being too optimistic? Did you miss risks?
3. Re-calibrate your merge_probability considering the risks you might have overlooked
4. Output your FINAL, calibrated assessment

AI-generated code often looks plausible but has hidden issues. Be skeptical — look deeper."""

P7_USER_TEMPLATE = """Review this pull request using SELF-REFLECTION.

{few_shot}

---

## Current Pull Request

{context}

---

## Self-Reflection Process

Step 1 — Initial Assessment: What is your first impression? Would this PR likely be merged?

Step 2 — Critical Re-examination:
- Are you being too optimistic? Why?
- What risks might you have missed?
- If this were a high-stakes repository, would you still merge this?
- Does the PR have: tests? documentation? reasonable scope? clear motivation?

Step 3 — Re-calibrated Final Assessment:

{output_format}

IMPORTANT: If during Step 2 you found ANY significant risks, lower your merge_probability accordingly.
Do NOT output the step-by-step reasoning in the JSON — only the final calibrated result."""


# ============================================================
# P8: Strict Maintainer Prompt
# ============================================================
P8_SYSTEM = """You are a STRICT open-source maintainer reviewing AI-generated code contributions.

Your standards are HIGH. You treat AI-generated code with extra scrutiny because:
- AI code can be syntactically correct but semantically wrong
- AI code often misses project conventions and edge cases
- AI code frequently lacks proper testing and documentation
- The burden of proof is on the contributor, not the reviewer

Review guidelines:
1. If tests are missing → SIGNIFICANTLY reduce merge_probability
2. If the change affects core modules or public APIs → require strong justification
3. If the PR description is insufficient → mark as high risk
4. If any AI generation artifacts are present → apply stricter review
5. Focus your comments on BLOCKER and MAJOR issues, not style nits
6. Every review comment must be ACTIONABLE and SPECIFIC"""

P8_USER_TEMPLATE = """As a STRICT maintainer, review this AI-generated pull request.

{few_shot}

---

## Current Pull Request

{context}

---

{output_format}

Remember:
- Missing tests = serious problem, not a minor nit
- Large scope = higher chance of hidden bugs
- AI-generated = extra scrutiny on correctness and conventions
- If you see ANY blocker-level issue, merge_probability should be LOW (≤0.3)
- Be fair but firm — your job is to protect the codebase quality"""


# ============================================================
# Prompt 构建入口
# ============================================================
def build_messages(context_text: str, prompt_type: str = "P5") -> List[Dict]:
    """构建 API messages"""

    prompt_configs = {
        "P5": {
            "system": P5_SYSTEM,
            "template": P5_USER_TEMPLATE,
        },
        "P6": {
            "system": P6_SYSTEM,
            "template": P6_USER_TEMPLATE,
        },
        "P7": {
            "system": P7_SYSTEM,
            "template": P7_USER_TEMPLATE,
        },
        "P8": {
            "system": P8_SYSTEM,
            "template": P8_USER_TEMPLATE,
        },
    }

    config = prompt_configs.get(prompt_type, prompt_configs["P5"])
    system = config["system"]

    user = config["template"].format(
        few_shot=FEW_SHOT_EXAMPLES_V2,
        context=context_text,
        output_format=OUTPUT_FORMAT_V2,
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# 兼容旧接口
def build_prompt_v1(context_text: str, prompt_type: str = "P2") -> List[Dict]:
    """构建实验五兼容 prompt (P2)"""
    system = (
        "You are an experienced code reviewer analyzing pull requests. "
        "Your task is to:\n"
        "1. Predict whether a PR will be merged (merged / not_merged)\n"
        "2. Generate relevant code review comments\n\n"
        "Base your analysis ONLY on the information provided (PR description, diff, commit messages). "
        "Do NOT use any external knowledge about the repository or its maintainers."
    )

    few_shot = FEW_SHOT_EXAMPLES_V2

    user = (
        "Here are some examples of pull request analysis:\n\n"
        f"{few_shot}\n\n"
        "---\n\n"
        "Now analyze the following pull request:\n\n"
        f"{context_text}\n\n"
        f"{OUTPUT_FORMAT_V2}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
