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
from logicscout.theory import Predictor, Transition, _eq
from logicscout.logbook import Logbook

MAX_TOPICS = 3
MAX_CLAIMS = 5
SNIPPET_CHARS = 900
QUOTE_CHARS = 200
EXCLUDE_DOMAINS = [
    "merriam-webster.com", "dictionary.com", "wiktionary.org", "collinsdictionary.com",
    "thefreedictionary.com", "vocabulary.com", "dictionary.cambridge.org", "oxfordlearnersdictionaries.com",
]
_DICT_TITLE = re.compile(r"\b(definition|meaning|dictionary|synonyms?)\b", re.I)
_META: dict[str, dict[str, Any]] = {}  # rule id -> {citations: [{url, title, published_date}], evidence: quote}

SYSTEM = (
    "You turn public documentation excerpts about a KIND of system into formal, testable prior hypotheses "
    "about one specific unfamiliar system. Excerpts are claims by third parties, not facts about this system. "
    "Only propose a claim if an excerpt supports it AND you can express it as a rule over the given actions and "
    "fields. Prefer operational norms an operator would assume (sequencing, warm-up, capacity/overflow, "
    "ordering, limits) over restating the interface. Every claim must quote verbatim the excerpt sentence it rests "
    "on, and that sentence must by itself state the norm (not just mention the topic); never propose a claim the "
    "excerpts do not state. Fewer claims, even zero, beat weakly supported ones. Reply with JSON only."
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


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _quote_in(quote: str, srcs: list[Source]) -> bool:
    q = _norm(quote).strip(" .\"'")
    return len(q) >= 12 and any(q in _norm(s.content) for s in srcs)


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
            found = await client.search(
                q, max_results=per + 1, search_depth="advanced", exclude_domains=EXCLUDE_DOMAINS)
            taken = 0
            for s in found:
                if s.url in seen or len(sources) >= max_sources or taken >= per or _DICT_TITLE.search(s.title):
                    continue
                seen.add(s.url)
                sources.append(s)
                taken += 1
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
        f'"quote": exact sentence copied verbatim from one cited excerpt (<= {QUOTE_CHARS} chars), '
        '"rule": {"kind": "transition|precondition|constraint|delay|resource|periodic|other", '
        '"action": action name or "*", "when": DSL condition, "effects": {field: DSL expr for its next value}, '
        '"memory": {var: DSL expr}, "delay": int}}]}. Use only the listed actions and fields. '
        "A precondition claim (X needs Y first) is a rule whose `when` is the violated condition and whose effects "
        "say what does NOT change (field keeps its obs value) or which fault appears."
    )
    out: dict[str, Any] = await llm.json("briefing_priors", SYSTEM, user, tier="fast")

    hyps: list[Hypothesis] = []
    for i, c in enumerate((out.get("claims") or [])[:MAX_CLAIMS], 1):
        try:
            r = dict(c["rule"])
            idx = list(dict.fromkeys(int(n) for n in c.get("sources", []) if 0 < int(n) <= len(sources)))
            cited = [sources[n - 1] for n in idx]
            hid = f"brief_{i}_{_slug(c['claim'])}"
            quote = str(c.get("quote") or "").strip()[:QUOTE_CHARS]
            if not cited:
                log.append("note", {"text": f"briefing: dropped claim {hid}: no valid source"})
                continue
            if not _quote_in(quote, cited):
                log.append("note", {"text": f"briefing: dropped claim {hid}: quote not found in cited sources"})
                continue
            rule = Rule(
                id=hid, statement=c["claim"], kind=r.get("kind", "transition"), action=r.get("action", "*"),
                when=r.get("when") or "True", effects=r.get("effects") or {}, memory=r.get("memory") or {},
                delay=int(r.get("delay") or 0), status="tentative", confidence=0.4, source="briefing",
                citations=[s.url for s in cited],
            )
        except (KeyError, TypeError, ValueError):
            continue
        errs = _rule_errors(rule, manual)
        if errs:
            log.append("note", {"text": f"briefing: dropped claim {hid}: {'; '.join(errs[:2])}"})
            continue
        cites = [{"url": s.url, "title": s.title, "published_date": s.published_date} for s in cited]
        _META[hid] = {"citations": cites, "evidence": quote}
        h = Hypothesis(id=hid, statement=c["claim"], rule=rule, source="briefing")
        hyps.append(h)
        log.append("briefing.claim", {"hypothesis": h.model_dump(), "citations": cites, "evidence": quote})
    return hyps


def _cites(h: Hypothesis) -> list[dict[str, Any]]:
    meta = _META.get(h.rule.id, {}).get("citations")
    return meta or [{"url": u, "title": "", "published_date": None} for u in h.rule.citations]


def _row(h: Hypothesis, status: str, **extra: Any) -> dict[str, Any]:
    return {"claim": h.statement, "status": status, "citations": _cites(h),
            "evidence": _META.get(h.rule.id, {}).get("evidence", ""), "rule_id": h.rule.id, **extra}


def assess(hyps: list[Hypothesis], transitions: list[Transition]) -> list[dict[str, Any]]:
    """Score each public claim against real experience: run only its rule, on steps where it fires."""
    out = []
    for h in hyps:
        rule = h.rule.model_copy(update={"status": "tentative", "delay": 0})
        p = Predictor(Theory(world_id="briefing", rules=[rule]))
        fired = agree = total = 0
        counter = ""
        for prev, act, nxt in transitions:
            p.reset(prev)
            pred = p.predict(prev, act)
            if rule.id not in p.fired:
                continue
            fired += 1
            for f in rule.effects:
                if f not in nxt.fields:
                    continue
                total += 1
                if _eq(pred.get(f), nxt.fields[f]):
                    agree += 1
                elif not counter:
                    args = f" {act.args}" if act.args else ""
                    counter = (f"public docs predict {f}={pred.get(f)!r}; observed {f}={nxt.fields[f]!r} "
                               f"at t={prev.t} after {act.name}{args}")
        rate = agree / total if total else 0.0
        if fired >= 2 and total and rate >= 0.9:
            status = "confirmed"
        elif fired and total and rate < 0.5:
            status = "contradicted"
        else:
            status = "untested"
        extra: dict[str, Any] = {"fired": fired, "agreement": round(rate, 3)}
        if status == "contradicted":
            extra["counterexample"] = counter
        out.append(_row(h, status, **extra))
    return out


def check(hyps: list[Hypothesis], theory: Theory, transitions: list[Transition] | None = None) -> list[dict[str, Any]]:
    """Did experiments confirm or overturn each public-knowledge prior? Prefers data (assess) when given."""
    if transitions:
        return assess(hyps, transitions)
    rules = {r.id: r for r in theory.rules}
    out = []
    for h in hyps:
        state = h.status
        r = rules.get(h.rule.id)
        if state == "open" and r is not None and r.status in ("supported", "refuted"):
            state = r.status
        out.append(_row(h, {"supported": "confirmed", "refuted": "contradicted"}.get(state, "untested")))
    return out
