"""
Experiment 7 Configuration — paths, ports, limits, environment variables.

Uses pathlib.Path to locate the project root (parent of this file's directory),
so imports work regardless of the current working directory.
"""

import os
import logging
from pathlib import Path

# ── Project root ──────────────────────────────────────────────
SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent

# ── Paths to sibling experiments ──────────────────────────────
EXPERIMENTS_ROOT = PROJECT_ROOT.parent  # experiments/
EXPERIMENT2_DIR = EXPERIMENTS_ROOT / "experiment2"
EXPERIMENT6_DIR = EXPERIMENTS_ROOT / "experiment6"

# ── Output directories ────────────────────────────────────────
RESULTS_DIR = PROJECT_ROOT / "results"
HISTORY_DIR = RESULTS_DIR / "history"
COMPAT_DIR = RESULTS_DIR / "compatibility"
TESTS_RESULTS_DIR = RESULTS_DIR / "tests"
PERF_DIR = RESULTS_DIR / "performance"
MODELS_DIR = RESULTS_DIR / "models"
FIGURES_DIR = PROJECT_ROOT / "figures"

for _d in [RESULTS_DIR, HISTORY_DIR, COMPAT_DIR, TESTS_RESULTS_DIR, PERF_DIR, MODELS_DIR, FIGURES_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Server ────────────────────────────────────────────────────
HOST = os.environ.get("REVIEW_HOST", "127.0.0.1")
PORT = int(os.environ.get("REVIEW_PORT", "8765"))
SERVER_URL = f"http://{HOST}:{PORT}"

# ── Input limits ──────────────────────────────────────────────
MAX_CONTENT_CHARS = int(os.environ.get("REVIEW_MAX_CONTENT_CHARS", "24000"))
MAX_FILE_COUNT = int(os.environ.get("REVIEW_MAX_FILE_COUNT", "50"))
MAX_DIFF_CHARS = int(os.environ.get("REVIEW_MAX_DIFF_CHARS", "32000"))

# ── Git ───────────────────────────────────────────────────────
GIT_DIFF_CONTEXT_LINES = int(os.environ.get("REVIEW_GIT_CONTEXT", "3"))

# ── LLM / experiment 6 adapter ────────────────────────────────
LLM_API_KEY = os.environ.get("LLM_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2000"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))

# ── Experiment 2 model paths ──────────────────────────────────
EXP2_SVM_MODEL = EXPERIMENT2_DIR / "results" / "models" / "svm_main.joblib"
EXP2_RF_MODEL = EXPERIMENT2_DIR / "results" / "models" / "randomforest_main.joblib"
EXP2_SCALER = EXPERIMENT2_DIR / "results" / "models" / "scaler_main.joblib"
EXP2_FEATURES_CSV = EXPERIMENT2_DIR / "results" / "processed" / "features_main.csv"

# Experiment 2 deployment-compatible variants. These are trained from the
# Experiment 2 dataset but live in Experiment 7 to preserve the original PR
# research artifacts unchanged.
EXP2_DEPLOYABLE_MODELS_DIR = MODELS_DIR / "exp2_deployable"
EXP2_DEPLOYABLE_CONTRACT = EXP2_DEPLOYABLE_MODELS_DIR / "feature_contract.json"
EXP2_DEPLOYABLE_METRICS = EXP2_DEPLOYABLE_MODELS_DIR / "metrics.json"

# ── History ───────────────────────────────────────────────────
HISTORY_FILE = HISTORY_DIR / "reviews.jsonl"
MAX_HISTORY_DEFAULT = 20

# ── Logging ───────────────────────────────────────────────────
PIPELINE_LOG = RESULTS_DIR / "pipeline.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(PIPELINE_LOG, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("experiment7")
