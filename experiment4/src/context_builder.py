"""
实验三 步骤二：上下文构建
构建 4 种上下文（C1-C4），全部只使用 PR 刚提交时可获得的信息。
"""
import pandas as pd
from pathlib import Path

from config import (
    CONTEXT_CONFIG, PATCH_INDEX_JSON,
    MAX_DIFF_CHARS, MAX_BODY_CHARS, MAX_COMMIT_MSG_CHARS, MAX_ADDED_LINES_CHARS,
)
from utils import (
    log, read_json, clean_text, truncate_text,
    classify_file_type, is_test_file, get_main_language,
)


def load_patch_index():
    """加载 patch 索引。"""
    log.info("加载 patch 索引...")
    return read_json(PATCH_INDEX_JSON)


def build_diff_context(pr_row, patch_entry: dict) -> str:
    """
    构建 diff 上下文。

    包含：
    - changed file paths
    - unified diff / patch（新增代码行）
    - 文件级 additions / deletions
    """
    if patch_entry is None or not patch_entry.get("patch_available"):
        return _build_diff_from_csv(pr_row)

    parts = []
    files = patch_entry.get("files", [])

    # 文件变更概览
    parts.append("## Changed Files")
    for f in files:
        status = f.get("status", "modified")
        filename = f.get("filename", "unknown")
        adds = f.get("additions", 0)
        dels = f.get("deletions", 0)
        ftype = classify_file_type(filename)
        test_mark = " [TEST]" if is_test_file(filename) else ""
        parts.append(f"- [{status}] {filename} (+{adds} -{dels}) [{ftype}]{test_mark}")
    parts.append("")

    # 新增代码行（patch）
    parts.append("## Added Code Lines (from diff)")
    added_text = ""
    for f in files:
        filename = f.get("filename", "unknown")
        added_lines = f.get("added_lines", "")
        if added_lines:
            added_text += f"\n### {filename}\n```\n"
            added_text += truncate_text(added_lines, MAX_ADDED_LINES_CHARS // max(len(files), 1))
            added_text += "\n```\n"
            if len(added_text) > MAX_DIFF_CHARS:
                break

    if added_text.strip():
        parts.append(truncate_text(added_text, MAX_DIFF_CHARS))
    else:
        parts.append("(No code additions available)")

    return "\n".join(parts)


def _build_diff_from_csv(pr_row) -> str:
    """当 patch_index 不可用时，从 CSV 字段构建简化 diff 上下文。"""
    parts = ["## Changed Files"]
    changed_files = str(pr_row.get("changed_files_list", ""))
    if changed_files:
        for f in changed_files.split(","):
            f = f.strip()
            if f:
                ftype = classify_file_type(f)
                test_mark = " [TEST]" if is_test_file(f) else ""
                parts.append(f"- {f} [{ftype}]{test_mark}")
    else:
        parts.append("- (No file list available)")

    parts.append("")
    parts.append(f"- Total files changed: {pr_row.get('num_changed_files', 'N/A')}")
    parts.append(f"- Total additions: {pr_row.get('total_additions', 'N/A')}")
    parts.append(f"- Total deletions: {pr_row.get('total_deletions', 'N/A')}")

    return "\n".join(parts)


def build_pr_description_context(pr_row) -> str:
    """
    构建 PR 描述上下文。

    包含：
    - PR title
    - PR body
    """
    parts = []
    parts.append(f"## PR Title\n{clean_text(pr_row.get('title', ''))}")
    parts.append("")

    body = clean_text(str(pr_row.get("body", "")))
    body = truncate_text(body, MAX_BODY_CHARS)
    parts.append(f"## PR Body\n{body}")

    return "\n".join(parts)


def build_commit_context(pr_row) -> str:
    """
    构建 commit 上下文。

    包含：
    - commit messages
    - changed files summary
    """
    parts = []

    commit_msgs = clean_text(str(pr_row.get("commit_messages", "")))
    commit_msgs = truncate_text(commit_msgs, MAX_COMMIT_MSG_CHARS)
    parts.append(f"## Commit Messages\n{commit_msgs}")
    parts.append("")

    parts.append(f"## Commit Summary")
    parts.append(f"- Number of commits: {pr_row.get('num_commits', 'N/A')}")
    parts.append(f"- Number of changed files: {pr_row.get('num_changed_files', 'N/A')}")

    return "\n".join(parts)


def build_code_summary_context(pr_row, patch_entry: dict) -> str:
    """
    构建代码结构摘要上下文（C4 额外部分）。

    包含：
    - AST 摘要
    - CFG 摘要
    - 修改规模统计
    - 文件类型统计
    - 是否包含测试文件
    - 主要语言类型
    """
    parts = []
    parts.append("## Code Structure Summary")

    # AST 摘要
    ast_nodes = pr_row.get("ast_total_nodes", 0)
    ast_depth = pr_row.get("ast_max_depth", 0)
    ast_success = pr_row.get("ast_parse_success_rate", 0)
    ast_funcs = pr_row.get("ast_func_def_count", 0)
    ast_classes = pr_row.get("ast_class_def_count", 0)
    ast_if = pr_row.get("ast_if_count", 0)
    ast_loops = pr_row.get("ast_loop_count", 0)
    ast_try = pr_row.get("ast_try_count", 0)
    ast_returns = pr_row.get("ast_return_count", 0)
    ast_assigns = pr_row.get("ast_assignment_count", 0)

    if pd.notna(ast_nodes) and ast_nodes > 0:
        parts.append(f"### AST Summary")
        parts.append(f"- Total AST nodes: {ast_nodes}")
        parts.append(f"- Max AST depth: {ast_depth}")
        parts.append(f"- Parse success rate: {ast_success}")
        parts.append(f"- Function definitions: {ast_funcs}")
        parts.append(f"- Class definitions: {ast_classes}")
        parts.append(f"- If statements: {ast_if}")
        parts.append(f"- Loops: {ast_loops}")
        parts.append(f"- Try blocks: {ast_try}")
        parts.append(f"- Return statements: {ast_returns}")
        parts.append(f"- Assignments: {ast_assigns}")

    # CFG 摘要
    cfg_nodes = pr_row.get("cfg_total_nodes", 0)
    cfg_edges = pr_row.get("cfg_total_edges", 0)
    cfg_branches = pr_row.get("cfg_branch_nodes", 0)
    cfg_loops = pr_row.get("cfg_loop_nodes", 0)
    cfg_cyclomatic = pr_row.get("cfg_cyclomatic_complexity", 0)
    cfg_max_depth = pr_row.get("cfg_max_branch_depth", 0)

    if pd.notna(cfg_nodes) and cfg_nodes > 0:
        parts.append(f"### CFG Summary")
        parts.append(f"- CFG nodes: {cfg_nodes}, edges: {cfg_edges}")
        parts.append(f"- Branch nodes: {cfg_branches}")
        parts.append(f"- Loop nodes: {cfg_loops}")
        parts.append(f"- Cyclomatic complexity: {cfg_cyclomatic}")
        parts.append(f"- Max branch depth: {cfg_max_depth}")

    # 修改规模统计
    parts.append(f"### Change Scale")
    parts.append(f"- Files changed: {pr_row.get('num_changed_files', 'N/A')}")
    parts.append(f"- Lines added: {pr_row.get('total_additions', 'N/A')}")
    parts.append(f"- Lines deleted: {pr_row.get('total_deletions', 'N/A')}")
    parts.append(f"- Code churn: {pr_row.get('code_churn', 'N/A')}")

    # 文件类型统计
    if patch_entry and patch_entry.get("files"):
        files = patch_entry["files"]
        file_types = {}
        test_count = 0
        for f in files:
            ftype = classify_file_type(f.get("filename", ""))
            file_types[ftype] = file_types.get(ftype, 0) + 1
            if is_test_file(f.get("filename", "")):
                test_count += 1

        parts.append(f"### File Type Distribution")
        for ftype, count in sorted(file_types.items()):
            parts.append(f"- {ftype}: {count} files")
        parts.append(f"- Test files: {test_count}")
        parts.append(f"- Has test files: {test_count > 0}")

        # 主要语言
        main_lang = get_main_language(files)
        parts.append(f"- Main language: {main_lang}")

    return "\n".join(parts)


def build_context(
    pr_row,
    patch_entry: dict,
    context_type: str,
) -> str:
    """
    根据上下文类型构建完整的 prompt 上下文。

    Args:
        pr_row: PR 数据行（DataFrame row）
        patch_entry: patch_index 中对应的条目
        context_type: C1/C2/C3/C4

    Returns:
        构建好的上下文字符串
    """
    config = CONTEXT_CONFIG.get(context_type)
    if config is None:
        raise ValueError(f"未知的上下文类型: {context_type}")

    sections = []

    # PR 基本信息
    sections.append(f"# PR Context")
    sections.append(f"Repository: {pr_row.get('repo', 'unknown')}")
    sections.append(f"PR ID: {pr_row.get('pr_id', 'unknown')}")
    sections.append("")

    # Diff（C1-C4 都包含）
    if config["include_diff"]:
        sections.append(build_diff_context(pr_row, patch_entry))
        sections.append("")

    # PR Description（C2-C4）
    if config["include_pr_description"]:
        sections.append(build_pr_description_context(pr_row))
        sections.append("")

    # Commit（C3-C4）
    if config["include_commit"]:
        sections.append(build_commit_context(pr_row))
        sections.append("")

    # Code Summary（仅 C4）
    if config["include_code_summary"]:
        sections.append(build_code_summary_context(pr_row, patch_entry))
        sections.append("")

    return "\n".join(sections)


def build_all_contexts(sample_df: pd.DataFrame) -> dict:
    """
    为 50 条样本构建所有 4 种上下文。

    Returns:
        {pr_id: {context_type: context_text}}
    """
    patch_index = load_patch_index()
    patch_map = {p["pr_id"]: p for p in patch_index}

    all_contexts = {}

    for _, row in sample_df.iterrows():
        pr_id = row["pr_id"]
        patch_entry = patch_map.get(pr_id)
        pr_contexts = {}

        for ctx_type in ["C1", "C2", "C3", "C4"]:
            try:
                ctx_text = build_context(row, patch_entry, ctx_type)
                pr_contexts[ctx_type] = ctx_text
            except Exception as e:
                log.error(f"构建上下文失败 pr_id={pr_id}, ctx={ctx_type}: {e}")
                pr_contexts[ctx_type] = f"[Context build error: {e}]"

        all_contexts[pr_id] = pr_contexts

    # 统计上下文长度
    for ctx_type in ["C1", "C2", "C3", "C4"]:
        lengths = [
            len(ctxs.get(ctx_type, ""))
            for ctxs in all_contexts.values()
        ]
        if lengths:
            avg_len = sum(lengths) / len(lengths)
            max_len = max(lengths)
            truncation_count = sum(
                1 for l in lengths
                if l > 10000  # 超过 ~2500 tokens 视为可能截断
            )
            log.info(f"{ctx_type}: 平均长度={avg_len:.0f} chars, "
                     f"最大={max_len}, 超长={truncation_count}/{len(lengths)}")

    return all_contexts


if __name__ == "__main__":
    from utils import setup_logger
    from config import PROCESSED_DIR
    log = setup_logger("experiment3", PROCESSED_DIR.parent / "pipeline.log")
    import pandas as pd
    sample_df = pd.read_csv(PROCESSED_DIR / "llm_sample_50.csv")
    contexts = build_all_contexts(sample_df)
    log.info(f"构建了 {len(contexts)} 个 PR 的上下文")
