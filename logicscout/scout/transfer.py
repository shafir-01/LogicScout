"""Mechanism library: abstract lessons from past worlds, offered as tentative priors in new ones.

Only supported rules are abstracted, and only into domain-free mechanisms (no field or action names).
Mapping a mechanism onto a new world is a guess the scout still has to test: priors are tentative
hypotheses with source="transfer".
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from logicscout.contracts import LLM, Hypothesis, Rule, Theory, WorldManual
from logicscout.dsl import DSL_GUIDE, validate

ABSTRACT_SYSTEM = (
    "You distil experimental findings about one system into reusable, domain-free mechanisms, such as "
    "'delayed effect', 'thermal-style lockout after threshold', 'periodic availability window', 'hidden "
    "depleting resource', 'ordering precondition'. A mechanism signature describes the abstract causal "
    "pattern only: never mention the system's field names, action names, units or domain. Answer with one "
    "JSON object only."
)
MAP_SYSTEM = (
    "You map abstract mechanisms learned in other systems onto a new system's control panel as tentative, "
    "testable rules in the LogicScout DSL. Use only the new system's listed fields and actions. Propose a "
    "mapping only where the mechanism plausibly applies; an empty list is a fine answer. Answer with one JSON object only."
)
ABSTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"mechanisms": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "signature": {"type": "string"}},
        "required": ["name", "signature"],
    }}},
    "required": ["mechanisms"],
}
MAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"hypotheses": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "mechanism": {"type": "string"}, "statement": {"type": "string"}, "kind": {"type": "string"},
            "action": {"type": "string"}, "when": {"type": "string"}, "effects": {"type": "object"},
            "memory": {"type": "object"}, "delay": {"type": "integer"},
        },
        "required": ["mechanism", "statement", "action", "when", "effects"],
    }}},
    "required": ["hypotheses"],
}
KINDS = {"transition", "precondition", "constraint", "delay", "resource", "periodic", "other"}


def _names(manual: WorldManual) -> set[str]:
    out = {a.name for a in manual.actions} | {f.name for f in manual.observations}
    out |= {p.name for a in manual.actions for p in a.params}
    return {n for n in out if len(n) > 2}


def _mentions(text: str, names: set[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(n.lower())}\b", low) for n in names)


def _obs_refs(expr: str) -> set[str]:
    return set(re.findall(r"\bobs\.([A-Za-z_]\w*)", expr)) | set(re.findall(r"\bobs\[['\"](\w+)['\"]\]", expr))


class MechanismLibrary:
    def __init__(self, path: Path) -> None:
        self.dir = Path(path)
        self.file = self.dir / "mechanisms.json"

    def load(self) -> list[dict[str, Any]]:
        if not self.file.exists():
            return []
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def save(self, mechanisms: list[dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(mechanisms, indent=1), encoding="utf-8")

    async def learn(self, llm: LLM, theory: Theory, manual: WorldManual) -> list[dict[str, Any]]:
        """Abstract supported rules into mechanisms and persist them. Returns the newly stored ones."""
        supported = [r for r in theory.rules if r.status == "supported"]
        if not supported:
            return []
        user = "Supported findings:\n" + json.dumps(
            [r.model_dump(include={"statement", "kind", "action", "when", "effects", "memory", "delay"}) for r in supported],
            indent=1,
        ) + '\n\nReturn {"mechanisms": [{"name": "...", "signature": "abstract causal pattern"}]}'
        raw = await llm.json("abstract_mechanisms", ABSTRACT_SYSTEM, user, schema=ABSTRACT_SCHEMA, tier="fast")
        names = _names(manual)
        library = self.load()
        known = {m["name"].strip().lower(): m for m in library}
        added = []
        for m in raw.get("mechanisms", []):
            name, sig = str(m.get("name", "")).strip(), str(m.get("signature", "")).strip()
            if not name or not sig or _mentions(name + " " + sig, names):
                continue  # domain-specific: not a transferable mechanism
            entry = known.get(name.lower())
            if entry:
                if manual.world_id not in entry["evidence"]:
                    entry["evidence"].append(manual.world_id)
                continue
            entry = {"name": name, "signature": sig, "evidence": [manual.world_id], "learned_at": time.time()}
            library.append(entry)
            known[name.lower()] = entry
            added.append(entry)
        self.save(library)
        return added

    async def priors(self, llm: LLM, manual: WorldManual) -> list[Hypothesis]:
        """Map stored mechanisms onto a new manual as tentative hypotheses. Empty library -> []."""
        library = self.load()
        if not library:
            return []
        mechs = [{"name": m["name"], "signature": m["signature"]} for m in library]
        user = "\n\n".join([
            DSL_GUIDE,
            f"New system: {manual.title} ({manual.domain}). {manual.summary}",
            "Actions: " + json.dumps([a.model_dump() for a in manual.actions]),
            "Observed fields: " + json.dumps([f.model_dump() for f in manual.observations]),
            "Mechanisms seen in other systems: " + json.dumps(mechs),
            'Return {"hypotheses": [{"mechanism": "<name>", "statement": "...", "kind": "...", "action": "<action or *>", '
            '"when": "<DSL>", "effects": {"<field>": "<DSL>"}, "memory": {}, "delay": 0}]}',
        ])
        raw = await llm.json("transfer_priors", MAP_SYSTEM, user, schema=MAP_SCHEMA, tier="fast")
        fields = {f.name for f in manual.observations}
        actions = {a.name for a in manual.actions} | {"*"}
        out: list[Hypothesis] = []
        for h in raw.get("hypotheses", []):
            try:
                rule = Rule(
                    id=f"tr-{uuid.uuid4().hex[:6]}", statement=str(h["statement"]),
                    kind=h.get("kind") if h.get("kind") in KINDS else "other",
                    action=str(h.get("action", "*")), when=str(h.get("when", "True")),
                    effects={str(k): str(v) for k, v in (h.get("effects") or {}).items()},
                    memory={str(k): str(v) for k, v in (h.get("memory") or {}).items()},
                    delay=max(0, int(h.get("delay") or 0)), confidence=0.3, source="transfer",
                )
            except (KeyError, TypeError, ValueError):
                continue
            exprs = [rule.when, *rule.effects.values(), *rule.memory.values()]
            if rule.action not in actions or not set(rule.effects) <= fields:
                continue
            if any(validate(e) for e in exprs) or any(not _obs_refs(e) <= fields for e in exprs):
                continue
            out.append(Hypothesis(id=f"h-{rule.id}", statement=f"[{h.get('mechanism', '')}] {rule.statement}",
                                  rule=rule, source="transfer"))
        return out
