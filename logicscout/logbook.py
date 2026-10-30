"""Append-only run log. Every event is digested with the previous digest, persisted as JSONL,
and fanned out to live subscribers (SSE)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from logicscout.contracts import Event, Phase

EVENT_KINDS = {
    "run.started", "run.finished", "run.failed", "phase",
    "briefing.query", "briefing.source", "briefing.claim", "briefing.checked",
    "hypothesis.proposed", "hypothesis.supported", "hypothesis.refuted",
    "probe.designed", "probe.step", "probe.outcome",
    "theory.revised", "playbook.compiled", "playbook.rejected",
    "control.step", "control.goal",
    "shift.applied",  # public: only "the hidden world changed", never what
    "drift.suspected", "drift.confirmed", "recovery.done",
    "transfer.loaded", "transfer.saved",
    "referee.report", "model.call", "note", "error",
}


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class Logbook:
    def __init__(self, run_id: str, path: Path | None = None) -> None:
        self.run_id = run_id
        self.path = path
        self.events: list[Event] = []
        self.phase: Phase = "encounter"
        self._subs: list[asyncio.Queue[Event | None]] = []
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def set_phase(self, phase: Phase, **data: Any) -> Event:
        self.phase = phase
        return self.append("phase", {"phase": phase, **data})

    def append(self, kind: str, data: dict[str, Any] | None = None) -> Event:
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        data = data or {}
        prev = self.events[-1].digest if self.events else ""
        seq = len(self.events)
        digest = hashlib.sha256(canonical([seq, self.run_id, kind, data, prev]).encode()).hexdigest()
        ev = Event(seq=seq, run_id=self.run_id, ts=time.time(), kind=kind, phase=self.phase, data=data, digest=digest)
        self.events.append(ev)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(ev.model_dump_json() + "\n")
        for q in self._subs:
            q.put_nowait(ev)
        return ev

    def close(self) -> None:
        for q in self._subs:
            q.put_nowait(None)

    def subscribe(self) -> asyncio.Queue[Event | None]:
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event | None]) -> None:
        if q in self._subs:
            self._subs.remove(q)

    @staticmethod
    def verify(events: list[Event]) -> bool:
        """Recompute the digest chain. Proves the log was not edited, not that its claims are true."""
        prev = ""
        for ev in events:
            d = hashlib.sha256(canonical([ev.seq, ev.run_id, ev.kind, ev.data, prev]).encode()).hexdigest()
            if d != ev.digest:
                return False
            prev = d
        return True

    @classmethod
    def load(cls, path: Path) -> list[Event]:
        return [Event.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
