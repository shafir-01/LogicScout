"""External anchoring of a run's digest chain.

A digest chain alone only shows that a log is internally consistent: whoever holds the file can
rewrite every event and recompute every digest. `anchor()` records the chain head (digest, event
count, time) in data/anchors.jsonl, which is committed to git. Git history and the remote then act
as the external witness: a log rewritten after its head was published no longer matches the anchor.

`verify()` proves integrity since anchoring. It does NOT prove the logged claims are correct, and
it cannot prove anything about a run that was never anchored or whose anchor was never published."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from logicscout import config
from logicscout.logbook import Logbook


def anchors_path() -> Path:
    return config.DATA_DIR / "anchors.jsonl"


def _events(run_dir: Path):
    p = Path(run_dir) / "events.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"no events.jsonl in {run_dir}")
    return Logbook.load(p)


def read_anchors(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or anchors_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def anchor(run_dir: Path, path: Path | None = None) -> dict[str, Any]:
    evs = _events(run_dir)
    if not evs:
        raise ValueError("empty log, nothing to anchor")
    rec = {"run_id": evs[0].run_id, "head_digest": evs[-1].digest, "n_events": len(evs), "ts": time.time()}
    p = path or anchors_path()
    for a in read_anchors(p):
        if a.get("run_id") == rec["run_id"] and a.get("head_digest") == rec["head_digest"]:
            return a
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def verify(run_dir: Path, path: Path | None = None) -> dict[str, Any]:
    """Report: chain_ok, anchored, anchor_ok (log still extends every anchored head), ok, plain-language notes."""
    evs = _events(run_dir)
    chain_ok = bool(evs) and Logbook.verify(evs)
    run_id = evs[0].run_id if evs else None
    mine = [a for a in read_anchors(path) if a.get("run_id") == run_id]
    anchor_ok, notes = None, []
    if not chain_ok:
        notes.append("FAILED: the digest chain does not recompute; events were edited or the log is corrupt.")
    if not mine:
        notes.append("No external anchor exists for this run, so nothing outside this file vouches for it. "
                     "The chain is only self-consistent.")
    else:
        anchor_ok = True
        for a in mine:
            n = a["n_events"]
            if n > len(evs):
                anchor_ok = False
                notes.append(f"FAILED: anchor covers {n} events but the log has {len(evs)} (truncated).")
            elif evs[n - 1].digest != a["head_digest"]:
                anchor_ok = False
                notes.append(f"FAILED: event {n} no longer matches the anchored head (log was rewritten after anchoring).")
        if anchor_ok:
            first = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(min(a["ts"] for a in mine)))
            notes.append(f"Log matches {len(mine)} anchored head(s); unchanged since the earliest anchor ({first}).")
    notes.append("Proves integrity since anchoring only. It does not prove the logged claims are correct, "
                 "and the anchor is only as trustworthy as the committed/pushed git history holding it.")
    ok = chain_ok and anchor_ok is True
    return {"run_id": run_id, "n_events": len(evs), "head_digest": evs[-1].digest if evs else None,
            "chain_ok": chain_ok, "anchored": bool(mine), "anchor_ok": anchor_ok, "ok": ok, "notes": notes}
