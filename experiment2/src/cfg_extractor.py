"""
实验二 步骤五：CFG 构建
基于 patch 新增代码行构建简化控制流图。
由于 PR patch 只有局部新增行，缺少完整函数上下文，
本模块构建 patch 级简化 CFG（非编译器级完整 CFG）。
"""
import re
import pandas as pd
from pathlib import Path

from config import PROCESSED_DIR, CODE_EXTENSIONS
from utils import log, read_json


# ============================================================
# 控制流关键词模式（多语言正则）
# ============================================================
# 按缩进级别和语言分类
CFG_PATTERNS = {
    # Python（缩进敏感）
    ".py": {
        "branch_start": re.compile(
            r'^(\s*)(if|elif)\s+.*:\s*$', re.MULTILINE),
        "branch_else": re.compile(
            r'^(\s*)(else)\s*:\s*$', re.MULTILINE),
        "loop_start": re.compile(
            r'^(\s*)(for|while)\s+.*:\s*$', re.MULTILINE),
        "try_start": re.compile(
            r'^(\s*)(try)\s*:\s*$', re.MULTILINE),
        "except_start": re.compile(
            r'^(\s*)(except)[\s:].*:\s*$', re.MULTILINE),
        "finally_start": re.compile(
            r'^(\s*)(finally)\s*:\s*$', re.MULTILINE),
        "exit_stmt": re.compile(
            r'^(\s*)(return|raise|yield)\b', re.MULTILINE),
        "jump_stmt": re.compile(
            r'^(\s*)(break|continue)\b', re.MULTILINE),
        "match_start": re.compile(
            r'^(\s*)(match)\s+.*:\s*$', re.MULTILINE),
        "case_start": re.compile(
            r'^(\s*)(case)\s+.*:\s*$', re.MULTILINE),
    },
}

# C-like（大括号语言）通用模式
_CLIKE_PATTERNS = {
    "branch_start": re.compile(
        r'^\s*(if|else\s+if|elif)\s*\(.*\)\s*\{?', re.MULTILINE),
    "branch_else": re.compile(
        r'^\s*else\s*\{?', re.MULTILINE),
    "loop_start": re.compile(
        r'^\s*(for|while|do)\s*\(.*\)\s*\{?', re.MULTILINE),
    "try_start": re.compile(
        r'^\s*try\s*\{?', re.MULTILINE),
    "except_start": re.compile(
        r'^\s*(catch|except)\s*\(?.*\)?\s*\{?', re.MULTILINE),
    "finally_start": re.compile(
        r'^\s*finally\s*\{?', re.MULTILINE),
    "exit_stmt": re.compile(
        r'^\s*(return|throw|raise|yield)\b', re.MULTILINE),
    "jump_stmt": re.compile(
        r'^\s*(break|continue)\b', re.MULTILINE),
    "switch_start": re.compile(
        r'^\s*(switch|match)\s*\(.*\)\s*\{?', re.MULTILINE),
    "case_start": re.compile(
        r'^\s*(case|default)\s+', re.MULTILINE),
}

# Go 专用（略有不同）
_GO_PATTERNS = {
    "branch_start": re.compile(
        r'^\s*(if|else\s+if)\s+.*\{', re.MULTILINE),
    "branch_else": re.compile(
        r'^\s*else\s*\{', re.MULTILINE),
    "loop_start": re.compile(
        r'^\s*for\s+.*\{', re.MULTILINE),
    "try_start": re.compile(
        r'^\s*defer\b', re.MULTILINE),  # Go 无 try/catch
    "except_start": re.compile(
        r'^\s*if\s+err\s*!=\s*nil', re.MULTILINE),
    "finally_start": None,
    "exit_stmt": re.compile(
        r'^\s*(return|panic)\b', re.MULTILINE),
    "jump_stmt": re.compile(
        r'^\s*(break|continue|goto)\b', re.MULTILINE),
    "switch_start": re.compile(
        r'^\s*switch\s+.*\{', re.MULTILINE),
    "case_start": re.compile(
        r'^\s*(case|default)\s*:', re.MULTILINE),
}

CLIKE_EXTS = {".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp", ".rs"}


def _get_patterns(ext: str) -> dict:
    """获取语言对应的 CFG 模式。"""
    if ext == ".py":
        return CFG_PATTERNS[".py"]
    elif ext == ".go":
        return _GO_PATTERNS
    elif ext in CLIKE_EXTS:
        return _CLIKE_PATTERNS
    else:
        return _CLIKE_PATTERNS  # 默认 C-like


# ============================================================
# 简化 CFG 构建
# ============================================================
class SimpleCFG:
    """patch 级简化 CFG。"""

    def __init__(self):
        self.nodes = []       # list of (node_id, node_type)
        self.edges = []       # list of (from_id, to_id, edge_type)
        self.next_id = 0
        self.branch_depth = 0
        self.max_branch_depth = 0

    def _add_node(self, node_type: str, line_idx: int = -1) -> int:
        """添加节点，返回 node_id。"""
        nid = self.next_id
        self.next_id += 1
        self.nodes.append((nid, node_type, line_idx))
        return nid

    def _add_edge(self, from_id: int, to_id: int, edge_type: str = "seq"):
        """添加边。"""
        self.edges.append((from_id, to_id, edge_type))

    def build_from_lines(self, lines: list, ext: str) -> bool:
        """从代码行构建简化 CFG。"""
        patterns = _get_patterns(ext)
        if not lines:
            return False

        # 1. 添加入口节点
        entry_id = self._add_node("entry")

        # 2. 解析每行，识别控制流结构
        # 简化策略：顺序扫描，追踪分支嵌套
        structured_lines = []  # (line_idx, line_type, indent_level)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//", "/*", "*", "'''", '"""')):
                continue

            indent = len(line) - len(line.lstrip())

            line_type = "statement"
            if patterns["exit_stmt"] and patterns["exit_stmt"].match(line):
                line_type = "exit"
            elif patterns["jump_stmt"] and patterns["jump_stmt"].match(line):
                line_type = "jump"
            elif patterns["branch_start"] and patterns["branch_start"].match(line):
                line_type = "branch"
                indent = self._get_indent(line, ext)
            elif patterns["branch_else"] and patterns["branch_else"].match(line):
                line_type = "branch_else"
                indent = self._get_indent(line, ext)
            elif patterns["loop_start"] and patterns["loop_start"].match(line):
                line_type = "loop"
                indent = self._get_indent(line, ext)
            elif patterns["try_start"] and patterns["try_start"].match(line):
                line_type = "try"
                indent = self._get_indent(line, ext)
            elif patterns["except_start"] and patterns["except_start"].match(line):
                line_type = "except"
                indent = self._get_indent(line, ext)
            elif patterns["finally_start"] and patterns["finally_start"]:
                if patterns["finally_start"].match(line):
                    line_type = "finally"
                    indent = self._get_indent(line, ext)
            elif patterns.get("switch_start") and patterns["switch_start"].match(line):
                line_type = "branch"
                indent = self._get_indent(line, ext)
            elif patterns.get("case_start") and patterns["case_start"].match(line):
                line_type = "branch"
                indent = self._get_indent(line, ext)

            structured_lines.append((i, line_type, indent))

        if not structured_lines:
            # 只有注释/空行
            stmt_id = self._add_node("statement")
            self._add_edge(entry_id, stmt_id, "seq")
            return True

        # 3. 构建节点和边
        last_node_id = entry_id
        # 追踪分支/循环栈：(start_node_id, indent_level, type)
        branch_stack = []

        in_branch_body = False  # 标记是否在分支语句的第一行（需要 true/false 分支）

        for i, (line_idx, line_type, indent) in enumerate(structured_lines):
            # 弹出已退出的分支/循环
            while branch_stack and indent <= branch_stack[-1][1]:
                popped = branch_stack.pop()
                self.max_branch_depth = max(self.max_branch_depth,
                                            len(branch_stack) + 1)

            if line_type in ("statement",):
                nid = self._add_node("statement", line_idx)
                self._add_edge(last_node_id, nid, "seq")

                # 如果是分支/循环体第一条语句，添加 true 分支边
                if in_branch_body and branch_stack:
                    branch_nid = branch_stack[-1][0]
                    # 确保分支节点有 true 边通向第一条语句
                    if not any(e[0] == branch_nid and e[2] == "true"
                              for e in self.edges):
                        self._add_edge(branch_nid, nid, "true")
                    in_branch_body = False

                last_node_id = nid

            elif line_type == "branch":
                nid = self._add_node("branch", line_idx)
                self._add_edge(last_node_id, nid, "seq")
                branch_stack.append((nid, indent, "branch"))
                in_branch_body = True
                last_node_id = nid

            elif line_type == "branch_else":
                # else 是之前分支的 false 路径
                if branch_stack and branch_stack[-1][2] == "branch":
                    nid = self._add_node("branch", line_idx)
                    # 从上一个分支节点的 false 边
                    prev_branch = branch_stack[-1][0]
                    self._add_edge(prev_branch, nid, "false")
                    branch_stack[-1] = (nid, indent, "branch")
                    in_branch_body = True
                    last_node_id = nid

            elif line_type == "loop":
                nid = self._add_node("loop", line_idx)
                self._add_edge(last_node_id, nid, "seq")
                branch_stack.append((nid, indent, "loop"))
                in_branch_body = True
                last_node_id = nid

            elif line_type in ("try", "except", "finally"):
                nid = self._add_node("exception", line_idx)
                self._add_edge(last_node_id, nid, "seq")
                if in_branch_body:
                    in_branch_body = False
                last_node_id = nid

            elif line_type == "exit":
                nid = self._add_node("exit", line_idx)
                self._add_edge(last_node_id, nid, "seq")
                if in_branch_body and branch_stack:
                    branch_nid = branch_stack[-1][0]
                    if not any(e[0] == branch_nid and e[2] == "true"
                              for e in self.edges):
                        self._add_edge(branch_nid, nid, "true")
                    in_branch_body = False
                last_node_id = nid

            elif line_type == "jump":
                nid = self._add_node("exit", line_idx)
                self._add_edge(last_node_id, nid, "seq")
                if in_branch_body:
                    in_branch_body = False
                last_node_id = nid

        # 4. 处理分支节点的 false 边：如果没有 else，指向分支后的下一条语句
        # （简化处理：false 边留空，由后续分析处理）

        # 5. 为循环节点添加回边（简化：如果循环后有语句，循环回边指向自身）
        # （在简化 CFG 中，我们主要通过节点计数和边计数来近似圈复杂度）

        return True

    @staticmethod
    def _get_indent(line: str, ext: str) -> int:
        """获取行的缩进级别。"""
        if ext == ".py":
            stripped = line.lstrip()
            return len(line) - len(stripped)
        else:
            # C-like: 大括号嵌套
            return line.count("{") - line.count("}")

    def get_features(self) -> dict:
        """从 CFG 提取特征。"""
        total_nodes = len(self.nodes)
        total_edges = len(self.edges)

        node_types = {}
        for _, ntype, _ in self.nodes:
            node_types[ntype] = node_types.get(ntype, 0) + 1

        branch_nodes = node_types.get("branch", 0)
        loop_nodes = node_types.get("loop", 0)
        exit_nodes = node_types.get("exit", 0) + node_types.get("jump", 0)

        # 出度统计
        out_degrees = {}
        for src, dst, _ in self.edges:
            out_degrees[src] = out_degrees.get(src, 0) + 1
        avg_out_degree = (sum(out_degrees.values()) / max(len(out_degrees), 1)
                         if out_degrees else 0)

        # 简化圈复杂度: E - N + 2 (假设单个连通分量 P=1)
        cyclomatic = max(0, total_edges - total_nodes + 2)

        return {
            "cfg_total_nodes": total_nodes,
            "cfg_total_edges": total_edges,
            "cfg_branch_nodes": branch_nodes,
            "cfg_loop_nodes": loop_nodes,
            "cfg_exit_nodes": exit_nodes,
            "cfg_entry_nodes": 1,
            "cfg_cyclomatic_complexity": cyclomatic,
            "cfg_max_branch_depth": self.max_branch_depth,
            "cfg_avg_out_degree": round(avg_out_degree, 4),
            "cfg_available": total_nodes > 0,
        }


# ============================================================
# 文件级 CFG 构建
# ============================================================
def extract_file_cfg(added_lines: str, ext: str) -> dict:
    """对单个文件的 added_lines 构建 CFG 并提取特征。"""
    if not added_lines or not added_lines.strip():
        return {
            "cfg_total_nodes": 0, "cfg_total_edges": 0,
            "cfg_branch_nodes": 0, "cfg_loop_nodes": 0,
            "cfg_exit_nodes": 0, "cfg_entry_nodes": 0,
            "cfg_cyclomatic_complexity": 0,
            "cfg_max_branch_depth": 0,
            "cfg_avg_out_degree": 0.0, "cfg_available": False,
        }

    lines = added_lines.split("\n")
    cfg = SimpleCFG()
    success = cfg.build_from_lines(lines, ext)

    features = cfg.get_features()
    features["cfg_available"] = success
    return features


# ============================================================
# PR 级 CFG 汇总
# ============================================================
def extract_pr_cfg(pr_record: dict) -> dict:
    """对单个 PR 的所有代码文件汇总 CFG 特征。"""
    pr_id = pr_record["pr_id"]
    repo = pr_record["repo"]

    agg = {
        "cfg_total_nodes": 0, "cfg_total_edges": 0,
        "cfg_branch_nodes": 0, "cfg_loop_nodes": 0,
        "cfg_exit_nodes": 0, "cfg_entry_nodes": 0,
        "cfg_cyclomatic_complexity": 0,
        "cfg_max_branch_depth": 0,
        "cfg_files_processed": 0, "cfg_files_with_cfg": 0,
    }

    for f in pr_record.get("files", []):
        if f.get("file_type") != "code":
            continue
        if not f.get("has_patch"):
            continue

        ext = f.get("ext", "")
        if ext not in CODE_EXTENSIONS:
            continue

        agg["cfg_files_processed"] += 1
        added_lines = f.get("added_lines", "")

        result = extract_file_cfg(added_lines, ext)

        if result["cfg_available"]:
            agg["cfg_files_with_cfg"] += 1

        for key in ["cfg_total_nodes", "cfg_total_edges",
                     "cfg_branch_nodes", "cfg_loop_nodes",
                     "cfg_exit_nodes", "cfg_entry_nodes",
                     "cfg_cyclomatic_complexity"]:
            agg[key] += result.get(key, 0)

        agg["cfg_max_branch_depth"] = max(
            agg["cfg_max_branch_depth"],
            result.get("cfg_max_branch_depth", 0)
        )

    # 平均出度：PR 级重新计算
    total_edges = agg["cfg_total_edges"]
    total_nodes = max(agg["cfg_total_nodes"], 1)
    avg_out = round(total_edges / total_nodes, 4)

    return {
        "pr_id": pr_id,
        "repo": repo,
        "cfg_total_nodes": agg["cfg_total_nodes"],
        "cfg_total_edges": agg["cfg_total_edges"],
        "cfg_branch_nodes": agg["cfg_branch_nodes"],
        "cfg_loop_nodes": agg["cfg_loop_nodes"],
        "cfg_exit_nodes": agg["cfg_exit_nodes"],
        "cfg_entry_nodes": agg["cfg_entry_nodes"],
        "cfg_cyclomatic_complexity": agg["cfg_cyclomatic_complexity"],
        "cfg_max_branch_depth": agg["cfg_max_branch_depth"],
        "cfg_avg_out_degree": avg_out,
        "cfg_files_processed": agg["cfg_files_processed"],
        "cfg_files_with_cfg": agg["cfg_files_with_cfg"],
        "cfg_available": agg["cfg_files_with_cfg"] > 0,
    }


# ============================================================
# 批量处理
# ============================================================
def run(patch_index_path: Path = None, output_dir: Path = None) -> pd.DataFrame:
    if patch_index_path is None:
        patch_index_path = PROCESSED_DIR / "patch_index.json"
    if output_dir is None:
        output_dir = PROCESSED_DIR

    log.info(f"加载 patch 索引: {patch_index_path}")
    patch_index = read_json(patch_index_path)
    log.info(f"共 {len(patch_index)} 条 PR，开始 CFG 构建...")

    rows = []
    cfg_available_count = 0
    for i, pr in enumerate(patch_index):
        row = extract_pr_cfg(pr)
        rows.append(row)
        if row["cfg_available"]:
            cfg_available_count += 1

        if (i + 1) % 200 == 0:
            log.info(f"CFG 进度: {i+1}/{len(patch_index)} "
                     f"(有 CFG: {cfg_available_count})")

    log.info(f"CFG 构建完成: {len(rows)} 条 PR, "
             f"有 CFG: {cfg_available_count} "
             f"({100*cfg_available_count/max(len(rows),1):.1f}%)")

    df = pd.DataFrame(rows)

    # 统计
    log.info(f"CFG 可用率: {cfg_available_count}/{len(rows)}")
    log.info(f"平均 CFG 节点数: {df['cfg_total_nodes'].mean():.1f}")
    log.info(f"平均圈复杂度: {df['cfg_cyclomatic_complexity'].mean():.1f}")

    # 保存
    csv_path = output_dir / "cfg_features.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info(f"CFG 特征已保存: {csv_path} ({len(df)} 行 × {len(df.columns)} 列)")

    return df


# ============================================================
# CFG 样例输出
# ============================================================
def get_cfg_sample(patch_index_path: Path = None):
    """获取 CFG 构建样例供报告展示。"""
    if patch_index_path is None:
        patch_index_path = PROCESSED_DIR / "patch_index.json"

    patch_index = read_json(patch_index_path)

    for pr in patch_index:
        for f in pr.get("files", []):
            if f.get("file_type") != "code" or not f.get("has_patch"):
                continue
            ext = f.get("ext", "")
            if ext not in (".py", ".go"):
                continue
            added = f.get("added_lines", "")
            if not added or len(added) < 100:
                continue

            cfg = SimpleCFG()
            success = cfg.build_from_lines(added.split("\n"), ext)
            if success and len(cfg.nodes) > 5:
                return {
                    "pr_id": pr["pr_id"],
                    "repo": pr["repo"],
                    "filename": f["filename"],
                    "ext": ext,
                    "code_snippet": added[:400],
                    "nodes": [(nid, ntype) for nid, ntype, _ in cfg.nodes],
                    "edges": [(src, dst, etype) for src, dst, etype in cfg.edges],
                    "features": cfg.get_features(),
                    "cfg_available": success,
                }
    return None


if __name__ == "__main__":
    from utils import setup_logger
    log_file = PROCESSED_DIR.parent / "pipeline.log"
    log = setup_logger("experiment2", log_file)
    df = run()

    sample = get_cfg_sample()
    if sample:
        log.info(f"\nCFG 样例: {sample['filename']} ({sample['ext']})")
        log.info(f"  节点: {sample['nodes']}")
        log.info(f"  边: {sample['edges']}")
        log.info(f"  特征: {sample['features']}")
