"""The full arc: encounter -> briefing/transfer -> probing -> control -> hidden change -> drift -> recovery -> referee.

`state` (RunState) is updated in place so the server can serve it live. Ground truth (session.admin) is
only used to apply hidden changes and to record private scores; nothing from it reaches the scout.
The referee is injected by the caller (server/CLI): scout-side code never imports it.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from logicscout import config as cfg
from logicscout.contracts import (
    LLM, Action, Event, Hypothesis, Mismatch, ModelCall, Objective, Observation, Phase, RunConfig, RunState, Theory,
    WorldManual,
)
from logicscout.dsl import safe_evaluate
from logicscout.logbook import Logbook
from logicscout.scout import synth
from logicscout.scout.investigator import Investigator
from logicscout.scout.monitor import DriftMonitor
from logicscout.scout.transfer import MechanismLibrary
from logicscout.theory import Predictor, accuracy, compare, persistence_accuracy

EPISODES = 4
MAX_EPISODES = 8  # extra episodes are allowed only while a hidden change is still unrecovered
MAX_REPROBES = 3
MAX_REFITS = 3
REFIT_BUDGET = 6
REPROBE_CAPS = {"hypothesize": 2, "design_probe": 1, "revise_theory": 1}  # model calls are finite
RefereeFn = Callable[..., Any]


@dataclass
class MissionControls:
    shift_requested: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)


class _Stopped(Exception):
    pass


def call_recorder(log: Logbook, previous: Callable[[ModelCall], Any] | None = None) -> Callable[[ModelCall], None]:
    """on_call hook: every model call becomes a public `model.call` event."""
    def record(call: ModelCall) -> None:
        log.append("model.call", call.model_dump())
        if previous:
            previous(call)
    return record


def objective_of(manual: WorldManual, objective_id: str | None) -> Objective:
    if objective_id:
        for o in manual.objectives:
            if o.id == objective_id:
                return o
        raise ValueError(f"unknown objective {objective_id!r} for {manual.world_id}")
    return manual.objectives[0]


def episode_seeds(manual: WorldManual, start: int, n: int) -> list[int]:
    lo, hi = manual.lab_seeds
    span = max(1, hi - lo)
    return [lo + (start - lo + i) % span for i in range(n)]


def goal_met(objective: Objective, obs: Observation) -> bool:
    return bool(safe_evaluate(objective.success, {"obs": obs.fields, "args": {}, "mem": {}, "t": obs.t}))


class _Mirror:
    """Keeps RunState in step with the logbook (theory, hypotheses, playbook, model usage)."""

    def __init__(self, log: Logbook, state: RunState) -> None:
        self.log, self.state = log, state
        self.q = log.subscribe()
        self.task = asyncio.create_task(self._run())
        m = state.metrics
        m.setdefault("model_calls", 0)
        m.setdefault("tokens", 0)
        m.setdefault("model_ids", [])
        m.setdefault("probes_used", 0)

    async def _run(self) -> None:
        while True:
            ev = await self.q.get()
            if ev is None:
                return
            self.apply(ev)

    def apply(self, ev: Event) -> None:
        s, m, d = self.state, self.state.metrics, ev.data
        try:
            if ev.kind == "theory.revised" and "theory" in d:
                s.theory = Theory.model_validate(d["theory"])
                m["theory_versions"] = s.theory.version
            elif ev.kind == "hypothesis.proposed" and "hypothesis" in d:
                h = Hypothesis.model_validate(d["hypothesis"])
                s.hypotheses = [x for x in s.hypotheses if x.id != h.id] + [h]
            elif ev.kind in ("hypothesis.supported", "hypothesis.refuted"):
                status = "supported" if ev.kind.endswith("supported") else "refuted"
                for h in s.hypotheses:
                    if h.id == d.get("id"):
                        h.status = status
            elif ev.kind == "probe.step":
                m["probes_used"] = m.get("probes_used", 0) + 1
            elif ev.kind == "model.call":
                m["model_calls"] += 1
                m["tokens"] += (d.get("prompt_tokens") or 0) + (d.get("completion_tokens") or 0)
                if d.get("model") and d["model"] not in m["model_ids"]:
                    m["model_ids"].append(d["model"])
        except Exception:
            pass  # a malformed event never breaks the mission

    def drain(self) -> None:
        while not self.q.empty():
            ev = self.q.get_nowait()
            if ev is not None:
                self.apply(ev)

    def close(self) -> None:
        self.log.unsubscribe(self.q)
        self.task.cancel()
        self.drain()


class Mission:
    def __init__(self, config: RunConfig, log: Logbook, llm: LLM, session: Any, state: RunState,
                 controls: MissionControls, prompt_log: Path | None, referee: RefereeFn | None,
                 mirror: _Mirror) -> None:
        self.config, self.log, self.llm, self.session, self.state = config, log, llm, session, state
        self.controls, self.prompt_log, self.referee, self.mirror = controls, prompt_log, referee, mirror
        self.port = session.port
        self.private_dir = cfg.DATA_DIR / "runs" / state.run_id
        self.m = state.metrics
        self.control_steps = 0
        self.shifts = 0
        self.shift_at: int | None = None  # control step of the latest unrecovered hidden change
        self.auto_shift_done = False
        self.truth: list[dict[str, Any]] = []  # private ground-truth per episode, merged at the end
        self.wrong_actions = 0
        self.reprobed_since_shift = False

    # ---- helpers -------------------------------------------------------------------------
    def phase(self, p: Phase, **data: Any) -> None:
        self.log.set_phase(p, **data)
        self.state.phase = p

    def note(self, text: str) -> None:
        self.log.append("note", {"text": text})

    def check_stop(self) -> None:
        if self.controls.stop.is_set():
            raise _Stopped()

    async def act(self, action: Action):
        return await asyncio.to_thread(self.port.act, action)

    async def true_success(self) -> bool:
        return bool(await asyncio.to_thread(self.session.admin.success, self.objective.id))

    async def reset(self, seed: int) -> Observation:
        return await asyncio.to_thread(self.port.reset, seed)

    def probes_used(self) -> int:
        self.mirror.drain()
        return self.m.get("probes_used", 0)

    def score_theory(self) -> None:
        self.mirror.drain()
        tr = self.inv.transitions
        self.m["accuracy"] = round(accuracy(self.theory, tr), 4) if tr else None
        self.m["baseline_accuracy"] = round(persistence_accuracy(tr), 4) if tr else None
        self.m["theory_versions"] = self.theory.version
        self.state.theory = self.theory
        if self.briefing_hyps:
            from logicscout.briefing import check
            self.log.append("briefing.checked", {"claims": check(self.briefing_hyps, self.theory)})

    def sync_hypotheses(self) -> None:
        hyps = getattr(self.inv, "hypotheses", None)
        if isinstance(hyps, dict):
            hyps = list(hyps.values())
        if isinstance(hyps, list) and all(isinstance(h, Hypothesis) for h in hyps):
            self.state.hypotheses = list(hyps)

    # ---- hidden change (private) ---------------------------------------------------------
    def maybe_shift(self) -> None:
        auto = (self.config.shift_after is not None and not self.auto_shift_done
                and self.control_steps >= self.config.shift_after)
        if not (self.controls.shift_requested.is_set() or auto):
            return
        if auto:
            self.auto_shift_done = True
        self.controls.shift_requested.clear()
        seed = self.config.seed * 31 + self.shifts
        kind = getattr(self.controls, "shift_kind", None)
        if kind:
            self.controls.shift_kind = None
            try:
                rec = self.session.admin.shift(seed, kind=kind)
            except TypeError:  # sandbox without a shift menu
                rec = self.session.admin.shift(seed)
        else:
            rec = self.session.admin.shift(seed)
        self.shifts += 1
        self.private_dir.mkdir(parents=True, exist_ok=True)
        path = self.private_dir / "private.json"
        try:
            private = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except json.JSONDecodeError:
            private = {}
        private.setdefault("shifts", []).append({"control_step": self.control_steps, **rec.model_dump()})
        path.write_text(json.dumps(private, indent=1, default=str), encoding="utf-8")
        self.log.append("shift.applied", {})
        if self.shift_at is None:
            self.shift_at = self.control_steps
            self.wrong_actions = 0
            self.reprobed_since_shift = False

    # ---- phases --------------------------------------------------------------------------
    async def run(self) -> RunState:
        self.phase("encounter")
        self.manual = manual = await asyncio.to_thread(self.port.manual)
        self.objective = objective_of(manual, self.config.objective_id)
        self.log.append("run.started", {"config": self.config.model_dump(), "manual": manual.model_dump()})
        priors: list[Hypothesis] = []
        self.briefing_hyps: list[Hypothesis] = []

        if self.config.use_briefing:
            if not cfg.TAVILY_API_KEY:
                self.note("briefing skipped: TAVILY_API_KEY is not set")
            else:
                self.phase("briefing")
                from logicscout.briefing import brief
                try:
                    self.briefing_hyps = await brief(manual, self.llm, self.log)
                    priors += self.briefing_hyps
                except Exception as e:
                    self.log.append("error", {"message": f"briefing failed: {type(e).__name__}: {e}"})
                    self.note("continuing without briefing priors")
        if self.config.use_transfer:
            lib = MechanismLibrary(cfg.DATA_DIR / "library")
            try:
                tp = await lib.priors(self.llm, manual)
            except Exception as e:
                tp = []
                self.log.append("error", {"message": f"transfer priors failed: {type(e).__name__}: {e}"})
            self.log.append("transfer.loaded", {"mechanisms": [m["name"] for m in lib.load()],
                                                "hypotheses": [h.model_dump() for h in tp]})
            priors += tp
        self.state.hypotheses = list(priors)
        self.check_stop()

        self.phase("probing")
        self.budget = self.config.probe_budget or manual.probe_budget
        self.inv = Investigator(self.llm, self.port, manual, self.log, priors)
        self.theory = await self.inv.investigate(Theory(world_id=manual.world_id), self.budget)
        self.sync_hypotheses()
        self.phase("theory")
        self.score_theory()
        self.check_stop()

        await self.control()
        self.check_stop()
        await self.finish()
        return self.state

    async def compile(self, seed: int, model: bool = True) -> None:
        start = await self.reset(seed)
        self.policy, self.playbook = await synth.synthesize(self.llm, self.theory, self.manual, self.objective,
                                                            self.log, start, attempts=synth.RETRIES + 1 if model else 0)
        self.state.playbook = self.playbook

    async def control(self) -> None:
        self.phase("control")
        seeds = episode_seeds(self.manual, self.config.seed, MAX_EPISODES)
        await self.compile(seeds[0])
        self.monitor = DriftMonitor(self.theory)
        self.calibrate()
        episodes: list[dict[str, Any]] = []
        self.m["episodes"] = episodes
        self.m["drift"] = {"detected_after_steps": None, "probes": 0, "recovered": False}
        self.m.setdefault("time_to_competence", None)
        reprobes = refits = 0
        for ep, seed in enumerate(seeds):
            pending = self.config.shift_after is not None and not self.auto_shift_done
            if ep >= EPISODES and self.shift_at is None and not pending:
                break
            self.check_stop()
            result = await self.episode(ep, seed)
            episodes.append({"seed": seed, "success": result["success"], "steps": result["steps"]})
            self.truth.append({"episode": ep, "seed": seed, "true_success": result["true_success"]})
            if result["success"] and self.m["time_to_competence"] is None:
                self.m["time_to_competence"] = self.probes_used()
            if result["success"] and self.shift_at is not None and result["after_reprobe"]:
                self.recovered(result)
            if not result["success"] and not result["drift"] and refits < MAX_REFITS:
                refits += 1
                await self.refit(seeds[min(ep + 1, len(seeds) - 1)])
            if result["drift"]:
                if reprobes >= MAX_REPROBES:
                    self.note("drift confirmed again but the re-investigation limit is reached; refitting on control experience")
                    if refits >= MAX_REFITS + 2:
                        break
                    refits += 1
                    await self.refit(seeds[min(ep + 1, len(seeds) - 1)])
                    continue
                reprobes += 1
                await self.reprobe(result["focus"], seeds[min(ep + 1, len(seeds) - 1)])

    async def episode(self, ep: int, seed: int) -> dict[str, Any]:
        obs = await self.reset(seed)
        policy = synth.make_policy(self.playbook, self.theory, self.manual, self.objective)
        predictor = Predictor(self.theory)
        predictor.reset(obs)
        recent: list[Mismatch] = []
        out = {"success": False, "steps": 0, "true_success": False, "drift": False, "focus": [],
               "after_reprobe": self.reprobed_since_shift}
        if goal_met(self.objective, obs):
            out.update(success=True, true_success=await self.true_success())
            self.log.append("control.goal", {"episode": ep, "steps": 0})
            return out
        for step in range(1, self.objective.horizon + 1):
            self.check_stop()
            self.maybe_shift()
            action = policy.next_action(obs)
            predicted = predictor.predict(obs, action)
            res = await self.act(action)
            new = res.observation
            mismatches = compare(predicted, new.fields, predictor.last_rules)
            predictor_rules = {f: list(r[-1:]) for f, r in predictor.last_rules.items()}
            predictor.advance(new)
            policy.after_step(new)
            self.inv.transitions.append((obs, action, new))
            self.control_steps += 1
            out["steps"] = step
            self.log.append("control.step", {
                "episode": ep, "step": step, "action": action.model_dump(), "predicted": predicted,
                "observation": new.model_dump(), "mismatches": [m.model_dump() for m in mismatches],
                **({"error": res.error} if res.error else {}),
            })
            if self.shift_at is not None and mismatches and not out["after_reprobe"]:
                self.wrong_actions += 1
            recent = (recent + mismatches)[-20:]
            obs = new
            wrong = {m.field for m in mismatches}
            correct = [k for f in new.fields if f != "t" and f not in wrong
                       for k in (predictor_rules.get(f) or [f"field:{f}"])]
            status = self.monitor.observe([m for m in mismatches if not self.within_resolution(m)], correct)
            if status == "suspected" and self.state.phase != "drift":
                self.phase("drift")
                self.log.append("drift.suspected", {"mismatches": [m.model_dump() for m in mismatches],
                                                    "surprise": round(self.monitor.rate(), 4)})
            elif status == "ok" and self.state.phase == "drift":
                self.note("suspected drift cleared: predictions match again")
                self.phase("control")
            elif status == "confirmed" and not out["drift"]:
                if self.state.phase != "drift":
                    self.phase("drift")
                    self.log.append("drift.suspected", {"mismatches": [m.model_dump() for m in mismatches],
                                                        "surprise": round(self.monitor.rate(), 4)})
                self.log.append("drift.confirmed", {"rules_implicated": self.monitor.rules_implicated})
                if self.shift_at is not None and self.m["drift"]["detected_after_steps"] is None:
                    self.m["drift"]["detected_after_steps"] = self.control_steps - self.shift_at
                out["drift"], out["focus"] = True, recent
                if any(m.field in self.objective.success for m in recent):
                    break  # the change touches what the goal depends on: stop and re-investigate now
                self.note("drift is in fields the goal does not depend on: finishing the episode first")
            if goal_met(self.objective, obs):
                out["success"] = True
                self.log.append("control.goal", {"episode": ep, "steps": step})
                break
            if res.done:
                break
        out["true_success"] = await self.true_success()
        return out

    def within_resolution(self, m: Mismatch) -> bool:
        """A float reading off by one display step (e.g. 1.5 vs 1.6) is rounding, not evidence of change."""
        p, o = m.predicted, m.observed
        if not all(isinstance(x, float) or (isinstance(x, int) and not isinstance(x, bool)) for x in (p, o)):
            return False
        if not any(f.name == m.field and f.type == "float" for f in self.manual.observations):
            return False
        vals = sorted({round(float(a.fields.get(m.field)), 6) for a, _, _ in self.inv.transitions[-80:]
                       if isinstance(a.fields.get(m.field), (int, float))})
        steps = [b - a for a, b in zip(vals, vals[1:]) if b - a > 1e-9]
        return bool(steps) and abs(p - o) <= min(steps) + 1e-9

    def adapt_budget(self, want: int) -> int:
        """Probes after the first investigation share one allowance equal to the probe budget."""
        return max(0, min(want, 2 * self.budget - self.probes_used()))

    async def refit(self, next_seed: int) -> None:
        """A failed episode is experience too: refit the theory on it (code-side fits, a few test probes,
        no model calls) and recompile; a model playbook is re-synthesized only if it was in use."""
        recent = getattr(self.inv, "refit_recent", None)
        if self.adapt_budget(REFIT_BUDGET) <= 0 and not callable(recent):
            return
        self.phase("reprobing")
        self.note("episode missed the goal: refitting the theory on the control experience")
        before = self.theory.version
        if self.adapt_budget(REFIT_BUDGET) > 0:
            self.theory = await self.inv.investigate(self.theory, budget=self.adapt_budget(REFIT_BUDGET),
                                                     caps={"hypothesize": 0, "design_probe": 0, "revise_theory": 0})
        else:  # probe allowance spent: learn from the latest control experience alone
            self.theory = recent(self.theory)
        self.sync_hypotheses()
        self.score_theory()
        self.check_stop()
        if self.theory.version != before:
            await self.compile(next_seed, model=self.playbook.origin != "planner")
            self.monitor.reset(self.theory)
            self.calibrate()
        self.phase("control")

    async def reprobe(self, focus: list[Mismatch], next_seed: int) -> None:
        self.phase("reprobing")
        before = self.probes_used()
        budget = self.adapt_budget(max(6, self.budget // 2))
        self.theory = await self.inv.investigate(self.theory, budget=budget, focus=focus, caps=REPROBE_CAPS)
        self.sync_hypotheses()
        used = self.probes_used() - before
        self.m["drift"]["probes"] = self.m["drift"].get("probes", 0) + used
        self.score_theory()
        self.check_stop()
        await self.compile(next_seed, model=self.playbook.origin != "planner")
        self.monitor.reset(self.theory)
        self.calibrate()
        if self.shift_at is not None:
            self.reprobed_since_shift = True
        self.phase("control")

    def calibrate(self) -> None:
        residuals = getattr(self.inv, "residuals", None)
        if callable(residuals):
            self.monitor.calibrate(residuals(self.theory))

    def recovered(self, result: dict[str, Any]) -> None:
        d = self.m["drift"]
        d["recovered"] = True
        self.log.append("recovery.done", {
            "steps_down": self.control_steps - (self.shift_at or 0),
            "probes_used": d.get("probes", 0),
            "wrong_actions": self.wrong_actions,
        })
        self.phase("recovered")
        self.shift_at = None
        self.reprobed_since_shift = False

    async def finish(self) -> None:
        self.phase("referee")
        if self.referee is None:
            self.note("no referee attached; held-out evaluation skipped")
        else:
            args = (self.manual.world_id, self.theory, self.playbook, self.objective.id, self.state.run_id,
                    self.prompt_log)
            params = inspect.signature(self.referee).parameters
            kw: dict[str, Any] = {}
            if "events" in params:
                kw["events"] = list(self.log.events)
            if "variant" in params:
                kw["variant"] = getattr(self.config, "variant", "standard")
            if inspect.iscoroutinefunction(self.referee):
                report = await self.referee(*args, **kw)
            else:
                report = await asyncio.to_thread(self.referee, *args, **kw)
            self.state.referee = report
            self.log.append("referee.report", {"report": report.model_dump()})
        if self.config.use_transfer or any(e["success"] for e in self.m.get("episodes", [])):
            try:
                added = await MechanismLibrary(cfg.DATA_DIR / "library").learn(self.llm, self.theory, self.manual)
                self.log.append("transfer.saved", {"mechanisms": added})
            except Exception as e:
                self.log.append("error", {"message": f"saving mechanisms failed: {type(e).__name__}: {e}"})


async def run_mission(
    config: RunConfig,
    log: Logbook,
    llm: LLM,
    session: Any,
    state: RunState,
    controls: MissionControls | None = None,
    prompt_log: Path | None = None,
    referee: RefereeFn | None = None,
) -> RunState:
    """Run the full arc. Never raises: failures end in phase "failed" with everything preserved.
    The caller owns the logbook and closes it. Pass `referee` (logicscout.referee.evaluate) to score the run."""
    controls = controls or MissionControls()
    state.started_at = state.started_at or time.time()
    mirror = _Mirror(log, state)
    hooked = hasattr(llm, "on_call") and llm.on_call is None  # the server/CLI may already log model calls
    if hooked:
        previous = llm.on_call
        llm.on_call = call_recorder(log, previous)
    mission = Mission(config, log, llm, session, state, controls, prompt_log, referee, mirror)
    try:
        await mission.run()
        mission.phase("done")
        mirror.close()
        _merge_truth(state, mission)
        log.append("run.finished", {"metrics": state.metrics})
    except _Stopped:
        log.append("note", {"text": "stopped by operator"})
        mission.phase("done")
        mirror.close()
        _merge_truth(state, mission)
        log.append("run.finished", {"metrics": state.metrics, "stopped": True})
    except Exception as e:
        log.append("error", {"message": f"{type(e).__name__}: {e}"})
        mission.phase("failed")
        mirror.close()
        _merge_truth(state, mission)
        log.append("run.failed", {"message": f"{type(e).__name__}: {e}", "metrics": state.metrics})
    finally:
        if hooked:
            llm.on_call = previous
        state.finished_at = time.time()
    return state


def _merge_truth(state: RunState, mission: Mission) -> None:
    """Ground-truth episode outcomes become visible only once the run is over."""
    for e, t in zip(state.metrics.get("episodes", []), mission.truth):
        e["true_success"] = t["true_success"]
