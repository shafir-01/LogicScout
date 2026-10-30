"""Copy a finished run into data/replays/<name>: uv run python -m logicscout.server.record <run_id> <name>"""
from __future__ import annotations

import json
import shutil
import sys

from logicscout.server import runs as R


def record(run_id: str, name: str) -> None:
    if not (R.ID_RE.match(run_id) and R.ID_RE.match(name)):
        raise SystemExit("invalid run id or name")
    src = R.runs_dir() / run_id
    if not (src / "state.json").exists():
        raise SystemExit(f"run {run_id} is not finished (no state.json)")
    dst = R.replays_dir() / name
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("events.jsonl", "state.json"):  # prompts.jsonl and private.json are never copied
        shutil.copy2(src / f, dst / f)
    (dst / "debrief.json").write_text(json.dumps(R.debrief_from_disk(src), indent=2), encoding="utf-8")
    from logicscout.anchor import anchor
    anchor(dst)
    print(f"recorded {run_id} -> {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m logicscout.server.record <run_id> <name>")
    record(sys.argv[1], sys.argv[2])
