"""
实验一：构建数据集 — 工具函数库
提供网络请求、限速控制、分页、检查点等通用能力。
"""

import json
import logging
import os
import re
import time
import random
from datetime import datetime
from pathlib import Path

import requests

import config

# ============================================================
# 日志配置
# ============================================================
LOG_FILE = config.DATA_DIR / "pipeline.log"


def setup_logging(level=logging.INFO):
    """配置日志：同时输出到控制台和文件。"""
    logger = logging.getLogger("experiment1")
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 文件 handler
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


log = setup_logging()


# ============================================================
# 限速控制器
# ============================================================
class RateLimiter:
    """GitHub API 限速控制器。

    读取响应头中的 X-RateLimit-Remaining 和 X-RateLimit-Reset，
    在剩余次数不足时自动休眠等待重置。
    """

    def __init__(self, buffer=config.RATE_LIMIT_BUFFER,
                 min_delay=config.REQUEST_DELAY):
        self.buffer = buffer
        self.min_delay = min_delay
        self.remaining = None
        self.reset_time = None
        self.last_request_time = 0

    def wait_if_needed(self):
        """在发起请求前调用，必要时休眠等待。"""
        now = time.time()

        # 保证最小请求间隔
        elapsed = now - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

        # 检查限速状态
        if self.remaining is not None and self.remaining <= self.buffer:
            if self.reset_time:
                wait = self.reset_time - time.time() + 5  # 加 5 秒安全余量
                if wait > 0:
                    log.info(
                        f"限速预警：剩余 {self.remaining} 次，"
                        f"休眠 {wait:.0f} 秒至重置时间..."
                    )
                    time.sleep(wait)

    def update_from_response(self, response):
        """从响应头更新限速状态。"""
        self.remaining = int(response.headers.get(
            "X-RateLimit-Remaining", self.remaining or 5000))
        self.reset_time = int(response.headers.get(
            "X-RateLimit-Reset", self.reset_time or 0))
        self.last_request_time = time.time()


# 全局限速器实例
rate_limiter = RateLimiter()


# ============================================================
# 安全请求
# ============================================================
def safe_request(url, session, params=None, max_retries=config.MAX_RETRIES):
    """带自动重试和限速控制的 HTTP GET 请求。

    Args:
        url: 请求 URL
        session: requests.Session 实例
        params: 查询参数字典
        max_retries: 最大重试次数

    Returns:
        解析后的 JSON 数据，或 None（请求失败时）
    """
    for attempt in range(max_retries):
        try:
            rate_limiter.wait_if_needed()
            resp = session.get(url, params=params, timeout=30)
            rate_limiter.update_from_response(resp)

            if resp.status_code == 200:
                return resp.json()

            elif resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                jitter = random.uniform(0, 2)
                wait = retry_after + jitter
                log.warning(
                    f"触发速率限制 (429)，休眠 {wait:.1f} 秒 "
                    f"(第 {attempt+1}/{max_retries} 次重试)..."
                )
                time.sleep(wait)
                continue

            elif resp.status_code == 404:
                log.warning(f"404 Not Found: {url}")
                return None

            elif resp.status_code in (403, 502, 503):
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning(
                    f"HTTP {resp.status_code}，{wait:.1f} 秒后重试 "
                    f"(第 {attempt+1}/{max_retries})..."
                )
                time.sleep(wait)
                continue

            else:
                log.warning(f"未预期的状态码 {resp.status_code}: {url}")
                return None

        except (requests.ConnectionError, requests.Timeout) as e:
            wait = (2 ** attempt) + random.uniform(0, 1)
            log.warning(
                f"网络错误: {e}，{wait:.1f} 秒后重试 "
                f"(第 {attempt+1}/{max_retries})..."
            )
            time.sleep(wait)

        except Exception as e:
            log.error(f"请求异常: {e}")
            return None

    log.error(f"重试 {max_retries} 次后仍失败: {url}")
    return None


# ============================================================
# 分页获取
# ============================================================
LINK_RE = re.compile(r'<([^>]+)>;\s*rel="(\w+)"')


def parse_link_header(link_header):
    """解析 GitHub Link 头，返回 rel→url 映射。"""
    links = {}
    if not link_header:
        return links
    for part in link_header.split(","):
        m = LINK_RE.search(part)
        if m:
            links[m.group(2)] = m.group(1)
    return links


def paginated_fetch(url, session, max_pages=None):
    """分页获取生成器。

    Args:
        url: 初始请求 URL（含查询参数）
        session: requests.Session 实例
        max_pages: 最多获取页数，None 表示不限制

    Yields:
        每页的数据列表
    """
    current_url = url
    page_count = 0

    while current_url:
        if max_pages and page_count >= max_pages:
            break

        data = safe_request(current_url, session)
        if data is None:
            log.error(f"分页获取失败: {current_url}")
            break

        page_count += 1
        yield data

        # 获取下一页 URL
        # 注意：safe_request 返回的是解析后的 JSON，不是 Response 对象
        # 我们需要从最新的响应中获取 Link 头
        # 由于 safe_request 返回的是 JSON body，我们单独处理分页
        # 这里重新发起带特殊处理的请求
        rate_limiter.wait_if_needed()
        resp = session.get(current_url, timeout=30)
        rate_limiter.update_from_response(resp)
        links = parse_link_header(resp.headers.get("Link", ""))
        current_url = links.get("next")

        if current_url:
            log.debug(f"获取下一页: {current_url}")


def fetch_all_pages(url, session, max_pages=None):
    """获取所有分页数据，合并为一个列表。

    Args:
        url: 初始请求 URL
        session: requests.Session 实例
        max_pages: 最多获取页数

    Returns:
        合并后的数据列表
    """
    all_data = []
    for page_data in paginated_fetch(url, session, max_pages):
        if isinstance(page_data, list):
            all_data.extend(page_data)
        elif isinstance(page_data, dict) and "items" in page_data:
            # 搜索 API 返回格式
            all_data.extend(page_data["items"])
        else:
            all_data.append(page_data)
        log.info(f"已获取 {len(all_data)} 条记录...")
    return all_data


# ============================================================
# 检查点 I/O
# ============================================================
def save_checkpoint(filename, data):
    """原子写入检查点文件（先写临时文件再替换）。"""
    path = config.CHECKPOINT_DIR / filename
    tmp_path = path.with_suffix(".tmp")
    data["last_updated"] = datetime.now().isoformat()
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def load_checkpoint(filename):
    """读取检查点文件。"""
    path = config.CHECKPOINT_DIR / filename
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 辅助函数
# ============================================================
def safe_str(value, default=""):
    """安全地将值转为字符串，处理 None 情况。"""
    if value is None:
        return default
    return str(value)


def clean_text(text, max_len=None):
    """清洗文本：去除非UTF8字符，可选截断。"""
    if text is None:
        return ""
    text = str(text)
    # 替换换行符为空格（利于 CSV 存储）
    text = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    if max_len and len(text) > max_len:
        text = text[:max_len] + "..."
    return text
