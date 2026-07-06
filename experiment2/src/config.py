"""
实验二：基于机器学习的人类编写代码代码审查 — 集中配置
"""
import os
from pathlib import Path

# ============================================================
# 目录路径
# ============================================================
EXPERIMENT2_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = EXPERIMENT2_DIR / "src"
RESULTS_DIR = EXPERIMENT2_DIR / "results"
PROCESSED_DIR = RESULTS_DIR / "processed"
MODELS_DIR = RESULTS_DIR / "models"
EVALUATION_DIR = RESULTS_DIR / "evaluation"
FIGURES_DIR = EXPERIMENT2_DIR / "figures"
DOCS_DIR = EXPERIMENT2_DIR / "docs"
REPORT_DIR = EXPERIMENT2_DIR / "report"

# 实验一数据路径
EXPERIMENT1_DIR = EXPERIMENT2_DIR.parent / "experiment1"
EXPERIMENT1_DATASET = EXPERIMENT1_DIR / "results" / "processed" / "dataset.csv"
EXPERIMENT1_DATASET_JSON = EXPERIMENT1_DIR / "results" / "processed" / "dataset.json"
RAW_MERGED_JSON = EXPERIMENT2_DIR.parent / "raw" / "merged_raw.json"

# ============================================================
# 随机种子与划分
# ============================================================
RANDOM_SEED = 42
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
TEST_RATIO = 0.15

# ============================================================
# 模型超参数搜索空间
# ============================================================
SVM_PARAM_GRID = {
    "kernel": ["linear", "rbf"],
    "C": [0.1, 1, 10],
    "gamma": ["scale", 0.01, 0.1],
}

RF_PARAM_GRID = {
    "n_estimators": [200, 500],
    "max_depth": [8, 16, None],
    "min_samples_split": [2, 5, 10],
    "min_samples_leaf": [1, 2, 4],
    "max_features": ["sqrt", "log2"],
}

# ============================================================
# 特征工程配置
# ============================================================
# 极端值截断分位
WINSORIZE_Q = 0.99

# 代码文件扩展名（用于 AST/CFG 解析）
CODE_EXTENSIONS = {
    ".py", ".go", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".c", ".cpp", ".h", ".hpp", ".rs",
}

# P0 优先解析的语言
P0_EXTENSIONS = {".py", ".go", ".js", ".jsx", ".ts", ".tsx"}

# 配置/数据文件扩展名
CONFIG_EXTENSIONS = {".json", ".yml", ".yaml", ".toml", ".xml"}

# 文档文件扩展名
DOC_EXTENSIONS = {".md", ".rst", ".txt"}

# 测试文件标记（文件名包含）
TEST_FILE_MARKERS = ["test_", "_test", "test.", "spec.", ".spec."]

# ============================================================
# 图表配置
# ============================================================
FIGURE_DPI = 300
FIGURE_FORMAT = "png"

# ============================================================
# 辅助函数
# ============================================================
def ensure_dirs():
    """创建所有需要的目录。"""
    for d in [PROCESSED_DIR, MODELS_DIR, EVALUATION_DIR,
              FIGURES_DIR, DOCS_DIR, REPORT_DIR]:
        d.mkdir(parents=True, exist_ok=True)

ensure_dirs()
