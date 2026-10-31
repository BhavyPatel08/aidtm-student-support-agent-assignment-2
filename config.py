"""Central configuration. Values are read at call time so eval/tests can switch them."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
RUNTIME = Path(os.getenv("RUNTIME_DIR", DATA_DIR / "runtime"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

MAX_TOOL_STEPS = 5       # agent-loop safety limit
HISTORY_MESSAGES = 4     # only the last 2 turns are sent (context selection)
TOP_K = 2                # policy chunks returned per search
MIN_SCORE = 0.10         # minimum TF-IDF cosine for a chunk to count as relevant
MIN_COVERAGE = 0.45      # share of query terms (idf-weighted) a chunk must cover

# Assignment 2 controls (privacy, approval, audit, redaction). 0 = Assignment 1 baseline.
CONTROLS_ENABLED = os.getenv("CONTROLS_ENABLED", "1") == "1"


def runtime_path(name: str) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    return RUNTIME / name
