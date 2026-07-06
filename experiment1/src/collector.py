"""
实验一：构建数据集 — 数据采集引擎（多线程并行版）
通过 GitHub API 从 5 个大型开源项目各采集 300 条 PR 的完整数据。
支持断点续传。
"""

import json
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

import requests

import config
from utils import log, rate_limiter, save_checkpoint, load_checkpoint

# 写日志锁，避免多线程输出错乱
log_lock = Lock()


# ============================================================
# PR 采集器（并行版）
# ============================================================
class PRCollector:
    """GitHub PR 数据采集器 — 多线程并行采集。"""

    def __init__(self, workers=5):
        self.workers = workers
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {config.GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "experiment1-dataset-builder",
        })

    # --------------------------------------------------------
    # 内部请求方法
    # --------------------------------------------------------
    def _get(self, url, params=None):
        """发起 GET 请求，返回 (json_data, response) 元组。"""
        for attempt in range(config.MAX_RETRIES):
            try:
                rate_limiter.wait_if_needed()
                resp = self.session.get(url, params=params, timeout=30)
                rate_limiter.update_from_response(resp)

                if resp.status_code == 200:
                    return resp.json(), resp

                elif resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    with log_lock:
                        log.warning(
                            f"速率限制 (429)，休眠 {retry_after}s"
                        )
                    time.sleep(retry_after + 1)
                    continue

                elif resp.status_code == 404:
                    return None, resp

                elif resp.status_code in (403, 502, 503):
                    wait = (2 ** attempt) + 1
                    time.sleep(wait)
                    continue

                else:
                    return None, resp

            except (requests.ConnectionError, requests.Timeout):
                wait = (2 ** attempt) + 1
                time.sleep(wait)

        return None, None

    # --------------------------------------------------------
    # 收集不分页的完整列表
    # --------------------------------------------------------
    def _collect_all_pages(self, url, max_items=None):
        """分页获取全部数据。"""
        all_items = []
        current_url = url

        while current_url:
            data, resp = self._get(current_url)
            if data is None or resp is None:
                break

            if isinstance(data, list):
                all_items.extend(data)
            elif isinstance(data, dict) and "items" in data:
                all_items.extend(data["items"])
            else:
                all_items.append(data)

            if max_items and len(all_items) >= max_items:
                all_items = all_items[:max_items]
                break

            # 解析 Link 头获取下一页
            link = resp.headers.get("Link", "")
            current_url = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    start = part.find("<") + 1
                    end = part.find(">")
                    if start > 0 and end > start:
                        current_url = part[start:end]
                    break

        return all_items

    # --------------------------------------------------------
    # 并行抓取单条 PR 的全部数据
    # --------------------------------------------------------
    def _fetch_single_pr(self, owner, repo, pr_number):
        """抓取单条 PR 的全部数据（5 路并行）。

        对应文档步骤：
        1.7.1 PR 详情 (detail)
        1.7.2 Code Review (reviews + inline comments)
        1.7.3 代码修改 (files + commits)
        """
        base = f"{config.API_BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}"

        def fetch_detail():
            data, _ = self._get(base)
            return data

        def fetch_reviews():
            return self._collect_all_pages(f"{base}/reviews")

        def fetch_review_comments():
            """获取 inline review comments（文档1.7.2要求）"""
            return self._collect_all_pages(f"{base}/comments")

        def fetch_files():
            return self._collect_all_pages(f"{base}/files")

        def fetch_commits():
            """获取 commits 信息（文档1.7.3要求）"""
            return self._collect_all_pages(f"{base}/commits")

        with ThreadPoolExecutor(max_workers=5) as pool:
            f_detail = pool.submit(fetch_detail)
            f_reviews = pool.submit(fetch_reviews)
            f_comments = pool.submit(fetch_review_comments)
            f_files = pool.submit(fetch_files)
            f_commits = pool.submit(fetch_commits)

            detail = f_detail.result()
            reviews = f_reviews.result() or []
            review_comments = f_comments.result() or []
            files = f_files.result() or []
            commits = f_commits.result() or []

        if detail is None:
            return None

        return {
            "repo": f"{owner}/{repo}",
            "detail": detail,
            "reviews": reviews,
            "review_comments": review_comments,
            "files": files,
            "commits": commits,
            "collected_at": datetime.now().isoformat(),
        }

    # --------------------------------------------------------
    # 采集单个仓库
    # --------------------------------------------------------
    def collect_repo(self, owner, repo, target_count,
                     skip_pr_numbers=None, random_sample=False):
        """采集单个仓库的 closed PR。

        Args:
            random_sample: True=从大池中随机采样（避免时间集群效应），
                           False=按创建时间降序取
        """
        skip_set = skip_pr_numbers or set()
        repo_name = f"{owner}/{repo}"
        mode = "随机采样" if random_sample else "按创建时间降序"
        log.info(
            f"开始采集 {repo_name}，目标 {target_count} 条（{mode}）"
            f"（{self.workers} 线程并行）..."
        )

        list_url = (
            f"{config.API_BASE_URL}/repos/{owner}/{repo}/pulls"
            f"?state=closed&sort=created&direction=desc"
            f"&per_page={config.PER_PAGE}"
        )

        if random_sample:
            # 拉取大池（目标10倍），然后随机选
            pool_size = target_count * 10
            pr_list = self._collect_all_pages(list_url, max_items=pool_size)
            log.info(f"{repo_name}: 大池获取到 {len(pr_list)} 条")
            # 去重
            seen = set(skip_set)
            unique = []
            for pr in pr_list:
                pn = pr["number"]
                if pn not in seen:
                    seen.add(pn)
                    unique.append(pr)
            # 随机采样
            sample = random.sample(unique, min(target_count, len(unique)))
            to_fetch = [pr["number"] for pr in sample]
            merged_in_list = sum(1 for pr in sample
                                if pr.get("merged_at") is not None)
        else:
            pr_list = self._collect_all_pages(list_url, max_items=target_count)
            log.info(f"{repo_name}: 获取到 {len(pr_list)} 条 closed PR")
            to_fetch = []
            for pr in pr_list:
                pn = pr["number"]
                if pn not in skip_set and pn not in to_fetch:
                    to_fetch.append(pn)
                if len(to_fetch) >= target_count:
                    break
            merged_in_list = sum(1 for pr in pr_list
                                if pr.get("merged_at") is not None
                                and pr["number"] in to_fetch)

        log.info(
            f"{repo_name}: {len(to_fetch)} 条 PR，"
            f"其中 merged≈{merged_in_list}"
            f"（{100*merged_in_list/max(len(to_fetch),1):.0f}%）"
        )

        # 第二步：多线程并行抓取
        prs_data = []
        completed = 0

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            future_map = {
                pool.submit(self._fetch_single_pr, owner, repo, pn): pn
                for pn in to_fetch
            }

            for future in as_completed(future_map):
                pn = future_map[future]
                try:
                    result = future.result()
                    if result is not None:
                        prs_data.append(result)
                        completed += 1
                        if completed % 20 == 0 or completed == len(to_fetch):
                            log.info(
                                f"[{repo_name}] {completed}/{len(to_fetch)}"
                            )
                    else:
                        log.warning(
                            f"[{repo_name}] PR #{pn} 获取失败，跳过"
                        )
                except Exception as e:
                    log.warning(f"[{repo_name}] PR #{pn} 异常: {e}")

        log.info(f"{repo_name}: 完成，共采集 {len(prs_data)} 条 PR")
        return prs_data

    # --------------------------------------------------------
    # 采集全部仓库
    # --------------------------------------------------------
    def collect_all(self):
        """采集全部 5 个仓库，支持断点续传。"""
        checkpoint = load_checkpoint("collector_state.json")
        completed_repos = []
        if checkpoint:
            completed_repos = checkpoint.get("completed_repos", [])
            log.info(f"从检查点恢复，已完成: {completed_repos}")

        all_prs = {}

        for owner, repo in config.TARGET_REPOS:
            repo_key = f"{owner}/{repo}"

            if repo_key in completed_repos:
                log.info(f"跳过已完成的仓库: {repo_key}")
                raw_file = config.RAW_DATA_DIR / f"{repo}_raw.json"
                if raw_file.exists():
                    with open(raw_file, "r", encoding="utf-8") as f:
                        all_prs[repo_key] = json.load(f)
                continue

            # 断点续传
            skip_numbers = set()
            if checkpoint and checkpoint.get("current_repo") == repo_key:
                skip_numbers = set(
                    checkpoint.get("collected_pr_numbers", [])
                )

            prs = self.collect_repo(
                owner, repo,
                target_count=config.PRS_PER_REPO,
                skip_pr_numbers=skip_numbers,
            )

            if skip_numbers:
                existing = all_prs.get(repo_key, [])
                all_prs[repo_key] = existing + prs
            else:
                all_prs[repo_key] = prs

            # 保存单仓库
            raw_file = config.RAW_DATA_DIR / f"{repo}_raw.json"
            with open(raw_file, "w", encoding="utf-8") as f:
                json.dump(all_prs[repo_key], f, ensure_ascii=False, indent=2)

            completed_repos.append(repo_key)
            save_checkpoint("collector_state.json", {
                "completed_repos": completed_repos,
                "current_repo": None,
                "collected_pr_numbers": [],
                "total_collected_prs": sum(
                    len(v) for v in all_prs.values()
                ),
            })

        # 保存合并数据
        merged = []
        for repo_prs in all_prs.values():
            merged.extend(repo_prs)

        merged_file = config.RAW_DATA_DIR / "merged_raw.json"
        with open(merged_file, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        log.info(f"全部采集完成！总计 {len(merged)} 条 PR")
        return merged


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    if not config.validate_token():
        exit(1)

    collector = PRCollector(workers=3)
    collector.collect_all()
