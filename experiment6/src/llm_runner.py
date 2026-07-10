"""
LLM Runner — 调用 DeepSeek API 执行实验

支持:
  - 断点续跑
  - 多线程并发
  - smoke test (--limit)
  - 多方法组合
"""

import json
import os
import re
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
    EVAL_BALANCED_50,
    EVAL_BALANCED_120,
    EVAL_HARD_FP_40,
    METHOD_COMBOS,
    IMPROVED_COMBOS,
    IMPROVED_CONTEXTS,
    IMPROVED_CONTEXTS_50,
    TASK_LIST,
    TASK_LIST_IMPROVED_4X4,
    RAW_RESPONSES,
    PARSED_PREDICTIONS,
    IMPROVED_4X4_RAW,
    IMPROVED_4X4_PARSED,
    RESULTS_RESPONSES_DIR,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT,
    MAX_WORKERS,
    logger,
)

from enhanced_context_builder import build_context, _load_patch_index, _load_full_dataset
from improved_prompt_templates import build_messages

_jsonl_lock = Lock()

# All context types needed
ALL_CONTEXT_TYPES = ["C5", "C6", "C7", "C8"]


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


# ============================================================
# JSON 解析
# ============================================================
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
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 提取 { ... } (最外层)
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 4. 修复尾部逗号
    try:
        fixed = text.strip()
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 5. 尝试提取第一个 { 到最后一个 }
    try:
        first = text.find('{')
        last = text.rfind('}')
        if first >= 0 and last > first:
            return json.loads(text[first:last + 1])
    except json.JSONDecodeError:
        pass

    return None


# ============================================================
# 断点续跑
# ============================================================
def _load_completed_tasks_4x4(raw_path: str = None) -> set:
    """加载已完成的 task keys"""
    path = raw_path or RAW_RESPONSES
    completed = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    completed.add((
                        rec.get("method_id", ""),
                        str(rec.get("pr_id", "")),
                    ))
                except json.JSONDecodeError:
                    pass
    return completed


# 兼容旧名
def _load_completed_tasks() -> set:
    return _load_completed_tasks_4x4(RAW_RESPONSES)


# ============================================================
# 主流程
# ============================================================
def run_llm_experiment(
    suite: str = "balanced",
    method_ids: List[str] = None,
    dry_run: bool = False,
    limit: int = 0,
    allow_full: bool = False,
) -> bool:
    """
    运行 LLM 实验。

    参数:
        suite: "improved-4x4" | "balanced" | "hard-fp" | "full"
        method_ids: 默认取决于 suite
        dry_run: 只生成任务列表
        limit: 限制调用次数 (smoke test)
        allow_full: 必须显式传入才能跑 full-343
    """
    # --- 确定 combos 和 eval_csv ---
    if suite == "improved-4x4":
        # 主实验: I01-I16 在 Balanced-50 上
        combos = IMPROVED_COMBOS
        eval_csv = EVAL_BALANCED_50
        raw_output = IMPROVED_4X4_RAW
        parsed_output = IMPROVED_4X4_PARSED
        if method_ids is None:
            method_ids = list(IMPROVED_COMBOS.keys())  # I01-I16
    elif suite == "balanced":
        combos = METHOD_COMBOS
        eval_csv = EVAL_BALANCED_120
        raw_output = RAW_RESPONSES
        parsed_output = PARSED_PREDICTIONS
        if method_ids is None:
            method_ids = ["M1", "M2", "M3", "M4"]
    elif suite == "hard-fp":
        combos = METHOD_COMBOS
        eval_csv = EVAL_HARD_FP_40
        raw_output = RAW_RESPONSES
        parsed_output = PARSED_PREDICTIONS
        if method_ids is None:
            method_ids = ["M1", "M2", "M3", "M4"]
    elif suite == "full":
        if not allow_full:
            logger.error("Full-343 需要 --allow-full 确认！")
            return False
        from config import EXP5_DATASET_CSV
        combos = METHOD_COMBOS
        eval_csv = EXP5_DATASET_CSV
        raw_output = RAW_RESPONSES
        parsed_output = PARSED_PREDICTIONS
        if method_ids is None:
            method_ids = ["M1", "M2", "M3", "M4"]
    else:
        logger.error(f"未知 suite: {suite}")
        return False

    logger.info("=" * 60)
    logger.info("阶段: LLM API 调用")
    logger.info(f"Suite: {suite}, Methods: {method_ids}")
    logger.info(f"Model: {LLM_MODEL}, Dry run: {dry_run}, Limit: {limit or 'unlimited'}")
    logger.info("=" * 60)

    if not os.path.exists(eval_csv):
        logger.error(f"评估集不存在: {eval_csv}")
        return False

    # 加载数据
    eval_df = pd.read_csv(eval_csv, encoding="utf-8-sig")
    logger.info(f"加载评估集: {len(eval_df)} 条")

    full_df = _load_full_dataset()
    patch_index = _load_patch_index()

    # 构建任务
    tasks = []
    for method_id in method_ids:
        if method_id not in combos:
            logger.warning(f"未知方法: {method_id}, 跳过")
            continue
        combo = combos[method_id]
        prompt_type = combo["prompt"]
        context_type = combo["context"]

        for _, row in eval_df.iterrows():
            pr_id = str(row["pr_id"])
            context_text = build_context(row, context_type, patch_index, full_df)

            is_merged = row.get("is_merged_bool",
                                row.get("is_merged", False))
            if hasattr(is_merged, "item"):
                is_merged = bool(is_merged.item())
            elif isinstance(is_merged, str):
                is_merged = is_merged.lower() in ("true", "1", "yes")
            else:
                is_merged = bool(is_merged)

            tasks.append({
                "method_id": method_id,
                "prompt_type": prompt_type,
                "context_type": context_type,
                "pr_id": pr_id,
                "repo": row.get("repo", ""),
                "is_merged": is_merged,
                "context_text": context_text,
                "context_length": len(context_text),
            })

    logger.info(f"总任务数: {len(tasks)} ({len(method_ids)} 方法 × {len(eval_df)} 样本)")

    if dry_run:
        logger.info("Dry run 模式，跳过 API 调用")
        # 仍输出任务列表摘要
        for t in tasks[:5]:
            logger.info(f"  示例任务: {t['method_id']} | {t['prompt_type']}+{t['context_type']} | "
                        f"{t['pr_id']} | {t['repo']} | len={t['context_length']}")
        if len(tasks) > 5:
            logger.info(f"  ... 共 {len(tasks)} 任务")
        return True

    if not LLM_API_KEY:
        logger.warning("未设置 DEEPSEEK_API_KEY/LLM_API_KEY 环境变量！")
        logger.warning("请设置后运行: set DEEPSEEK_API_KEY=your-key")
        return False

    # 断点续跑
    completed = _load_completed_tasks_4x4(raw_output)
    logger.info(f"  已完成: {len(completed)}")

    pending = [t for t in tasks
               if (t["method_id"], str(t["pr_id"])) not in completed]

    if limit and limit > 0:
        pending = pending[:limit]

    if not pending:
        logger.info("所有任务已完成")
    else:
        logger.info(f"  待处理: {len(pending)}")
        processed = 0
        t_start = time.time()

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
                    "method_id": task["method_id"],
                    "prompt_type": task["prompt_type"],
                    "context_type": task["context_type"],
                    "pr_id": task["pr_id"],
                    "repo": task["repo"],
                    "is_merged": task["is_merged"],
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
                    with open(raw_output, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

                processed += 1
                if processed % 10 == 0:
                    elapsed = time.time() - t_start
                    speed = processed / max(elapsed, 1)
                    remaining = (len(pending) - processed) / max(speed, 0.01)
                    logger.info(f"  进度: {processed}/{len(pending)} "
                                f"({speed:.1f}/s, ETA {remaining:.0f}s)")

        elapsed_total = time.time() - t_start
        logger.info(f"API 调用完成: {processed}/{len(pending)}, 总耗时 {elapsed_total:.0f}s")

    # 导出解析预测
    logger.info("导出解析预测...")
    export_parsed_predictions_4x4(raw_output, parsed_output)
    logger.info("=" * 60)

    return True


def export_parsed_predictions_4x4(raw_path: str = None, output_path: str = None):
    """从 raw_responses.jsonl 导出 CSV"""
    raw_path = raw_path or RAW_RESPONSES
    output_path = output_path or PARSED_PREDICTIONS

    if not os.path.exists(raw_path):
        logger.warning(f"raw_responses 不存在: {raw_path}")
        return

    rows = []
    with open(raw_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            parsed = rec.get("parsed_data") or {}
            review_comments = parsed.get("review_comments", [])
            risk_factors = parsed.get("risk_factors", [])

            rows.append({
                "method_id": rec.get("method_id", ""),
                "prompt_type": rec.get("prompt_type", ""),
                "context_type": rec.get("context_type", ""),
                "pr_id": rec.get("pr_id", ""),
                "repo": rec.get("repo", ""),
                "is_merged": rec.get("is_merged", False),
                "api_success": rec.get("api_success", False),
                "parse_success": rec.get("parse_success", False),
                "duration_ms": rec.get("duration_ms", 0),
                "context_length": rec.get("context_length", 0),
                "merge_prediction": parsed.get("merge_prediction", ""),
                "merge_probability": parsed.get("merge_probability", None),
                "unmerged_risk_score": parsed.get("unmerged_risk_score", None),
                "confidence": parsed.get("confidence", ""),
                "evidence_summary": parsed.get("evidence_summary", ""),
                "num_risk_factors": len(risk_factors),
                "risk_factors": " || ".join(risk_factors) if risk_factors else "",
                "num_review_comments": len(review_comments),
                "review_severities": ", ".join(
                    c.get("severity", "?") for c in review_comments
                ),
            })

    if rows:
        pred_df = pd.DataFrame(rows)
        pred_df.to_csv(output_path, index=False, encoding="utf-8-sig")
        logger.info(f"解析预测已保存: {output_path} ({len(rows)} 行)")
    else:
        logger.warning("无可用预测数据")


# 兼容旧名
def export_parsed_predictions():
    export_parsed_predictions_4x4(RAW_RESPONSES, PARSED_PREDICTIONS)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="balanced",
                        choices=["improved-4x4", "balanced", "hard-fp", "full"])
    parser.add_argument("--methods", nargs="+", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--allow-full", action="store_true")
    args = parser.parse_args()
    run_llm_experiment(
        suite=args.suite,
        method_ids=args.methods,
        dry_run=args.dry_run,
        limit=args.limit,
        allow_full=args.allow_full,
    )
