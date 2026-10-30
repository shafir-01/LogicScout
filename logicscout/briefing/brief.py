"""Public knowledge as priors: Tavily sources -> attributed, formal, testable hypotheses.

Queries come only from manual.briefing_topics. Search results are never ground truth:
each claim becomes a tentative Rule that probes must confirm or overturn.
"""
from __future__ import annotations

import json
import re
from typing import Any

from logicscout.briefing.tavily import Source, TavilyClient
from logicscout.contracts import LLM, Hypothesis, Rule, Theory, WorldManual
from logicscout.logbook import Logbook

MAX_TOPICS = 3
MAX_CLAIMS = 5
SNIPPET_CHARS = 600

SYSTEM = (
    "You turn public documentation excerpts about a KIND of system into formal, testable prior hypotheses "
    "about one specific unfamiliar system. Excerpts are claims by third parties, not facts about this system. "
    "Only propose a claim if an excerpt supports it AND you can express it as a rule over the given actions and "
    "fields. Reply with JSON only."
)

_FALLBACK_GUIDE = (
    "Expressions: obs.<field>, args.<param>, mem.<var>, t, literals, + - * /, comparisons, "
    "and/or/not, x if c else y, min/max/abs/round/len, in."
)


def _dsl_guide() -> str:
    try:
        from logicscout.dsl import DSL_GUIDE
    except ImportError:
        return _FALLBACK_GUIDE
    return DSL_GUIDE


def _validate(expr: str) -> list[str]:
    try:
        from logicscout.dsl import validate
    except ImportError:
        return []
    return validate(expr)


def _rule_errors(rule: Rule, manual: WorldManual) -> list[str]:
    errs: list[str] = []
    actions = {a.name for a in manual.actions}
    fields = {f.name for f in manual.observations}
    if rule.action != "*" and rule.action not in actions:
        errs.append(f"unknown action {rule.action}")
    errs += [f"unknown field {f}" for f in rule.effects if f not in fields]
    for e in [rule.when, *rule.effects.values(), *rule.memory.values()]:
        errs += _validate(e)
    if not rule.effects and not rule.memory:
        errs.append("rule has no effects")
    return errs


def _describe(manual: WorldManual) -> str:
    acts = [
        {"name": a.name, "description": a.description,
         "params": [{"name": p.name, "type": p.type, "min": p.min, "max": p.max, "choices": p.choices} for p in a.params]}
        for a in manual.actions
    ]
    flds = [{"name": f.name, "type": f.type, "description": f.description} for f in manual.observations]
    return json.dumps({"actions": acts, "fields": flds}, indent=1)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:24] or "claim"


async def brief(
    manual: WorldManual, llm: LLM, log: Logbook, max_sources: int = 6, client: TavilyClient | None = None
) -> list[Hypothesis]:
    own = client is None
    client = client or TavilyClient()
    sources: list[Source] = []
    seen: set[str] = set()
    try:
        topics = manual.briefing_topics[:MAX_TOPICS]
        per = max(2, -(-max_sources // max(1, len(topics))))
        for q in topics:
            log.append("briefing.query", {"query": q})
            for s in await client.search(q, max_results=per):
                if s.url in seen or len(sources) >= max_sources:
                    continue
                seen.add(s.url)
                sources.append(s)
                log.append("briefing.source", {"url": s.url, "title": s.title, "published": s.published_date})
    finally:
        if own:
            await client.aclose()
    if not sources:
        log.append("note", {"text": "briefing: no public sources found; proceeding without priors"})
        return []

    numbered = "\n\n".join(f"[{i}] {s.title} ({s.url})\n{s.content[:SNIPPET_CHARS]}" for i, s in enumerate(sources, 1))
    user = (
        f"System kind: {manual.domain}. Title: {manual.title}.\n\nThis system's interface:\n{_describe(manual)}\n\n"
        f"Rule expression language:\n{_dsl_guide()}\n\nPublic excerpts:\n{numbered}\n\n"
        f"Propose at most {MAX_CLAIMS} claims. JSON: "
        '{"claims": [{"claim": plain-language statement, "sources": [excerpt numbers], '
        '"rule": {"kind": "transition|precondition|constraint|delay|resource|periodic|other", '
        '"action": action name or "*", "when": DSL condition, "effects": {field: DSL expr for its next value}, '
        '"memory": {var: DSL expr}, "delay": int}}]}. Use only the listed actions and fields.'
    )
    out: dict[str, Any] = await llm.json("briefing_priors", SYSTEM, user, tier="fast")

    hyps: list[Hypothesis] = []
    for i, c in enumerate((out.get("claims") or [])[:MAX_CLAIMS], 1):
        try:
            r = dict(c["rule"])
            cites = [sources[int(n) - 1].url for n in c.get("sources", []) if 0 < int(n) <= len(sources)]
            if not cites:
                continue
            hid = f"brief_{i}_{_slug(c['claim'])}"
            rule = Rule(
                id=hid, statement=c["claim"], kind=r.get("kind", "transition"), action=r.get("action", "*"),
                when=r.get("when") or "True", effects=r.get("effects") or {}, memory=r.get("memory") or {},
                delay=int(r.get("delay") or 0), status="tentative", confidence=0.4, source="briefing",
                citations=list(dict.fromkeys(cites)),
            )
        except (KeyError, TypeError, ValueError):
            continue
        errs = _rule_errors(rule, manual)
        if errs:
            log.append("note", {"text": f"briefing: dropped claim {hid}: {'; '.join(errs[:2])}"})
            continue
        h = Hypothesis(id=hid, statement=c["claim"], rule=rule, source="briefing")
        hyps.append(h)
        log.append("briefing.claim", {"hypothesis": h.model_dump(), "citations": rule.citations})
    return hyps


def check(hyps: list[Hypothesis], theory: Theory) -> list[dict[str, Any]]:
    """Did experiments confirm or overturn each public-knowledge prior?"""
    rules = {r.id: r for r in theory.rules}
    out = []
    for h in hyps:
        state = h.status
        r = rules.get(h.rule.id)
        if state == "open" and r is not None and r.status in ("supported", "refuted"):
            state = r.status
        status = {"supported": "confirmed", "refuted": "contradicted"}.get(state, "untested")
        out.append({"claim": h.statement, "status": status, "citations": h.rule.citations, "rule_id": h.rule.id})
    return out
