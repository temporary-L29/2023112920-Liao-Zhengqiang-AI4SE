"""
增强上下文构建模块 — C5/C6/C7/C8

基于实验五 C4 基础上，增加:
  C5: Risk Checklist Context — AI 代码风险检查清单
  C6: Repository Policy Context — 仓库级规则
  C7: Historical Similar PR Context — 历史相似 PR
  C8: Full Improved Context — 完整增强上下文

遵循信息可用性约束: 不泄露目标 PR 的 merge 标签、review 结果等。
"""

import json
import os
import re
import sys
from typing import Dict, List, Any, Optional, Set

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    EXP5_DATASET_CSV,
    EXP5_PATCH_INDEX,
    EVAL_BALANCED_50,
    EVAL_BALANCED_120,
    EVAL_HARD_FP_40,
    IMPROVED_CONTEXTS,
    IMPROVED_CONTEXTS_50,
    TASK_LIST,
    TASK_LIST_IMPROVED_4X4,
    MAX_CONTEXT_TOKENS,
    MAX_DIFF_CHARS,
    MAX_BODY_CHARS,
    MAX_COMMIT_MSG_CHARS,
    RANDOM_SEED,
    logger,
)


# ============================================================
# 工具函数
# ============================================================
def _load_patch_index() -> Dict:
    if os.path.exists(EXP5_PATCH_INDEX):
        with open(EXP5_PATCH_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_full_dataset() -> pd.DataFrame:
    """加载完整实验五数据集（用于构建仓库级统计等）"""
    df = pd.read_csv(EXP5_DATASET_CSV, encoding="utf-8-sig")
    df["is_merged_bool"] = df["is_merged"].apply(
        lambda x: True if str(x).lower() in ("true", "1") else False
    )
    return df


def _is_test_file(fname: str) -> bool:
    """判断是否为测试文件"""
    fname_lower = fname.lower()
    test_patterns = ["test", "spec", "__tests__", "tests/", "/test/"]
    return any(p in fname_lower for p in test_patterns)


def _is_config_file(fname: str) -> bool:
    """判断是否为配置/CI/依赖文件"""
    fname_lower = fname.lower()
    config_patterns = [
        ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".lock",
        "dockerfile", "makefile", ".env", "requirements", "package.json",
        "cargo.toml", "setup.py", "setup.cfg", "pyproject.toml",
        ".github/", "jenkins", "travis", "circle", "gitlab-ci",
    ]
    return any(p in fname_lower for p in config_patterns)


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数 (中文字符=1 token, 英文单词~1.3 tokens)"""
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    other = len(text) - chinese_chars - len(re.findall(r'[a-zA-Z\s]', text))
    return chinese_chars + int(english_words * 1.3) + other // 2


# ============================================================
# 基础上下文 (复用实验五 C4)
# ============================================================
def build_base_context(row: pd.Series, patch_index: Dict) -> str:
    """构建 C4 基础上下文"""
    parts = [f"**Repository**: {row.get('repo', '?')}", f"**PR ID**: {row.get('pr_id', '?')}", ""]

    # Diff
    pr_id = str(row.get("pr_id", ""))
    pi = patch_index.get(pr_id, {})
    files = pi.get("files", [])

    parts.append("## Changed Files\n")
    for f in files:
        fname = f.get("filename", "?")
        status = f.get("status", "?")
        adds = f.get("additions", 0)
        dels = f.get("deletions", 0)
        test_marker = " [TEST]" if _is_test_file(fname) else ""
        config_marker = " [CONFIG]" if _is_config_file(fname) else ""
        parts.append(f"- `{fname}` ({status}, +{adds}/-{dels}){test_marker}{config_marker}")

    # 代码行
    added_lines = []
    for f in files:
        patch = f.get("patch", "")
        if patch:
            for line in patch.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    added_lines.append(line[1:])
    if added_lines:
        added_text = "\n".join(added_lines[:200])  # 限制行数
        if len(added_text) > 6000:
            added_text = added_text[:6000] + "\n... (truncated)"
        parts.append(f"\n## Added Code Lines\n```\n{added_text}\n```")

    # PR Description
    title = str(row.get("title", ""))
    body = str(row.get("body", ""))
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n... (truncated)"
    parts.append(f"## PR Description\n**Title**: {title}\n\n**Body**:\n{body}")

    # Commits
    commits = str(row.get("commit_messages", ""))
    if len(commits) > MAX_COMMIT_MSG_CHARS:
        commits = commits[:MAX_COMMIT_MSG_CHARS] + "\n... (truncated)"
    parts.append(f"## Commit Information\n"
                 f"Number of commits: {row.get('num_commits', 1)}\n"
                 f"Changed files: {row.get('num_changed_files', 0)}\n"
                 f"Lines added: {row.get('total_additions', '?')}, deleted: {row.get('total_deletions', '?')}\n"
                 f"**Commit Messages**:\n{commits}")

    return "\n\n".join(parts)


# ============================================================
# C5: Risk Checklist Context
# ============================================================
def build_risk_checklist(row: pd.Series, patch_index: Dict) -> str:
    """
    构建 AI 代码风险检查清单。

    观察事实，不给出 merge 标签！
    """
    pr_id = str(row.get("pr_id", ""))
    pi = patch_index.get(pr_id, {})
    files = pi.get("files", [])

    risks = []
    observations = []

    # 1. 测试文件检查
    n_test_files = sum(1 for f in files if _is_test_file(f.get("filename", "")))
    if n_test_files == 0:
        risks.append("⚠ MISSING_TESTS: No test files found in this PR")
    else:
        observations.append(f"✓ Has {n_test_files} test file(s)")

    # 2. 文件数量检查
    n_files = len(files)
    if n_files > 10:
        risks.append(f"⚠ LARGE_SCOPE: Changes {n_files} files (>10, may be too large)")
    elif n_files > 5:
        observations.append(f"• Moderate scope: {n_files} files changed")
    else:
        observations.append(f"• Small scope: {n_files} file(s) changed")

    # 3. 新增行数检查
    additions = int(row.get("total_additions", 0))
    deletions = int(row.get("total_deletions", 0))
    if additions > 500:
        risks.append(f"⚠ LARGE_ADDITIONS: +{additions} lines added (>500)")
    elif additions > 200:
        observations.append(f"• Moderate additions: +{additions} lines")
    else:
        observations.append(f"• Small additions: +{additions} lines")

    # 4. 配置/CI/依赖文件检查
    config_files = [f for f in files if _is_config_file(f.get("filename", ""))]
    if config_files:
        risks.append(f"⚠ CONFIG_DEP_CHANGE: Changes to config/CI/dependency files: "
                     f"{', '.join(f.get('filename', '?') for f in config_files[:3])}")

    # 5. 是否涉及核心模块或 public API
    core_keywords = ["public", "api", "export", "interface", "abstract", "core",
                     "main", "init", "index"]
    core_files = []
    for f in files:
        fname = f.get("filename", "")
        if any(kw in fname.lower() for kw in core_keywords):
            core_files.append(fname)
    if core_files:
        risks.append(f"⚠ CORE_MODULE: Changes to potentially core/API files: "
                     f"{', '.join(core_files[:3])}")

    # 6. PR body 检查
    body = str(row.get("body", ""))
    if len(body) < 100:
        risks.append("⚠ SHORT_DESCRIPTION: PR body is very short (<100 chars), may lack context")
    elif len(body) < 300:
        observations.append("• PR body is relatively short (<300 chars)")

    # 7. AI 工具痕迹
    ai_traces = []
    title_body = (str(row.get("title", "")) + " " + str(row.get("body", ""))).lower()
    ai_keywords = ["copilot", "chatgpt", "gpt", "claude", "cursor", "codex",
                   "generated by", "ai-generated", "code agent", "deepseek",
                   "qwen", "generated with", "co-authored-by: copilot"]
    for kw in ai_keywords:
        if kw in title_body:
            ai_traces.append(kw)
    if ai_traces:
        risks.append(f"⚠ AI_TOOL_TRACES: Found AI generation indicators: {', '.join(ai_traces)}")

    # 8. 是否修改 public API 但无文档
    doc_files = [f for f in files
                 if any(d in f.get("filename", "").lower()
                        for d in ["doc", "readme", "changelog", ".md", ".rst"])]
    has_api_change = any(
        "public" in (f.get("patch", "") or "") or "export" in (f.get("patch", "") or "")
        for f in files
    )
    if has_api_change and not doc_files:
        risks.append("⚠ API_CHANGE_NO_DOCS: Possible API change without documentation updates")

    # 组装
    parts = ["## AI Code Risk Checklist (C5)", ""]
    parts.append("The following risk signals are observed from the PR content ONLY. "
                 "They are NOT labels — use them to guide your analysis.\n")

    if risks:
        parts.append("### Risk Signals")
        for r in risks:
            parts.append(f"- {r}")
    else:
        parts.append("### Risk Signals\n- No obvious risk signals detected from automated checks.\n")

    if observations:
        parts.append("\n### Neutral Observations")
        for o in observations:
            parts.append(f"- {o}")

    # 添加自动生成痕迹分析
    commit_msgs = str(row.get("commit_messages", "")).lower()
    if "generated" in commit_msgs or "copilot" in commit_msgs or "ai" in commit_msgs:
        parts.append("\n### AI Generation Indicators in Commits")
        parts.append("- Commit messages contain AI generation references — review quality carefully.")

    if str(row.get("has_ai_generated_code", "")).lower() == "true":
        parts.append("- This PR is flagged as containing AI-generated code.")

    return "\n".join(parts)


# ============================================================
# C6: Repository Policy Context
# ============================================================
def build_repository_policy(row: pd.Series, full_df: pd.DataFrame,
                            exclude_pr_id: str) -> str:
    """
    构建仓库级策略上下文。

    使用 leave-one-out: 排除当前 PR 自己。
    """
    pr_id = exclude_pr_id
    repo = row.get("repo", "")

    # 同一仓库的其他 PR (leave-one-out)
    same_repo = full_df[(full_df["repo"] == repo) & (full_df["pr_id"].astype(str) != pr_id)]

    if same_repo.empty:
        return "## Repository Policy (C6)\n\nNo historical data available for this repository.\n"

    # 该仓库 AI PR 统计
    repo_total = len(same_repo)
    repo_merge_rate = same_repo["is_merged_bool"].mean()

    # 常见未合并原因关键词
    unmerged_repo = same_repo[~same_repo["is_merged_bool"]]
    unmerged_titles = " ".join(unmerged_repo["title"].fillna("").tolist())
    unmerged_keywords = []
    for kw in ["test", "documentation", "breaking", "WIP", "refactor", "draft",
               "dependency", "bump", "fail", "bug", "fix", "feature"]:
        count = unmerged_titles.lower().count(kw.lower())
        if count >= 2:
            unmerged_keywords.append(f"{kw}(×{count})")

    # 仓库是否有 AI agent policy 迹象
    has_ai_policy = False
    ai_policy_signals = []
    policy_keywords = ["ai-generated", "ai policy", "no ai", "ban ai", "ai contribution",
                       "generated code", "llm", "chatgpt", "copilot policy"]
    for _, r in same_repo.iterrows():
        review_text = str(r.get("review_comments_text", "")).lower()
        if any(p in review_text for p in policy_keywords):
            ai_policy_signals.append(review_text[:200])
            has_ai_policy = True
            break

    # 历史 review 风格摘要
    review_texts = same_repo["review_comments_text"].dropna()
    review_texts = review_texts[review_texts.str.strip() != ""]
    avg_review_len = review_texts.str.len().mean() if len(review_texts) > 0 else 0
    has_review_ratio = len(review_texts) / max(repo_total, 1)

    parts = ["## Repository Policy Context (C6)", ""]
    parts.append(f"**Repository**: {repo}")
    parts.append(f"Historical AI PRs in this repo (excluding current): {repo_total}")
    parts.append(f"Historical AI PR merge rate: {repo_merge_rate:.1%}")
    parts.append(f"AI PRs with reviewer comments: {has_review_ratio:.1%}")

    if unmerged_keywords:
        parts.append(f"\nCommon patterns in UNMERGED AI PRs: {', '.join(unmerged_keywords[:8])}")

    if has_ai_policy:
        parts.append(f"\n⚠ This repository shows signs of AI code policy discussion. "
                     f"Reviewer may apply stricter standards for AI-generated code.")

    parts.append(f"\nReview style: Average review comment length = {avg_review_len:.0f} chars. "
                 f"Reviewers {'actively' if has_review_ratio > 0.5 else 'selectively'} "
                 f"comment on AI PRs in this repository.")

    # 仓库级建议（基于数据，不针对当前 PR）
    if repo_merge_rate < 0.5:
        parts.append(f"\nNote: This repository has a low AI PR merge rate ({repo_merge_rate:.1%}). "
                     f"AI-generated PRs face higher scrutiny here.")

    return "\n".join(parts)


# ============================================================
# C7: Historical Similar PR Context
# ============================================================
def build_historical_similar_prs(row: pd.Series, full_df: pd.DataFrame,
                                  exclude_pr_id: str, top_k: int = 3) -> str:
    """
    检索历史相似 PR 摘要。

    检索维度:
      - 相同仓库优先
      - 相似 changed file extension
      - 相似修改规模
      - 相似 title/body 关键词
    """
    pr_id = exclude_pr_id
    repo = row.get("repo", "")

    # 候选池: 排除当前 PR 自己, reset_index 保证位置索引
    candidates = full_df[full_df["pr_id"].astype(str) != pr_id].copy().reset_index(drop=True)

    if candidates.empty:
        return "## Historical Similar PRs (C7)\n\nNo historical PRs available for comparison.\n"

    # 相似度评分 (使用位置索引)
    scores = np.zeros(len(candidates))

    # 1. 相同仓库 (+3)
    scores += (candidates["repo"] == repo).astype(float).values * 3.0

    # 2. 相似文件数
    curr_files = int(row.get("num_changed_files", 0) or 0)
    files_diff = np.abs(candidates["num_changed_files"].fillna(0).astype(float).values - curr_files)
    scores += np.exp(-files_diff / 10) * 2.0

    # 3. 相似新增行数
    curr_add = int(row.get("total_additions", 0) or 0)
    add_diff = np.abs(candidates["total_additions"].fillna(0).astype(float).values - curr_add)
    scores += np.exp(-add_diff / 500) * 2.0

    # 4. Title 关键词重叠
    curr_title_words = set(str(row.get("title", "")).lower().split())
    for i, (_, cand) in enumerate(candidates.iterrows()):
        cand_words = set(str(cand.get("title", "")).lower().split())
        if curr_title_words:
            overlap = len(curr_title_words & cand_words) / len(curr_title_words)
            scores[i] += overlap * 2.0

    # 选 top_k
    top_indices = np.argsort(scores)[::-1][:top_k]
    top = candidates.iloc[top_indices]

    parts = ["## Historical Similar PRs (C7)", ""]
    parts.append(f"The following {len(top)} historical PR(s) from the dataset are most similar "
                 f"to the current PR. Their outcomes and review patterns may help your analysis.\n")

    for rank, (_, pr) in enumerate(top.iterrows(), 1):
        h_title = str(pr.get("title", ""))[:150]
        h_repo = pr.get("repo", "?")
        h_files = pr.get("num_changed_files", "?")
        h_adds = pr.get("total_additions", "?")
        h_dels = pr.get("total_deletions", "?")
        h_merged = "merged" if pr.get("is_merged_bool") else "not_merged"
        h_review = str(pr.get("review_comments_text", ""))[:300]

        score_val = float(scores[top_indices[rank - 1]]) if top_indices[rank - 1] < len(scores) else 0.0
        parts.append(f"### Similar PR #{rank} (Score: {score_val:.1f})")
        parts.append(f"- **Title**: {h_title}")
        parts.append(f"- **Repository**: {h_repo}")
        parts.append(f"- **Files**: {h_files}, **Changes**: +{h_adds}/-{h_dels}")
        parts.append(f"- **Outcome**: {h_merged}")

        if h_review.strip():
            parts.append(f"- **Review Summary**: {h_review[:200]}")
        parts.append("")

    parts.append("**Note**: These historical outcomes are for reference only. "
                 "Your prediction must be based on the current PR content.")

    return "\n".join(parts)


# ============================================================
# 上下文构建入口
# ============================================================
def build_context(row: pd.Series, context_type: str, patch_index: Dict,
                  full_df: Optional[pd.DataFrame] = None) -> str:
    """
    构建指定类型的上下文。

    context_type: "C5", "C6", "C7", "C8"
    """
    pr_id = str(row.get("pr_id", ""))
    base = build_base_context(row, patch_index)

    if context_type == "C4":
        # 纯 C4 基线（用于对比）
        return base

    if context_type == "C5":
        # C4 + Risk Checklist
        risk = build_risk_checklist(row, patch_index)
        return base + "\n\n---\n\n" + risk

    if context_type == "C6":
        # C5 + Repository Policy
        risk = build_risk_checklist(row, patch_index)
        repo_policy = ""
        if full_df is not None:
            repo_policy = build_repository_policy(row, full_df, pr_id)
        return base + "\n\n---\n\n" + risk + "\n\n---\n\n" + repo_policy

    if context_type == "C7":
        # C5 + Historical Similar PRs
        risk = build_risk_checklist(row, patch_index)
        historical = ""
        if full_df is not None:
            historical = build_historical_similar_prs(row, full_df, pr_id)
        return base + "\n\n---\n\n" + risk + "\n\n---\n\n" + historical

    if context_type == "C8":
        # Full: C5 + C6 + C7
        risk = build_risk_checklist(row, patch_index)
        parts = [base, "---", risk]

        if full_df is not None:
            repo_policy = build_repository_policy(row, full_df, pr_id)
            parts.append("---")
            parts.append(repo_policy)

            historical = build_historical_similar_prs(row, full_df, pr_id)
            parts.append("---")
            parts.append(historical)

        result = "\n\n".join(parts)

        # 长度控制: 限制在 ~14k tokens
        estimated = _estimate_tokens(result)
        if estimated > MAX_CONTEXT_TOKENS - 2000:  # 留 2k 给 prompt
            # 截断策略: 优先保留 PR info + risk + repo policy
            priority_parts = [
                base[:MAX_DIFF_CHARS],
                risk,
                build_repository_policy(row, full_df, pr_id) if full_df else "",
            ]
            result = "\n\n".join(priority_parts)
            if _estimate_tokens(result) > MAX_CONTEXT_TOKENS - 2000:
                result = result[:MAX_CONTEXT_TOKENS * 4]  # 粗略字符截断

        return result

    # fallback: C4
    return base


def build_all_contexts(eval_csv: str, output_key: str,
                       full_df: pd.DataFrame,
                       patch_index: Dict,
                       context_types: List[str]) -> Dict[str, str]:
    """为评估集中的所有样本构建所有上下文类型"""
    eval_df = pd.read_csv(eval_csv, encoding="utf-8-sig")
    contexts = {}

    for ctx_type in context_types:
        for _, row in eval_df.iterrows():
            pr_id = str(row["pr_id"])
            key = f"{output_key}_{pr_id}_{ctx_type}"
            contexts[key] = build_context(row, ctx_type, patch_index, full_df)
            if len(contexts) % 50 == 0:
                logger.info(f"  构建 {output_key} 上下文: {len(contexts)} 条目...")

    logger.info(f"  {output_key} 上下文构建完成: {len(contexts)} 条目 "
                f"({len(context_types)} types × {len(eval_df)} samples)")
    return contexts


def build_task_list(eval_csv: str, methods: Dict, output_key: str) -> List[Dict]:
    """构建 API 调用任务列表"""
    eval_df = pd.read_csv(eval_csv, encoding="utf-8-sig")
    tasks = []

    for method_id, combo in methods.items():
        prompt_type = combo["prompt"]
        context_type = combo["context"]
        for _, row in eval_df.iterrows():
            pr_id = str(row["pr_id"])
            context_key = f"{output_key}_{pr_id}_{context_type}"

            is_merged = row.get("is_merged_bool", row.get("is_merged", False))
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
                "context_key": context_key,
            })

    logger.info(f"  任务列表: {len(tasks)} 任务 ({len(methods)} 方法 × {len(eval_df)} 样本)")
    return tasks


def run_build_contexts() -> bool:
    """构建所有增强上下文 (主入口)"""
    logger.info("=" * 60)
    logger.info("阶段: 构建增强上下文")
    logger.info("=" * 60)

    # 1. 加载数据
    full_df = _load_full_dataset()
    patch_index = _load_patch_index()
    logger.info(f"完整数据集: {len(full_df)} 条, Patch index: {len(patch_index)} 条目")

    all_context_types = ["C5", "C6", "C7", "C8"]

    # ================================================================
    # 2. Balanced-50 上下文 (主实验 I01-I16)
    # ================================================================
    if os.path.exists(EVAL_BALANCED_50):
        logger.info("--- 构建 Balanced-50 增强上下文 (主实验 I01-I16) ---")
        balanced_50_contexts = build_all_contexts(
            EVAL_BALANCED_50, "balanced50", full_df, patch_index, all_context_types
        )
        with open(IMPROVED_CONTEXTS_50, "w", encoding="utf-8") as f:
            json.dump(balanced_50_contexts, f, ensure_ascii=False)
        logger.info(f"Balanced-50 上下文已保存: {IMPROVED_CONTEXTS_50} ({len(balanced_50_contexts)} 条目)")

        # 构建 I01-I16 任务列表
        from config import IMPROVED_COMBOS
        improved_4x4_tasks = build_task_list(EVAL_BALANCED_50, IMPROVED_COMBOS, "balanced50")
        with open(TASK_LIST_IMPROVED_4X4, "w", encoding="utf-8") as f:
            json.dump(improved_4x4_tasks, f, ensure_ascii=False, indent=2)
        logger.info(f"I01-I16 任务列表已保存: {TASK_LIST_IMPROVED_4X4} ({len(improved_4x4_tasks)} 任务)")
        # 验证: 应为 16 × 50 = 800
        expected = 16 * 50
        if len(improved_4x4_tasks) != expected:
            logger.warning(f"  任务数 {len(improved_4x4_tasks)} != 预期 {expected}")
    else:
        logger.warning(f"Balanced-50 不存在: {EVAL_BALANCED_50}, 跳过主实验任务构建")

    # ================================================================
    # 3. Balanced-120 上下文 (验证)
    # ================================================================
    all_contexts = {}
    if os.path.exists(EVAL_BALANCED_120):
        balanced_contexts = build_all_contexts(
            EVAL_BALANCED_120, "balanced", full_df, patch_index, all_context_types
        )
        all_contexts.update(balanced_contexts)

    # 4. Hard-FP-40 上下文 (验证)
    if os.path.exists(EVAL_HARD_FP_40):
        hardfp_contexts = build_all_contexts(
            EVAL_HARD_FP_40, "hardfp", full_df, patch_index, all_context_types
        )
        all_contexts.update(hardfp_contexts)

    # 5. 保存上下文
    if all_contexts:
        with open(IMPROVED_CONTEXTS, "w", encoding="utf-8") as f:
            json.dump(all_contexts, f, ensure_ascii=False)
        logger.info(f"增强上下文已保存: {IMPROVED_CONTEXTS} ({len(all_contexts)} 条目)")

    # 6. 构建 M1-M4 任务列表 (兼容)
    all_tasks = {}
    from config import METHOD_COMBOS

    if os.path.exists(EVAL_BALANCED_120):
        all_tasks["balanced"] = build_task_list(EVAL_BALANCED_120, METHOD_COMBOS, "balanced")
    if os.path.exists(EVAL_HARD_FP_40):
        all_tasks["hard_fp"] = build_task_list(EVAL_HARD_FP_40, METHOD_COMBOS, "hardfp")

    if all_tasks:
        with open(TASK_LIST, "w", encoding="utf-8") as f:
            json.dump(all_tasks, f, ensure_ascii=False, indent=2)
        logger.info(f"任务列表已保存: {TASK_LIST}")

        balanced_tasks = len(all_tasks.get("balanced", []))
        hardfp_tasks = len(all_tasks.get("hard_fp", []))
        logger.info(f"M1-M4 任务数: {balanced_tasks + hardfp_tasks} "
                    f"(Balanced: {balanced_tasks}, Hard-FP: {hardfp_tasks})")

    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    run_build_contexts()
