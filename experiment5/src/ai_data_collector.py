"""
GitHub API 增强数据采集模块

功能:
  1. 使用 GitHub Search API 搜索含 AI 关键词的 closed PR
  2. 对候选 PR 拉取详情、files、commits、reviews、review_comments
  3. 多线程并行拉取，支持断点续跑
  4. AI 检测并记录 ai_detection_reason

输出:
  - results/raw/ai_pr_candidates.json    搜索候选列表
  - results/raw/ai_pr_collected.json     完整采集数据
  - results/raw/ai_pr_collected_checkpoint.json  断点文件
"""

import json
import os
import sys
import time
import csv
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Any, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

# 确保 src 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    GITHUB_TOKEN,
    GITHUB_API_BASE,
    ORIGINAL_REPOS,
    EXTENDED_REPOS,
    ALL_REPOS,
    MAX_PER_REPO,
    SEARCH_PER_PAGE,
    MAX_SEARCH_PAGES,
    MAX_WORKERS,
    REQUEST_TIMEOUT,
    TARGET_TOTAL_SAMPLES,
    RANDOM_SEED,
    AI_CANDIDATES_JSON,
    AI_COLLECTED_JSON,
    AI_COLLECTED_CHECKPOINT,
    RESULTS_RAW_DIR,
    logger,
)
from ai_detection import detect_ai_generated

# ============================================================
# GitHub API 请求工具
# ============================================================
_write_lock = Lock()
_rate_lock = Lock()
_last_core_request = 0.0
_last_search_request = 0.0
_CORE_DELAY = 0.15   # 核心 API 最小间隔 (s)
_SEARCH_DELAY = 2.5   # 搜索 API 最小间隔 (s)


def _rate_limit_wait(is_search: bool = False):
    """简单的请求频率控制"""
    global _last_core_request, _last_search_request
    now = time.time()
    if is_search:
        elapsed = now - _last_search_request
        min_delay = _SEARCH_DELAY
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        _last_search_request = time.time()
    else:
        elapsed = now - _last_core_request
        min_delay = _CORE_DELAY
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        _last_core_request = time.time()


def github_api_request(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    is_search: bool = False,
    accept: Optional[str] = None,
) -> Tuple[int, Dict[str, Any], str]:
    """
    发送 GitHub API 请求。

    返回:
        (status_code: int, data: dict, error_msg: str)
    """
    _rate_limit_wait(is_search=is_search)

    if params is None:
        params = {}
    # 过滤掉 None 值
    params = {k: v for k, v in params.items() if v is not None}
    query_string = urlencode(params)
    url = f"{GITHUB_API_BASE}{path}"
    if query_string:
        url += f"?{query_string}"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": accept or "application/vnd.github.v3+json",
        "User-Agent": "experiment5-ai-data-collector",
    }

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            return resp.status, data, ""
    except HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")[:500]
        except Exception:
            pass
        if e.code == 403 and "rate limit" in error_body.lower():
            # 被限频，等待后重试
            logger.warning(f"触发 GitHub 频率限制，等待 60s...")
            time.sleep(60)
            # 重试一次
            try:
                req = Request(url, headers=headers)
                with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    raw = resp.read()
                    data = json.loads(raw.decode("utf-8"))
                    return resp.status, data, ""
            except Exception as e2:
                return 0, {}, f"Rate limited retry failed: {e2}"
        elif e.code == 422:
            return e.code, {}, f"Validation failed (422): {error_body[:200]}"
        return e.code, {}, f"HTTP {e.code}: {error_body[:200]}"
    except URLError as e:
        return 0, {}, f"Network error: {e}"
    except json.JSONDecodeError as e:
        return 0, {}, f"JSON parse error: {e}"
    except Exception as e:
        return 0, {}, f"Unexpected error: {e}"


def github_api_paginated(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    max_pages: int = 10,
    per_page: int = 100,
    is_search: bool = False,
) -> List[Dict[str, Any]]:
    """
    分页拉取 GitHub API。

    返回:
        List[dict]: 所有页的合并结果
    """
    if params is None:
        params = {}
    params["per_page"] = per_page

    all_items = []
    for page in range(1, max_pages + 1):
        params["page"] = page
        status, data, error = github_api_request(
            path, params=params, is_search=is_search
        )
        if error:
            logger.warning(f"  分页请求失败 page={page}: {error}")
            break

        if is_search:
            items = data.get("items", [])
        else:
            items = data if isinstance(data, list) else [data]

        if not items:
            break

        all_items.extend(items)

        if is_search and len(items) < per_page:
            break
        if not is_search and len(items) < per_page:
            break

    return all_items


# ============================================================
# PR 数据提取
# ============================================================
def _safe_str(value: Any) -> str:
    """安全转换为字符串"""
    if value is None:
        return ""
    return str(value)


def _clean_review_comments_text(review_comments: List[Dict]) -> str:
    """格式化 review comments 文本（与实验一一致）"""
    parts = []
    for cmt in review_comments:
        user_login = cmt.get("user", {}).get("login", "unknown") if cmt.get("user") else "unknown"
        body = cmt.get("body", "")
        if body:
            parts.append(f"[Inline on {cmt.get('path', '?')} L{cmt.get('line', '?')}]: {body}")
    return "\n".join(parts)


def _extract_reviews_text(reviews: List[Dict]) -> str:
    """格式化 reviews 文本"""
    parts = []
    for rev in reviews:
        user_login = rev.get("user", {}).get("login", "unknown") if rev.get("user") else "unknown"
        body = rev.get("body", "")
        if body:
            parts.append(f"[Review by {user_login}]: {body}")
    return "\n".join(parts)


def extract_pr_data(
    detail: Dict,
    files: List[Dict],
    commits: List[Dict],
    reviews: List[Dict],
    review_comments: List[Dict],
    ai_detection_reason: str = "",
) -> Dict[str, Any]:
    """
    从 GitHub API 原始数据提取结构化 PR 特征。

    字段尽量与实验一 dataset.csv 一致。
    """
    pr_id = detail.get("id", "")
    pr_number = detail.get("number", "")
    repo_full = detail.get("base", {}).get("repo", {}).get("full_name", "")

    title = detail.get("title") or ""
    body = detail.get("body") or ""
    author = detail.get("user", {}).get("login", "") if detail.get("user") else ""
    created_at = detail.get("created_at", "")

    is_merged = detail.get("merged", False) or detail.get("merged_at") is not None
    merge_status = "merged" if is_merged else "closed_not_merged"

    additions = detail.get("additions", 0)
    deletions = detail.get("deletions", 0)
    changed_files_count = detail.get("changed_files", len(files))

    # 文件列表
    changed_files_list = [f.get("filename", "") for f in files]

    # commit 信息
    commit_messages = []
    for c in commits:
        msg = c.get("commit", {}).get("message", "")
        first_line = msg.split("\n")[0].strip() if msg else ""
        if first_line:
            commit_messages.append(first_line)
    commit_messages_str = " | ".join(commit_messages)

    # review 信息
    review_decision = ""
    for rev in reviews:
        state = rev.get("state", "")
        if state in ("APPROVED", "CHANGES_REQUESTED"):
            review_decision = state
            break
        elif state == "COMMENTED" and not review_decision:
            review_decision = "COMMENTED"
    if not review_decision:
        review_decision = "NONE"

    # review comments 文本
    review_comments_text = _clean_review_comments_text(review_comments)
    reviews_text = _extract_reviews_text(reviews)
    all_review_text = "\n".join(
        [t for t in [reviews_text, review_comments_text] if t]
    )

    # 标签
    labels = detail.get("labels", [])
    label_names = [lbl.get("name", "") for lbl in labels]

    # PR 长度
    pr_length = len(title) + len(body) if body else len(title)

    # 文件类型分类
    code_files, doc_files, config_files, test_files = 0, 0, 0, 0
    doc_exts = {".md", ".rst", ".txt", ".doc", ".pdf"}
    config_exts = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml"}
    test_patterns = ["test", "spec", "__test__", "__tests__"]
    for fname in changed_files_list:
        ext = os.path.splitext(fname)[1].lower()
        base = os.path.basename(fname).lower()
        if any(p in base or p in fname.lower() for p in test_patterns):
            test_files += 1
        elif ext in doc_exts:
            doc_files += 1
        elif ext in config_exts:
            config_files += 1
        else:
            code_files += 1

    return {
        # --- PR 基本信息 ---
        "pr_id": pr_id,
        "pr_number": pr_number,
        "repo": repo_full,
        "title": title,
        "body": body,
        "pr_length": pr_length,
        "author": author,
        "created_at": created_at,
        # --- 合并信息 ---
        "is_merged": is_merged,
        "merge_status": merge_status,
        # --- 代码修改 ---
        "num_changed_files": changed_files_count,
        "total_additions": additions,
        "total_deletions": deletions,
        "changed_files_list": ", ".join(changed_files_list),
        "num_code_files": code_files,
        "num_doc_files": doc_files,
        "num_config_files": config_files,
        "num_test_files": test_files,
        # --- commit 信息 ---
        "num_commits": len(commits),
        "commit_messages": commit_messages_str,
        # --- review 信息 (仅用于评价，不进入模型输入) ---
        "num_reviewers": len(set(
            (r.get("user") or {}).get("login", "")
            for r in reviews
            if (r.get("user") or {}).get("login")
        )),
        "review_decision": review_decision,
        "num_review_comments": len(review_comments) + len(reviews),
        "num_inline_comments": len(review_comments),
        "review_comments_text": all_review_text[:3000],
        # --- 标签 ---
        "num_labels": len(labels),
        "label_names": ", ".join(label_names),
        # --- 元信息 ---
        "has_ai_reviewer": False,  # 增强采集中默认 False
        "has_ai_generated_code": True,
        "ai_detection_reason": ai_detection_reason,
        # --- 原始数据 (供复核) ---
        "_files": files,
        "_commits": commits,
        "_reviews": reviews,
        "_review_comments": review_comments,
    }


# ============================================================
# 搜索候选 PR
# ============================================================
def _build_search_keyword_groups() -> List[str]:
    """构建搜索关键词组（每组可独立作为 OR 查询）"""
    return [
        '(copilot OR chatgpt OR gpt OR claude OR cursor OR codex)',
        '("ai generated" OR "ai-generated" OR "generated by ai" OR "generated with ai")',
        '(openai OR deepseek OR qwen)',
        '("co-authored-by: copilot" OR "code agent" OR "ai agent")',
    ]


def search_ai_prs_for_repo(
    repo: str, max_per_repo: int = MAX_PER_REPO
) -> List[Dict[str, Any]]:
    """
    搜索指定仓库的 AI 相关 PR。

    返回:
        List[dict]: 候选 PR 列表 (GitHub search items)
    """
    logger.info(f"搜索仓库: {repo}")
    keyword_groups = _build_search_keyword_groups()
    all_candidates = {}
    total_found = 0

    for kg in keyword_groups:
        query = f'repo:{repo} is:pr state:closed {kg} in:title,body'
        logger.info(f"  搜索: {query[:120]}...")

        status, data, error = github_api_request(
            "/search/issues",
            params={"q": query, "per_page": SEARCH_PER_PAGE, "sort": "created", "order": "desc"},
            is_search=True,
            accept="application/vnd.github.v3+json",
        )

        if error:
            logger.warning(f"  搜索失败: {error}")
            continue

        total_count = data.get("total_count", 0)
        items = data.get("items", [])
        logger.info(f"  匹配总数: {total_count}, 本页获取: {len(items)}")

        # 如果结果较多，分页获取
        if total_count > SEARCH_PER_PAGE and len(items) < min(total_count, MAX_SEARCH_PAGES * SEARCH_PER_PAGE):
            for page in range(2, MAX_SEARCH_PAGES + 1):
                if len(items) >= total_count:
                    break
                s2, d2, e2 = github_api_request(
                    "/search/issues",
                    params={
                        "q": query,
                        "per_page": SEARCH_PER_PAGE,
                        "page": page,
                        "sort": "created",
                        "order": "desc",
                    },
                    is_search=True,
                )
                if e2 or not d2.get("items"):
                    break
                items.extend(d2["items"])
                if len(d2["items"]) < SEARCH_PER_PAGE:
                    break

        for item in items:
            pr_key = str(item.get("number", ""))
            if pr_key not in all_candidates:
                all_candidates[pr_key] = {
                    "number": item.get("number"),
                    "title": item.get("title", ""),
                    "body": item.get("body", ""),
                    "state": item.get("state", ""),
                    "created_at": item.get("created_at", ""),
                    "updated_at": item.get("updated_at", ""),
                    "user_login": item.get("user", {}).get("login", "") if item.get("user") else "",
                    "labels": [l.get("name", "") for l in item.get("labels", [])],
                    "html_url": item.get("html_url", ""),
                    "repo": repo,
                }

        total_found = len(all_candidates)
        if total_found >= max_per_repo:
            logger.info(f"  已达到每仓库上限 {max_per_repo}，停止搜索 {repo}")
            break

    candidates = list(all_candidates.values())
    # 限制每仓库数量
    if len(candidates) > max_per_repo:
        # 随机采样避免时间偏置
        import random
        random.seed(RANDOM_SEED)
        random.shuffle(candidates)
        candidates = candidates[:max_per_repo]

    logger.info(f"  仓库 {repo} 去重后候选: {len(candidates)}")
    return candidates


# ============================================================
# 采集完整 PR 数据
# ============================================================
def collect_single_pr(
    repo: str, pr_number: int, pr_basic: Dict
) -> Optional[Dict[str, Any]]:
    """
    采集单个 PR 的完整数据（详情 + files + commits + reviews + comments）。

    返回:
        dict 或 None（失败时）
    """
    logger.debug(f"采集 PR: {repo}#{pr_number}")
    collected = {"repo": repo}

    # 1. PR 详情
    status, detail, error = github_api_request(
        f"/repos/{repo}/pulls/{pr_number}"
    )
    if error:
        logger.warning(f"  获取 PR #{pr_number} 详情失败: {error}")
        return None
    collected["detail"] = detail

    # 2. Files
    files = github_api_paginated(
        f"/repos/{repo}/pulls/{pr_number}/files",
        max_pages=5,
    )
    collected["files"] = files

    # 3. Commits
    commits = github_api_paginated(
        f"/repos/{repo}/pulls/{pr_number}/commits",
        max_pages=5,
    )
    collected["commits"] = commits

    # 4. Reviews
    reviews = github_api_paginated(
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        max_pages=5,
    )
    collected["reviews"] = reviews

    # 5. Review Comments (inline)
    review_comments = github_api_paginated(
        f"/repos/{repo}/pulls/{pr_number}/comments",
        max_pages=5,
    )
    collected["review_comments"] = review_comments

    return collected


def run_ai_detection_on_collected(
    collected: Dict[str, Any]
) -> Tuple[bool, str]:
    """对采集到的数据运行 AI 检测"""
    detail = collected.get("detail", {})
    commits = collected.get("commits", [])
    labels = detail.get("labels", [])

    title = detail.get("title") or ""
    body = detail.get("body") or ""
    author = (detail.get("user") or {}).get("login", "")

    commit_messages_list = [
        (c.get("commit", {}).get("message", "").split("\n")[0].strip())
        for c in commits
    ]
    commit_messages_str = " | ".join(commit_messages_list)

    label_names = ", ".join(
        [lbl.get("name", "") for lbl in labels]
    )

    # Review text (也可用于检测)
    reviews = collected.get("reviews", [])
    review_comments = collected.get("review_comments", [])
    review_text = _clean_review_comments_text(review_comments)
    reviews_text = _extract_reviews_text(reviews)
    all_review_text = "\n".join([t for t in [reviews_text, review_text] if t])

    return detect_ai_generated(
        title=title,
        body=body,
        commit_messages=commit_messages_str,
        label_names=label_names,
        author=author,
        review_comments_text=all_review_text,
    )


# ============================================================
# 主采集流程
# ============================================================
def _load_json_safe(filepath: str) -> Optional[Any]:
    """安全加载 JSON"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"加载 {filepath} 失败: {e}")
        return None


def _save_json_safe(filepath: str, data: Any):
    """安全保存 JSON（线程安全）"""
    with _write_lock:
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)


def _load_seed_pr_keys() -> set:
    """加载 seed 数据中的 (repo, pr_number) 键集合"""
    seed_csv = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "results", "processed", "ai_generated_dataset_seed.csv",
    )
    keys = set()
    if not os.path.exists(seed_csv):
        return keys
    try:
        with open(seed_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                keys.add((row.get("repo", ""), int(row.get("pr_number", 0))))
    except Exception:
        pass
    return keys


def collect_ai_prs(
    max_samples: int = TARGET_TOTAL_SAMPLES,
    resume: bool = True,
    skip_search: bool = False,
) -> bool:
    """
    主采集函数。

    流程:
      1. 对各仓库搜索候选 PR
      2. 排除 seed 中已存在的 PR
      3. 多线程并行采集完整数据
      4. 运行 AI 检测，记录 ai_detection_reason
      5. 保存结果

    参数:
        max_samples: 目标样本数
        resume: 是否支持断点续跑

    返回:
        bool: 成功返回 True
    """
    logger.info("=" * 60)
    logger.info("阶段: Enhanced 数据采集")
    logger.info(f"目标样本数: {max_samples}")
    logger.info(f"多线程工作数: {MAX_WORKERS}")
    logger.info("=" * 60)

    # 加载 seed 键（去重用）
    seed_keys = _load_seed_pr_keys()
    logger.info(f"Seed 已有 PR 数: {len(seed_keys)}")

    # ---- 阶段1: 搜索候选 PR ----
    if skip_search and os.path.exists(AI_CANDIDATES_JSON):
        logger.info("阶段1: 跳过搜索，加载已有候选列表...")
        all_candidates = _load_json_safe(AI_CANDIDATES_JSON) or []
        logger.info(f"  加载候选: {len(all_candidates)}")
    else:
        logger.info("阶段1: 搜索候选 PR...")
        all_candidates = []

        # 先搜原始仓库，再扩展仓库
        repos_order = ORIGINAL_REPOS + EXTENDED_REPOS
        for repo in repos_order:
            candidates = search_ai_prs_for_repo(repo, max_per_repo=MAX_PER_REPO)
            for c in candidates:
                c["_priority"] = (
                    0 if repo in ORIGINAL_REPOS else 1
                )
            all_candidates.extend(candidates)
            logger.info(f"  累计候选: {len(all_candidates)}")

        # 保存候选列表
        _save_json_safe(AI_CANDIDATES_JSON, all_candidates)
        logger.info(f"候选列表已保存: {AI_CANDIDATES_JSON}")

    # 去重（同 PR number + repo）
    seen = set()
    unique_candidates = []
    for c in all_candidates:
        key = (c["repo"], c["number"])
        if key not in seen:
            seen.add(key)
            unique_candidates.append(c)
    all_candidates = unique_candidates

    # 排除 seed 中已存在的
    new_candidates = [
        c for c in all_candidates
        if (c["repo"], c["number"]) not in seed_keys
    ]
    logger.info(
        f"候选 PR: {len(all_candidates)} 总计, "
        f"{len(new_candidates)} 新增 (排除 {len(all_candidates) - len(new_candidates)} 个 seed 重复)"
    )

    if not new_candidates:
        logger.warning("没有新的候选 PR 可采集")
        # 仍然保存空的 collected
        _save_json_safe(AI_COLLECTED_JSON, [])
        return True

    # ---- 阶段2: 多线程采集完整数据 ----
    logger.info(f"阶段2: 多线程采集 {len(new_candidates)} 个候选 PR 的完整数据...")

    # 加载 checkpoint
    checkpoint = {}
    if resume:
        checkpoint = _load_json_safe(AI_COLLECTED_CHECKPOINT) or {}
        logger.info(f"  断点恢复: 已有 {len(checkpoint)} 条已采集数据")

    # 在 checkpoint 中存储时使用 "repo#number" 作为键
    def ckpt_key(repo: str, number: int) -> str:
        return f"{repo}#{number}"

    collected_results = dict(checkpoint)  # key -> collected_data
    failed_prs = []

    # 过滤掉已完成的
    remaining = [
        c for c in new_candidates
        if ckpt_key(c["repo"], c["number"]) not in checkpoint
    ]

    if not remaining:
        logger.info("所有候选 PR 已在 checkpoint 中完成")
    else:
        logger.info(f"  待采集: {len(remaining)}, 已完成: {len(checkpoint)}")

        completed_count = 0
        batch_save_interval = 10

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_pr = {}
            for c in remaining:
                future = executor.submit(
                    collect_single_pr,
                    c["repo"],
                    c["number"],
                    c,
                )
                future_to_pr[future] = c

            for future in as_completed(future_to_pr):
                c = future_to_pr[future]
                key = ckpt_key(c["repo"], c["number"])
                try:
                    result = future.result(timeout=120)
                    if result is not None:
                        # 运行 AI 检测
                        has_ai, reason = run_ai_detection_on_collected(result)
                        result["_ai_detection"] = {
                            "has_ai_generated_code": has_ai,
                            "ai_detection_reason": reason,
                        }
                        collected_results[key] = result
                    else:
                        failed_prs.append(key)
                except Exception as e:
                    logger.warning(f"采集失败 {key}: {e}")
                    failed_prs.append(key)

                completed_count += 1

                # 定期保存 checkpoint
                if completed_count % batch_save_interval == 0:
                    _save_json_safe(AI_COLLECTED_CHECKPOINT, collected_results)
                    logger.info(
                        f"  进度: {completed_count}/{len(remaining)} "
                        f"(成功: {len(collected_results) - len(checkpoint)}, "
                        f"失败: {len(failed_prs)})"
                    )

        # 最终保存 checkpoint
        _save_json_safe(AI_COLLECTED_CHECKPOINT, collected_results)

    logger.info(
        f"采集完成: 成功 {len(collected_results)}, 失败 {len(failed_prs)}"
    )

    # ---- 阶段3: 提取结构化数据并保存 ----
    logger.info("阶段3: 提取结构化数据...")
    extracted_prs = []

    for key, raw in collected_results.items():
        detail = raw.get("detail", {})
        files = raw.get("files", [])
        commits = raw.get("commits", [])
        reviews = raw.get("reviews", [])
        review_comments = raw.get("review_comments", [])

        ai_info = raw.get("_ai_detection", {})
        ai_reason = ai_info.get("ai_detection_reason", "")
        has_ai = ai_info.get("has_ai_generated_code", True)

        if not has_ai:
            # 搜索候选中但 AI 检测未通过 — 记录但标记
            ai_reason = ai_reason or "search candidate but AI detection negative"

        pr_data = extract_pr_data(
            detail, files, commits, reviews, review_comments,
            ai_detection_reason=ai_reason,
        )
        # 覆盖 has_ai_generated_code 为检测结果
        pr_data["has_ai_generated_code"] = has_ai

        # 保留原始数据引用
        pr_data["_raw_ref"] = key
        extracted_prs.append(pr_data)

    # 只保留 AI 检测通过的
    ai_positive = [p for p in extracted_prs if p["has_ai_generated_code"]]
    logger.info(
        f"AI 检测通过: {len(ai_positive)}/{len(extracted_prs)}"
    )

    # 按优先级排序：原始仓库优先
    def sort_key(pr):
        priority = 0 if pr["repo"] in ORIGINAL_REPOS else 1
        return (priority, pr["repo"], pr["pr_number"])

    ai_positive.sort(key=sort_key)

    # 限制总数
    if len(ai_positive) > max_samples:
        ai_positive = ai_positive[:max_samples]

    # 保存采集数据
    collected_output = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "total_candidates": len(all_candidates),
        "total_collected": len(collected_results),
        "total_ai_positive": len(ai_positive),
        "total_failed": len(failed_prs),
        "prs": extracted_prs,  # 全部（含 AI 检测未通过的）
        "ai_positive_prs": ai_positive,  # 仅 AI 检测通过的
    }
    _save_json_safe(AI_COLLECTED_JSON, collected_output)
    logger.info(f"采集结果已保存: {AI_COLLECTED_JSON}")

    # ---- 阶段4: 统计摘要 ----
    logger.info("=" * 60)
    logger.info("Enhanced 数据采集完成")
    logger.info(f"  搜索候选:     {len(all_candidates)}")
    logger.info(f"  成功采集:     {len(collected_results)}")
    logger.info(f"  采集失败:     {len(failed_prs)}")
    logger.info(f"  AI 检测通过:  {len(ai_positive)}")
    logger.info("  仓库分布:")
    repo_counts = {}
    for p in ai_positive:
        repo_counts[p["repo"]] = repo_counts.get(p["repo"], 0) + 1
    for repo, count in sorted(repo_counts.items(), key=lambda x: -x[1]):
        logger.info(f"    {repo}: {count}")
    logger.info("=" * 60)

    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-samples", type=int, default=TARGET_TOTAL_SAMPLES)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    success = collect_ai_prs(
        max_samples=args.max_samples,
        resume=not args.no_resume,
    )
    sys.exit(0 if success else 1)
