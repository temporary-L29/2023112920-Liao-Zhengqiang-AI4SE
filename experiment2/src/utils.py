"""
实验二：工具函数 — 日志、文件IO、文本清洗
"""
import json
import logging
import sys
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

    # 控制台 handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(ch)

    # 文件 handler
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logger.addHandler(fh)

    return logger

# 默认 logger（写日志到文件，用 run_all.py 设置）
log = logging.getLogger("experiment2")
log.setLevel(logging.DEBUG)

# ============================================================
# JSON 读写
# ============================================================
def read_json(path: Path):
    """读取 JSON 文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(data, path: Path):
    """写入 JSON 文件（自动创建目录，缩进格式）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def write_json_compact(data, path: Path):
    """写入紧凑 JSON 文件（无缩进，适合大文件）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

# ============================================================
# 文本清洗
# ============================================================
def safe_str(val) -> str:
    """安全转换为字符串，None → ''。"""
    if val is None:
        return ""
    return str(val)

def clean_text(text, max_len: int = None) -> str:
    """清洗文本：去除多余空白和控制字符。"""
    if not text:
        return ""
    import re
    text = safe_str(text)
    # 去除除换行外的控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    # 合并连续空白行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 去除首尾空白
    text = text.strip()
    if max_len and len(text) > max_len:
        text = text[:max_len]
    return text
