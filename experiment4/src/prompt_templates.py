"""
实验三 步骤三：Prompt 模板
实现 4 种 Prompt（P1-P4），统一 JSON 输出格式。
"""
import json
from pathlib import Path

from config import PROMPT_CONFIG, FEW_SHOT_COUNT, PROCESSED_DIR
from utils import log, read_json


# ============================================================
# 统一的 JSON 输出格式指令
# ============================================================
OUTPUT_FORMAT_INSTRUCTION = """\
You MUST respond with a single JSON object in the following format (no markdown code fences, just the raw JSON):

{
  "merge_prediction": "merged" or "not_merged",
  "merge_probability": <float between 0.0 and 1.0>,
  "confidence": "low" or "medium" or "high",
  "evidence_summary": "<one sentence explaining the prediction rationale>",
  "review_comments": [
    {
      "file": "<path or 'unknown'>",
      "line": null,
      "severity": "nit" or "minor" or "major" or "blocker",
      "comment": "<review text>"
    }
  ]
}
"""


# ============================================================
# P1: Zero-shot Prompt
# ============================================================
P1_SYSTEM_PROMPT = """\
You are a code review assistant. Given information about a pull request (PR) at the time it was submitted, your task is to:

1. Predict whether this PR is likely to be merged or not merged.
2. Generate preliminary code review comments.

Consider the following factors:
- The quality and clarity of the code changes
- Whether tests are included
- The scope and size of the change
- Potential issues with correctness, maintainability, or compatibility
- The presence of documentation updates when needed
"""

P1_USER_TEMPLATE = """\
Based on the following pull request information, predict whether it will be merged and provide review comments.

{context}

{output_format}
"""


# ============================================================
# P2: Few-shot Prompt
# ============================================================
P2_SYSTEM_PROMPT = """\
You are a code review assistant. Given information about a pull request (PR) at the time it was submitted, your task is to:

1. Predict whether this PR is likely to be merged or not merged.
2. Generate preliminary code review comments.

You will be shown some examples of PRs and their outcomes first, then you will analyze a new PR.
"""

P2_USER_TEMPLATE = """\
Here are some examples of pull requests and how they should be analyzed:

{few_shot_examples}

---

Now, based on the following pull request information, predict whether it will be merged and provide review comments.

{context}

{output_format}
"""


def build_few_shot_examples_text(examples: list) -> str:
    """将 few-shot 示例格式化为文本。"""
    parts = []
    for i, ex in enumerate(examples, 1):
        parts.append(f"### Example {i}: {ex['type'].replace('_', ' ').title()}")
        parts.append(f"**Repository**: {ex.get('repo', 'unknown')}")
        parts.append(f"**Title**: {ex.get('title', '')}")
        body = ex.get('body', '')
        if len(body) > 400:
            body = body[:400] + "..."
        parts.append(f"**Body**: {body}")
        parts.append(f"**Expected Outcome**: {ex['type']}")
        parts.append("")
    return "\n".join(parts)


# ============================================================
# P3: Role-based Prompt
# ============================================================
P3_SYSTEM_PROMPT = """\
You are a senior maintainer of a large open-source project. Your role is to evaluate incoming pull requests at the time they are submitted and make preliminary judgments about their likelihood of being merged, as well as provide initial review comments.

As a senior maintainer, you pay close attention to:
- **Correctness**: Does the code change do what it claims to do? Are there obvious bugs?
- **Test Coverage**: Are tests included? Do they adequately cover the changes?
- **Change Scope**: Is the change appropriately sized? Is it focused or scattered?
- **Maintainability**: Is the code clean, well-structured, and easy to understand?
- **Compatibility**: Does the change break existing APIs or behaviors?
- **Documentation**: Are docs updated when necessary?

You are pragmatic — you know that not all PRs need to be perfect, but you can spot red flags that would cause a PR to be rejected.
"""

P3_USER_TEMPLATE = """\
A new pull request has been submitted. Review the following information and provide your assessment.

{context}

{output_format}
"""


# ============================================================
# P4: Chain-of-Thought Prompt
# ============================================================
P4_SYSTEM_PROMPT = """\
You are a code review assistant. Given information about a pull request (PR) at the time it was submitted, your task is to:

1. Predict whether this PR is likely to be merged or not merged.
2. Generate preliminary code review comments.

Before providing your final answer, analyze the PR systematically following this structure:

1. **Change Analysis**: What is being changed and why?
2. **Quality Assessment**: Code quality, test coverage, documentation
3. **Risk Evaluation**: Potential issues with correctness, compatibility, scope
4. **Merge Likelihood**: Weigh the evidence for and against merging

Keep your analysis concise — then output the final JSON result.
"""

P4_USER_TEMPLATE = """\
Analyze the following pull request step by step, then provide your structured assessment.

{context}

First, provide a brief structured analysis (1-2 sentences per step), then output the JSON result.

{output_format}
"""


# ============================================================
# Prompt 构建函数
# ============================================================
def build_prompt(
    prompt_type: str,
    context: str,
    few_shot_examples: list = None,
) -> dict:
    """
    根据 prompt 类型构建完整的 messages。

    Args:
        prompt_type: P1/P2/P3/P4
        context: 构建好的上下文字符串
        few_shot_examples: few-shot 示例列表（仅 P2 使用）

    Returns:
        {"system": str, "user": str} 或 {"messages": [...]}
    """
    config = PROMPT_CONFIG.get(prompt_type)
    if config is None:
        raise ValueError(f"未知的 Prompt 类型: {prompt_type}")

    output_fmt = OUTPUT_FORMAT_INSTRUCTION

    if config["few_shot"]:
        # P2: Few-shot
        if few_shot_examples is None:
            few_shot_examples = []
        examples_text = build_few_shot_examples_text(few_shot_examples)
        system_prompt = P2_SYSTEM_PROMPT
        user_prompt = P2_USER_TEMPLATE.format(
            few_shot_examples=examples_text,
            context=context,
            output_format=output_fmt,
        )
    elif config["role_based"]:
        # P3: Role-based
        system_prompt = P3_SYSTEM_PROMPT
        user_prompt = P3_USER_TEMPLATE.format(
            context=context,
            output_format=output_fmt,
        )
    elif config["cot"]:
        # P4: Chain-of-Thought
        system_prompt = P4_SYSTEM_PROMPT
        user_prompt = P4_USER_TEMPLATE.format(
            context=context,
            output_format=output_fmt,
        )
    else:
        # P1: Zero-shot (default)
        system_prompt = P1_SYSTEM_PROMPT
        user_prompt = P1_USER_TEMPLATE.format(
            context=context,
            output_format=output_fmt,
        )

    return {
        "system": system_prompt,
        "user": user_prompt,
    }


def build_full_messages(prompt_type: str, context: str,
                        few_shot_examples: list = None) -> list:
    """
    构建完整的 OpenAI 兼容 messages 列表。

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
    """
    prompts = build_prompt(prompt_type, context, few_shot_examples)
    return [
        {"role": "system", "content": prompts["system"]},
        {"role": "user", "content": prompts["user"]},
    ]


if __name__ == "__main__":
    # 测试：打印各 prompt 模板
    test_context = "[Sample PR context here]"
    for pt in ["P1", "P2", "P3", "P4"]:
        print(f"\n{'='*60}")
        print(f"Prompt: {pt}")
        print(f"{'='*60}")
        if pt == "P2":
            examples = load_few_shot_examples()
            msgs = build_full_messages(pt, test_context[:200], examples)
        else:
            msgs = build_full_messages(pt, test_context[:200])
        for m in msgs:
            print(f"\n[{m['role']}]:")
            print(m["content"][:500])
            print("...")
