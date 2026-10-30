"""Runtime configuration from environment (.env is loaded if present)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("LS_DATA_DIR", ROOT / "data"))

NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
MODEL_DEEP = os.getenv("LS_MODEL_DEEP", "")  # Nemotron for hard reasoning (hypotheses, theory, playbooks)
MODEL_FAST = os.getenv("LS_MODEL_FAST", "")  # Nemotron for routine steps

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

SANDBOX_URL = os.getenv("LS_SANDBOX_URL", "")  # empty = in-process sandbox
SANDBOX_TOKEN = os.getenv("LS_SANDBOX_TOKEN", "dev-sandbox-token")
GATE_URL = os.getenv("LS_GATE_URL", "http://127.0.0.1:8790")  # the separate HTTP device service

MAX_LIVE_RUNS = int(os.getenv("LS_MAX_LIVE_RUNS", "3"))
