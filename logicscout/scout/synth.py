"""Controller synthesis: the model writes a playbook, the learned theory checks it by simulation.

The returned policy runs with no model calls. If the model cannot produce a playbook that reaches the
objective inside the learned theory, a model-free planner on the same theory takes over.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from logicscout.contracts import LLM, Objective, Observation, Playbook, Theory, WorldManual
from logicscout.dsl import DSL_GUIDE
from logicscout.logbook import Logbook
from logicscout.planner import PlannerPolicy, progress
from logicscout.playbook import PlaybookRunner, simulate, validate_playbook

RETRIES = 2

SYSTEM = (
    "You are a control engineer. You are given an executable theory of how a system behaves (rules in the "
    "LogicScout DSL) and a goal. Write a playbook: an ordered list of condition -> action rules (first match "
    "fires) plus a fallback action, that reaches the goal within the horizon if the theory is right. "
    "Use only the listed actions, argument ranges and observed fields. The playbook runs without you, so it "
    "must be self-contained. You may keep your own memory variables (mem.*) updated after every step. "
    "Answer with one JSON object only."
)

PLAYBOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "memory": {"type": "object"},
        "updates": {"type": "object"},
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "when": {"type": "string"},
                    "do": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "args": {"type": "object"}},
                        "required": ["name"],
                    },
                    "why": {"type": "string"},
                },
                "required": ["when", "do"],
            },
        },
        "fallback": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "args": {"type": "object"}},
            "required": ["name"],
        },
    },
    "required": ["rules", "fallback"],
}

SHAPE = (
    '{"memory": {"<var>": <initial value>}, "updates": {"<var>": "<DSL expr, evaluated after each step>"}, '
    '"rules": [{"when": "<DSL condition on obs/mem/t>", "do": {"name": "<action>", '
    '"args": {"<arg>": "<DSL expr>"}}, "why": "plain words"}], '
    '"fallback": {"name": "<action>", "args": {"<arg>": "<DSL expr>"}}}'
)


def _theory_text(theory: Theory) -> str:
    keep = {"id", "statement", "action", "when", "effects", "memory", "delay", "status", "confidence"}
    rules = [r.model_dump(include=keep) for r in theory.rules if r.status not in ("refuted", "retired")]
    return json.dumps({"memory": theory.memory, "rules": rules, "unknowns": theory.unknowns}, indent=1)


def build_prompt(theory: Theory, manual: WorldManual, objective: Objective, start: Observation) -> str:
    return "\n\n".join([
        DSL_GUIDE,
        "Playbook rules use the same expressions; `when` sees obs, mem and t; action args are DSL expressions "
        "(write literal numbers as plain expressions, e.g. \"3\"; string/enum values must be quoted literals, e.g. "
        "\"'on'\"). Prefer few, general rules keyed on the fields the goal depends on.",
        f"System: {manual.title} ({manual.domain}). {manual.summary}",
        "Actions: " + json.dumps([a.model_dump() for a in manual.actions]),
        "Observed fields: " + json.dumps([f.model_dump() for f in manual.observations]),
        "Learned theory:\n" + _theory_text(theory),
        f"Goal: {objective.text}. Success condition: {objective.success}. Horizon: {objective.horizon} steps.",
        "A typical starting observation: " + json.dumps(start.fields),
        "Return JSON shaped like: " + SHAPE,
    ])


def _arg(manual: WorldManual | None, action: str, name: str, v: Any) -> str:
    """Args are DSL expressions; a bare enum choice (send via=buoy) is quoted instead of rejected."""
    if isinstance(v, bool) or not isinstance(v, str):
        return json.dumps(v) if not isinstance(v, bool) else str(v)
    spec = next((a for a in (manual.actions if manual else []) if a.name == action), None)
    p = next((p for p in (spec.params if spec else []) if p.name == name), None)
    if p is not None and p.choices and v in p.choices:
        return repr(v)
    return v


def _template(manual: WorldManual | None, do: Any) -> dict:
    do = do if isinstance(do, dict) else {}
    name = str(do.get("name", ""))
    return {"name": name, "args": {k: _arg(manual, name, k, v) for k, v in (do.get("args") or {}).items()}}


def _to_playbook(raw: dict[str, Any], theory: Theory, objective: Objective, manual: WorldManual | None = None) -> Playbook:
    rules = []
    for r in raw.get("rules", []):
        rules.append({"when": str(r.get("when", "True")), "why": str(r.get("why", "")),
                      "do": _template(manual, r.get("do"))})
    fb = raw.get("fallback") or {}
    return Playbook.model_validate({
        "id": f"pb-{uuid.uuid4().hex[:8]}",
        "world_id": theory.world_id,
        "objective_id": objective.id,
        "theory_version": theory.version,
        "origin": "synthesized",
        "memory": raw.get("memory") or {},
        "updates": {k: str(v) for k, v in (raw.get("updates") or {}).items()},
        "rules": rules,
        "fallback": _template(manual, fb),
    })


def make_policy(playbook: Playbook, theory: Theory, manual: WorldManual, objective: Objective):
    """Fresh, model-free policy for a new episode."""
    if playbook.origin == "planner":
        return PlannerPolicy(theory, manual, objective)
    return PlaybookRunner(playbook)


def _summary(sim: dict[str, Any]) -> dict[str, Any]:
    return {"success": bool(sim.get("success")), "steps": int(sim.get("steps") or 0)}


def _trace_tail(sim: dict[str, Any], n: int = 8) -> str:
    trace = sim.get("trace") or []
    return json.dumps(trace[-n:], default=str)[:3000]


async def synthesize(
    llm: LLM,
    theory: Theory,
    manual: WorldManual,
    objective: Objective,
    log: Logbook,
    start_obs: Observation,
    attempts: int = RETRIES + 1,
):
    """Return (policy, playbook). The playbook is checked by simulation inside the learned theory.
    attempts=0 skips the model and compiles the planner directly."""
    user = build_prompt(theory, manual, objective, start_obs)
    feedback = ""
    best: tuple[float, Playbook] | None = None
    for attempt in range(attempts):
        try:
            raw = await llm.json("synthesize_playbook", SYSTEM, user + feedback, schema=PLAYBOOK_SCHEMA, tier="deep")
            pb = _to_playbook(raw, theory, objective, manual)
        except Exception as e:  # model failure or malformed playbook: count as a failed attempt
            log.append("playbook.rejected", {"attempt": attempt, "errors": [f"{type(e).__name__}: {e}"]})
            feedback = f"\n\nYour previous answer could not be used: {e}. Return valid JSON in the shape above."
            continue
        errors = validate_playbook(pb, manual)
        if errors:
            log.append("playbook.rejected", {"attempt": attempt, "playbook": pb.model_dump(), "errors": errors})
            feedback = "\n\nYour previous playbook was invalid:\n- " + "\n- ".join(errors[:12]) + "\nFix these."
            continue
        sim = simulate(PlaybookRunner(pb), theory, start_obs, objective.success, objective.horizon)
        if sim.get("success"):
            log.append("playbook.compiled", {"playbook": pb.model_dump(), "simulated": _summary(sim)})
            return PlaybookRunner(pb), pb
        score = _progress(sim, objective, start_obs)
        if best is None or score > best[0]:
            best = (score, pb)
        log.append("playbook.rejected", {"attempt": attempt, "playbook": pb.model_dump(),
                                         "errors": ["did not reach the goal in simulation"], "simulated": _summary(sim)})
        feedback = (
            f"\n\nYour previous playbook did not reach the goal within {objective.horizon} steps when simulated "
            f"in the learned theory (closeness to the goal at the end: {score:.2f} of 1). "
            f"Check which theory rules move the goal fields and drive those. Previous playbook: {json.dumps(raw)[:2000]}\n"
            f"Last steps of the simulation: {_trace_tail(sim)}\nRevise it."
        )
    if attempts:
        log.append("note", {"text": "falling back to planner"})
    planner = PlannerPolicy(theory, manual, objective)
    pb = planner.as_playbook_stub()
    sim = simulate(PlannerPolicy(theory, manual, objective), theory, start_obs, objective.success, objective.horizon)
    if not sim.get("success") and best is not None and best[0] > _progress(sim, objective, start_obs):
        # neither reaches the goal in the theory: keep whichever got closest
        log.append("note", {"text": "planner did no better in simulation; keeping the closest playbook"})
        bsim = simulate(PlaybookRunner(best[1]), theory, start_obs, objective.success, objective.horizon)
        log.append("playbook.compiled", {"playbook": best[1].model_dump(), "simulated": _summary(bsim)})
        return PlaybookRunner(best[1]), best[1]
    log.append("playbook.compiled", {"playbook": pb.model_dump(), "simulated": _summary(sim)})
    return planner, pb


def _progress(sim: dict[str, Any], objective: Objective, start: Observation) -> float:
    if sim.get("success"):
        return 1.0
    trace = sim.get("trace") or []
    if not trace:
        return 0.0
    last = Observation(t=start.t + len(trace), fields=trace[-1]["predicted"])
    try:
        return max(progress(objective.success, last, {}), 0.0)
    except Exception:
        return 0.0
