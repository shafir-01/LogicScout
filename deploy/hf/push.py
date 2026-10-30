"""Deploy LogicScout to a free Hugging Face Docker Space.

Run: uv run --with huggingface_hub --with python-dotenv python deploy/hf/push.py
Reads HF_TOKEN, NEBIUS_API_KEY, TAVILY_API_KEY, LS_MODEL_DEEP, LS_MODEL_FAST from the repo .env.
Never prints secret values. Never requests paid hardware.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
REPO_ID = "shafir-01/logicscout"
URL = "https://shafir-01-logicscout.hf.space"
TIMEOUT_S = 15 * 60

ALLOW = [
    "logicscout/**", "web/**", "scripts/**", "data/**",
    "pyproject.toml", "uv.lock", "Dockerfile", ".dockerignore", "LICENSE",
]
IGNORE = [
    "**/node_modules/**", "web/dist/**", "**/__pycache__/**", "**/*.pyc",
    "data/runs/**", "data/library/**", "**/.pytest_cache/**", "**/.venv/**",
    "**/.env", "**/.env.*", "tests/**", "**/*.log",
]


def main() -> int:
    env = {**dotenv_values(ROOT / ".env"), **{k: v for k, v in os.environ.items() if v}}
    required = ["HF_TOKEN", "NEBIUS_API_KEY", "TAVILY_API_KEY", "LS_MODEL_DEEP", "LS_MODEL_FAST"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}", file=sys.stderr)
        return 1

    api = HfApi(token=env["HF_TOKEN"])
    api.create_repo(REPO_ID, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    print(f"space ready: {REPO_ID} (cpu-basic, free)")

    for key in ("NEBIUS_API_KEY", "TAVILY_API_KEY"):
        api.add_space_secret(REPO_ID, key, env[key])
    for key, value in (
        ("LS_MODEL_DEEP", env["LS_MODEL_DEEP"]),
        ("LS_MODEL_FAST", env["LS_MODEL_FAST"]),
        ("PORT", "7860"),
        ("LS_MAX_LIVE_RUNS", "3"),
    ):
        api.add_space_variable(REPO_ID, key, value)
    print("secrets and variables set")

    api.upload_folder(
        repo_id=REPO_ID, repo_type="space", folder_path=str(ROOT),
        allow_patterns=ALLOW, ignore_patterns=IGNORE,
        commit_message="Deploy LogicScout",
    )
    api.upload_file(
        repo_id=REPO_ID, repo_type="space",
        path_or_fileobj=str(ROOT / "deploy" / "hf" / "README.md"), path_in_repo="README.md",
        commit_message="Space README",
    )
    print("files uploaded; waiting for build")

    last, start = None, time.time()
    while time.time() - start < TIMEOUT_S:
        stage = str(api.get_space_runtime(REPO_ID).stage)
        if stage != last:
            print(f"[{int(time.time() - start):4d}s] stage: {stage}")
            last = stage
        if stage == "RUNNING":
            print(URL)
            return 0
        if stage in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE", "DELETING"):
            print(f"failed: {stage}; see https://huggingface.co/spaces/{REPO_ID}", file=sys.stderr)
            return 2
        time.sleep(10)
    print(f"timeout after 15 min (last stage {last}); {URL}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
