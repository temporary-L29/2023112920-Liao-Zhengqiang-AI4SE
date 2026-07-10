"""
DeepSeek 大语言模型实验 — 测试实验四方法在 AI 代码上的泛化

默认组合:
  P2_C3: Few-shot + Diff + PR Description + Commit
  P2_C4: Few-shot + Full Early Context (含 AST/CFG 摘要)

使用多线程调用 DeepSeek API, 支持断点续传。
"""

import json
import os
import sys
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    AI_DATASET_CSV,
    AI_PATCH_INDEX,
    RESULTS_PROCESSED_DIR,
    RESULTS_EVALUATION_DIR,
    MAX_WORKERS,
    RANDOM_SEED,
    ORIGINAL_REPOS,
    logger,
)

# ============================================================
# API 配置 (兼容环境变量)
# ============================================================
LLM_API_KEY = os.environ.get("LLM_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 2000
LLM_MAX_RETRIES = 2
LLM_TIMEOUT = 120

PREDICTIONS_DIR = os.path.join(os.path.dirname(RESULTS_PROCESSED_DIR), "predictions")
LLM_RAW_RESPONSES = os.path.join(PREDICTIONS_DIR, "llm_raw_responses.jsonl")
LLM_PARSED_PREDICTIONS = os.path.join(PREDICTIONS_DIR, "llm_parsed_predictions.csv")
LLM_TASK_LIST = os.path.join(RESULTS_PROCESSED_DIR, "ai_task_list.json")
LLM_CONTEXTS = os.path.join(RESULTS_PROCESSED_DIR, "ai_contexts.json")
LLM_METRICS_JSON = os.path.join(RESULTS_EVALUATION_DIR, "llm_metrics.json")

os.makedirs(PREDICTIONS_DIR, exist_ok=True)

_jsonl_lock = Lock()

# ============================================================
# Context 构建 (对齐实验四 C3/C4)
# ============================================================
MAX_DIFF_CHARS = 8000
MAX_BODY_CHARS = 3000
MAX_COMMIT_MSG_CHARS = 1500
MAX_ADDED_LINES_CHARS = 6000


def _load_patch_index() -> Dict:
    if os.path.exists(AI_PATCH_INDEX):
        with open(AI_PATCH_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_diff_context(row: pd.Series, patch_index: Dict) -> str:
    """构建 diff 上下文"""
    pr_id = str(row.get("pr_id", ""))
    pi = patch_index.get(pr_id, {})
    files = pi.get("files", [])

    parts = []
    parts.append("## Changed Files\n")
    for f in files:
        fname = f.get("filename", "?")
        status = f.get("status", "?")
        adds = f.get("additions", 0)
        dels = f.get("deletions", 0)
        ext = os.path.splitext(fname)[1].lower()
        is_test = "test" in fname.lower() or "spec" in fname.lower()
        marker = " [TEST]" if is_test else ""
        parts.append(f"- `{fname}` ({status}, +{adds}/-{dels}){marker}")

    # 添加代码行 (使用 patch)
    added_lines = []
    for f in files:
        patch = f.get("patch", "")
        if patch:
            for line in patch.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    added_lines.append(line[1:])
    if added_lines:
        added_text = "\n".join(added_lines)
        if len(added_text) > MAX_ADDED_LINES_CHARS:
            added_text = added_text[:MAX_ADDED_LINES_CHARS] + "\n... (truncated)"
        parts.append(f"\n## Added Code Lines\n```\n{added_text}\n```")

    result = "\n".join(parts)
    if len(result) > MAX_DIFF_CHARS:
        result = result[:MAX_DIFF_CHARS] + "\n... (diff truncated)"
    return result


def build_pr_description_context(row: pd.Series) -> str:
    """构建 PR 描述上下文"""
    title = str(row.get("title", ""))
    body = str(row.get("body", ""))
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n... (truncated)"
    return f"## PR Description\n**Title**: {title}\n\n**Body**:\n{body}"


def build_commit_context(row: pd.Series) -> str:
    """构建 commit 上下文"""
    commits = str(row.get("commit_messages", ""))
    if len(commits) > MAX_COMMIT_MSG_CHARS:
        commits = commits[:MAX_COMMIT_MSG_CHARS] + "\n... (truncated)"
    num_commits = row.get("num_commits", 1)
    num_files = row.get("num_changed_files", 0)
    return (
        f"## Commit Information\n"
        f"Number of commits: {num_commits}\n"
        f"Changed files: {num_files}\n\n"
        f"**Commit Messages**:\n{commits}"
    )


def build_code_summary_context(row: pd.Series) -> str:
    """构建代码结构摘要 (C4 专属)"""
    parts = ["## Code Structure Summary\n"]
    parts.append(f"- Changed files: {row.get('num_changed_files', '?')}")
    parts.append(f"- Lines added: {row.get('total_additions', '?')}, deleted: {row.get('total_deletions', '?')}")
    parts.append(f"- Code churn: {int(row.get('total_additions', 0)) + int(row.get('total_deletions', 0))}")
    parts.append(f"- Test files: {row.get('num_test_files', '?')}")
    parts.append(f"- AST nodes: {row.get('ast_total_nodes', 'N/A')}, max depth: {row.get('ast_max_depth', 'N/A')}")
    parts.append(f"- CFG complexity: {row.get('cfg_cyclomatic_complexity', 'N/A')}")
    return "\n".join(parts)


def build_context(row: pd.Series, context_type: str, patch_index: Dict) -> str:
    """构建指定类型的上下文"""
    parts = [f"**Repository**: {row.get('repo', '?')}", f"**PR ID**: {row.get('pr_id', '?')}", ""]
    parts.append(build_diff_context(row, patch_index))

    if context_type in ("C2", "C3", "C4"):
        parts.append(build_pr_description_context(row))
    if context_type in ("C3", "C4"):
        parts.append(build_commit_context(row))
    if context_type == "C4":
        parts.append(build_code_summary_context(row))

    return "\n\n".join(parts)


# ============================================================
# Prompt 模板 (P2: Few-shot)
# ============================================================
OUTPUT_FORMAT = """## Output Format
You MUST respond with ONLY a valid JSON object (no markdown, no extra text):

```json
{
  "merge_prediction": "merged" or "not_merged",
  "merge_probability": <float 0.0-1.0>,
  "confidence": "low" or "medium" or "high",
  "evidence_summary": "<one sentence explaining your reasoning>",
  "review_comments": [
    {"file": "<path>", "line": null, "severity": "nit|minor|major|blocker", "comment": "<review text>"}
  ]
}
```"""

FEW_SHOT_EXAMPLES = """## Examples

### Example 1: Merged PR
**Repository**: microsoft/vscode
**Title**: Fix copilot inline suggestion flickering
**Body**: This PR fixes the flickering issue when Copilot suggestions appear during fast typing. The root cause was a race condition in the suggestion provider.
**Outcome**: merged
**Analysis**: Well-scoped bugfix with clear description. Single file changed, existing tests pass. High confidence merge.

### Example 2: Not Merged PR
**Repository**: kubernetes/kubernetes
**Title**: WIP: refactor scheduler using GPT-generated code
**Body**: I used ChatGPT to generate a new scheduler implementation. Still needs testing and review.
**Outcome**: not_merged
**Analysis**: Large untested change generated by AI tool. No test coverage, unclear motivation. Low confidence in correctness.

### Example 3: Merged PR
**Repository**: pandas-dev/pandas
**Title**: Add type hints to DataFrame.groupby (generated with Copilot)
**Body**: Used GitHub Copilot to add missing type hints across the groupby module. All existing tests pass.
**Outcome**: merged
**Analysis**: Mechanical type hint additions with full test coverage. Low-risk change with clear scope.

### Example 4: Not Merged PR
**Repository**: huggingface/transformers
**Title**: Add new attention mechanism (Claude-assisted implementation)
**Body**: Claude helped implement a novel attention mechanism. No benchmarks included. Breaking change to existing API.
**Outcome**: not_merged
**Analysis**: Breaking API change without migration plan. Missing benchmarks and tests. High risk."""


def build_messages(context_text: str, prompt_type: str = "P2") -> List[Dict]:
    """构建 API messages"""
    system = (
        "You are an experienced code reviewer analyzing pull requests. "
        "Your task is to:\n"
        "1. Predict whether a PR will be merged (merged / not_merged)\n"
        "2. Generate relevant code review comments\n\n"
        "Base your analysis ONLY on the information provided (PR description, diff, commit messages). "
        "Do NOT use any external knowledge about the repository or its maintainers."
    )

    if prompt_type == "P2":
        user = (
            "Here are some examples of pull request analysis:\n\n"
            f"{FEW_SHOT_EXAMPLES}\n\n"
            "---\n\n"
            "Now analyze the following pull request:\n\n"
            f"{context_text}\n\n"
            f"{OUTPUT_FORMAT}"
        )
    elif prompt_type == "P1":
        user = (
            "Analyze the following pull request:\n\n"
            f"{context_text}\n\n"
            f"{OUTPUT_FORMAT}"
        )
    else:
        user = (
            "Analyze the following pull request:\n\n"
            f"{context_text}\n\n"
            f"{OUTPUT_FORMAT}"
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ============================================================
# API 调用
# ============================================================
def call_llm(messages: List[Dict]) -> Dict:
    """调用 DeepSeek API"""
    if not LLM_API_KEY:
        return {"success": False, "error": "LLM_API_KEY not set", "response_text": ""}

    try:
        from openai import OpenAI
    except ImportError:
        return {"success": False, "error": "openai package not installed", "response_text": ""}

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=LLM_TIMEOUT)

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            t0 = time.time()
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
            )
            elapsed = (time.time() - t0) * 1000
            return {
                "success": True,
                "response_text": resp.choices[0].message.content or "",
                "duration_ms": elapsed,
                "finish_reason": resp.choices[0].finish_reason or "stop",
                "retry_count": attempt,
                "error": "",
            }
        except Exception as e:
            if attempt < LLM_MAX_RETRIES:
                wait = 2 ** attempt
                logger.debug(f"API 重试 {attempt + 1}/{LLM_MAX_RETRIES}, 等待 {wait}s: {e}")
                time.sleep(wait)
            else:
                return {"success": False, "error": str(e), "response_text": "", "retry_count": attempt}

    return {"success": False, "error": "max retries", "response_text": ""}


def parse_json_response(text: str) -> Optional[Dict]:
    """解析 JSON 响应 (5级回退)"""
    if not text:
        return None

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取 ```json 代码块
    import re
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 提取 { ... }
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 4. 简单修复
    try:
        fixed = text.strip()
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return None


def _load_completed_tasks() -> set:
    """加载已完成的 task keys"""
    completed = set()
    if os.path.exists(LLM_RAW_RESPONSES):
        with open(LLM_RAW_RESPONSES, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    completed.add((rec.get("prompt_type", ""), rec.get("context_type", ""),
                                   str(rec.get("pr_id", ""))))
                except json.JSONDecodeError:
                    pass
    return completed


# ============================================================
# 主流程
# ============================================================
def run_llm_experiment(
    prompt_types: List[str] = None,
    context_types: List[str] = None,
    dry_run: bool = False,
    limit: int = 0,
) -> bool:
    """
    运行 LLM 实验。

    参数:
        prompt_types: 默认 ["P2"]
        context_types: 默认 ["C3", "C4"]
        dry_run: 只生成 task list，不调用 API
        limit: 限制调用次数 (用于 smoke test)
    """
    if prompt_types is None:
        prompt_types = ["P2"]
    if context_types is None:
        context_types = ["C3", "C4"]

    logger.info("=" * 60)
    logger.info("阶段: DeepSeek LLM 实验")
    logger.info(f"Prompt: {prompt_types}, Context: {context_types}")
    logger.info(f"Dry run: {dry_run}, Limit: {limit or 'unlimited'}")
    logger.info(f"Model: {LLM_MODEL}")
    logger.info("=" * 60)

    # 1. 加载数据
    if not os.path.exists(AI_DATASET_CSV):
        logger.error(f"AI 数据集未找到: {AI_DATASET_CSV}")
        return False

    df = pd.read_csv(AI_DATASET_CSV, encoding="utf-8-sig")
    logger.info(f"加载 {len(df)} 条 AI PR")

    patch_index = _load_patch_index()
    logger.info(f"Patch index: {len(patch_index)} 条目")

    # 2. 构建 context
    logger.info("构建上下文...")
    contexts = {}
    for ctx_type in context_types:
        for _, row in df.iterrows():
            pr_id = str(row["pr_id"])
            key = f"{pr_id}_{ctx_type}"
            contexts[key] = build_context(row, ctx_type, patch_index)

    # 保存 contexts
    serializable = {k: v for k, v in list(contexts.items())[:100]}  # 只保存前100个避免过大
    with open(LLM_CONTEXTS, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    logger.info(f"上下文已保存: {LLM_CONTEXTS} (前100个)")

    # 3. 构建任务列表
    tasks = []
    for prompt_type in prompt_types:
        for ctx_type in context_types:
            for _, row in df.iterrows():
                pr_id = str(row["pr_id"])
                ctx_key = f"{pr_id}_{ctx_type}"
                context_text = contexts.get(ctx_key, "")
                tasks.append({
                    "prompt_type": prompt_type,
                    "context_type": ctx_type,
                    "pr_id": pr_id,
                    "repo": row.get("repo", ""),
                    "is_merged": bool(row.get("is_merged", False)),
                    "has_review_text": bool(str(row.get("review_comments_text", "")).strip()),
                    "context_text": context_text,
                    "context_length": len(context_text),
                })

    logger.info(f"总任务数: {len(tasks)} ({len(prompt_types)}×{len(context_types)}×{len(df)})")

    with open(LLM_TASK_LIST, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    logger.info(f"任务列表已保存: {LLM_TASK_LIST}")

    if dry_run:
        logger.info("Dry run 模式，跳过 API 调用")
        logger.info(f"预计 API 调用次数: {len(tasks)}")
        return True

    if not LLM_API_KEY:
        logger.warning("未设置 LLM_API_KEY/DEEPSEEK_API_KEY 环境变量")
        logger.warning("请设置后运行: set LLM_API_KEY=your-key")
        logger.warning("当前仅生成任务列表 (dry run)")
        return True

    # 4. 多线程 API 调用
    logger.info(f"开始 API 调用 ({MAX_WORKERS} workers)...")
    completed = _load_completed_tasks()
    logger.info(f"  已完成: {len(completed)}")

    pending = [t for t in tasks
               if (t["prompt_type"], t["context_type"], str(t["pr_id"])) not in completed]

    if limit and limit > 0:
        pending = pending[:limit]

    if not pending:
        logger.info("所有任务已完成")
    else:
        logger.info(f"  待处理: {len(pending)}")
        processed = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_task = {}
            for task in pending:
                messages = build_messages(task["context_text"], task["prompt_type"])
                future = executor.submit(call_llm, messages)
                future_to_task[future] = task

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    api_result = future.result(timeout=LLM_TIMEOUT + 10)
                except Exception as e:
                    api_result = {"success": False, "error": str(e), "response_text": ""}

                # 解析
                parsed = None
                parse_success = False
                if api_result.get("success") and api_result.get("response_text"):
                    parsed = parse_json_response(api_result["response_text"])
                    parse_success = parsed is not None

                record = {
                    "prompt_type": task["prompt_type"],
                    "context_type": task["context_type"],
                    "pr_id": task["pr_id"],
                    "repo": task["repo"],
                    "is_merged": task["is_merged"],
                    "has_review_text": task["has_review_text"],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "api_success": api_result.get("success", False),
                    "retry_count": api_result.get("retry_count", 0),
                    "duration_ms": api_result.get("duration_ms", 0),
                    "finish_reason": api_result.get("finish_reason", ""),
                    "response_text": api_result.get("response_text", ""),
                    "parse_success": parse_success,
                    "parsed_data": parsed,
                    "context_length": task["context_length"],
                    "error": api_result.get("error", ""),
                }

                with _jsonl_lock:
                    with open(LLM_RAW_RESPONSES, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

                processed += 1
                if processed % 20 == 0:
                    logger.info(f"  进度: {processed}/{len(pending)}")

        logger.info(f"API 调用完成: {processed}/{len(pending)}")

    # 5. 导出解析预测
    logger.info("导出解析预测...")
    export_parsed_predictions()
    logger.info("=" * 60)

    return True


def export_parsed_predictions():
    """从 raw_responses.jsonl 导出 CSV"""
    if not os.path.exists(LLM_RAW_RESPONSES):
        logger.warning("raw_responses.jsonl 不存在")
        return

    rows = []
    with open(LLM_RAW_RESPONSES, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            parsed = rec.get("parsed_data") or {}
            rows.append({
                "prompt_type": rec.get("prompt_type", ""),
                "context_type": rec.get("context_type", ""),
                "pr_id": rec.get("pr_id", ""),
                "repo": rec.get("repo", ""),
                "is_merged": rec.get("is_merged", False),
                "has_review_text": rec.get("has_review_text", False),
                "api_success": rec.get("api_success", False),
                "parse_success": rec.get("parse_success", False),
                "duration_ms": rec.get("duration_ms", 0),
                "context_length": rec.get("context_length", 0),
                "merge_prediction": parsed.get("merge_prediction", ""),
                "merge_probability": parsed.get("merge_probability", None),
                "confidence": parsed.get("confidence", ""),
                "evidence_summary": parsed.get("evidence_summary", ""),
                "num_review_comments": len(parsed.get("review_comments", [])),
            })

    if rows:
        pred_df = pd.DataFrame(rows)
        pred_df.to_csv(LLM_PARSED_PREDICTIONS, index=False, encoding="utf-8-sig")
        logger.info(f"解析预测已保存: {LLM_PARSED_PREDICTIONS} ({len(rows)} 行)")
    else:
        logger.warning("无可用预测数据")


def compute_llm_metrics() -> dict:
    """计算 LLM 指标 (由 evaluator 调用)"""
    if not os.path.exists(LLM_PARSED_PREDICTIONS):
        return {}

    df = pd.read_csv(LLM_PARSED_PREDICTIONS, encoding="utf-8-sig")
    df_valid = df[df["parse_success"] == True].copy()

    metrics = {}
    for (pt, ct), group in df_valid.groupby(["prompt_type", "context_type"]):
        key = f"{pt}_{ct}"
        y_true = group["is_merged"].astype(int).values
        y_pred = (group["merge_prediction"].str.lower() == "merged").astype(int).values

        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score,
            f1_score, roc_auc_score, confusion_matrix,
        )
        try:
            auc = roc_auc_score(y_true, group["merge_probability"].fillna(0.5))
        except Exception:
            auc = None

        cm = confusion_matrix(y_true, y_pred)
        metrics[key] = {
            "prompt_type": pt,
            "context_type": ct,
            "n_valid": len(group),
            "n_total": len(group),
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
            "roc_auc": round(float(auc), 4) if auc else None,
            "confusion_matrix": cm.tolist(),
        }

    with open(LLM_METRICS_JSON, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    logger.info(f"LLM 指标已保存: {LLM_METRICS_JSON}")
    return metrics


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只生成任务列表")
    parser.add_argument("--limit", type=int, default=0, help="限制调用次数")
    args = parser.parse_args()
    run_llm_experiment(dry_run=args.dry_run, limit=args.limit)
