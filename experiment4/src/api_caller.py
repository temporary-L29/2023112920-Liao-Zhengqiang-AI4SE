"""
实验三 步骤四：API 调用
使用 OpenAI 兼容 SDK 调用 DeepSeek API，支持：
- 断点续跑（缓存到 raw_responses.jsonl）
- 失败重试（最多 2 次）
- JSON 解析与修复
- 并发调用（ThreadPoolExecutor）
"""
import json
import time
import re
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_MAX_RETRIES, LLM_TIMEOUT,
    LLM_MAX_WORKERS,
    CONTEXT_TYPES, PROMPT_TYPES,
    RAW_RESPONSES_JSONL, PARSED_PREDICTIONS_CSV,
    PROCESSED_DIR, RESPONSES_DIR,
)
from utils import log, read_jsonl, append_jsonl, write_json, read_json


def get_client():
    """创建 OpenAI 兼容客户端。"""
    try:
        from openai import OpenAI
    except ImportError:
        log.error("请安装 openai 包: pip install openai")
        raise

    if not LLM_API_KEY:
        log.warning("LLM_API_KEY 未设置！API 调用将失败。")
        log.warning("请设置环境变量: export LLM_API_KEY=<your-key>")

    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
    )
    log.info(f"API 客户端已创建: provider={LLM_PROVIDER}, "
             f"base_url={LLM_BASE_URL}, model={LLM_MODEL}")
    return client


def load_completed_tasks() -> set:
    """从缓存中加载已完成的任务 ID。"""
    records = read_jsonl(RAW_RESPONSES_JSONL)
    completed = set()
    for r in records:
        task_id = (r.get("prompt_type"), r.get("context_type"), str(r.get("pr_id")))
        completed.add(task_id)
    if completed:
        log.info(f"已缓存 {len(completed)} 条已完成响应（断点续跑）")
    return completed


def call_llm(client, messages: list, task_info: dict = None) -> dict:
    """
    调用 LLM API，带重试机制。

    Args:
        client: OpenAI 客户端
        messages: 消息列表
        task_info: 任务信息（用于日志）

    Returns:
        {"success": bool, "response_text": str, "error": str or None,
         "retry_count": int, "duration_ms": int}
    """
    last_error = None
    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            start_time = time.time()
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            finish_reason = response.choices[0].finish_reason
            response_text = response.choices[0].message.content or ""
            return {
                "success": True,
                "response_text": response_text,
                "error": None,
                "retry_count": attempt,
                "duration_ms": duration_ms,
                "finish_reason": finish_reason,
            }

        except Exception as e:
            last_error = str(e)
            if attempt < LLM_MAX_RETRIES:
                wait_time = 2 ** attempt  # 指数退避：1s, 2s
                log.warning(f"API 调用失败 (attempt {attempt+1}/{LLM_MAX_RETRIES+1}): "
                            f"{last_error[:200]}. {wait_time}s 后重试...")
                time.sleep(wait_time)
            else:
                log.error(f"API 调用最终失败: {last_error[:200]}")

    return {
        "success": False,
        "response_text": None,
        "error": last_error,
        "retry_count": LLM_MAX_RETRIES,
        "duration_ms": 0,
        "finish_reason": None,
    }


def _json_repair_truncated(text: str) -> str:
    """修复被截断的 JSON：补全未闭合的括号。"""
    # 移除尾部不完整的内容（如被截断的字符串值）
    # 找到最后一个完整的结构
    text = text.rstrip()

    # 如果在字符串中间被截断，尝试闭合字符串
    # 统计引号：奇数个未转义引号 → 补一个引号
    in_str = False
    clean = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            clean.append(ch)
            clean.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            in_str = not in_str
        clean.append(ch)
        i += 1
    if in_str:
        clean.append('"')
    text = ''.join(clean)

    # 移除尾部逗号
    text = text.rstrip()
    if text.endswith(','):
        text = text[:-1]

    # 统计括号
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')

    # 先闭合数组，再闭合对象
    text += ']' * open_brackets
    text += '}' * open_braces

    return text


def parse_json_response(response_text: str) -> dict:
    """
    解析 LLM 返回的 JSON，尝试修复常见格式问题。

    Returns:
        {"parse_success": bool, "data": dict or None, "parse_error": str or None}
    """
    if not response_text:
        return {"parse_success": False, "data": None, "parse_error": "Empty response"}

    text = response_text.strip()

    # 尝试 1: 直接解析
    try:
        data = json.loads(text)
        return {"parse_success": True, "data": data, "parse_error": None}
    except json.JSONDecodeError:
        pass

    # 尝试 2: 提取 ```json ... ``` 代码块
    json_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_block_match:
        try:
            data = json.loads(json_block_match.group(1).strip())
            return {"parse_success": True, "data": data, "parse_error": None}
        except json.JSONDecodeError:
            pass

    # 尝试 3: 匹配 { ... } 最外层 JSON 对象
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            data = json.loads(brace_match.group(0))
            return {"parse_success": True, "data": data, "parse_error": None}
        except json.JSONDecodeError:
            pass

    # 尝试 4: 简单修复（移除尾部逗号、修复引号等）
    try:
        fixed = _simple_json_repair(text)
        data = json.loads(fixed)
        return {"parse_success": True, "data": data, "parse_error": None}
    except (json.JSONDecodeError, Exception):
        pass

    # 尝试 5: 补全被截断的 JSON（max_tokens 不足导致）
    try:
        fixed = _json_repair_truncated(text)
        data = json.loads(fixed)
        return {"parse_success": True, "data": data, "parse_error": "repaired_truncated"}
    except (json.JSONDecodeError, Exception):
        pass

    return {
        "parse_success": False,
        "data": None,
        "parse_error": f"Failed to parse JSON from: {text[:200]}...",
    }


def _simple_json_repair(text: str) -> str:
    """简单的 JSON 修复。"""
    # 移除尾部逗号
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    # 修复单引号（谨慎处理）
    # 不做过于激进的修复
    return text


def build_task_list(sample_df, few_shot_examples: list,
                    contexts: dict) -> list:
    """
    构建完整的任务列表：4 Prompt × 4 Context × 50 PR = 800 个任务。

    Returns:
        [{"prompt_type": str, "context_type": str, "pr_id": int, ...}, ...]
    """
    tasks = []
    for _, row in sample_df.iterrows():
        pr_id = row["pr_id"]
        pr_contexts = contexts.get(pr_id, {})

        for prompt_type in PROMPT_TYPES:
            for context_type in CONTEXT_TYPES:
                context_text = pr_contexts.get(context_type, "")
                if not context_text:
                    log.warning(f"缺少上下文: pr_id={pr_id}, ctx={context_type}")
                    continue

                tasks.append({
                    "prompt_type": prompt_type,
                    "context_type": context_type,
                    "pr_id": pr_id,
                    "repo": row["repo"],
                    "is_merged": bool(row["is_merged"]),
                    "has_review_text": bool(
                        row.get("review_comments_text") and
                        str(row["review_comments_text"]).strip()
                    ),
                    "context_text": context_text,
                    "few_shot_examples": few_shot_examples if prompt_type == "P2" else None,
                })

    log.info(f"构建任务列表: {len(tasks)} 个任务")
    log.info(f"  = {len(PROMPT_TYPES)} prompts × {len(CONTEXT_TYPES)} contexts "
             f"× {len(sample_df)} PRs")
    return tasks


# 线程安全锁，保护 JSONL 写入
_jsonl_lock = threading.Lock()
_counter_lock = threading.Lock()


def _process_single_task(client, task: dict, idx: int, total: int) -> dict:
    """处理单个任务（供线程池调用）。"""
    from prompt_templates import build_full_messages

    pr_id = task["pr_id"]
    prompt_type = task["prompt_type"]
    context_type = task["context_type"]

    # 构建 messages
    messages = build_full_messages(
        prompt_type=prompt_type,
        context=task["context_text"],
        few_shot_examples=task.get("few_shot_examples"),
    )

    # 调用 API
    result = call_llm(client, messages)

    # 解析 JSON
    parse_result = None
    if result["success"]:
        parse_result = parse_json_response(result["response_text"])

    # 构建响应记录
    record = {
        "prompt_type": prompt_type,
        "context_type": context_type,
        "pr_id": pr_id,
        "repo": task["repo"],
        "is_merged": task["is_merged"],
        "has_review_text": task["has_review_text"],
        "timestamp": datetime.now().isoformat(),
        "api_success": result["success"],
        "api_error": result["error"],
        "retry_count": result["retry_count"],
        "duration_ms": result["duration_ms"],
        "finish_reason": result.get("finish_reason"),
        "response_text": result["response_text"],
        "parse_success": parse_result["parse_success"] if parse_result else False,
        "parse_error": parse_result["parse_error"] if parse_result else None,
        "parsed_data": parse_result["data"] if parse_result else None,
        "context_length": len(task["context_text"]),
    }

    # 线程安全写入 JSONL
    with _jsonl_lock:
        append_jsonl(record, RAW_RESPONSES_JSONL)

    ok = result["success"] and (parse_result and parse_result["parse_success"])
    status = "OK" if ok else "FAIL"
    log.info(f"  [{idx}/{total}] {status} {prompt_type}/{context_type}/pr={pr_id} "
             f"({result['duration_ms']}ms)")

    return record


def run_tasks(client, tasks: list, dry_run: bool = False,
              limit: int = None, max_workers: int = None) -> list:
    """
    执行所有任务（支持并发）。

    Args:
        client: OpenAI 客户端
        tasks: 任务列表
        dry_run: 如果为 True，只打印任务信息不实际调用 API
        limit: 限制执行的任务数量（用于 smoke test）
        max_workers: 并发数（默认 LLM_MAX_WORKERS）

    Returns:
        所有响应记录列表
    """
    if max_workers is None:
        max_workers = LLM_MAX_WORKERS

    completed_tasks = load_completed_tasks()

    pending_tasks = []
    for task in tasks:
        task_id = (task["prompt_type"], task["context_type"], str(task["pr_id"]))
        if task_id not in completed_tasks:
            pending_tasks.append(task)

    total = len(tasks)
    done = len(completed_tasks)
    log.info(f"总任务: {total}, 已完成: {done}, 待执行: {len(pending_tasks)}")

    if dry_run:
        log.info("[DRY RUN] 不会实际调用 API")
        for i, task in enumerate(pending_tasks[:limit or 5]):
            log.info(f"  [{i+1}] prompt={task['prompt_type']}, "
                     f"context={task['context_type']}, "
                     f"pr_id={task['pr_id']}, "
                     f"repo={task['repo']}")
            log.info(f"      上下文长度: {len(task['context_text'])} chars")
        return list(read_jsonl(RAW_RESPONSES_JSONL))

    if limit:
        pending_tasks = pending_tasks[:limit]
        log.info(f"限制执行: {limit} 个任务")

    if not pending_tasks:
        log.info("所有任务已完成，无需调用 API")
        return list(read_jsonl(RAW_RESPONSES_JSONL))

    if not LLM_API_KEY:
        log.error("未设置 LLM_API_KEY，无法调用 API！")
        return list(read_jsonl(RAW_RESPONSES_JSONL))

    n_workers = min(max_workers, len(pending_tasks))
    log.info(f"开始并发执行 {len(pending_tasks)} 个任务 (workers={n_workers})...")

    start_time = time.time()
    records = []
    success_count = 0
    fail_count = 0

    # 对 smoke test (limit 较小) 用 1 个 worker 保证顺序输出
    if limit and limit <= 3:
        n_workers = 1

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {}
        for i, task in enumerate(pending_tasks):
            idx = done + i + 1
            future = executor.submit(_process_single_task, client, task, idx, total)
            futures[future] = task

        for future in as_completed(futures):
            try:
                record = future.result()
                records.append(record)
                if record["api_success"] and record["parse_success"]:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                log.error(f"  任务异常: {e}")

    elapsed = time.time() - start_time
    log.info(f"执行完成: 成功={success_count}, 失败={fail_count}, "
             f"总耗时={elapsed:.0f}s, "
             f"平均={elapsed/max(len(pending_tasks),1):.1f}s/条")

    return list(read_jsonl(RAW_RESPONSES_JSONL))


def export_parsed_predictions(responses: list, output_path: Path = None):
    """从缓存的响应中提取并保存解析后的预测结果。"""
    import pandas as pd

    if output_path is None:
        output_path = PARSED_PREDICTIONS_CSV

    rows = []
    for r in responses:
        parsed = r.get("parsed_data") or {}

        row = {
            "prompt_type": r["prompt_type"],
            "context_type": r["context_type"],
            "pr_id": r["pr_id"],
            "repo": r["repo"],
            "is_merged": r["is_merged"],
            "has_review_text": r["has_review_text"],
            "api_success": r["api_success"],
            "parse_success": r.get("parse_success", False),
            "duration_ms": r.get("duration_ms", 0),
            "context_length": r.get("context_length", 0),
            "merge_prediction": parsed.get("merge_prediction", None),
            "merge_probability": parsed.get("merge_probability", None),
            "confidence": parsed.get("confidence", None),
            "evidence_summary": parsed.get("evidence_summary", None),
            "num_review_comments": len(parsed.get("review_comments", [])),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    log.info(f"解析后的预测结果已保存: {output_path} ({len(df)} 条)")


def run(sample_df, few_shot_examples: list, contexts: dict,
        dry_run: bool = False, limit: int = None):
    """主入口：执行 API 调用。"""
    log.info("=" * 60)
    log.info("步骤四：API 调用")
    log.info("=" * 60)

    # 构建任务列表
    tasks = build_task_list(sample_df, few_shot_examples, contexts)

    # 保存任务列表
    tasks_path = PROCESSED_DIR / "task_list.json"
    # 只保存元数据（不保存完整 context，避免文件过大）
    tasks_meta = [
        {k: v for k, v in t.items() if k != "context_text"}
        for t in tasks
    ]
    write_json(tasks_meta, tasks_path)
    log.info(f"任务列表已保存: {tasks_path}")

    # 创建客户端
    if not dry_run and LLM_API_KEY:
        client = get_client()
    else:
        client = None

    # 执行任务
    responses = run_tasks(client, tasks, dry_run=dry_run, limit=limit)

    # 导出解析后的预测
    export_parsed_predictions(responses)

    return responses


if __name__ == "__main__":
    from utils import setup_logger
    log = setup_logger("experiment3", PROCESSED_DIR.parent / "pipeline.log")
    import pandas as pd
    sample_df = pd.read_csv(PROCESSED_DIR / "llm_sample_50.csv")
    few_shot = read_json(PROCESSED_DIR / "few_shot_examples.json")
    contexts = read_json(PROCESSED_DIR / "all_contexts.json")
    run(sample_df, few_shot, contexts, dry_run=True, limit=3)
