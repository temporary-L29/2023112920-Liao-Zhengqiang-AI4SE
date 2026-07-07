"""
实验三：基于大语言模型的人类编写代码代码审查 — 集中配置
"""
import os
from pathlib import Path

# ============================================================
# 目录路径
# ============================================================
EXPERIMENT3_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = EXPERIMENT3_DIR / "src"
PROMPTS_DIR = EXPERIMENT3_DIR / "prompts"
RESULTS_DIR = EXPERIMENT3_DIR / "results"
PROCESSED_DIR = RESULTS_DIR / "processed"
RESPONSES_DIR = RESULTS_DIR / "responses"
EVALUATION_DIR = RESULTS_DIR / "evaluation"
FIGURES_DIR = EXPERIMENT3_DIR / "figures"
DOCS_DIR = EXPERIMENT3_DIR / "docs"
REPORT_DIR = EXPERIMENT3_DIR / "report"

# 实验二数据路径
EXPERIMENTS_DIR = EXPERIMENT3_DIR.parent
EXPERIMENT2_PROCESSED = EXPERIMENTS_DIR / "experiment2" / "results" / "processed"
SPLITS_CSV = EXPERIMENT2_PROCESSED / "splits.csv"
HUMAN_DATASET_CSV = EXPERIMENT2_PROCESSED / "human_only_dataset.csv"
PATCH_INDEX_JSON = EXPERIMENT2_PROCESSED / "patch_index.json"
FEATURES_MAIN_CSV = EXPERIMENT2_PROCESSED / "features_main.csv"
AST_FEATURES_CSV = EXPERIMENT2_PROCESSED / "ast_features.csv"
CFG_FEATURES_CSV = EXPERIMENT2_PROCESSED / "cfg_features.csv"
RAW_MERGED_JSON = EXPERIMENTS_DIR / "raw" / "merged_raw.json"

# ============================================================
# 抽样配置
# ============================================================
SAMPLE_SIZE = 50
PER_REPO = 10
REPOS = [
    "facebook/react",
    "huggingface/transformers",
    "kubernetes/kubernetes",
    "microsoft/vscode",
    "pandas-dev/pandas",
]
# 最少需要多少条有非空 review_comments_text 的样本
MIN_WITH_REVIEW_COMMENTS = 25
RANDOM_SEED = 42

# ============================================================
# LLM API 配置
# ============================================================
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

# 调用参数
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 2000
LLM_MAX_RETRIES = 2
LLM_TIMEOUT = 120  # 秒
LLM_MAX_WORKERS = 8  # 并发数

# ============================================================
# 上下文配置
# ============================================================
CONTEXT_TYPES = ["C1", "C2", "C3", "C4"]

CONTEXT_CONFIG = {
    "C1": {
        "name": "Diff Only",
        "include_diff": True,
        "include_pr_description": False,
        "include_commit": False,
        "include_code_summary": False,
    },
    "C2": {
        "name": "Diff + PR Description",
        "include_diff": True,
        "include_pr_description": True,
        "include_commit": False,
        "include_code_summary": False,
    },
    "C3": {
        "name": "Diff + PR Description + Commit",
        "include_diff": True,
        "include_pr_description": True,
        "include_commit": True,
        "include_code_summary": False,
    },
    "C4": {
        "name": "Full Early Context",
        "include_diff": True,
        "include_pr_description": True,
        "include_commit": True,
        "include_code_summary": True,
    },
}

# ============================================================
# Prompt 配置
# ============================================================
PROMPT_TYPES = ["P1", "P2", "P3", "P4"]

PROMPT_CONFIG = {
    "P1": {"name": "Zero-shot Prompt", "few_shot": False, "role_based": False, "cot": False},
    "P2": {"name": "Few-shot Prompt", "few_shot": True, "role_based": False, "cot": False},
    "P3": {"name": "Role-based Prompt", "few_shot": False, "role_based": True, "cot": False},
    "P4": {"name": "Chain-of-Thought Prompt", "few_shot": False, "role_based": False, "cot": True},
}

# Few-shot 示例数量
FEW_SHOT_COUNT = 4  # 2 merged + 2 not merged

# ============================================================
# 输出文件路径
# ============================================================
LLM_SAMPLE_CSV = PROCESSED_DIR / "llm_sample_50.csv"
FEW_SHOT_EXAMPLES_JSON = PROCESSED_DIR / "few_shot_examples.json"
RAW_RESPONSES_JSONL = RESPONSES_DIR / "raw_responses.jsonl"
PARSED_PREDICTIONS_CSV = RESPONSES_DIR / "parsed_predictions.csv"
METRICS_BY_PROMPT_CONTEXT_JSON = EVALUATION_DIR / "metrics_by_prompt_context.json"
COMMENT_GENERATION_METRICS_JSON = EVALUATION_DIR / "comment_generation_metrics.json"

# ============================================================
# 图表配置
# ============================================================
FIGURE_DPI = 300
FIGURE_FORMAT = "png"

# ============================================================
# 上下文长度限制（防止超出 token 限制）
# ============================================================
MAX_DIFF_CHARS = 8000       # diff 文本最大字符数
MAX_BODY_CHARS = 3000       # PR body 最大字符数
MAX_COMMIT_MSG_CHARS = 1500 # commit message 最大字符数
MAX_ADDED_LINES_CHARS = 6000 # 新增代码行最大字符数


def ensure_dirs():
    """创建所有需要的目录。"""
    for d in [PROCESSED_DIR, RESPONSES_DIR, EVALUATION_DIR,
              FIGURES_DIR, DOCS_DIR, REPORT_DIR, PROMPTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()
