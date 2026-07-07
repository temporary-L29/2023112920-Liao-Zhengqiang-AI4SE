"""
实验三：工具函数 — 日志、文件IO、文本清洗
"""
import json
import logging
import sys
import re
from pathlib import Path


# ============================================================
# 日志配置
# ============================================================
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


def setup_logger(name: str, log_file: Path = None) -> logging.Logger:
    """创建同时输出到控制台和文件的 Logger。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(ch)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logger.addHandler(fh)

    return logger


log = logging.getLogger("experiment3")
log.setLevel(logging.DEBUG)


# ============================================================
# JSON 读写
# ============================================================
def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_json_compact(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


# ============================================================
# JSONL 读写（用于缓存 API 响应）
# ============================================================
def read_jsonl(path: Path) -> list:
    """读取 JSONL 文件，每行一个 JSON 对象。"""
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning(f"跳过无效 JSONL 行: {line[:80]}...")
    return records


def append_jsonl(record: dict, path: Path):
    """追加一条记录到 JSONL 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ============================================================
# 文本清洗
# ============================================================
def safe_str(val) -> str:
    if val is None:
        return ""
    return str(val)


def clean_text(text, max_len: int = None) -> str:
    """清洗文本：去除多余空白和控制字符。"""
    if not text:
        return ""
    text = safe_str(text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    if max_len and len(text) > max_len:
        text = text[:max_len]
    return text


def truncate_text(text: str, max_chars: int) -> str:
    """截断文本并添加截断标记。"""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


# ============================================================
# 文件类型分类
# ============================================================
CODE_EXTENSIONS = {
    ".py", ".go", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".c", ".cpp", ".h", ".hpp", ".rs",
}
CONFIG_EXTENSIONS = {".json", ".yml", ".yaml", ".toml", ".xml"}
DOC_EXTENSIONS = {".md", ".rst", ".txt"}
TEST_FILE_MARKERS = ["test_", "_test", "test.", "spec.", ".spec."]


def classify_file_type(filename: str) -> str:
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
    fname = Path(filename).name.lower()
    for marker in TEST_FILE_MARKERS:
        if marker in fname:
            return True
    parts = Path(filename).parts
    for p in parts:
        if p.lower() in ("test", "tests", "spec", "__tests__", "testing"):
            return True
    return False


def get_main_language(files: list) -> str:
    """从文件列表中推断主要语言。"""
    from collections import Counter
    ext_map = {
        ".py": "Python", ".go": "Go", ".js": "JavaScript",
        ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".java": "Java", ".c": "C", ".cpp": "C++", ".rs": "Rust",
    }
    exts = []
    for f in files:
        fn = f if isinstance(f, str) else f.get("filename", "")
        ext = Path(fn).suffix.lower()
        if ext in CODE_EXTENSIONS:
            exts.append(ext)
    if not exts:
        return "unknown"
    counter = Counter(exts)
    dominant = counter.most_common(1)[0][0]
    return ext_map.get(dominant, dominant)
