"""
AI 生成代码关键词判定模块

规则：
1. 至少命中 1 个强信号关键词 → 候选
2. 如果只命中弱词 "ai"，必须同时命中上下文词
3. 每条样本记录 ai_detection_reason
"""

import re
import os
import sys
from typing import Tuple, Optional, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import STRONG_KEYWORDS, AI_CONTEXT_WORDS, DETECTION_FIELDS, logger


def _normalize(text: str) -> str:
    """标准化文本：小写"""
    if not text:
        return ""
    return str(text).lower().strip()


def _check_text_for_keywords(
    text: str, keywords: list, field_name: str
) -> list:
    """检查文本中是否包含关键词，返回命中的 (keyword, field_name) 列表"""
    if not text:
        return []
    normalized = _normalize(text)
    hits = []
    for kw in keywords:
        if kw.lower() in normalized:
            hits.append((kw, field_name))
    return hits


def _check_ai_context(text: str) -> bool:
    """检查文本中 ai 是否配合了上下文词"""
    if not text:
        return False
    normalized = _normalize(text)
    # 必须同时包含 "ai" 和至少一个上下文词
    if "ai" not in normalized:
        return False
    for ctx_word in AI_CONTEXT_WORDS:
        if ctx_word in normalized:
            return True
    return False


def detect_ai_generated(
    title: str = "",
    body: str = "",
    commit_messages: str = "",
    label_names: str = "",
    author: str = "",
    review_comments_text: str = "",
) -> Tuple[bool, str]:
    """
    检测一条 PR 是否为 AI 生成代码。

    参数:
        title: PR 标题
        body: PR 正文
        commit_messages: 提交信息（管道分隔或换行分隔）
        label_names: 标签名（逗号分隔）
        author: 作者/机器人名
        review_comments_text: 已有审查评论

    返回:
        (has_ai_generated_code: bool, ai_detection_reason: str)
    """
    reasons = []

    # 构建字段字典
    fields: Dict[str, str] = {
        "title": title,
        "body": body,
        "commit_messages": commit_messages,
        "label_names": label_names,
        "author": author,
        "review_comments_text": review_comments_text,
    }

    # 1. 检查强信号关键词
    for field_name in DETECTION_FIELDS:
        text = fields.get(field_name, "")
        hits = _check_text_for_keywords(text, STRONG_KEYWORDS, field_name)
        for kw, fn in hits:
            reasons.append(f'{fn} contains "{kw}"')

    # 2. 检查弱词 "ai" + 上下文词
    if not reasons:
        for field_name in DETECTION_FIELDS:
            text = fields.get(field_name, "")
            if _check_ai_context(text):
                reasons.append(
                    f'{field_name} contains "ai" with context words'
                )

    if reasons:
        return True, "; ".join(reasons)
    else:
        return False, ""


def detect_ai_from_pr_data(pr_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    从 PR 数据字典中检测 AI 生成代码。

    参数:
        pr_data: 包含 title, body, commit_messages, label_names, author,
                  review_comments_text 等字段的字典

    返回:
        (has_ai_generated_code: bool, ai_detection_reason: str)
    """
    return detect_ai_generated(
        title=str(pr_data.get("title", "")),
        body=str(pr_data.get("body", "")),
        commit_messages=str(pr_data.get("commit_messages", "")),
        label_names=str(pr_data.get("label_names", "")),
        author=str(pr_data.get("author", "")),
        review_comments_text=str(pr_data.get("review_comments_text", "")),
    )


def compute_detection_stats(
    samples: list, has_ai_key: str = "has_ai_generated_code"
) -> dict:
    """
    计算 AI 检测统计。

    返回:
        dict: {
            "total": int,
            "ai_detected": int,
            "human": int,
            "ai_ratio": float,
            "keyword_hits": {keyword: count},
            "field_hits": {field: count},
        }
    """
    total = len(samples)
    ai_detected = sum(
        1 for s in samples if s.get(has_ai_key, False) is True
    )
    human = total - ai_detected

    keyword_hits = {}
    field_hits = {}

    for s in samples:
        if s.get(has_ai_key, False) is not True:
            continue
        reason = s.get("ai_detection_reason", "")
        if not reason:
            continue

        # 解析 reason（格式: 'field contains "keyword"; ...'）
        parts = [p.strip() for p in reason.split(";") if p.strip()]
        for part in parts:
            # 提取 field name
            for field in DETECTION_FIELDS:
                if part.startswith(field):
                    field_hits[field] = field_hits.get(field, 0) + 1
                    break

            # 提取 keyword
            for kw in STRONG_KEYWORDS:
                if kw.lower() in part.lower():
                    keyword_hits[kw] = keyword_hits.get(kw, 0) + 1
                    break
            else:
                if "ai" in part.lower() and "context" in part.lower():
                    keyword_hits["ai+context"] = (
                        keyword_hits.get("ai+context", 0) + 1
                    )

    return {
        "total": total,
        "ai_detected": ai_detected,
        "human": human,
        "ai_ratio": round(ai_detected / total, 4) if total > 0 else 0.0,
        "keyword_hits": dict(
            sorted(keyword_hits.items(), key=lambda x: -x[1])
        ),
        "field_hits": dict(
            sorted(field_hits.items(), key=lambda x: -x[1])
        ),
    }
