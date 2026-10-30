"""Run registry: creates runs, drives missions as asyncio tasks, persists artefacts."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from logicscout import config
from logicscout.contracts import RunConfig, RunState
from logicscout.logbook import Logbook

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
IP_LIMIT = 3
IP_WINDOW = 600.0

# Late-bound collaborators (owned by other modules); tests may override these attributes.
run_mission = None
MissionControls = None
open_session = None
Nemotron = None


class _Controls:
    def __init__(self) -> None:
        self.shift_requested = asyncio.Event()
        self.stop = asyncio.Event()


def _deps():
    global run_mission, MissionControls, open_session, Nemotron
    if run_mission is None or MissionControls is None:
        from logicscout.scout import mission
        run_mission = run_mission or mission.run_mission
        MissionControls = MissionControls or mission.MissionControls
    if open_session is None:
        from logicscout.sandbox import open_session as _os
        open_session = _os
    if Nemotron is None:
        from logicscout.llm import Nemotron as _N
        Nemotron = _N
    return run_mission, MissionControls, open_session, Nemotron


def check_variant(world_id: str, variant: str) -> None:
    """Runs use the lab variant; forge also accepts g<seed> (a generated system). ValueError -> HTTP 400."""
    if variant == "standard":
        return
    if world_id == "forge":
        from logicscout.worlds.forge import VARIANT_RE
        if VARIANT_RE.match(variant or ""):
            return
        raise ValueError(f"forge variant must be 'standard' or g<seed> (1-6 digits), got {variant!r}")
    raise ValueError(f"world {world_id!r} only runs the 'standard' variant")


def runs_dir() -> Path:
    return config.DATA_DIR / "runs"


def replays_dir() -> Path:
    return config.DATA_DIR / "replays"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def shift_menu(world_id: str | None) -> list[dict] | None:
    """Human-only list of hidden changes for a world; never sent to the scout."""
    from logicscout.worlds.base import REGISTRY, load_all
    if world_id not in REGISTRY:
        load_all()
    cls = REGISTRY.get(world_id or "")
    return cls.shift_menu() if cls else None


def _label_shifts(shifts: list, world_id: str | None) -> list:
    labels = {m["id"]: m["label"] for m in (shift_menu(world_id) or [])}
    return [{**s, "label": labels.get(s.get("kind"), s.get("description"))} if isinstance(s, dict) else s
            for s in shifts]


def debrief_from_disk(run_dir: Path) -> dict[str, Any]:
    """Build the debrief from private files. The raw files are never served."""
    private = read_json(run_dir / "private.json") or {}
    state = read_json(run_dir / "state.json") or {}
    return {
        "run_id": state.get("run_id", run_dir.name),
        "world_id": (state.get("config") or {}).get("world_id"),
        "hidden_laws": private.get("truth", []),
        "shifts": _label_shifts(private.get("shifts", private.get("shift_records", [])),
                                (state.get("config") or {}).get("world_id")),
        "final_theory": state.get("theory"),
        "playbook": state.get("playbook"),
        "referee": state.get("referee"),
    }


@dataclass
class Run:
    run_id: str
    log: Logbook
    state: RunState
    controls: Any
    session: Any
    ip: str
    task: asyncio.Task | None = None
    done: bool = False
    dir: Path = field(default_factory=Path)


class RunRegistry:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self._ip_hits: dict[str, list[float]] = {}
        self._day: tuple[str, int] = ("", 0)

    def daily_left(self) -> int:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self._day[0] != today:
            self._day = (today, 0)
        return config.MAX_RUNS_PER_DAY - self._day[1]

    def live_count(self) -> int:
        return sum(1 for r in self.runs.values() if not r.done)

    def check_ip(self, ip: str) -> bool:
        now = time.time()
        hits = [t for t in self._ip_hits.get(ip, []) if now - t < IP_WINDOW]
        self._ip_hits[ip] = hits
        return len(hits) < IP_LIMIT

    def create(self, cfg: RunConfig, ip: str) -> Run:
        mission, controls_cls, opener, llm_cls = _deps()
        run_id = uuid.uuid4().hex[:10]
        d = runs_dir() / run_id
        d.mkdir(parents=True, exist_ok=True)
        log = Logbook(run_id, d / "events.jsonl")
        llm = llm_cls(on_call=lambda c: log.append("model.call", c.model_dump()), prompt_log=d / "prompts.jsonl")
        check_variant(cfg.world_id, cfg.variant)
        session = opener(cfg.world_id, cfg.variant)
        state = RunState(run_id=run_id, config=cfg, phase="encounter", live=True, started_at=time.time())
        run = Run(run_id, log, state, controls_cls(), session, ip, dir=d)
        self.runs[run_id] = run
        self._ip_hits.setdefault(ip, []).append(time.time())
        self.daily_left()
        self._day = (self._day[0], self._day[1] + 1)
        run.task = asyncio.create_task(self._drive(run, mission, llm))
        return run

    async def _drive(self, run: Run, mission, llm) -> None:
        try:
            kwargs: dict[str, Any] = {}
            params = inspect.signature(mission).parameters
            if "prompt_log" in params:
                kwargs["prompt_log"] = run.dir / "prompts.jsonl"
            if "referee" in params:
                try:
                    from logicscout.referee import evaluate
                    kwargs["referee"] = evaluate
                except ImportError:
                    run.log.append("note", {"text": "referee unavailable"})
            if "trial_port_factory" in params:  # a separate session of the same world for reality trials
                opener, c = _deps()[2], run.state.config
                kwargs["trial_port_factory"] = lambda: opener(c.world_id, c.variant)
            result = await mission(run.state.config, run.log, llm, run.session, run.state, run.controls, **kwargs)
            if isinstance(result, RunState):
                run.state = result
        except asyncio.CancelledError:
            run.log.append("error", {"message": "run cancelled"})
            run.state.phase = "failed"
        except Exception as e:  # surfaced to the UI, never swallowed
            run.log.append("error", {"message": f"{type(e).__name__}: {e}"})
            run.log.set_phase("failed")
            run.state.phase = "failed"
        finally:
            self._finish(run)

    def _finish(self, run: Run) -> None:
        run.state.live = False
        run.state.finished_at = run.state.finished_at or time.time()
        if run.state.phase not in ("done", "failed"):
            run.state.phase = "done"
        kinds = {e.kind for e in run.log.events}
        if not kinds & {"run.finished", "run.failed"}:
            run.log.append("run.finished", {"phase": run.state.phase})
        try:
            private = read_json(run.dir / "private.json") or {}
            private["truth"] = run.session.admin.truth()
            (run.dir / "private.json").write_text(json.dumps(private, default=str), encoding="utf-8")
        except Exception as e:
            run.log.append("note", {"text": f"debrief truth unavailable: {type(e).__name__}"})
        (run.dir / "state.json").write_text(run.state.model_dump_json(), encoding="utf-8")
        run.done = True
        run.log.close()
        try:
            from logicscout.anchor import anchor
            anchor(run.dir)
        except Exception:
            pass

    # ---- disk-backed lookups -------------------------------------------------------
    def summary(self, run_id: str) -> dict[str, Any] | None:
        r = self.runs.get(run_id)
        if r:
            s = r.state
        else:
            raw = read_json(runs_dir() / run_id / "state.json")
            if not raw:
                return None
            s = RunState.model_validate(raw)
        return {
            "run_id": s.run_id, "world_id": s.config.world_id, "phase": s.phase,
            "live": bool(r and not r.done), "started_at": s.started_at, "finished_at": s.finished_at,
            "success_rate": s.referee.success_rate if s.referee else None,
        }

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        ids = set(self.runs)
        if runs_dir().exists():
            ids |= {p.name for p in runs_dir().iterdir() if p.is_dir()}
        out = [s for i in ids if (s := self.summary(i))]
        return sorted(out, key=lambda s: s["started_at"], reverse=True)[:limit]

    def state(self, run_id: str) -> RunState | None:
        r = self.runs.get(run_id)
        if r:
            return r.state
        raw = read_json(runs_dir() / run_id / "state.json")
        return RunState.model_validate(raw) if raw else None
