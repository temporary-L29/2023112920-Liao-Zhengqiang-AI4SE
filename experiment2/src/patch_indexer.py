"""
实验二 步骤三：Patch 抽取与索引
从 raw/merged_raw.json 提取每个 PR 的文件 patch 和新增代码行，
与 human_only_dataset 对齐，输出 patch_index.json。
"""
import json
import re
import pandas as pd
from pathlib import Path
from collections import Counter

from config import (
    RAW_MERGED_JSON, PROCESSED_DIR,
    CODE_EXTENSIONS, CONFIG_EXTENSIONS, DOC_EXTENSIONS,
    TEST_FILE_MARKERS, P0_EXTENSIONS,
)
from utils import log, write_json, write_json_compact


# ============================================================
# Diff 解析
# ============================================================
# 匹配 hunk header: @@ -old,count +new,count @@
HUNK_RE = re.compile(r'^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@')

# diff 元数据行（不应被当作代码行）
DIFF_META_RE = re.compile(r'^(---|\+\+\+|@@|diff |index |new file|deleted file|'
                          r'rename |similarity|Binary files|\\ No newline)')

# 文件名提取
FILENAME_RE = re.compile(r'^\+\+\+\s+b/(.+)$')


def extract_added_lines(patch: str) -> list:
    """从 unified diff patch 中提取新增代码行（+ 开头）。"""
    if not patch:
        return []

    added_lines = []
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            # 去掉首字符 '+'，保留缩进和内容
            code_line = line[1:]
            # 跳过纯 diff 元数据行
            if DIFF_META_RE.match(code_line):
                continue
            # 保留空行和代码行
            added_lines.append(code_line)

    return added_lines


def classify_file_type(filename: str) -> str:
    """根据文件名和扩展名分类文件类型。"""
    ext = Path(filename).suffix.lower()
    if ext in CODE_EXTENSIONS:
        return "code"
    elif ext in CONFIG_EXTENSIONS:
        return "config"
    elif ext in DOC_EXTENSIONS:
        return "doc"
    else:
        return "other"


def is_test_file(filename: str) -> bool:
    """判断是否为测试文件。"""
    fname = Path(filename).name.lower()
    for marker in TEST_FILE_MARKERS:
        if marker in fname:
            return True
    # 常见测试目录
    parts = Path(filename).parts
    for p in parts:
        if p.lower() in ("test", "tests", "spec", "__tests__", "testing"):
            return True
    return False


# ============================================================
# Patch 索引构建
# ============================================================
def build_patch_index(human_df: pd.DataFrame, raw_path: Path) -> tuple:
    """
    从 raw JSON 提取与 human_only_dataset 对齐的 patch 数据。

    Returns:
        (patch_index: list[dict], coverage_stats: dict)
    """
    log.info(f"加载原始数据: {raw_path}")
    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # 建立 pr_id → raw entry 的映射
    pr_to_raw = {}
    for entry in raw_data:
        detail = entry.get("detail") or {}
        pr_id = detail.get("id")
        if pr_id is not None:
            pr_to_raw[pr_id] = entry

    log.info(f"原始数据 {len(raw_data)} 条, 建立 pr_id 映射 {len(pr_to_raw)} 条")

    # 构建 patch index
    patch_index = []
    matched = 0
    unmatched = 0
    pr_with_patch = 0
    total_files = 0
    files_with_patch = 0
    ext_counter = Counter()
    added_lines_total = 0

    for _, row in human_df.iterrows():
        pr_id = row["pr_id"]
        raw_entry = pr_to_raw.get(pr_id)

        pr_record = {
            "pr_id": pr_id,
            "repo": row["repo"],
            "is_merged": bool(row["is_merged"]),
            "patch_available": False,
            "files": [],
        }

        if raw_entry is None:
            unmatched += 1
            patch_index.append(pr_record)
            continue

        matched += 1
        files = raw_entry.get("files") or []

        has_any_patch = False
        pr_files = []

        for f in files:
            filename = f.get("filename", "")
            ext = Path(filename).suffix.lower()
            patch = f.get("patch") or ""
            added_lines = extract_added_lines(patch)
            additions = f.get("additions", 0)
            deletions = f.get("deletions", 0)
            changes = f.get("changes", 0)
            status = f.get("status", "modified")

            file_type = classify_file_type(filename)
            is_test = is_test_file(filename)

            total_files += 1
            if patch:
                files_with_patch += 1
                has_any_patch = True

            ext_counter[ext] += 1
            added_lines_total += len(added_lines)

            pr_files.append({
                "filename": filename,
                "ext": ext,
                "status": status,
                "additions": additions,
                "deletions": deletions,
                "changes": changes,
                "file_type": file_type,
                "is_test": is_test,
                "p0_language": ext in P0_EXTENSIONS,
                "has_patch": bool(patch),
                "added_line_count": len(added_lines),
                "added_lines": "\n".join(added_lines) if added_lines else "",
            })

        pr_record["patch_available"] = has_any_patch
        pr_record["files"] = pr_files
        if has_any_patch:
            pr_with_patch += 1

        patch_index.append(pr_record)

    # 覆盖率统计
    total_prs = len(human_df)
    coverage_stats = {
        "total_prs": total_prs,
        "matched_prs": matched,
        "unmatched_prs": unmatched,
        "pr_with_patch": pr_with_patch,
        "pr_patch_coverage": round(100 * pr_with_patch / max(total_prs, 1), 2),
        "total_files": total_files,
        "files_with_patch": files_with_patch,
        "file_patch_coverage": round(100 * files_with_patch / max(total_files, 1), 2),
        "total_added_lines": added_lines_total,
        "extension_distribution": dict(ext_counter.most_common(30)),
    }

    log.info(f"PR 级匹配: {matched}/{total_prs} (未匹配: {unmatched})")
    log.info(f"PR 级 patch 覆盖: {pr_with_patch}/{total_prs} "
             f"({coverage_stats['pr_patch_coverage']}%)")
    log.info(f"文件级 patch 覆盖: {files_with_patch}/{total_files} "
             f"({coverage_stats['file_patch_coverage']}%)")
    log.info(f"总计新增代码行: {added_lines_total}")
    log.info(f"Top 扩展名: {dict(ext_counter.most_common(10))}")

    return patch_index, coverage_stats


def run(human_csv_path: Path = None, raw_path: Path = None,
        output_dir: Path = None):
    if human_csv_path is None:
        human_csv_path = PROCESSED_DIR / "human_only_dataset.csv"
    if raw_path is None:
        raw_path = RAW_MERGED_JSON
    if output_dir is None:
        output_dir = PROCESSED_DIR

    human_df = pd.read_csv(human_csv_path)
    log.info(f"加载人类代码数据集: {len(human_df)} 条")

    patch_index, coverage_stats = build_patch_index(human_df, raw_path)

    # 保存 patch_index.json（紧凑格式，因为含有大量代码行）
    index_path = output_dir / "patch_index.json"
    write_json_compact(patch_index, index_path)
    log.info(f"Patch 索引已保存: {index_path} ({len(patch_index)} 条 PR)")

    # 保存覆盖率统计（缩进格式，方便阅读）
    coverage_path = output_dir / "patch_coverage_stats.json"
    write_json(coverage_stats, coverage_path)
    log.info(f"覆盖率统计已保存: {coverage_path}")

    return patch_index, coverage_stats


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    run()
