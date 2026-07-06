"""
实验二 步骤四：AST 提取
对 patch 中新增代码行提取 AST 结构特征。
主方案：tree-sitter（P0: .py/.go/.js/.jsx/.ts/.tsx）
降级方案：lexical AST fallback（P1 语言或 tree-sitter 失败时）
"""
import re
import pandas as pd
from pathlib import Path
from collections import Counter

from config import PROCESSED_DIR, P0_EXTENSIONS, CODE_EXTENSIONS
from utils import log, read_json, write_json

# ============================================================
# Tree-sitter 初始化（延迟加载）
# ============================================================
_TS_PARSERS = {}  # ext → (parser, language) 缓存

def _init_tree_sitter():
    """初始化 tree-sitter 语言 parser。"""
    if _TS_PARSERS:
        return

    try:
        import tree_sitter_python as tspy
        import tree_sitter_javascript as tsjs
        import tree_sitter_typescript as tsts
        import tree_sitter_go as tsgo
    except ImportError as e:
        log.warning(f"tree-sitter 语言包导入失败: {e}，将全部使用 lexical fallback")
        return

    try:
        import tree_sitter
        for ext, lang_lib, lang_func_name in [
            (".py", tspy, "language"),
            (".js", tsjs, "language"),
            (".jsx", tsjs, "language"),
            (".ts", tsts, "language_typescript"),
            (".tsx", tsts, "language_tsx"),
            (".go", tsgo, "language"),
        ]:
            try:
                lang_func = getattr(lang_lib, lang_func_name)
                lang = tree_sitter.Language(lang_func())
                parser = tree_sitter.Parser(lang)
                _TS_PARSERS[ext] = parser
            except Exception as e:
                log.warning(f"tree-sitter 初始化失败 ({ext}): {e}")

        log.info(f"tree-sitter 初始化完成: {len(_TS_PARSERS)} 种语言可用 "
                 f"({sorted(_TS_PARSERS.keys())})")
    except ImportError:
        log.warning("tree-sitter 不可用，全部使用 lexical fallback")


# ============================================================
# tree-sitter AST 特征提取
# ============================================================
def _count_ts_nodes(node, depth=0) -> dict:
    """递归遍历 tree-sitter AST，统计节点类型。"""
    stats = {
        "total_nodes": 0,
        "max_depth": depth,
        "error_nodes": 0,
        "func_def": 0,
        "class_def": 0,
        "if_nodes": 0,
        "loop_nodes": 0,
        "try_nodes": 0,
        "return_nodes": 0,
        "assignment_nodes": 0,
    }

    def walk(n, d):
        stats["total_nodes"] += 1
        stats["max_depth"] = max(stats["max_depth"], d)

        node_type = n.type

        if node_type == "ERROR" or "ERROR" in str(node_type):
            stats["error_nodes"] += 1

        # 函数定义
        if node_type in ("function_definition", "function_declaration",
                         "method_definition", "method_declaration",
                         "arrow_function", "function_expression",
                         "func_literal"):
            stats["func_def"] += 1

        # 类定义
        if node_type in ("class_definition", "class_declaration",
                         "type_spec", "type_declaration",
                         "interface_declaration", "struct_type"):
            stats["class_def"] += 1

        # 条件分支
        if node_type in ("if_statement", "if_expression",
                         "switch_statement", "switch_expression",
                         "case_clause", "else_clause", "elif_clause"):
            stats["if_nodes"] += 1

        # 循环
        if node_type in ("for_statement", "for_in_statement",
                         "while_statement", "range_clause",
                         "do_statement"):
            stats["loop_nodes"] += 1

        # 异常处理
        if node_type in ("try_statement", "try_expression",
                         "catch_clause", "except_clause",
                         "finally_clause"):
            stats["try_nodes"] += 1

        # 返回
        if node_type in ("return_statement", "return_expression",
                         "yield", "yield_expression"):
            stats["return_nodes"] += 1

        # 赋值
        if node_type in ("assignment", "assignment_expression",
                         "assignment_statement", "short_var_declaration",
                         "variable_declaration", "augmented_assignment",
                         "var_spec"):
            stats["assignment_nodes"] += 1

        for child in n.children:
            walk(child, d + 1)

    if node is not None:
        walk(node, depth)
    return stats


def _parse_with_tree_sitter(code: str, ext: str) -> dict:
    """使用 tree-sitter 解析代码并提取 AST 特征。"""
    parser = _TS_PARSERS.get(ext)
    if parser is None:
        return None  # 无可用 parser

    # tree-sitter 需要 bytes
    code_bytes = code.encode("utf-8")
    tree = parser.parse(code_bytes)

    if tree.root_node is None:
        return None

    stats = _count_ts_nodes(tree.root_node)
    stats["success"] = True
    stats["fallback"] = False
    return stats


# ============================================================
# Lexical AST Fallback
# ============================================================
# 各语言的关键词模式
LANG_PATTERNS = {
    # Python-like
    ".py": {
        "func_def": re.compile(r'^\s*(def|async def)\s+(\w+)', re.MULTILINE),
        "class_def": re.compile(r'^\s*class\s+(\w+)', re.MULTILINE),
        "if_nodes": re.compile(r'^\s*(if|elif|else)\b', re.MULTILINE),
        "loop_nodes": re.compile(r'^\s*(for|while)\b', re.MULTILINE),
        "try_nodes": re.compile(r'^\s*(try|except|finally)\b', re.MULTILINE),
        "return_nodes": re.compile(r'^\s*(return|yield)\b', re.MULTILINE),
        "assignment_nodes": re.compile(r'^\s*\w[\w.]*\s*=\s*', re.MULTILINE),
    },
    # Go
    ".go": {
        "func_def": re.compile(r'^\s*func\s+(?:\([^)]*\)\s+)?(\w+)', re.MULTILINE),
        "class_def": re.compile(r'^\s*type\s+\w+\s+struct\b', re.MULTILINE),
        "if_nodes": re.compile(r'^\s*(if|else|switch|case|default)\b', re.MULTILINE),
        "loop_nodes": re.compile(r'^\s*for\b', re.MULTILINE),
        "try_nodes": re.compile(r'^\s*defer\b', re.MULTILINE),
        "return_nodes": re.compile(r'^\s*return\b', re.MULTILINE),
        "assignment_nodes": re.compile(r'^\s*\w[\w.]*\s*:?=\s*', re.MULTILINE),
    },
    # JavaScript / TypeScript / JSX / TSX
    ".js": {
        "func_def": re.compile(
            r'^\s*(function|async function|const\s+\w+\s*=\s*(async\s*)?\(|'
            r'let\s+\w+\s*=\s*(async\s*)?\(|'
            r'var\s+\w+\s*=\s*(async\s*)?\()', re.MULTILINE),
        "class_def": re.compile(r'^\s*class\s+\w+', re.MULTILINE),
        "if_nodes": re.compile(r'^\s*(if|else|switch|case|default)\b', re.MULTILINE),
        "loop_nodes": re.compile(r'^\s*(for|while|do)\b', re.MULTILINE),
        "try_nodes": re.compile(r'^\s*(try|catch|finally)\b', re.MULTILINE),
        "return_nodes": re.compile(r'^\s*return\b', re.MULTILINE),
        "assignment_nodes": re.compile(r'^\s*(const|let|var)\s+\w', re.MULTILINE),
    },
    ".jsx": {
        "func_def": re.compile(
            r'^\s*(function|async function|const\s+\w+\s*=\s*(async\s*)?\(|'
            r'let\s+\w+\s*=\s*(async\s*)?\(|'
            r'var\s+\w+\s*=\s*(async\s*)?\()', re.MULTILINE),
        "class_def": re.compile(r'^\s*class\s+\w+', re.MULTILINE),
        "if_nodes": re.compile(r'^\s*(if|else|switch|case|default)\b', re.MULTILINE),
        "loop_nodes": re.compile(r'^\s*(for|while|do)\b', re.MULTILINE),
        "try_nodes": re.compile(r'^\s*(try|catch|finally)\b', re.MULTILINE),
        "return_nodes": re.compile(r'^\s*return\b', re.MULTILINE),
        "assignment_nodes": re.compile(r'^\s*(const|let|var)\s+\w', re.MULTILINE),
    },
    ".ts": {
        "func_def": re.compile(
            r'^\s*(function|async function|const\s+\w+\s*=\s*(async\s*)?\(|'
            r'let\s+\w+\s*=\s*(async\s*)?\()', re.MULTILINE),
        "class_def": re.compile(r'^\s*(class|interface|type)\s+\w+', re.MULTILINE),
        "if_nodes": re.compile(r'^\s*(if|else|switch|case|default)\b', re.MULTILINE),
        "loop_nodes": re.compile(r'^\s*(for|while|do)\b', re.MULTILINE),
        "try_nodes": re.compile(r'^\s*(try|catch|finally)\b', re.MULTILINE),
        "return_nodes": re.compile(r'^\s*return\b', re.MULTILINE),
        "assignment_nodes": re.compile(r'^\s*(const|let|var)\s+\w', re.MULTILINE),
    },
    ".tsx": {
        "func_def": re.compile(
            r'^\s*(function|async function|const\s+\w+\s*=\s*(async\s*)?\(|'
            r'let\s+\w+\s*=\s*(async\s*)?\()', re.MULTILINE),
        "class_def": re.compile(r'^\s*(class|interface|type)\s+\w+', re.MULTILINE),
        "if_nodes": re.compile(r'^\s*(if|else|switch|case|default)\b', re.MULTILINE),
        "loop_nodes": re.compile(r'^\s*(for|while|do)\b', re.MULTILINE),
        "try_nodes": re.compile(r'^\s*(try|catch|finally)\b', re.MULTILINE),
        "return_nodes": re.compile(r'^\s*return\b', re.MULTILINE),
        "assignment_nodes": re.compile(r'^\s*(const|let|var)\s+\w', re.MULTILINE),
    },
}

# Generic C-like fallback
_GENERIC_PATTERNS = {
    "func_def": re.compile(
        r'^\s*(def|function|func|fn|async def|async function)\b|'
        r'^\s*[\w<>[\]:,]+\s+\w+\s*\([^)]*\)\s*[\{:]', re.MULTILINE),
    "class_def": re.compile(
        r'^\s*(class|interface|struct|type)\s+\w+', re.MULTILINE),
    "if_nodes": re.compile(r'^\s*(if|else|elif|switch|case|default|match)\b', re.MULTILINE),
    "loop_nodes": re.compile(r'^\s*(for|while|do|range)\b', re.MULTILINE),
    "try_nodes": re.compile(r'^\s*(try|catch|except|finally|defer)\b', re.MULTILINE),
    "return_nodes": re.compile(r'^\s*(return|yield|raise|throw)\b', re.MULTILINE),
    "assignment_nodes": re.compile(
        r'^\s*(\w[\w.]*\s*=\s*|const\s+\w|let\s+\w|var\s+\w|'
        r'\w+\s*:?=\s*)', re.MULTILINE),
}


def _estimate_depth_lexical(code: str, ext: str) -> int:
    """根据缩进或大括号层级估算代码深度。"""
    lines = code.split("\n")
    if ext == ".py":
        # Python: 缩进级别
        max_indent = 0
        for line in lines:
            stripped = line.rstrip()
            if stripped and not stripped.startswith(("#", '"""', "'''")):
                indent = len(line) - len(line.lstrip())
                max_indent = max(max_indent, indent)
        return max(1, max_indent // 4 + 1)  # 假设每 4 空格为一级
    else:
        # C-like: 大括号嵌套
        max_brace_depth = 0
        current = 0
        for line in lines:
            current += line.count("{") - line.count("}")
            max_brace_depth = max(max_brace_depth, current)
        return max(1, max_brace_depth + 1)


def _parse_lexical(code: str, ext: str) -> dict:
    """Lexical AST fallback：基于正则的轻量结构分析。"""
    if not code or not code.strip():
        return {
            "success": True, "fallback": True,
            "total_nodes": 0, "max_depth": 0, "error_nodes": 0,
            "func_def": 0, "class_def": 0, "if_nodes": 0,
            "loop_nodes": 0, "try_nodes": 0, "return_nodes": 0,
            "assignment_nodes": 0,
        }

    patterns = LANG_PATTERNS.get(ext, _GENERIC_PATTERNS)

    counts = {}
    for key, pat in patterns.items():
        matches = pat.findall(code)
        counts[key] = len(matches)

    # 估算总节点数：代码行数 + 关键字计数加权
    lines = [l for l in code.split("\n") if l.strip()
             and not l.strip().startswith(("#", "//", "/*", "*", "'''", '"""'))]
    statement_count = len(lines)
    keyword_sum = sum(counts.values())
    total_nodes = max(1, statement_count + keyword_sum)

    depth = _estimate_depth_lexical(code, ext)

    return {
        "success": True,
        "fallback": True,
        "total_nodes": total_nodes,
        "max_depth": depth,
        "error_nodes": 0,
        "func_def": counts.get("func_def", 0),
        "class_def": counts.get("class_def", 0),
        "if_nodes": counts.get("if_nodes", 0),
        "loop_nodes": counts.get("loop_nodes", 0),
        "try_nodes": counts.get("try_nodes", 0),
        "return_nodes": counts.get("return_nodes", 0),
        "assignment_nodes": counts.get("assignment_nodes", 0),
    }


# ============================================================
# 文件级 AST 特征提取
# ============================================================
def extract_file_ast(added_lines: str, ext: str) -> dict:
    """对单个文件的 added_lines 提取 AST 特征。"""
    if not added_lines or not added_lines.strip():
        return {
            "success": False, "fallback": False,
            "total_nodes": 0, "max_depth": 0, "error_nodes": 0,
            "func_def": 0, "class_def": 0, "if_nodes": 0,
            "loop_nodes": 0, "try_nodes": 0, "return_nodes": 0,
            "assignment_nodes": 0,
        }

    # 尝试 tree-sitter
    result = _parse_with_tree_sitter(added_lines, ext)
    if result is not None:
        return result

    # tree-sitter 不可用或失败，使用 fallback
    return _parse_lexical(added_lines, ext)


# ============================================================
# PR 级 AST 特征汇总
# ============================================================
def extract_pr_ast(pr_record: dict) -> dict:
    """对单个 PR 的所有代码文件汇总 AST 特征。"""
    pr_id = pr_record["pr_id"]
    repo = pr_record["repo"]

    # 汇总统计
    agg = {
        "total_nodes": 0, "max_depth": 0, "error_nodes": 0,
        "func_def": 0, "class_def": 0, "if_nodes": 0,
        "loop_nodes": 0, "try_nodes": 0, "return_nodes": 0,
        "assignment_nodes": 0,
    }
    files_parsed = 0
    files_fallback = 0
    files_attempted = 0

    for f in pr_record.get("files", []):
        if f.get("file_type") != "code":
            continue
        if not f.get("has_patch"):
            continue

        ext = f.get("ext", "")
        if ext not in CODE_EXTENSIONS:
            continue

        files_attempted += 1
        added_lines = f.get("added_lines", "")

        result = extract_file_ast(added_lines, ext)

        if result["success"]:
            files_parsed += 1
            if result.get("fallback"):
                files_fallback += 1

            for key in agg:
                agg[key] += result.get(key, 0)

    # 构建输出行
    total_parsed = max(files_parsed, 1)
    return {
        "pr_id": pr_id,
        "repo": repo,
        # AST 整体特征
        "ast_total_nodes": agg["total_nodes"],
        "ast_max_depth": agg["max_depth"],
        "ast_files_parsed": files_parsed,
        "ast_files_attempted": files_attempted,
        "ast_files_fallback": files_fallback,
        "ast_parse_success_rate": round(files_parsed / max(files_attempted, 1), 4),
        "ast_error_node_count": agg["error_nodes"],
        # 结构分解
        "ast_func_def_count": agg["func_def"],
        "ast_class_def_count": agg["class_def"],
        "ast_if_count": agg["if_nodes"],
        "ast_loop_count": agg["loop_nodes"],
        "ast_try_count": agg["try_nodes"],
        "ast_return_count": agg["return_nodes"],
        "ast_assignment_count": agg["assignment_nodes"],
    }


# ============================================================
# 批量处理
# ============================================================
def run(patch_index_path: Path = None, output_dir: Path = None) -> pd.DataFrame:
    if patch_index_path is None:
        patch_index_path = PROCESSED_DIR / "patch_index.json"
    if output_dir is None:
        output_dir = PROCESSED_DIR

    # 初始化 tree-sitter（在批量处理前）
    _init_tree_sitter()

    log.info(f"加载 patch 索引: {patch_index_path}")
    patch_index = read_json(patch_index_path)
    log.info(f"共 {len(patch_index)} 条 PR，开始 AST 提取...")

    rows = []
    ts_used = 0
    fallback_used = 0
    for i, pr in enumerate(patch_index):
        row = extract_pr_ast(pr)
        rows.append(row)

        if row["ast_files_fallback"] < row["ast_files_parsed"]:
            ts_used += 1
        if row["ast_files_fallback"] > 0:
            fallback_used += 1

        if (i + 1) % 200 == 0:
            log.info(f"AST 进度: {i+1}/{len(patch_index)} "
                     f"(tree-sitter: {ts_used}, fallback: {fallback_used})")

    log.info(f"AST 提取完成: {len(rows)} 条 PR, "
             f"至少部分使用 tree-sitter: {ts_used}, "
             f"含 fallback: {fallback_used}")

    df = pd.DataFrame(rows)

    # 统计
    log.info(f"AST 解析成功率: avg={df['ast_parse_success_rate'].mean():.3f}")
    log.info(f"含 fallback 文件 PR 数: {fallback_used}")
    log.info(f"完全未解析 PR 数: {(df['ast_files_parsed'] == 0).sum()}")

    # 保存
    csv_path = output_dir / "ast_features.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info(f"AST 特征已保存: {csv_path} ({len(df)} 行 × {len(df.columns)} 列)")

    return df


# ============================================================
# AST 样例输出（供报告使用）
# ============================================================
def get_ast_samples(patch_index_path: Path = None, n_samples: int = 2):
    """获取 AST 解析样例，用于实验报告展示。"""
    if patch_index_path is None:
        patch_index_path = PROCESSED_DIR / "patch_index.json"

    _init_tree_sitter()

    patch_index = read_json(patch_index_path)
    samples = []

    for pr in patch_index:
        if len(samples) >= n_samples:
            break
        for f in pr.get("files", []):
            if len(samples) >= n_samples:
                break
            if f.get("file_type") != "code" or not f.get("has_patch"):
                continue
            ext = f.get("ext", "")
            if ext not in P0_EXTENSIONS:
                continue
            added = f.get("added_lines", "")
            if not added or len(added) < 50:
                continue

            result = extract_file_ast(added, ext)
            samples.append({
                "pr_id": pr["pr_id"],
                "repo": pr["repo"],
                "filename": f["filename"],
                "ext": ext,
                "code_snippet": added[:500],
                "ast_features": result,
                "used_tree_sitter": not result.get("fallback", False),
            })

    return samples


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    df = run()

    # 打印样例
    samples = get_ast_samples()
    for s in samples:
        log.info(f"\nAST 样例: {s['filename']} ({s['ext']})")
        log.info(f"  使用 tree-sitter: {s['used_tree_sitter']}")
        for k, v in s["ast_features"].items():
            log.info(f"  {k}: {v}")
