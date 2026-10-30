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
from logicscout.planner import PlannerPolicy
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
        "(write literal numbers as plain expressions, e.g. \"3\").",
        f"System: {manual.title} ({manual.domain}). {manual.summary}",
        "Actions: " + json.dumps([a.model_dump() for a in manual.actions]),
        "Observed fields: " + json.dumps([f.model_dump() for f in manual.observations]),
        "Learned theory:\n" + _theory_text(theory),
        f"Goal: {objective.text}. Success condition: {objective.success}. Horizon: {objective.horizon} steps.",
        "A typical starting observation: " + json.dumps(start.fields),
        "Return JSON shaped like: " + SHAPE,
    ])


def _to_playbook(raw: dict[str, Any], theory: Theory, objective: Objective) -> Playbook:
    rules = []
    for r in raw.get("rules", []):
        do = r.get("do", {})
        rules.append({"when": str(r.get("when", "True")), "why": str(r.get("why", "")),
                      "do": {"name": do.get("name", ""), "args": {k: str(v) for k, v in (do.get("args") or {}).items()}}})
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
        "fallback": {"name": fb.get("name", ""), "args": {k: str(v) for k, v in (fb.get("args") or {}).items()}},
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
):
    """Return (policy, playbook). The playbook is checked by simulation inside the learned theory."""
    user = build_prompt(theory, manual, objective, start_obs)
    feedback = ""
    for attempt in range(RETRIES + 1):
        try:
            raw = await llm.json("synthesize_playbook", SYSTEM, user + feedback, schema=PLAYBOOK_SCHEMA, tier="deep")
            pb = _to_playbook(raw, theory, objective)
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
        log.append("playbook.rejected", {"attempt": attempt, "playbook": pb.model_dump(),
                                         "errors": ["did not reach the goal in simulation"], "simulated": _summary(sim)})
        feedback = (
            f"\n\nYour previous playbook did not reach the goal within {objective.horizon} steps when simulated "
            f"in the learned theory. Previous playbook: {json.dumps(raw)[:2000]}\n"
            f"Last steps of the simulation: {_trace_tail(sim)}\nRevise it."
        )
    log.append("note", {"text": "falling back to planner"})
    planner = PlannerPolicy(theory, manual, objective)
    pb = planner.as_playbook_stub()
    sim = simulate(PlannerPolicy(theory, manual, objective), theory, start_obs, objective.success, objective.horizon)
    log.append("playbook.compiled", {"playbook": pb.model_dump(), "simulated": _summary(sim)})
    return planner, pb
