"""List models on Nebius Token Factory: uv run python -m logicscout.llm.models"""
from __future__ import annotations

import httpx

from logicscout import config


def list_models() -> list[str]:
    if not config.NEBIUS_API_KEY:
        raise SystemExit("NEBIUS_API_KEY is not set (add it to .env)")
    r = httpx.get(config.NEBIUS_BASE_URL.rstrip("/") + "/models",
                  headers={"Authorization": f"Bearer {config.NEBIUS_API_KEY}"}, timeout=30)
    r.raise_for_status()
    return sorted(m["id"] for m in r.json().get("data", []))


if __name__ == "__main__":
    ids = list_models()
    for i in ids:
        print(("* " if "nemotron" in i.lower() else "  ") + i)
    print(f"\n{len(ids)} models, {sum('nemotron' in i.lower() for i in ids)} nemotron (*)")
