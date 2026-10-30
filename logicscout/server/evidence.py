"""GET /api/evidence: a summary assembled from whatever result files exist. Missing sources are omitted."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from logicscout import config

ARM_ORDER = ["full", "no_model", "model_only", "classical", "random", "idle"]
_ARM_MAP = {
    "full": "full", "code_only_no_model": "no_model", "no_model": "no_model", "code_only": "no_model",
    "model_only": "model_only", "classical": "classical", "random_probe": "random", "random": "random", "idle": "idle",
}


def _arm_name(raw: str) -> str | None:
    if raw in _ARM_MAP:
        return _ARM_MAP[raw]
    return "classical" if raw.startswith("classical") else None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _row(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"success": round(k / n, 4) if n else None, "n": n, "ci": [lo, hi]}


def _bench(root: Path) -> dict[str, Any] | None:
    base = root / "bench"
    if not base.is_dir():
        return None
    tally: dict[str, dict[str, list[int]]] = {}  # group -> arm -> [k, n]
    seeds = 0

    def add(group: str, arm: str, k: int, n: int) -> None:
        t = tally.setdefault(group, {}).setdefault(arm, [0, 0])
        t[0] += k
        t[1] += n

    for f in sorted(base.glob("*/*/seed-*.json")):
        d = _load(f)
        arm = _arm_name(f.parent.name)
        if not isinstance(d, dict) or arm is None or not isinstance(d.get("cases"), list):
            continue
        cases = [c for c in d["cases"] if isinstance(c, dict) and "success" in c]
        if not cases:
            continue
        group = "out" if f.parent.parent.name.startswith("forge") else "in"
        k, n = sum(1 for c in cases if c["success"]), len(cases)
        add(group, arm, k, n)
        if arm == "full":
            seeds += 1
            for base_arm in ("random", "idle"):
                v = d.get(base_arm)
                if isinstance(v, (int, float)):
                    add(group, base_arm, round(v * n), n)
    if not tally:
        return None

    def table(groups: list[str]) -> dict[str, Any]:
        agg: dict[str, list[int]] = {}
        for g in groups:
            for arm, (k, n) in tally.get(g, {}).items():
                a = agg.setdefault(arm, [0, 0])
                a[0] += k
                a[1] += n
        return {arm: _row(*agg[arm]) for arm in ARM_ORDER if arm in agg}

    return {
        "arms": table(["in", "out"]), "in_family": table(["in"]), "out_of_family": table(["out"]),
        "full_runs": seeds, "order": ARM_ORDER,
    }


def _model_value(root: Path) -> Any:
    d = root / "model_value"
    if not d.is_dir():
        return None
    out = {}
    for f in sorted(d.glob("*.json"))[:6]:
        j = _load(f)
        if j is not None:
            out[f.stem] = j
    return out or None


def _anchors(root: Path) -> dict[str, Any] | None:
    f = root / "anchors.jsonl"
    if not f.is_file():
        return None
    rows = []
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if isinstance(j, dict):
                rows.append(j)
    except OSError:
        return None
    return {"count": len(rows), "latest": rows[-3:]} if rows else None


def _forge_table(docs: Path) -> list[list[str]] | None:
    f = docs / "forge.md"
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return None
    for sec in re.split(r"\n(?=#{1,3} )", text):
        head = sec.splitlines()[0].lower() if sec else ""
        if not re.search(r"result|out-of-family|evidence|score", head):
            continue
        rows = [l for l in sec.splitlines() if l.strip().startswith("|")]
        cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.fullmatch(r"[\s|:-]+", r)]
        if len(cells) >= 2:
            return cells
    return None


def build(root: Path | None = None, docs: Path | None = None) -> dict[str, Any]:
    root = root or config.ROOT / "data"
    docs = docs or config.ROOT / "docs"
    out: dict[str, Any] = {}
    for key, val in (
        ("bench", _bench(root)),
        ("model_value", _model_value(root)),
        ("drift", next((j for p in (docs / "drift.json", root / "drift.json") if (j := _load(p)) is not None), None)),
        ("forge_table", _forge_table(docs)),
        ("anchors", _anchors(root)),
    ):
        if val:
            out[key] = val
    return out


router = APIRouter()


@router.get("/api/evidence")
def evidence():
    return build()
