"""
实验六配置：路径、方法组合、API参数

目标：通过上下文增强和 Prompt 优化改进 DeepSeek 对 AI 生成代码 PR 的代码审查能力。

实验六核心矩阵：
  - 实验五基线 B01-B16: P1-P4 × C1-C4 (已完成，直接读取)
  - 实验六改进 I01-I16: P5-P8 × C5-C8 (需要运行 16×50=800 次 API)
"""

import os

# ============================================================
# 路径
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

EXPERIMENT5_DIR = os.path.join(PROJECT_ROOT, "experiment5")
EXPERIMENT6_DIR = BASE_DIR

# 实验五输入路径
EXP5_DATASET_CSV = os.path.join(
    EXPERIMENT5_DIR, "results", "processed", "ai_generated_dataset.csv"
)
EXP5_PATCH_INDEX = os.path.join(
    EXPERIMENT5_DIR, "results", "processed", "ai_patch_index.json"
)
EXP5_CONTEXTS = os.path.join(
    EXPERIMENT5_DIR, "results", "processed", "ai_contexts.json"
)
EXP5_LLM_PARSED = os.path.join(
    EXPERIMENT5_DIR, "results", "predictions", "llm_parsed_predictions.csv"
)
EXP5_LLM_RAW = os.path.join(
    EXPERIMENT5_DIR, "results", "predictions", "llm_raw_responses.jsonl"
)
EXP5_LLM_METRICS = os.path.join(
    EXPERIMENT5_DIR, "results", "evaluation", "llm_metrics.json"
)
EXP5_COMMENT_METRICS = os.path.join(
    EXPERIMENT5_DIR, "results", "evaluation", "comment_generation_metrics.json"
)
EXP5_ERROR_ANALYSIS = os.path.join(
    EXPERIMENT5_DIR, "results", "evaluation", "error_analysis.json"
)
EXP5_AI_FEATURES = os.path.join(
    EXPERIMENT5_DIR, "results", "processed", "ai_features_main.csv"
)

# 实验五 4×4 基线文件
EXP5_LLM_SAMPLE_50 = os.path.join(
    EXPERIMENT5_DIR, "results", "processed", "ai_llm_sample_50.csv"
)
EXP5_4X4_TASK_LIST = os.path.join(
    EXPERIMENT5_DIR, "results", "processed", "ai_llm_4x4_task_list.json"
)
EXP5_4X4_RAW = os.path.join(
    EXPERIMENT5_DIR, "results", "predictions", "llm_4x4_raw_responses.jsonl"
)
EXP5_4X4_PARSED = os.path.join(
    EXPERIMENT5_DIR, "results", "predictions", "llm_4x4_parsed_predictions.csv"
)
EXP5_4X4_METRICS = os.path.join(
    EXPERIMENT5_DIR, "results", "evaluation", "llm_4x4_metrics.json"
)

# 输出目录
RESULTS_PROCESSED_DIR = os.path.join(EXPERIMENT6_DIR, "results", "processed")
RESULTS_RESPONSES_DIR = os.path.join(EXPERIMENT6_DIR, "results", "responses")
RESULTS_EVALUATION_DIR = os.path.join(EXPERIMENT6_DIR, "results", "evaluation")
FIGURES_DIR = os.path.join(EXPERIMENT6_DIR, "figures")

# ============================================================
# 主实验样本: Balanced-50 (复用实验五 ai_llm_sample_50.csv)
# ============================================================
EVAL_BALANCED_50 = os.path.join(RESULTS_PROCESSED_DIR, "eval_balanced_50.csv")
IMPROVED_CONTEXTS_50 = os.path.join(RESULTS_PROCESSED_DIR, "improved_contexts_balanced_50.json")
TASK_LIST_IMPROVED_4X4 = os.path.join(RESULTS_PROCESSED_DIR, "task_list_improved_4x4_balanced_50.json")

# 验证样本
EVAL_BALANCED_120 = os.path.join(RESULTS_PROCESSED_DIR, "eval_balanced_120.csv")
EVAL_HARD_FP_40 = os.path.join(RESULTS_PROCESSED_DIR, "eval_hard_fp_40.csv")
EVAL_SAMPLE_STATS = os.path.join(RESULTS_PROCESSED_DIR, "eval_sample_stats.json")
IMPROVED_CONTEXTS = os.path.join(RESULTS_PROCESSED_DIR, "improved_contexts.json")
TASK_LIST = os.path.join(RESULTS_PROCESSED_DIR, "task_list.json")

# 主实验 4×4 响应/预测输出
IMPROVED_4X4_RAW = os.path.join(RESULTS_RESPONSES_DIR, "improved_4x4_raw_responses.jsonl")
IMPROVED_4X4_PARSED = os.path.join(RESULTS_RESPONSES_DIR, "improved_4x4_parsed_predictions.csv")

# 原有 M1-M4 响应/预测 (兼容)
RAW_RESPONSES = os.path.join(RESULTS_RESPONSES_DIR, "raw_responses.jsonl")
PARSED_PREDICTIONS = os.path.join(RESULTS_RESPONSES_DIR, "parsed_predictions.csv")

# 评估输出
IMPROVED_4X4_METRICS = os.path.join(RESULTS_EVALUATION_DIR, "improved_4x4_metrics.json")
ALL_32_COMBO_METRICS = os.path.join(RESULTS_EVALUATION_DIR, "all_32_combo_metrics.csv")
BASELINE_VS_IMPROVED_SUMMARY = os.path.join(RESULTS_EVALUATION_DIR, "baseline_vs_improved_summary.json")
COMMENT_GENERATION_METRICS = os.path.join(RESULTS_EVALUATION_DIR, "comment_generation_metrics.json")

METRICS_BALANCED = os.path.join(RESULTS_EVALUATION_DIR, "metrics_balanced_120.json")
METRICS_HARD_FP = os.path.join(RESULTS_EVALUATION_DIR, "metrics_hard_fp_40.json")
COMMENT_QUALITY = os.path.join(RESULTS_EVALUATION_DIR, "comment_quality_metrics.json")
BASELINE_COMPARISON = os.path.join(RESULTS_EVALUATION_DIR, "baseline_comparison.json")
BEST_METHOD_SUMMARY = os.path.join(RESULTS_EVALUATION_DIR, "best_method_summary.json")

# 确保目录存在
for _d in [
    RESULTS_PROCESSED_DIR,
    RESULTS_RESPONSES_DIR,
    RESULTS_EVALUATION_DIR,
    FIGURES_DIR,
]:
    os.makedirs(_d, exist_ok=True)

# ============================================================
# 实验方法组合
# ============================================================

# 实验六改进矩阵 I01-I16: P5-P8 × C5-C8
# I01-I04: P5 × C5/C6/C7/C8
# I05-I08: P6 × C5/C6/C7/C8
# I09-I12: P7 × C5/C6/C7/C8
# I13-I16: P8 × C5/C6/C7/C8
IMPROVED_COMBOS = {
    "I01": {"prompt": "P5", "context": "C5"},
    "I02": {"prompt": "P5", "context": "C6"},
    "I03": {"prompt": "P5", "context": "C7"},
    "I04": {"prompt": "P5", "context": "C8"},
    "I05": {"prompt": "P6", "context": "C5"},
    "I06": {"prompt": "P6", "context": "C6"},
    "I07": {"prompt": "P6", "context": "C7"},
    "I08": {"prompt": "P6", "context": "C8"},
    "I09": {"prompt": "P7", "context": "C5"},
    "I10": {"prompt": "P7", "context": "C6"},
    "I11": {"prompt": "P7", "context": "C7"},
    "I12": {"prompt": "P7", "context": "C8"},
    "I13": {"prompt": "P8", "context": "C5"},
    "I14": {"prompt": "P8", "context": "C6"},
    "I15": {"prompt": "P8", "context": "C7"},
    "I16": {"prompt": "P8", "context": "C8"},
}

# 实验五基线组合 B01-B16: P1-P4 × C1-C4 (只读，不调用)
BASELINE_COMBOS = {
    "B01": {"prompt": "P1", "context": "C1"},
    "B02": {"prompt": "P1", "context": "C2"},
    "B03": {"prompt": "P1", "context": "C3"},
    "B04": {"prompt": "P1", "context": "C4"},
    "B05": {"prompt": "P2", "context": "C1"},
    "B06": {"prompt": "P2", "context": "C2"},
    "B07": {"prompt": "P2", "context": "C3"},
    "B08": {"prompt": "P2", "context": "C4"},
    "B09": {"prompt": "P3", "context": "C1"},
    "B10": {"prompt": "P3", "context": "C2"},
    "B11": {"prompt": "P3", "context": "C3"},
    "B12": {"prompt": "P3", "context": "C4"},
    "B13": {"prompt": "P4", "context": "C1"},
    "B14": {"prompt": "P4", "context": "C2"},
    "B15": {"prompt": "P4", "context": "C3"},
    "B16": {"prompt": "P4", "context": "C4"},
}

# M1-M4 (兼容旧代码，映射到 I01/I05/I10/I16)
METHOD_COMBOS = {
    "M1": {"prompt": "P5", "context": "C5"},   # = I01
    "M2": {"prompt": "P6", "context": "C5"},   # = I05
    "M3": {"prompt": "P7", "context": "C6"},   # = I10
    "M4": {"prompt": "P8", "context": "C8"},   # = I16
}

# 实验五基线（用于子集重算）
EXP5_BASELINES = ["P2_C3", "P2_C4"]

# ============================================================
# 评估样本配置
# ============================================================
BALANCED_SIZE = 120     # 主评估集 (验证用)
HARD_FP_SIZE = 40       # Hard False Positive 子集
RANDOM_SEED = 42
BALANCED_50_SEED = 20260709  # 计划书指定种子

# ============================================================
# 上下文长度限制
# ============================================================
MAX_CONTEXT_TOKENS = 16000   # C8 最大上下文
MAX_DIFF_CHARS = 8000
MAX_BODY_CHARS = 3000
MAX_COMMIT_MSG_CHARS = 1500

# ============================================================
# API 配置
# ============================================================
LLM_API_KEY = os.environ.get("LLM_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 2000
LLM_MAX_RETRIES = 2
LLM_TIMEOUT = 120
MAX_WORKERS = 8

# ============================================================
# 日志
# ============================================================
import logging

PIPELINE_LOG = os.path.join(EXPERIMENT6_DIR, "results", "pipeline.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(PIPELINE_LOG, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("experiment6")
