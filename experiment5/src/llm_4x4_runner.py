"""
实验五 2.6.2 — AI 代码上的 Prompt × Context 全组合基线
========================================================
4 Prompt × 4 Context × 50 AI PR = 800 次 DeepSeek API 调用

Prompt 和 Context 构建:
  - Prompt 模板: 直接复用实验四 prompt_templates.py (P1-P4)
  - Context 构建: 直接复用实验四 context_builder.py (C1-C4)
  - 实验五只负责: 抽样50条AI PR + 多线程API调用 + 评估 + 热力图

组合矩阵 (B01-B16):
  B01-B04: P1 (Zero-shot)   × C1/C2/C3/C4
  B05-B08: P2 (Few-shot)    × C1/C2/C3/C4
  B09-B12: P3 (Role-based)  × C1/C2/C3/C4
  B13-B16: P4 (CoT)         × C1/C2/C3/C4

输出:
  results/processed/ai_llm_sample_50.csv
  results/processed/ai_llm_4x4_task_list.json
  results/predictions/llm_4x4_raw_responses.jsonl
  results/predictions/llm_4x4_parsed_predictions.csv
  results/evaluation/llm_4x4_metrics.json
  figures/09_llm_4x4_prompt_context_heatmap.png
"""

import json
import os
import sys
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

# ============================================================
# 关键步骤: 从实验四导入 Prompt 模板和 Context 构建器
# 实验四的模块依赖其自身 config.py/utils.py, 需要处理与实验五 config 的冲突
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_EXPERIMENT5_SRC = _THIS_DIR
_EXPERIMENT4_SRC = os.path.join(
    os.path.dirname(os.path.dirname(_THIS_DIR)), "experiment4", "src"
)

# 保存并清理 sys.modules 中的实验五模块 (避免 config 冲突)
_original_modules = dict(sys.modules)
_saved_exp5_modules = {}
for _mod_name in list(sys.modules.keys()):
    _mod = sys.modules[_mod_name]
    if hasattr(_mod, '__file__') and _mod.__file__ and \
       os.path.abspath(_mod.__file__).startswith(os.path.abspath(_EXPERIMENT5_SRC)):
        _saved_exp5_modules[_mod_name] = sys.modules.pop(_mod_name)

# 保存并重设 sys.path
_original_path = list(sys.path)
sys.path = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(_EXPERIMENT5_SRC)]
sys.path.insert(0, _EXPERIMENT4_SRC)

# --- 从实验四导入 Prompt 模板 ---
from prompt_templates import (                    # noqa: E402
    build_full_messages,
    build_few_shot_examples_text,
    OUTPUT_FORMAT_INSTRUCTION,
)

# --- 从实验四导入 Context 构建器 ---
from context_builder import (                     # noqa: E402
    build_context as exp4_build_context,
)

# --- 从实验四导入 utils ---
from utils import log as _exp4_log                 # noqa: E402

# 记录实验四导入过程中新增的模块 (它们指向实验四的代码)
_exp4_imported = set()
for _mod_name in list(sys.modules.keys()):
    if _mod_name not in _original_modules:
        _exp4_imported.add(_mod_name)
    elif _mod_name in _saved_exp5_modules:
        # 这个模块原本指向实验五, 但现在可能被覆盖了
        _exp4_imported.add(_mod_name)

# 恢复 sys.modules 中的实验五模块
for _mod_name, _mod in _saved_exp5_modules.items():
    sys.modules[_mod_name] = _mod

# 清理仍指向实验四的模块 (config, utils 等)
for _mod_name in list(_exp4_imported):
    _mod = sys.modules.get(_mod_name)
    if _mod and hasattr(_mod, '__file__') and _mod.__file__ and \
       os.path.abspath(_mod.__file__).startswith(os.path.abspath(_EXPERIMENT4_SRC)):
        del sys.modules[_mod_name]

# 恢复原始 sys.path
sys.path = _original_path
if _EXPERIMENT5_SRC not in sys.path:
    sys.path.insert(0, _EXPERIMENT5_SRC)

# 现在导入实验五自身的模块
from config import (                               # noqa: E402
    AI_DATASET_CSV,
    AI_PATCH_INDEX,
    RESULTS_PROCESSED_DIR,
    RESULTS_EVALUATION_DIR,
    FIGURES_DIR,
    MAX_WORKERS,
    RANDOM_SEED,
    logger,
)

# ============================================================
# API 配置
# ============================================================
LLM_API_KEY = os.environ.get(
    "LLM_API_KEY",
    os.environ.get("DEEPSEEK_API_KEY", "sk-7aeecb917944461d87380040892a7752"),
)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 2000
LLM_MAX_RETRIES = 2
LLM_TIMEOUT = 120

PREDICTIONS_DIR = os.path.join(os.path.dirname(RESULTS_PROCESSED_DIR), "predictions")
os.makedirs(PREDICTIONS_DIR, exist_ok=True)

# 4×4 输出路径
SAMPLE_50_CSV = os.path.join(RESULTS_PROCESSED_DIR, "ai_llm_sample_50.csv")
TASK_LIST_4X4 = os.path.join(RESULTS_PROCESSED_DIR, "ai_llm_4x4_task_list.json")
RAW_RESPONSES_4X4 = os.path.join(PREDICTIONS_DIR, "llm_4x4_raw_responses.jsonl")
PARSED_PREDICTIONS_4X4 = os.path.join(PREDICTIONS_DIR, "llm_4x4_parsed_predictions.csv")
METRICS_4X4 = os.path.join(RESULTS_EVALUATION_DIR, "llm_4x4_metrics.json")
HEATMAP_FIG = os.path.join(FIGURES_DIR, "09_llm_4x4_prompt_context_heatmap.png")

_jsonl_lock = Lock()


# ============================================================
# 辅助: 加载 AI 数据
# ============================================================
def _load_patch_index() -> Dict:
    """加载 patch index"""
    if os.path.exists(AI_PATCH_INDEX):
        with open(AI_PATCH_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_ai_features() -> Optional[pd.DataFrame]:
    """加载 ai_features_main.csv (AST/CFG 列, 给 C4 用)"""
    fp = os.path.join(RESULTS_PROCESSED_DIR, "ai_features_main.csv")
    if os.path.exists(fp):
        df = pd.read_csv(fp, encoding="utf-8-sig")
        return df
    return None


# ============================================================
# Few-shot 示例 (来自人类代码 validation set, 不泄露 AI PR)
# ============================================================
FEW_SHOT_EXAMPLES = [
    {
        "id": "fewshot_merged_1", "type": "merged",
        "repo": "microsoft/vscode",
        "title": "Fix copilot inline suggestion flickering",
        "body": "This PR fixes the flickering issue when Copilot suggestions appear "
                "during fast typing. The root cause was a race condition in the "
                "suggestion provider.",
    },
    {
        "id": "fewshot_merged_2", "type": "merged",
        "repo": "pandas-dev/pandas",
        "title": "Add type hints to DataFrame.groupby (generated with Copilot)",
        "body": "Used GitHub Copilot to add missing type hints across the groupby "
                "module. All existing tests pass.",
    },
    {
        "id": "fewshot_unmerged_1", "type": "not_merged",
        "repo": "kubernetes/kubernetes",
        "title": "WIP: refactor scheduler using GPT-generated code",
        "body": "I used ChatGPT to generate a new scheduler implementation. Still "
                "needs testing and review.",
    },
    {
        "id": "fewshot_unmerged_2", "type": "not_merged",
        "repo": "huggingface/transformers",
        "title": "Add new attention mechanism (Claude-assisted implementation)",
        "body": "Claude helped implement a novel attention mechanism. No benchmarks "
                "included. Breaking change to existing API.",
    },
]

# ============================================================
# 抽样 50 条 (目标 25 merged + 25 unmerged, 仓库分层)
# ============================================================

COMBO_LABELS = {
    ("P1", "C1"): "B01", ("P1", "C2"): "B02", ("P1", "C3"): "B03", ("P1", "C4"): "B04",
    ("P2", "C1"): "B05", ("P2", "C2"): "B06", ("P2", "C3"): "B07", ("P2", "C4"): "B08",
    ("P3", "C1"): "B09", ("P3", "C2"): "B10", ("P3", "C3"): "B11", ("P3", "C4"): "B12",
    ("P4", "C1"): "B13", ("P4", "C2"): "B14", ("P4", "C3"): "B15", ("P4", "C4"): "B16",
}


def sample_50_prs(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """从 AI 数据集中按仓库分层抽取 50 条 (25 merged + 25 unmerged)"""
    np.random.seed(seed)

    df = df.copy()
    df["is_merged_bool"] = df["is_merged"].apply(
        lambda x: True if str(x).lower() in ("true", "1") else False
    )
    df["pr_id_str"] = df["pr_id"].astype(str)

    merged_pool = df[df["is_merged_bool"]].copy()
    unmerged_pool = df[~df["is_merged_bool"]].copy()
    logger.info(f"抽样池: merged={len(merged_pool)}, unmerged={len(unmerged_pool)}")

    def pick_from_pool(pool, n_target):
        """按仓库分层抽样"""
        picked = []
        repos_in_pool = pool["repo"].value_counts()
        # 每个仓库分配配额
        quotas = {}
        for repo in repos_in_pool.index:
            q = max(1, min(n_target // max(len(repos_in_pool), 1),
                           min(repos_in_pool.get(repo, 0), 15)))
            quotas[repo] = q

        # 调整配额总和
        total = sum(quotas.values())
        if total > n_target:
            excess = total - n_target
            for repo in sorted(quotas, key=lambda r: -quotas[r]):
                if excess <= 0:
                    break
                reduce_by = min(excess, quotas[repo] - 1)
                quotas[repo] -= reduce_by
                excess -= reduce_by
        elif total < n_target:
            deficit = n_target - total
            for repo in sorted(quotas,
                               key=lambda r: -(len(pool[pool["repo"] == r]) - quotas.get(r, 0))):
                if deficit <= 0:
                    break
                available = len(pool[pool["repo"] == repo]) - quotas.get(repo, 0)
                add = min(deficit, available)
                quotas[repo] = quotas.get(repo, 0) + add
                deficit -= add

        for repo, q in quotas.items():
            repo_pool = pool[pool["repo"] == repo]
            picked.append(
                repo_pool if len(repo_pool) <= q
                else repo_pool.sample(q, random_state=seed)
            )

        result = pd.concat(picked, ignore_index=True) if picked else pd.DataFrame()
        if len(result) > n_target:
            result = result.sample(n_target, random_state=seed)
        return result

    merged_sel = pick_from_pool(merged_pool, 25)
    unmerged_sel = pick_from_pool(unmerged_pool, 25)
    result = pd.concat([merged_sel, unmerged_sel], ignore_index=True)
    result = result.sample(frac=1, random_state=seed).reset_index(drop=True)

    n_m = result["is_merged_bool"].sum()
    logger.info(f"抽样 50 条: merged={n_m}, unmerged={50 - n_m}")
    for repo in sorted(result["repo"].unique()):
        sub = result[result["repo"] == repo]
        logger.info(f"  {repo}: {len(sub)} (merged={sub['is_merged_bool'].sum()})")

    return result


# ============================================================
# Context 构建: 复用实验四 context_builder.build_context
# ============================================================

def _prepare_row_for_exp4(row: pd.Series, features_df: Optional[pd.DataFrame]) -> pd.Series:
    """
    将 experiment5 的 AI PR 行转换为实验四 context_builder 期望的格式。
    实验四的 build_context 需要这些列:
      repo, pr_id, title, body, commit_messages, num_commits,
      num_changed_files, total_additions, total_deletions, code_churn,
      以及 AST/CFG 特征列 (对 C4 很重要)
    """
    pr_id_str = str(row.get("pr_id", ""))

    # 合并特征列 (AST/CFG)
    if features_df is not None:
        feat_match = features_df[features_df["pr_id"].astype(str) == pr_id_str]
        if len(feat_match) > 0:
            feat_row = feat_match.iloc[0]
            # 将特征列合并到 row
            for col in feat_match.columns:
                if col not in row.index and col != "pr_id":
                    row[col] = feat_row[col]

    # 补充可能缺失的列
    if "code_churn" not in row.index or pd.isna(row.get("code_churn")):
        adds = int(row.get("total_additions", 0) or 0)
        dels = int(row.get("total_deletions", 0) or 0)
        row["code_churn"] = adds + dels

    return row


def build_contexts_for_sample(
    sample_df: pd.DataFrame,
    patch_index: Dict,
    features_df: Optional[pd.DataFrame],
) -> Dict[str, Dict[str, str]]:
    """
    为 50 条样本构建 C1-C4 上下文。
    直接调用实验四的 build_context() 和 build_all_contexts()。

    Returns:
        {pr_id: {"C1": text, "C2": text, "C3": text, "C4": text}}
    """
    # 构建 patch_map (实验四格式: {pr_id: patch_entry})
    patch_map = {}
    for key, val in patch_index.items():
        patch_map[key] = val

    # 准备行
    prepared_rows = []
    for _, row in sample_df.iterrows():
        prepared = _prepare_row_for_exp4(row.copy(), features_df)
        prepared_rows.append(prepared)

    all_contexts = {}
    for row in prepared_rows:
        pr_id = row["pr_id"]
        pr_contexts = {}
        patch_entry = patch_map.get(str(pr_id))

        for ctx_type in ["C1", "C2", "C3", "C4"]:
            try:
                ctx_text = exp4_build_context(row, patch_entry, ctx_type)
                pr_contexts[ctx_type] = ctx_text
            except Exception as e:
                logger.error(f"构建上下文失败 pr_id={pr_id}, ctx={ctx_type}: {e}")
                pr_contexts[ctx_type] = f"[Context build error: {e}]"

        all_contexts[str(pr_id)] = pr_contexts

    # 统计上下文长度
    for ctx_type in ["C1", "C2", "C3", "C4"]:
        lengths = [len(ctxs.get(ctx_type, "")) for ctxs in all_contexts.values()]
        if lengths:
            avg_len = sum(lengths) / len(lengths)
            max_len = max(lengths)
            truncation_count = sum(1 for l in lengths if l > 10000)
            logger.info(f"  {ctx_type}: avg={avg_len:.0f} chars, "
                         f"max={max_len}, 超长={truncation_count}/{len(lengths)}")

    return all_contexts


# ============================================================
# API 调用
# ============================================================

def call_llm(messages: List[Dict]) -> Dict:
    """调用 DeepSeek API (多线程安全)"""
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
                return {"success": False, "error": str(e), "response_text": "",
                        "retry_count": attempt}

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

    # 2. ```json 代码块
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

    # 4. 修复尾部逗号
    try:
        fixed = text.strip()
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 5. 补齐截断的括号
    try:
        m2 = re.search(r'\{.*', text, re.DOTALL)
        if m2:
            s = m2.group(0)
            open_braces = s.count('{') - s.count('}')
            s += '}' * open_braces
            return json.loads(s)
    except (json.JSONDecodeError, Exception):
        pass

    return None


def _load_completed_4x4() -> set:
    """加载已完成任务 (断点续跑)"""
    completed = set()
    if os.path.exists(RAW_RESPONSES_4X4):
        with open(RAW_RESPONSES_4X4, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    completed.add((
                        rec.get("prompt_type", ""),
                        rec.get("context_type", ""),
                        str(rec.get("pr_id", "")),
                    ))
                except json.JSONDecodeError:
                    pass
    return completed


# ============================================================
# 主流程
# ============================================================

def run_llm_4x4_experiment(
    dry_run: bool = False,
    limit: int = 0,
) -> bool:
    """
    运行 4 Prompt × 4 Context 全组合实验。

    参数:
        dry_run: 只生成 task list，不调用 API
        limit: 限制 API 调用次数 (用于 smoke test)
    """
    PROMPT_TYPES = ["P1", "P2", "P3", "P4"]
    CONTEXT_TYPES = ["C1", "C2", "C3", "C4"]

    logger.info("=" * 60)
    logger.info("阶段 2.6.2: Prompt × Context 全组合基线 (4×4)")
    logger.info(f"  复用实验四: prompt_templates.py + context_builder.py")
    logger.info(f"  Prompts: {PROMPT_TYPES}")
    logger.info(f"  Contexts: {CONTEXT_TYPES}")
    logger.info(f"  Dry run: {dry_run}, Limit: {limit or 'unlimited'}")
    logger.info(f"  Model: {LLM_MODEL}")
    logger.info("=" * 60)

    # 1. 加载数据
    if not os.path.exists(AI_DATASET_CSV):
        logger.error(f"AI 数据集未找到: {AI_DATASET_CSV}")
        return False

    df = pd.read_csv(AI_DATASET_CSV, encoding="utf-8-sig")
    logger.info(f"加载 {len(df)} 条 AI PR")

    # 2. 抽样 50 条
    sample_df = sample_50_prs(df, seed=RANDOM_SEED)
    sample_df.to_csv(SAMPLE_50_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"抽样结果已保存: {SAMPLE_50_CSV}")

    patch_index = _load_patch_index()
    logger.info(f"Patch index: {len(patch_index)} 条目")

    features_df = _load_ai_features()
    logger.info(f"特征数据: {len(features_df) if features_df is not None else 0} 条目")

    # 3. 构建 C1-C4 上下文 (复用实验四 context_builder)
    logger.info("构建 C1-C4 上下文 (复用实验四 context_builder)...")
    all_contexts = build_contexts_for_sample(sample_df, patch_index, features_df)
    logger.info(f"上下文构建完成: {len(all_contexts)} 个 PR")

    # 4. 构建任务列表 (4 Prompt × 4 Context × 50 PR)
    tasks = []
    for prompt_type in PROMPT_TYPES:
        for ctx_type in CONTEXT_TYPES:
            for _, row in sample_df.iterrows():
                pr_id = str(row["pr_id"])
                ctx = all_contexts.get(pr_id, {}).get(ctx_type, "")
                combo = COMBO_LABELS.get((prompt_type, ctx_type), f"{prompt_type}_{ctx_type}")
                tasks.append({
                    "prompt_type": prompt_type,
                    "context_type": ctx_type,
                    "combo": combo,
                    "pr_id": pr_id,
                    "repo": row.get("repo", ""),
                    "is_merged": bool(row.get("is_merged_bool",
                                    str(row.get("is_merged", "")).lower() in ("true", "1"))),
                    "has_review_text": bool(str(row.get("review_comments_text", "")).strip()),
                    "context_text": ctx,
                    "context_length": len(ctx),
                })

    n_tasks = len(tasks)
    logger.info(f"总任务数: {n_tasks} "
                f"({len(PROMPT_TYPES)}×{len(CONTEXT_TYPES)}×{len(sample_df)})")
    logger.info(f"预计 API 调用次数: {n_tasks}")

    # 保存任务列表
    with open(TASK_LIST_4X4, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    logger.info(f"任务列表已保存: {TASK_LIST_4X4}")

    if dry_run:
        logger.info("Dry run 模式，跳过 API 调用")
        for combo in sorted(set(t["combo"] for t in tasks)):
            lens = [t["context_length"] for t in tasks if t["combo"] == combo]
            avg = sum(lens) / len(lens) if lens else 0
            logger.info(f"  {combo}: avg_context={avg:.0f} chars, "
                        f"min={min(lens) if lens else 0}, max={max(lens) if lens else 0}")
        return True

    if not LLM_API_KEY:
        logger.warning("未设置 LLM_API_KEY/DEEPSEEK_API_KEY 环境变量")
        logger.warning("当前仅生成任务列表 (dry run)")
        return True

    # 5. 多线程 API 调用 (断点续跑)
    logger.info(f"开始 API 调用 ({MAX_WORKERS} workers, 支持断点续跑)...")
    completed = _load_completed_4x4()
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
        t_start = time.time()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_task = {}
            for task in pending:
                # 复用实验四 build_full_messages 构建 Prompt
                if task["prompt_type"] == "P2":
                    messages = build_full_messages(
                        "P2", task["context_text"],
                        few_shot_examples=FEW_SHOT_EXAMPLES,
                    )
                else:
                    messages = build_full_messages(
                        task["prompt_type"], task["context_text"],
                    )
                future = executor.submit(call_llm, messages)
                future_to_task[future] = task

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    api_result = future.result(timeout=LLM_TIMEOUT + 10)
                except Exception as e:
                    api_result = {"success": False, "error": str(e), "response_text": ""}

                parsed = None
                parse_success = False
                if api_result.get("success") and api_result.get("response_text"):
                    parsed = parse_json_response(api_result["response_text"])
                    parse_success = parsed is not None

                record = {
                    "prompt_type": task["prompt_type"],
                    "context_type": task["context_type"],
                    "combo": task["combo"],
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
                    with open(RAW_RESPONSES_4X4, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

                processed += 1
                if processed % 50 == 0 or processed == len(pending):
                    elapsed = time.time() - t_start
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (len(pending) - processed) / rate if rate > 0 else 0
                    logger.info(f"  进度: {processed}/{len(pending)} "
                                f"({processed*100/len(pending):.1f}%), "
                                f"速率: {rate:.1f}/s, ETA: {eta:.0f}s")

        logger.info(f"API 调用完成: {processed}/{len(pending)}, "
                    f"总耗时: {time.time() - t_start:.1f}s")

    # 6. 导出解析预测
    logger.info("导出解析预测...")
    export_parsed_predictions_4x4()
    logger.info("=" * 60)
    return True


def export_parsed_predictions_4x4():
    """从 raw_responses.jsonl 导出 CSV"""
    if not os.path.exists(RAW_RESPONSES_4X4):
        logger.warning("llm_4x4_raw_responses.jsonl 不存在")
        return

    rows = []
    with open(RAW_RESPONSES_4X4, "r", encoding="utf-8") as f:
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
                "combo": rec.get("combo", ""),
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
        pred_df.to_csv(PARSED_PREDICTIONS_4X4, index=False, encoding="utf-8-sig")
        logger.info(f"解析预测已保存: {PARSED_PREDICTIONS_4X4} ({len(rows)} 行)")
    else:
        logger.warning("无可用预测数据")


# ============================================================
# 评估
# ============================================================

def compute_4x4_metrics() -> dict:
    """计算 4×4 全组合指标"""
    if not os.path.exists(PARSED_PREDICTIONS_4X4):
        logger.warning("llm_4x4_parsed_predictions.csv 不存在")
        return {}

    df = pd.read_csv(PARSED_PREDICTIONS_4X4, encoding="utf-8-sig")
    df_valid = df[df["parse_success"] == True].copy()
    logger.info(f"4x4 有效预测: {len(df_valid)}/{len(df)}")

    if len(df_valid) == 0:
        return {}

    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score,
        f1_score, roc_auc_score, confusion_matrix,
    )

    metrics = {}
    for combo, group in df_valid.groupby("combo"):
        y_true = group["is_merged"].astype(int).values
        y_pred = (group["merge_prediction"].str.lower() == "merged").astype(int).values

        try:
            probs = group["merge_probability"].fillna(0.5).astype(float)
            auc = roc_auc_score(y_true, probs) if len(set(y_true)) > 1 else None
        except Exception:
            auc = None

        cm = confusion_matrix(y_true, y_pred)
        pt = group["prompt_type"].iloc[0]
        ct = group["context_type"].iloc[0]

        metrics[combo] = {
            "combo": combo,
            "prompt_type": pt,
            "context_type": ct,
            "n_valid": len(group),
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
            "roc_auc": round(float(auc), 4) if auc is not None else None,
            "confusion_matrix": cm.tolist(),
        }

    metrics = dict(sorted(metrics.items()))

    with open(METRICS_4X4, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    logger.info(f"4x4 指标已保存: {METRICS_4X4}")

    logger.info("\n4×4 指标摘要 (F1):")
    for combo, m in metrics.items():
        logger.info(f"  {combo} ({m['prompt_type']}_{m['context_type']}): "
                    f"F1={m['f1']}, Acc={m['accuracy']}, AUC={m['roc_auc']}, n={m['n_valid']}")

    return metrics


# ============================================================
# 热力图
# ============================================================

def generate_4x4_heatmap():
    """生成 4×4 Prompt×Context 热力图 (figure 09)"""
    if not os.path.exists(METRICS_4X4):
        logger.warning("4x4 指标文件不存在，跳过热力图")
        return

    with open(METRICS_4X4, "r", encoding="utf-8") as f:
        metrics = json.load(f)
    if not metrics:
        return

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    PROMPT_LABELS = ["P1\nZero-shot", "P2\nFew-shot", "P3\nRole-based", "P4\nCoT"]
    CONTEXT_LABELS = ["C1\nDiff Only", "C2\n+PR Desc", "C3\n+Commit", "C4\nFull"]

    metrics_list = ["f1", "accuracy", "precision", "recall", "roc_auc"]
    matrices = {m: np.full((4, 4), np.nan) for m in metrics_list}

    for combo, vals in metrics.items():
        pt = vals.get("prompt_type", "")
        ct = vals.get("context_type", "")
        if not pt or not ct:
            continue
        p_idx = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(pt, -1)
        c_idx = {"C1": 0, "C2": 1, "C3": 2, "C4": 3}.get(ct, -1)
        if p_idx < 0 or c_idx < 0:
            continue
        for m in metrics_list:
            v = vals.get(m)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                matrices[m][p_idx, c_idx] = v

    fig, axes = plt.subplots(2, 3, figsize=(20, 13))
    axes = axes.flatten()

    for i, metric_name in enumerate(metrics_list):
        ax = axes[i]
        data = matrices[metric_name]
        mask = np.isnan(data)

        im = ax.imshow(data, cmap="YlOrRd", vmin=0.0, vmax=1.0, aspect="auto")
        ax.set_xticks(range(4))
        ax.set_xticklabels(CONTEXT_LABELS, fontsize=9)
        ax.set_yticks(range(4))
        ax.set_yticklabels(PROMPT_LABELS, fontsize=9)
        ax.set_title(metric_name.upper(), fontsize=13, fontweight="bold")

        for r in range(4):
            for c in range(4):
                if not mask[r, c]:
                    val = data[r, c]
                    text_color = "white" if val < 0.55 else "black"
                    ax.text(c, r, f"{val:.3f}", ha="center", va="center",
                            fontsize=10, fontweight="bold", color=text_color)

        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    # 第6格: 摘要
    ax = axes[5]
    ax.axis("off")
    best_items = sorted(metrics.items(),
                        key=lambda x: x[1].get("f1", 0) or 0, reverse=True)
    lines = [
        "4×4 Prompt×Context Matrix",
        "on AI-Generated PRs (n=50 sample)",
        "",
        f"Total combos evaluated: {len(metrics)} / 16",
    ]
    if best_items:
        best = best_items[0]
        lines.append(f"Best F1: {best[0]} = {best[1].get('f1', 0):.4f}")
        lines.append(f"Best Acc: {best[0]} = {best[1].get('accuracy', 0):.4f}")
    lines.append("")
    lines.append("Top-3 by F1:")
    for rank, (combo, vals) in enumerate(best_items[:3], 1):
        lines.append(f"  {rank}. {combo} F1={vals.get('f1', 0):.4f} "
                    f"Acc={vals.get('accuracy', 0):.4f}")

    ax.text(0.5, 0.5, "\n".join(lines), transform=ax.transAxes,
            fontsize=12, ha="center", va="center",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
            fontfamily="monospace")

    fig.suptitle("Prompt × Context Full Combination Baseline on AI-Generated PRs "
                 "(Experiment 5 §2.6.2, reusing Experiment 4 templates)",
                 fontsize=16, fontweight="bold")
    fig.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    fig.savefig(HEATMAP_FIG, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    logger.info(f"4×4 热力图已保存: {HEATMAP_FIG}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="4×4 Prompt×Context 全组合实验")
    parser.add_argument("--dry-run", action="store_true", help="只生成任务列表")
    parser.add_argument("--limit", type=int, default=0, help="限制 API 调用次数")
    parser.add_argument("--heatmap-only", action="store_true", help="仅生成热力图")
    parser.add_argument("--metrics-only", action="store_true", help="仅计算指标")
    args = parser.parse_args()

    if args.heatmap_only:
        generate_4x4_heatmap()
    elif args.metrics_only:
        compute_4x4_metrics()
        generate_4x4_heatmap()
    else:
        run_llm_4x4_experiment(dry_run=args.dry_run, limit=args.limit)
