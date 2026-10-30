"""Bench arms. Every arm is scored by the same referee on the same held-out cases with real Nemotron calls.

The bench is privileged evaluation code (like the referee): it may read world classes and referee cases.
Nothing here is imported by the scout.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

from logicscout.contracts import (
    Action,
    Case,
    ModelCall,
    Objective,
    Observation,
    Playbook,
    RunConfig,
    RunState,
    Theory,
    WorldManual,
)
from logicscout.logbook import Logbook
from logicscout.referee import audit
from logicscout.referee.referee import (
    IDLE_NAMES,
    cases_for,
    collect_transitions,
    evaluate,
    objective_of,
    random_action,
    rule_contradictions,
    run_case,
    world_class,
)

SHIFT_AFTER = 40  # control steps before the automatic hidden change in mission arms
HISTORY = 8
MODEL_ARMS = {"zero_shot", "prompt_only", "reasoning_control"}
MISSION_ARMS = {"full", "no_briefing", "no_transfer", "no_adaptation", "no_model", "model_only"}
NO_CALL_ARMS = {"no_model", "tabular", "random", "idle"}  # never touch the model
ARMS = ["full", "no_model", "model_only", "tabular", "random", "idle", "random_probe", "passive", "zero_shot",
        "prompt_only", "no_briefing", "no_transfer", "no_adaptation", "reasoning_control"]


@dataclass
class ArmContext:
    world_id: str
    arm: str
    objective_id: str
    seed: int  # lab seed for the run
    index: int  # bench seed index
    out: Path  # directory for this arm+seed (prompt log, events)
    max_cases: int = 2  # referee cases for per-step model arms
    max_steps: int = 25  # per-case step cap for per-step model arms
    cache: dict[str, Any] = field(default_factory=dict)  # shared across arms for one seed
    variant: str = "standard"  # forge: "g<seed>" = a freshly generated system
    shift_after: int | None = SHIFT_AFTER
    use_briefing: bool = True

    @property
    def run_id(self) -> str:
        v = "" if self.variant == "standard" else f"-{self.variant}"
        return f"bench-{self.world_id}{v}-{self.arm}-s{self.index}"


class NullLLM:
    """use_model=False: every model call fails at once, so the mission takes its code-only path (zero calls)."""

    async def json(self, purpose, system, user, schema=None, tier="fast"):
        from logicscout.llm.nemotron import LLMError

        raise LLMError(f"model disabled for this run (use_model=False): {purpose}")


# ---- shared helpers ---------------------------------------------------------------------------

def make_llm(prompt_log: Path, calls: list[ModelCall]):
    from logicscout.llm import Nemotron

    prompt_log.parent.mkdir(parents=True, exist_ok=True)
    prompt_log.unlink(missing_ok=True)
    return Nemotron(on_call=calls.append, prompt_log=prompt_log)


def model_stats(calls: list[ModelCall]) -> dict[str, Any]:
    n = len(calls)
    lat = [c.latency_ms for c in calls]
    return {
        "model_calls": n,
        "failed_calls": sum(not c.ok for c in calls),
        "failure_rate": round(sum(not c.ok for c in calls) / n, 4) if n else 0.0,
        "tokens": sum((c.prompt_tokens or 0) + (c.completion_tokens or 0) for c in calls),
        "latency_s": round(sum(lat) / 1000, 2),
        "models": sorted({c.model for c in calls}),
    }


def held_out_contradictions(world_id: str, theory: Theory, objective_id: str) -> int:
    cls = world_class(world_id)
    total = 0
    for c in cases_for(cls, objective_id):
        if c.variant == "standard":
            total += sum(rule_contradictions(theory, collect_transitions(cls, c)).values())
    return total


def report_fields(report) -> dict[str, Any]:
    return {
        "success": report.success_rate,
        "random": report.baselines.get("random"),
        "idle": report.baselines.get("idle"),
        "prediction_accuracy": report.prediction_accuracy,
        "persistence_accuracy": report.baselines.get("persistence_accuracy"),
        "cases": [c.model_dump() for c in report.cases],
        "leakage_checks": report.leakage_checks,
        "referee_notes": report.notes,
        "referee_digest": report.digest,
    }


def idle_action(manual: WorldManual) -> Action:
    spec = next((a for a in manual.actions if a.name in IDLE_NAMES and not a.params), None)
    return Action(name=spec.name if spec else manual.actions[0].name)


@contextmanager
def drift_monitor_disabled():
    """Ablation: the mission's drift monitor never reports anything."""
    from logicscout.scout import mission
    from logicscout.scout.monitor import DriftMonitor

    class BlindMonitor(DriftMonitor):
        def observe(self, mismatches):
            super().observe(mismatches)
            return "ok"

    with mock.patch.object(mission, "DriftMonitor", BlindMonitor):
        yield


# ---- mission arms (full and its toggles) --------------------------------------------------------

@contextmanager
def induction_setting(use_induction: bool):
    """Hands RunConfig.use_induction to the mission's Investigator."""
    from functools import partial

    from logicscout.scout import mission
    from logicscout.scout.investigator import Investigator

    if use_induction:
        yield
        return
    with mock.patch.object(mission, "Investigator", partial(Investigator, use_induction=False)):
        yield


def drift_metrics(events) -> dict[str, Any]:
    """From the logbook: false alarms before the change, detection delay and recovery time in control steps."""
    steps = 0
    shift_step = detect_step = None
    alarms_before = suspected_before = 0
    recovered, recovery_steps = False, None
    for e in events:
        if e.kind == "control.step":
            steps += 1
        elif e.kind == "shift.applied" and shift_step is None:
            shift_step = steps
        elif e.kind == "drift.confirmed":
            if shift_step is None:
                alarms_before += 1
            elif detect_step is None:
                detect_step = steps
        elif e.kind == "drift.suspected" and shift_step is None:
            suspected_before += 1
        elif e.kind == "recovery.done" and shift_step is not None and not recovered:
            recovered, recovery_steps = True, e.data.get("steps_down")
    return {
        "shift_applied": shift_step is not None, "shift_at_control_step": shift_step,
        "control_steps_before_shift": shift_step if shift_step is not None else steps,
        "false_alarms_before_shift": alarms_before, "suspected_before_shift": suspected_before,
        "detected": detect_step is not None,
        "detection_delay_steps": None if detect_step is None else detect_step - shift_step,
        "recovered": recovered, "recovery_steps": recovery_steps,
        "control_steps_total": steps,
    }


def case_counts(report) -> dict[str, int]:
    return {"n_cases": len(report.cases), "successes": sum(bool(c.success) for c in report.cases)}


async def arm_mission(ctx: ArmContext, *, use_briefing: bool | None = None, use_transfer: bool = True,
                      adaptation: bool = True, use_model: bool = True, use_induction: bool = True) -> dict[str, Any]:
    from logicscout.sandbox import open_session
    from logicscout.scout.mission import run_mission

    calls: list[ModelCall] = []
    prompt_log = ctx.out / "prompts.jsonl"
    log = Logbook(ctx.run_id)
    use_briefing = ctx.use_briefing if use_briefing is None else use_briefing
    cfg = RunConfig(world_id=ctx.world_id, objective_id=ctx.objective_id, seed=ctx.seed, variant=ctx.variant,
                    use_briefing=use_briefing and use_model, use_transfer=use_transfer and use_model,
                    shift_after=ctx.shift_after, use_model=use_model, use_induction=use_induction)
    llm = make_llm(prompt_log, calls) if cfg.use_model else NullLLM()
    state = RunState(run_id=ctx.run_id, config=cfg, phase="encounter", live=True)

    def referee(world_id, theory, playbook, objective_id, run_id, plog=None, variant="standard"):
        return evaluate(world_id, theory, playbook, objective_id, run_id, plog, events=list(log.events),
                        variant=variant)

    session = open_session(ctx.world_id, ctx.variant)
    t0 = time.perf_counter()
    with induction_setting(cfg.use_induction):
        if adaptation:
            state = await run_mission(cfg, log, llm, session, state, prompt_log=prompt_log, referee=referee)
        else:
            with drift_monitor_disabled():
                state = await run_mission(cfg, log, llm, session, state, prompt_log=prompt_log, referee=referee)
    wall = time.perf_counter() - t0
    (ctx.out / "events.jsonl").write_text("\n".join(e.model_dump_json() for e in log.events), encoding="utf-8")

    m = state.metrics
    out: dict[str, Any] = {"phase": state.phase, "wall_s": round(wall, 1), **model_stats(calls)}
    errors = [e.data.get("message") for e in log.events if e.kind in ("error", "run.failed")]
    if errors:
        out["errors"] = errors[-5:]
    if state.referee is None:
        out["status"] = "crash" if state.phase == "failed" else "no-referee"
        return out
    out.update(report_fields(state.referee))
    out.update(case_counts(state.referee))
    out["drift_metrics"] = drift_metrics(log.events)
    out["playbook_origin"] = state.playbook.origin if state.playbook else None
    out["status"] = "ok"
    out["probes_used"] = m.get("probes_used")
    out["probes_to_competence"] = m.get("time_to_competence")
    eps = m.get("episodes", [])
    out["control_actions"] = sum(e.get("steps", 0) for e in eps)
    out["episodes"] = eps
    drift = m.get("drift") or {}
    steps, after = 0, []
    for e in eps:
        if ctx.shift_after is not None and steps >= ctx.shift_after:
            after.append(bool(e.get("true_success")))
        steps += e.get("steps", 0)
    out["recovery"] = {
        "detected_after_steps": drift.get("detected_after_steps"),
        "reprobe_probes": drift.get("probes"),
        "recovered": drift.get("recovered"),
        "true_success_after_shift": round(sum(after) / len(after), 3) if after else None,
    }
    refuted = [r.id for r in (state.theory.rules if state.theory else []) if r.status in ("refuted", "retired")]
    out["false_conclusions"] = {
        "rules_refuted_in_run": len(refuted),
        "held_out_contradictions": held_out_contradictions(ctx.world_id, state.theory, ctx.objective_id)
        if state.theory else None,
    }
    if state.theory and state.playbook:
        ctx.cache["theory"], ctx.cache["playbook"] = state.theory, state.playbook
    return out


# ---- random-probe and passive arms -----------------------------------------------------------

def _gather(port, manual: WorldManual, log: Logbook, seed: int, budget: int, passive: bool) -> list:
    rng = random.Random(seed * 101 + (7 if passive else 3))
    lo, hi = manual.lab_seeds
    tr = []
    obs = None
    probe_n = 0
    for i in range(budget):
        if obs is None or (not passive and i % 8 == 0):
            s = seed if passive else rng.randrange(lo, hi)
            probe_n += 1
            log.append("probe.designed", {"probe": {"id": f"rp{probe_n}", "purpose": "random", "seed": s,
                                                    "hypotheses": [], "actions": []}})
            obs = port.reset(s)
        a = random_action(manual.actions, rng)
        res = port.act(a)
        log.append("probe.step", {"probe_id": f"rp{probe_n}", "action": a.model_dump(),
                                  "observation": res.observation.model_dump()})
        tr.append((obs, a, res.observation))
        obs = res.observation
    return tr


async def arm_random_probe(ctx: ArmContext, passive: bool = False) -> dict[str, Any]:
    from logicscout.sandbox import open_session
    from logicscout.scout import synth
    from logicscout.scout.investigator import Investigator

    calls: list[ModelCall] = []
    prompt_log = ctx.out / "prompts.jsonl"
    llm = make_llm(prompt_log, calls)
    log = Logbook(ctx.run_id)
    session = open_session(ctx.world_id)
    port = session.port
    manual = port.manual()
    objective = objective_of(manual, ctx.objective_id)
    t0 = time.perf_counter()
    tr = await asyncio.to_thread(_gather, port, manual, log, ctx.seed, manual.probe_budget, passive)
    inv = Investigator(llm, port, manual, log)
    inv.transitions = tr
    empty = Theory(world_id=ctx.world_id)
    theory, acc, msg = await inv._model_revision(empty, inv._accuracy(empty))  # the ONE theory-fitting call
    theory = theory.model_copy(update={"version": 1, "note": msg or "fit from random experience"})
    start = await asyncio.to_thread(port.reset, ctx.seed)
    _, playbook = await synth.synthesize(llm, theory, manual, objective, log, start)
    report = await asyncio.to_thread(evaluate, ctx.world_id, theory, playbook, ctx.objective_id, ctx.run_id,
                                     prompt_log, list(log.events))
    return {
        "status": "ok", "wall_s": round(time.perf_counter() - t0, 1), **model_stats(calls), **report_fields(report),
        "probes_used": len(tr), "fit_accuracy_on_own_data": round(acc, 4),
        "false_conclusions": {"rules_refuted_in_run": 0,
                              "held_out_contradictions": held_out_contradictions(ctx.world_id, theory, ctx.objective_id)},
    }


# ---- per-step model control --------------------------------------------------------------------

CONTROL_SYSTEM = (
    "You operate an unfamiliar system to reach an objective. Each turn choose exactly one next action from the "
    "listed actions, with valid arguments. Answer with one JSON object only."
)
ACTION_SCHEMA = {"type": "object", "properties": {"action": {"type": "object"}, "why": {"type": "string"}},
                 "required": ["action"]}


class ModelPolicy:
    """The model chooses every action. `context` is what it knows beyond the manual (theory, notes, or nothing)."""

    def __init__(self, llm, manual: WorldManual, objective: Objective, context: str, purpose: str) -> None:
        self.llm, self.manual, self.objective, self.context, self.purpose = llm, manual, objective, context, purpose
        self.history: list[str] = []
        self.failures = 0
        self.fallback = idle_action(manual)

    async def next_action(self, obs: Observation) -> Action:
        from logicscout.scout.prompts import manual_block

        user = "\n\n".join(p for p in [
            manual_block(self.manual),
            f"OBJECTIVE: {self.objective.text} (success when {self.objective.success}; "
            f"at most {self.objective.horizon} steps)",
            self.context,
            "RECENT STEPS:\n" + ("\n".join(self.history[-HISTORY:]) or "(none yet)"),
            "CURRENT OBSERVATION: " + json.dumps(obs.fields, sort_keys=True),
            'Reply: {"action":{"name":"...","args":{}},"why":"short reason"}',
        ] if p)
        try:
            out = await self.llm.json(self.purpose, CONTROL_SYSTEM, user, ACTION_SCHEMA, tier="fast")
            a = out.get("action") or {}
            return Action(name=str(a.get("name", "")), args=a.get("args") if isinstance(a.get("args"), dict) else {})
        except Exception:
            self.failures += 1
            return self.fallback

    def record(self, obs: Observation, action: Action, new: Observation, error: str | None) -> None:
        self.history.append(json.dumps({"t": obs.t, "action": action.model_dump(), "next": new.fields,
                                        **({"error": error} if error else {})}, sort_keys=True, default=str))


async def run_model_case(cls, case: Case, objective: Objective, policy: ModelPolicy, max_steps: int) -> dict:
    world = cls(variant=case.variant)
    obs = world.reset(case.seed)
    steps = errors = 0
    while steps < min(max_steps, objective.horizon) and not world.success(objective.id):
        a = await policy.next_action(obs)
        res = world.act(a)
        steps += 1
        errors += res.error is not None
        policy.record(obs, a, res.observation, res.error)
        obs = res.observation
    return {"case_id": case.case_id, "success": world.success(objective.id), "steps": steps,
            "inadmissible": errors}


async def model_control(ctx: ArmContext, llm, calls: list[ModelCall], context: str, purpose: str) -> dict[str, Any]:
    cls = world_class(ctx.world_id)
    manual = cls.manual()
    objective = objective_of(manual, ctx.objective_id)
    cases = cases_for(cls, ctx.objective_id)[: ctx.max_cases]
    t0 = time.perf_counter()
    before = len(calls)
    results, failures = [], 0
    for c in cases:
        pol = ModelPolicy(llm, manual, objective, context, purpose)
        results.append(await run_model_case(cls, c, objective, pol, ctx.max_steps))
        failures += pol.failures
    ctl = calls[before:]
    return {
        "subset_success": round(sum(r["success"] for r in results) / len(results), 4) if results else 0.0,
        "subset_cases": results, "subset_note": f"first {len(cases)} referee cases, steps capped at {ctx.max_steps}",
        "control_actions": sum(r["steps"] for r in results),
        "control_tokens": sum((c.prompt_tokens or 0) + (c.completion_tokens or 0) for c in ctl),
        "control_latency_s": round(sum(c.latency_ms for c in ctl) / 1000, 2),
        "control_wall_s": round(time.perf_counter() - t0, 1),
        "policy_failures": failures,
    }


def prompt_audit(ctx: ArmContext, prompt_log: Path) -> dict[str, bool]:
    cls = world_class(ctx.world_id)
    truths = [s for v in cls.variants() for s in cls.truth(cls.default_laws(v))]
    ok, notes = audit.no_law_text_in_prompts(prompt_log, truths, [cls.default_laws(v) for v in cls.variants()],
                                             cls.manual())
    return {"no_law_text_in_prompts": ok, **({"audit_notes": notes[:10]} if notes else {})}


async def arm_zero_shot(ctx: ArmContext) -> dict[str, Any]:
    calls: list[ModelCall] = []
    prompt_log = ctx.out / "prompts.jsonl"
    llm = make_llm(prompt_log, calls)
    t0 = time.perf_counter()
    res = await model_control(ctx, llm, calls, "", "zero_shot_control")
    return {"status": "ok", "wall_s": round(time.perf_counter() - t0, 1), **model_stats(calls), **res,
            "leakage_checks": prompt_audit(ctx, prompt_log)}


EXPLORE_SCHEMA = {"type": "object", "properties": {"tool": {"type": "string"}, "action": {"type": "object"},
                                                   "seed": {"type": "integer"}, "notes": {"type": "string"}},
                  "required": ["tool", "notes"]}


async def arm_prompt_only(ctx: ArmContext) -> dict[str, Any]:
    """Free tool use (act/reset) for the probe budget, then the model controls every step with its own notes."""
    from logicscout.sandbox import open_session
    from logicscout.scout.prompts import manual_block

    calls: list[ModelCall] = []
    prompt_log = ctx.out / "prompts.jsonl"
    llm = make_llm(prompt_log, calls)
    port = open_session(ctx.world_id).port
    manual = port.manual()
    lo, hi = manual.lab_seeds
    obs = port.reset(ctx.seed)
    notes, history, tool_errors = "", [], 0
    t0 = time.perf_counter()
    for _ in range(manual.probe_budget):
        user = "\n\n".join([
            manual_block(manual),
            "You may experiment freely to learn how this system works before you must operate it. Tools: "
            f'{{"tool":"act","action":{{"name":"...","args":{{}}}}}} or {{"tool":"reset","seed":<int in {lo}..{hi - 1}>}}.',
            "YOUR NOTES SO FAR: " + (notes or "(none)"),
            "RECENT STEPS:\n" + ("\n".join(history[-12:]) or "(none yet)"),
            "CURRENT OBSERVATION: " + json.dumps(obs.fields, sort_keys=True),
            'Reply: {"tool":"act"|"reset","action":{...},"seed":0,"notes":"your updated notes on how the system '
            'works (max 1500 chars)"}',
        ])
        try:
            out = await llm.json("prompt_only_explore", CONTROL_SYSTEM, user, EXPLORE_SCHEMA, tier="fast")
        except Exception:
            tool_errors += 1
            continue
        notes = str(out.get("notes") or notes)[:1500]
        try:
            if out.get("tool") == "reset":
                seed = int(out.get("seed", ctx.seed))
                obs = await asyncio.to_thread(port.reset, seed if lo <= seed < hi else ctx.seed)
                history.append(json.dumps({"reset": seed}))
            else:
                a = out.get("action") or {}
                act = Action(name=str(a.get("name", "")), args=a.get("args") if isinstance(a.get("args"), dict) else {})
                res = await asyncio.to_thread(port.act, act)
                history.append(json.dumps({"t": obs.t, "action": act.model_dump(), "next": res.observation.fields,
                                           **({"error": res.error} if res.error else {})}, default=str))
                tool_errors += res.error is not None
                obs = res.observation
        except Exception:
            tool_errors += 1
    explore_s = time.perf_counter() - t0
    res = await model_control(ctx, llm, calls, "YOUR NOTES FROM EXPERIMENTS: " + (notes or "(none)"),
                              "prompt_only_control")
    return {"status": "ok", "wall_s": round(time.perf_counter() - t0, 1), "explore_s": round(explore_s, 1),
            **model_stats(calls), **res, "probes_used": manual.probe_budget, "tool_errors": tool_errors,
            "leakage_checks": prompt_audit(ctx, prompt_log)}


async def arm_reasoning_control(ctx: ArmContext) -> dict[str, Any]:
    """Same learned theory; control by a model call per step vs the compiled playbook, same cases and cap."""
    from logicscout.referee.referee import controller
    from logicscout.scout.prompts import theory_block

    pre: dict[str, Any] = {}
    if "theory" not in ctx.cache:
        pre = await arm_mission(ArmContext(**{**ctx.__dict__, "arm": "full", "out": ctx.out / "full"}))
        if "theory" not in ctx.cache:
            return {"status": "crash", "errors": ["full mission produced no theory/playbook"], **pre}
    theory: Theory = ctx.cache["theory"]
    playbook: Playbook = ctx.cache["playbook"]
    calls: list[ModelCall] = []
    prompt_log = ctx.out / "prompts.jsonl"
    llm = make_llm(prompt_log, calls)
    res = await model_control(ctx, llm, calls, theory_block(theory), "reasoning_control")
    cls = world_class(ctx.world_id)
    t0 = time.perf_counter()
    compiled = [run_case(cls, c, ctx.objective_id, controller(theory, playbook), horizon=ctx.max_steps)
                for c in cases_for(cls, ctx.objective_id)[: ctx.max_cases]]
    compiled_s = time.perf_counter() - t0
    return {
        "status": "ok", **model_stats(calls), **res, "leakage_checks": prompt_audit(ctx, prompt_log),
        "compiled": {
            "subset_success": round(sum(c.success for c in compiled) / len(compiled), 4) if compiled else 0.0,
            "control_actions": sum(c.steps for c in compiled), "control_tokens": 0,
            "control_wall_s": round(compiled_s, 2), "playbook_origin": playbook.origin,
        },
        **({"full_run_model_calls": pre.get("model_calls"), "full_run_tokens": pre.get("tokens")} if pre else {}),
    }


# ---- classical baselines: tabular system identification, random and idle control ---------------

def _enum_params(manual: WorldManual) -> dict[str, list[str]]:
    return {a.name: [p.name for p in a.params if p.type == "enum" or p.choices] for a in manual.actions}


def coverage_actions(manual: WorldManual) -> list[Action]:
    """Every action once per enum choice (other params at their minimum): the coverage part of the experience."""
    out = []
    for a in manual.actions:
        base = {p.name: (p.choices[0] if p.choices else (p.min if p.min is not None else 0)) for p in a.params
                if p.type != "bool"} | {p.name: True for p in a.params if p.type == "bool"}
        enums = [p for p in a.params if p.type == "enum" or p.choices]
        if not enums:
            out.append(Action(name=a.name, args=base))
            continue
        for p in enums:
            for c in p.choices or []:
                out.append(Action(name=a.name, args={**base, p.name: c}))
    return out


def gather_experience(port, manual: WorldManual, seed: int, budget: int) -> list:
    """Coverage first, then uniformly random actions; a fresh lab seed every 8 steps or at episode end."""
    rng = random.Random(seed * 977 + 11)
    lo, hi = manual.lab_seeds
    cover = coverage_actions(manual)
    tr, obs = [], None
    for i in range(budget):
        if obs is None or i % 8 == 0:
            obs = port.reset(rng.randrange(lo, hi))
        a = cover[i] if i < len(cover) else random_action(manual.actions, rng)
        res = port.act(a)
        if not res.error:
            tr.append((obs, a, res.observation))
        obs = None if res.done else res.observation
    return tr


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def tabular_theory(manual: WorldManual, transitions: list, world_id: str) -> Theory:
    """Per (action, enum args) and field: mean delta for numeric fields, majority next value otherwise.
    Each entry is kept only if it does not lower accuracy on the experience it was learned from."""
    from collections import Counter

    from logicscout.contracts import Rule
    from logicscout.theory import accuracy, validate_theory

    enums = _enum_params(manual)
    groups: dict[tuple[str, str], dict[str, list]] = {}
    for b, a, o in transitions:
        when = " and ".join(f"args.{k} == {a.args[k]!r}" for k in enums.get(a.name, []) if k in a.args) or "True"
        g = groups.setdefault((a.name, when), {})
        for f, v in o.fields.items():
            if f != "t":
                g.setdefault(f, []).append((b.fields.get(f), v))
    cands = []
    for (act, when), fields in groups.items():
        for f, pairs in fields.items():
            if all(_num(x) and _num(y) for x, y in pairs):
                d = sum(y - x for x, y in pairs) / len(pairs)
                if all(isinstance(y, int) for _, y in pairs):
                    d = round(d)
                else:
                    d = round(d, 4)
                if d == 0:
                    continue
                expr = f"obs.{f} + {d!r}" if d > 0 else f"obs.{f} - {-d!r}"
            else:
                changed = sum(x != y for x, y in pairs)
                if changed * 2 <= len(pairs):
                    continue
                expr = Counter(repr(y) for _, y in pairs).most_common(1)[0][0]
            cands.append((len(pairs), Rule(id=f"T{len(cands) + 1}", statement=f"table: after {act!r}"
                                           f"{'' if when == 'True' else ' when ' + when}, {f} becomes {expr}",
                                           action=act, when=when, effects={f: expr}, status="supported")))
    theory = Theory(world_id=world_id, version=1, note="tabular model: per-action mean change per field")
    if not transitions:
        return theory
    acc = accuracy(theory, transitions)
    for _, rule in sorted(cands, key=lambda c: -c[0]):
        cand = theory.model_copy(deep=True)
        cand.rules.append(rule)
        if validate_theory(cand, manual):
            continue
        try:
            a = accuracy(cand, transitions)
        except Exception:
            continue
        if a >= acc:
            theory, acc = cand, a
    return theory


async def arm_tabular(ctx: ArmContext) -> dict[str, Any]:
    """Classical system identification with no model: same probe allowance as a mission (initial budget plus the
    re-investigation allowance), a table model, and the same planner and referee."""
    from logicscout.sandbox import open_session
    from logicscout.scout import synth
    from logicscout.theory import accuracy

    log = Logbook(ctx.run_id)
    port = open_session(ctx.world_id, ctx.variant).port
    manual = port.manual()
    objective = objective_of(manual, ctx.objective_id)
    t0 = time.perf_counter()
    budget = 2 * manual.probe_budget
    tr = await asyncio.to_thread(gather_experience, port, manual, ctx.seed, budget)
    theory = await asyncio.to_thread(tabular_theory, manual, tr, ctx.world_id)
    start = await asyncio.to_thread(port.reset, manual.lab_seeds[0])
    _, playbook = await synth.synthesize(NullLLM(), theory, manual, objective, log, start, attempts=0)
    report = await asyncio.to_thread(evaluate, ctx.world_id, theory, playbook, ctx.objective_id, ctx.run_id,
                                     None, list(log.events), ctx.variant)
    return {"status": "ok", "wall_s": round(time.perf_counter() - t0, 1), "model_calls": 0, "tokens": 0,
            **report_fields(report), **case_counts(report), "probes_used": budget,
            "table_rules": len(theory.rules), "fit_accuracy_on_own_data": round(accuracy(theory, tr), 4) if tr else None,
            "playbook_origin": playbook.origin}


def arm_fixed_policy(ctx: ArmContext, arm: str) -> dict[str, Any]:
    from logicscout.referee.referee import IdlePolicy, RandomPolicy

    cls = world_class(ctx.world_id)
    cases = cases_for(cls, ctx.objective_id, ctx.variant)
    res = []
    for c in cases:
        if arm == "random":
            fac = (lambda w, m, o, s=c.seed: RandomPolicy(m, s * 7919 + ctx.seed))
        else:
            fac = (lambda w, m, o: IdlePolicy(m, None))
        res.append(run_case(cls, c, ctx.objective_id, fac))
    return {"status": "ok", "model_calls": 0, "tokens": 0, "probes_used": 0, "n_cases": len(res),
            "successes": sum(bool(r.success) for r in res), "success": sum(bool(r.success) for r in res) / len(res)
            if res else 0.0, "cases": [r.model_dump() for r in res]}


async def run_arm(arm: str, ctx: ArmContext) -> dict[str, Any]:
    if arm == "full":  # transfer off in the three-way comparison: every system is met cold
        return await arm_mission(ctx, use_transfer=False)
    if arm == "no_model":
        return await arm_mission(ctx, use_model=False, use_transfer=False)
    if arm == "model_only":
        return await arm_mission(ctx, use_induction=False, use_transfer=False)
    if arm == "tabular":
        return await arm_tabular(ctx)
    if arm in ("random", "idle"):
        return await asyncio.to_thread(arm_fixed_policy, ctx, arm)
    if arm == "no_briefing":
        return await arm_mission(ctx, use_briefing=False)
    if arm == "no_transfer":
        return await arm_mission(ctx, use_transfer=False)
    if arm == "no_adaptation":
        return await arm_mission(ctx, adaptation=False)
    if arm == "random_probe":
        return await arm_random_probe(ctx)
    if arm == "passive":
        return await arm_random_probe(ctx, passive=True)
    if arm == "zero_shot":
        return await arm_zero_shot(ctx)
    if arm == "prompt_only":
        return await arm_prompt_only(ctx)
    if arm == "reasoning_control":
        return await arm_reasoning_control(ctx)
    raise ValueError(f"unknown arm {arm!r}; known: {ARMS}")


def estimate_calls(arm: str, manual: WorldManual, n_cases: int, max_steps: int) -> int:
    """Rough upper estimate of model calls per seed, printed before anything runs."""
    horizon = min(max_steps, max(o.horizon for o in manual.objectives))
    mission = 40  # briefing + hypothesize/design/revise caps + synthesis + reprobes (rough)
    return {
        "full": 35, "model_only": 35, "no_model": 0, "tabular": 0, "random": 0, "idle": 0,
        "no_briefing": mission - 8, "no_transfer": mission - 2, "no_adaptation": mission - 10,
        "random_probe": 4, "passive": 4,
        "zero_shot": n_cases * horizon, "prompt_only": manual.probe_budget + n_cases * horizon,
        "reasoning_control": n_cases * horizon,
    }.get(arm, 0)
