"""Prompt text for the Investigator. Compact, deterministic, JSON-lines experience."""
from __future__ import annotations

import json
from typing import Any

from logicscout.contracts import Hypothesis, Mismatch, Rule, Theory, WorldManual

SCIENTIST = (
    "You are a careful experimental scientist studying an unfamiliar system that has no manual of its laws. "
    "You only know the control panel (actions, observed fields) and the experiments run so far. "
    "Explain surprises with falsifiable, executable rules written in the LogicScout DSL. "
    "Every rule must make a concrete prediction that some experiment could contradict. "
    "Prefer simple rules; never claim certainty; never invent fields or actions that are not listed. "
    "Bool fields take True/False (not 1/0); match each field's listed type exactly. "
    "Answer with one JSON object only."
)

DESIGNER = (
    "You are an experimental scientist designing short, cheap experiments whose outcome differs depending on "
    "which rival rule is true. Use only the listed actions and argument ranges. Answer with one JSON object only."
)

RULE_SHAPE = (
    '{"statement": "plain words", "kind": "transition|precondition|constraint|delay|resource|periodic|other", '
    '"action": "<action name or *>", "when": "<DSL condition on obs/args/mem/t BEFORE the step>", '
    '"effects": {"<obs field>": "<DSL expr for its next value>"}, "memory": {"<mem var>": "<DSL expr>"}, '
    '"delay": 0, "replaces": "<existing rule id or null>"}'
)

RULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "statement": {"type": "string"},
        "kind": {"type": "string"},
        "action": {"type": "string"},
        "when": {"type": "string"},
        "effects": {"type": "object"},
        "memory": {"type": "object"},
        "delay": {"type": "integer"},
        "replaces": {"type": ["string", "null"]},
    },
    "required": ["statement", "action", "when", "effects"],
}

HYPOTHESIZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "rivals": {"type": "array", "items": RULE_SCHEMA}},
                "required": ["question", "rivals"],
            },
        },
        "memory": {"type": "object"},
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions"],
}

DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "probes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "purpose": {"type": "string"},
                    "seed": {"type": ["integer", "null"]},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "args": {"type": "object"}},
                            "required": ["name"],
                        },
                    },
                },
                "required": ["purpose", "actions"],
            },
        }
    },
    "required": ["probes"],
}

REVISE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rules": {"type": "array", "items": RULE_SCHEMA},
        "memory": {"type": "object"},
        "note": {"type": "string"},
    },
    "required": ["rules"],
}


def _j(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def manual_block(manual: WorldManual) -> str:
    lines = [f"SYSTEM: {manual.title} ({manual.domain}) - {manual.summary}", "ACTIONS:"]
    for a in manual.actions:
        params = [
            {k: v for k, v in p.model_dump().items() if v not in (None, "", [])} for p in a.params
        ]
        lines.append(_j({"name": a.name, "params": params, "description": a.description}))
    lines.append("OBSERVED FIELDS:")
    for f in manual.observations:
        lines.append(_j({"name": f.name, "type": f.type, "description": f.description}))
    lines.append("OBJECTIVES:")
    for o in manual.objectives:
        lines.append(_j({"id": o.id, "text": o.text, "success": o.success}))
    return "\n".join(lines)


def rule_line(r: Rule) -> str:
    d = {
        "id": r.id, "statement": r.statement, "action": r.action, "when": r.when, "effects": r.effects,
        "status": r.status, "confidence": round(r.confidence, 2),
    }
    if r.memory:
        d["memory"] = r.memory
    if r.delay:
        d["delay"] = r.delay
    return _j(d)


def theory_block(theory: Theory) -> str:
    lines = [f"CURRENT THEORY v{theory.version} (memory init {_j(theory.memory)}):"]
    lines += [rule_line(r) for r in theory.rules] or ["(no rules yet: prediction = nothing changes)"]
    if theory.unknowns:
        lines.append("OPEN UNKNOWNS: " + _j(theory.unknowns))
    return "\n".join(lines)


def surprise_line(t_before: int, fields_before: dict, action: dict, mism: list[Mismatch]) -> str:
    return _j({
        "t": t_before, "before": fields_before, "action": action,
        "wrong": [{"field": m.field, "predicted": m.predicted, "observed": m.observed} for m in mism],
    })


def priors_block(priors: list[Hypothesis]) -> str:
    if not priors:
        return ""
    lines = ["UNVERIFIED PRIOR KNOWLEDGE (public briefing / transferred from other systems; may be wrong here):"]
    for h in priors:
        lines.append(_j({"source": h.source, "claim": h.statement, "rule": rule_line(h.rule)}))
    return "\n".join(lines)


def hypothesize_user(manual: WorldManual, dsl_guide: str, theory: Theory, surprises: list[str],
                     recent: list[str], priors: list[Hypothesis], focus: list[Mismatch] | None,
                     tested: list[str]) -> str:
    parts = [manual_block(manual), "DSL:\n" + dsl_guide, theory_block(theory)]
    if focus:
        parts.append("RECENT LIVE MISMATCHES (the system may have changed):\n"
                     + "\n".join(_j(m.model_dump()) for m in focus))
    parts.append("SURPRISES (transitions the current theory mispredicted; explain these):\n"
                 + ("\n".join(surprises) or "(none - look for untested actions or conditions)"))
    if recent:
        parts.append("OTHER RECENT TRANSITIONS:\n" + "\n".join(recent))
    p = priors_block(priors)
    if p:
        parts.append(p)
    if tested:
        parts.append("ALREADY TESTED (do not repeat):\n" + "\n".join(tested))
    parts.append(
        "TASK: propose 1-3 questions. Each question has 2-3 RIVAL rules that explain the same surprise in "
        "different ways, so that some experiment would tell them apart. Each rival is one rule:\n" + RULE_SHAPE +
        "\nUse 'replaces' when a rival corrects an existing rule. Declare initial values for any new mem var in "
        '"memory". Reply: {"questions":[{"question":"...","rivals":[rule,...]}],"memory":{},"unknowns":["..."]}'
    )
    return "\n\n".join(parts)


def design_user(manual: WorldManual, questions: list[dict], start: dict, seeds: list[int],
                lab_seeds: tuple[int, int]) -> str:
    return "\n\n".join([
        manual_block(manual),
        "QUESTIONS AND RIVAL RULES:\n" + "\n".join(_j(q) for q in questions),
        "CURRENT STATE (seed=null continues from here): " + _j(start),
        f"Lab seeds allowed: {lab_seeds[0]}..{lab_seeds[1] - 1}; already seen start states for seeds {seeds}.",
        "TASK: propose 3 different probes, each at most 8 actions, whose observations would differ depending on "
        "which rival is true (make each rival's condition true, then watch its effect fields). "
        'Reply: {"probes":[{"purpose":"what it distinguishes","seed":null,"actions":[{"name":"...","args":{}}]}]}',
    ])


def revise_user(manual: WorldManual, dsl_guide: str, theory: Theory, residuals: list[str], accuracy: float) -> str:
    return "\n\n".join([
        manual_block(manual), "DSL:\n" + dsl_guide, theory_block(theory),
        f"Measured prediction accuracy on all experience: {accuracy:.3f}.",
        "TOP RESIDUAL MISPREDICTIONS:\n" + "\n".join(residuals),
        "TASK: return a corrected FULL rule list that keeps what works and fixes these errors. Keep the \"id\" of rules you "
        "keep or edit; omit \"id\" for new rules. Each rule:\n"
        + RULE_SHAPE + '\nReply: {"rules":[...],"memory":{},"note":"what you changed, plain words"}',
    ])
