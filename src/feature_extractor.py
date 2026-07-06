"""
实验一：构建数据集 — 特征提取
从原始 JSON 提取结构化特征，输出 CSV + JSON 数据集。

对应文档步骤：
  1.7.1 获取 Pull Request → pr_id, title, body, author, created_at, is_merged
  1.7.2 获取 Code Review   → reviewer, review_decision, review_time, comments
  1.7.3 获取代码修改       → changed_files, modified_functions, diff, commit_messages
  1.7.4 提取特征           → 8 项统计特征
"""

import csv
import json
import re

import config
from utils import log, safe_str, clean_text


# ============================================================
# Diff 函数名提取
# ============================================================
# Unified diff hunk header: @@ -old,count +new,count @@ context
HUNK_HEADER_RE = re.compile(r'^@@\s+-?\d+(?:,\d+)?\s+\+?\d+(?:,\d+)?\s+@@\s*(.*?)$', re.MULTILINE)

# 常见函数定义模式（添加行中以这些关键字开头）
FUNC_DEF_PATTERNS = [
    # Python
    r'^\+\s*(def|class|async def)\s+(\w+)',
    # JavaScript / TypeScript
    r'^\+\s*(function|class|const|let|var|export function|export class|export const)\s+(\w+)',
    # Go
    r'^\+\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)',
    # C / C++ / Java
    r'^\+\s*[\w<>[\]:]+\s+(\w+)\s*\([^)]*\)\s*\{',
    # Rust
    r'^\+\s*(pub\s+)?fn\s+(\w+)',
    # Ruby
    r'^\+\s*def\s+(\w+)',
]


def extract_modified_functions(files):
    """从文件变更的 diff patch 中提取被修改的函数名。

    策略：
    1. 解析 unified diff 的 hunk header (@@ ... @@)，提取上下文函数名
    2. 匹配新增行中的函数定义模式

    Args:
        files: GitHub files API 返回的列表，每项含 filename, patch 等

    Returns:
        逗号分隔的去重函数名字符串
    """
    func_names = set()

    for f in files or []:
        patch = f.get("patch") or ""

        # 方法1：从 hunk header 提取
        for m in HUNK_HEADER_RE.finditer(patch):
            ctx = m.group(1).strip()
            if ctx:
                # hunk header 中通常包含函数/类名
                # 如 "def foo():" 或 "function bar(args) {"
                words = re.findall(r'\b([a-zA-Z_]\w*)\s*\(', ctx)
                func_names.update(words)

        # 方法2：从新增行匹配函数定义
        for pattern in FUNC_DEF_PATTERNS:
            for m in re.finditer(pattern, patch, re.MULTILINE):
                name = m.group(2) if m.lastindex >= 2 else m.group(1)
                if name and len(name) > 1:
                    func_names.add(name)

    return ",".join(sorted(func_names)) if func_names else ""


def extract_commit_messages(commits):
    """从 commits 列表中提取 commit messages。

    Args:
        commits: GitHub commits API 返回的列表

    Returns:
        dict: {"messages": "msg1 | msg2 | ...", "count": N}
    """
    messages = []
    for c in (commits or []):
        msg = (c.get("commit") or {}).get("message") or ""
        if msg.strip():
            # 取每段 message 的第一行
            first_line = msg.strip().split("\n")[0]
            messages.append(first_line)

    return {
        "messages": " | ".join(messages),
        "count": len(messages),
    }


# ============================================================
# 特征提取器
# ============================================================
class FeatureExtractor:
    """从原始 API 数据中提取结构化特征。"""

    # CSV 列定义（含文档1.7.1~1.7.4 全部字段）
    COLUMNS = [
        # 1.7.1 PR 基本信息
        "pr_id", "pr_number", "repo", "title", "body",
        "pr_length", "author", "created_at", "is_merged",
        "merge_status",
        # 1.7.2 Code Review
        "num_reviewers", "review_decision",
        "num_review_comments",      # PR reviews
        "num_inline_comments",       # Inline review comments
        "review_comments_text",
        # 1.7.3 代码修改
        "num_changed_files", "total_additions",
        "total_deletions", "modified_functions",
        "num_commits", "commit_messages",
        "changed_files_list",
        # 元标签
        "num_labels", "label_names",
        "has_ai_reviewer", "has_ai_generated_code",
    ]

    def __init__(self, raw_data_path=None):
        self.raw_data_path = raw_data_path or (
            config.RAW_DATA_DIR / "merged_raw.json"
        )

    # --------------------------------------------------------
    # AI 检测
    # --------------------------------------------------------
    @staticmethod
    def _match_keywords(text, keywords):
        """检查文本是否匹配任一关键词（大小写不敏感）。"""
        if not text:
            return False
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    def _detect_ai_reviewer(self, reviews, review_comments, labels):
        """检测是否有 AI Reviewer。

        检查：review body + inline comment body + PR labels
        """
        # 检查 PR reviews
        for r in (reviews or []):
            body = r.get("body") or ""
            if self._match_keywords(body, config.AI_REVIEWER_KEYWORDS):
                return True
        # 检查 inline comments
        for c in (review_comments or []):
            body = c.get("body") or ""
            if self._match_keywords(body, config.AI_REVIEWER_KEYWORDS):
                return True
        # 检查标签
        for label in (labels or []):
            name = (label.get("name") or "").lower()
            if self._match_keywords(name, config.AI_REVIEWER_KEYWORDS):
                return True
        return False

    def _detect_ai_generated_code(self, pr_body, labels):
        """检测是否有 AI 生成代码。"""
        if self._match_keywords(pr_body, config.AI_GENERATED_CODE_KEYWORDS):
            return True
        for label in (labels or []):
            name = (label.get("name") or "").lower()
            if self._match_keywords(name, config.AI_GENERATED_CODE_KEYWORDS):
                return True
        return False

    # --------------------------------------------------------
    # 单条 PR 特征提取
    # --------------------------------------------------------
    def extract_one(self, pr_entry):
        """从单条原始 PR 数据提取完整特征字典。

        按照文档 1.7.1 → 1.7.4 的步骤顺序提取。
        """
        detail = pr_entry.get("detail") or {}
        reviews = pr_entry.get("reviews") or []
        review_comments = pr_entry.get("review_comments") or []
        files = pr_entry.get("files") or []
        commits = pr_entry.get("commits") or []

        # ================================================
        # 1.7.1 PR 基本信息
        # ================================================
        title = safe_str(detail.get("title"))
        body = safe_str(detail.get("body"))
        pr_length = len(title) + len(body)

        is_merged = bool(detail.get("merged", False))
        state = detail.get("state", "unknown")
        if is_merged:
            merge_status = "merged"
        elif state == "closed":
            merge_status = "closed_not_merged"
        else:
            merge_status = state

        labels = detail.get("labels") or []

        # ================================================
        # 1.7.2 Code Review 信息
        # ================================================
        # Reviewer 去重
        reviewer_set = set()
        for r in reviews:
            user = r.get("user")
            if user and user.get("login"):
                reviewer_set.add(user["login"])
        num_reviewers = len(reviewer_set)

        # Review 决策（多数投票）
        review_states = [
            r.get("state", "") for r in reviews if r.get("state")
        ]
        if review_states:
            approved = review_states.count("APPROVED")
            changes = review_states.count("CHANGES_REQUESTED")
            if approved >= changes and approved > 0:
                review_decision = "APPROVED"
            elif changes > approved:
                review_decision = "CHANGES_REQUESTED"
            else:
                review_decision = "COMMENTED"
        else:
            review_decision = "NONE"

        num_review_comments = len(reviews)
        num_inline_comments = len(review_comments)

        # 合并所有评论文本（reviews + inline comments）
        all_comment_texts = []
        for r in reviews:
            rbody = r.get("body") or ""
            if rbody.strip():
                all_comment_texts.append(
                    f"[Review by {safe_str((r.get('user') or {}).get('login'))}]: {rbody.strip()}"
                )
        for c in review_comments:
            cbody = c.get("body") or ""
            if cbody.strip():
                all_comment_texts.append(
                    f"[Inline on {safe_str(c.get('path'))} L{c.get('line')}]: {cbody.strip()}"
                )
        review_comments_text = " | ".join(all_comment_texts)
        review_comments_text = clean_text(review_comments_text, max_len=3000)

        # ================================================
        # 1.7.3 代码修改信息
        # ================================================
        num_changed_files = len(files)
        total_additions = sum(f.get("additions", 0) for f in files)
        total_deletions = sum(f.get("deletions", 0) for f in files)
        changed_files_list = ",".join(
            f.get("filename", "") for f in files
        )

        # 修改的函数（从 diff patch 解析）
        modified_functions = extract_modified_functions(files)

        # Commit 信息
        commit_info = extract_commit_messages(commits)
        num_commits = commit_info["count"]
        commit_messages = clean_text(commit_info["messages"], max_len=2000)

        # ================================================
        # 1.7.4 元标签
        # ================================================
        num_labels = len(labels)
        label_names = ",".join(
            l.get("name", "") for l in labels
        )

        has_ai_reviewer = self._detect_ai_reviewer(
            reviews, review_comments, labels
        )
        has_ai_generated_code = self._detect_ai_generated_code(body, labels)

        # ================================================
        # 组装特征字典
        # ================================================
        return {
            # 1.7.1
            "pr_id": detail.get("id"),
            "pr_number": detail.get("number"),
            "repo": pr_entry.get("repo", ""),
            "title": clean_text(title, max_len=500),
            "body": clean_text(body, max_len=3000),
            "pr_length": pr_length,
            "author": (detail.get("user") or {}).get("login", ""),
            "created_at": detail.get("created_at", ""),
            "is_merged": is_merged,
            "merge_status": merge_status,
            # 1.7.2
            "num_reviewers": num_reviewers,
            "review_decision": review_decision,
            "num_review_comments": num_review_comments,
            "num_inline_comments": num_inline_comments,
            "review_comments_text": review_comments_text,
            # 1.7.3
            "num_changed_files": num_changed_files,
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "modified_functions": modified_functions[:2000],
            "num_commits": num_commits,
            "commit_messages": commit_messages,
            "changed_files_list": changed_files_list[:2000],
            # 1.7.4
            "num_labels": num_labels,
            "label_names": label_names,
            "has_ai_reviewer": has_ai_reviewer,
            "has_ai_generated_code": has_ai_generated_code,
        }

    # --------------------------------------------------------
    # 批量提取
    # --------------------------------------------------------
    def extract_all(self):
        """从合并原始数据提取全部特征。"""
        log.info(f"加载原始数据: {self.raw_data_path}")
        with open(self.raw_data_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        log.info(f"共 {len(raw_data)} 条原始 PR 记录，开始特征提取...")

        dataset = []
        skipped = 0
        for i, entry in enumerate(raw_data):
            try:
                features = self.extract_one(entry)
                dataset.append(features)
            except Exception as e:
                log.warning(f"PR #{i+1} 特征提取失败: {e}")
                skipped += 1
                continue

            if (i + 1) % 100 == 0:
                log.info(f"已处理 {i+1}/{len(raw_data)}...")

        log.info(
            f"特征提取完成: {len(dataset)} 条有效记录"
            f"（跳过 {skipped} 条）"
        )

        # 保存 CSV
        csv_path = config.PROCESSED_DATA_DIR / "dataset.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.COLUMNS)
            writer.writeheader()
            writer.writerows(dataset)
        log.info(f"CSV 已保存至 {csv_path}")

        # 保存 JSON
        json_path = config.PROCESSED_DATA_DIR / "dataset.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)
        log.info(f"JSON 已保存至 {json_path}")

        # 统计摘要
        merged_count = sum(1 for d in dataset if d["is_merged"])
        ai_reviewer_count = sum(
            1 for d in dataset if d["has_ai_reviewer"]
        )
        ai_code_count = sum(
            1 for d in dataset if d["has_ai_generated_code"]
        )
        log.info(
            f"摘要: 总计={len(dataset)}, "
            f"合并={merged_count} "
            f"({100*merged_count/max(len(dataset),1):.1f}%), "
            f"AI Reviewer={ai_reviewer_count}, "
            f"AI 代码={ai_code_count}"
        )

        return dataset


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    extractor = FeatureExtractor()
    extractor.extract_all()
