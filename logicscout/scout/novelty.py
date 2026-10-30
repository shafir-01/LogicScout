"""Exploration that does not depend on rivals disagreeing.

Disagreement-based probe design has a blind spot: if every rival rule is wrong in the same way, they all
predict the same thing and no experiment looks informative, so the missing mechanism is never tested.
This module proposes experiments chosen from the scout's own experience instead:

1. residual probes: controls whose (control, reading, context) cells the current theory gets wrong most
   often, or that have barely been tried (count-based novelty over discretised readings x controls);
2. falsification probes: sequences that push the system somewhere it has never been (extreme arguments,
   long repeats, alternating controls), testing the whole family of rules at once;
3. delay probes: use a control once, then wait k steps, to expose effects that arrive late.

Each candidate is scored by its expected surprise under the current theory: the theory is rolled forward
over the plan and each step is charged the estimated chance that the theory mispredicts each reading
there (Laplace-smoothed error rate of that cell; an unseen cell counts as a coin flip), plus a bonus for
(previous control, control) pairs and (control, wait length) gaps never seen. Everything is code; no model.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from logicscout.contracts import Action, Observation, Theory, WorldManual
from logicscout.theory import Predictor, Transition, _eq, _replay

ENABLED = True  # module switch (offline evaluation compares with and without)
RESERVE_EVERY = 4  # every Nth designed probe is a novelty probe even when rivals disagree
MAX_ACTIONS = 8
IDLE_NAMES = ("wait", "idle", "noop", "hold", "coast", "pass", "status")
_BINS = 4


# ---- discretisation ----------------------------------------------------------------------------

def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def _edges(transitions: list[Transition]) -> dict[str, list[float]]:
    """Per numeric reading: quantile edges over every value seen so far."""
    vals: dict[str, list[float]] = defaultdict(list)
    for b, _, a in transitions:
        for obs in (b, a):
            for k, v in obs.fields.items():
                if k != "t" and _num(v):
                    vals[k].append(float(v))
    out = {}
    for k, xs in vals.items():
        xs.sort()
        out[k] = sorted({xs[min(len(xs) - 1, int(len(xs) * q / _BINS))] for q in range(1, _BINS)})
    return out


def _bin(field: str, v: Any, edges: dict[str, list[float]]) -> Any:
    if _num(v):
        e = edges.get(field)
        if e is None:
            return "num?"
        lo = min(e) if e else float(v)
        hi = max(e) if e else float(v)
        if float(v) < lo - (abs(lo) + 1):  # far below anything seen
            return "below"
        if float(v) > hi + (abs(hi) + 1):  # far above anything seen
            return "above"
        return sum(float(v) >= x for x in e)
    if isinstance(v, (list, tuple, dict)):
        return f"len{min(len(v), 6)}"
    if isinstance(v, str):
        return v[:24]
    return v


def sig(a: Action) -> str:
    """Control plus its choice/bool arguments; numbers bucketed to low/high so extremes count as new."""
    parts = []
    for k, v in sorted(a.args.items()):
        if isinstance(v, (str, bool)):
            parts.append(f"{k}={v}")
    return a.name + (f"({','.join(parts)})" if parts else "")


def _arg_sig(a: Action, manual: WorldManual) -> str:
    spec = next((s for s in manual.actions if s.name == a.name), None)
    parts = [sig(a)]
    for p in (spec.params if spec else []):
        v = a.args.get(p.name)
        if _num(v) and p.min is not None and p.max is not None and p.max > p.min:
            r = (float(v) - p.min) / (p.max - p.min)
            parts.append(f"{p.name}:{'lo' if r < 0.2 else 'hi' if r > 0.8 else 'mid'}")
    return "|".join(parts)


# ---- residual statistics -----------------------------------------------------------------------

class Stats:
    """Counts and theory errors per (control, reading, context bin), plus sequence/gap coverage."""

    def __init__(self, theory: Theory, transitions: list[Transition], manual: WorldManual) -> None:
        self.manual = manual
        self.edges = _edges(transitions)
        self.n: dict[tuple, int] = defaultdict(int)
        self.err: dict[tuple, int] = defaultdict(int)
        self.pairs: dict[tuple[str, str], int] = defaultdict(int)
        self.gaps: dict[tuple[str, int], int] = defaultdict(int)
        self.fields = sorted({k for _, _, a in transitions for k in a.fields if k != "t"})
        preds: list[dict | None]
        try:
            preds = [p for _, p, _ in _replay(theory, transitions)]
        except Exception:
            preds = [None] * len(transitions)
        prev_sig, last_active, since = None, None, 0
        prev_after = None
        for (b, a, o), p in zip(transitions, preds):
            s = _arg_sig(a, manual)
            if prev_after is None or b.t != prev_after.t:
                prev_sig, last_active, since = None, None, 0
            for f in self.fields:
                key = (s, f, _bin(f, b.fields.get(f), self.edges))
                self.n[key] += 1
                if p is None or not _eq(p.get(f), o.fields.get(f)):
                    self.err[key] += 1
            self.pairs[(prev_sig, s)] += 1
            if is_idle(a, manual):
                since += 1
                if last_active is not None:
                    self.gaps[(last_active, min(since, 8))] += 1
            else:
                last_active, since = s, 0
            prev_sig, prev_after = s, o

    def p_err(self, key: tuple) -> float:
        return (self.err.get(key, 0) + 1) / (self.n.get(key, 0) + 2)


def is_idle(a: Action, manual: WorldManual) -> bool:
    return a.name in IDLE_NAMES and not a.args


def idle_action(manual: WorldManual, stats: Stats | None = None) -> Action | None:
    for spec in manual.actions:
        if spec.name in IDLE_NAMES and not spec.params:
            return Action(name=spec.name)
    return None


# ---- scoring -----------------------------------------------------------------------------------

def expected_surprise(theory: Theory, stats: Stats, start: Observation, actions: list[Action]) -> float:
    """Mean expected surprise per step of running `actions` from `start` under `theory`."""
    if not actions:
        return 0.0
    n = defaultdict(int)  # virtual visits within this plan: repeating the same unknown pays less each time
    pairs = defaultdict(int)
    gaps = defaultdict(int)
    try:
        pred = Predictor(theory)
        pred.reset(start)
    except Exception:
        pred = None
    obs = start
    prev_sig = None
    last_active, since = None, 0
    total = 0.0
    nf = max(1, len(stats.fields))
    for a in actions:
        s = _arg_sig(a, stats.manual)
        step = 0.0
        for f in stats.fields:
            key = (s, f, _bin(f, obs.fields.get(f), stats.edges))
            seen = stats.n.get(key, 0) + n[key]
            step += stats.p_err(key) * (1.0 / math.sqrt(1 + n[key])) if seen else 0.5
            n[key] += 1
        step /= nf
        pk = (prev_sig, s)
        step += 0.25 / math.sqrt(1 + stats.pairs.get(pk, 0) + pairs[pk])
        pairs[pk] += 1
        if is_idle(a, stats.manual):
            since += 1
            if last_active is not None:
                gk = (last_active, min(since, 8))
                step += 0.25 / math.sqrt(1 + stats.gaps.get(gk, 0) + gaps[gk])
                gaps[gk] += 1
        else:
            last_active, since = s, 0
        total += step
        prev_sig = s
        try:
            fields = pred.predict(obs, a) if pred else dict(obs.fields)
            fields = {k: v for k, v in fields.items() if k != "t"}
            nxt = Observation(t=obs.t + 1, fields=fields)
            if pred:
                pred.advance(nxt)
        except Exception:
            nxt = Observation(t=obs.t + 1, fields=dict(obs.fields))
        obs = nxt
    return total / len(actions)


# ---- candidate generation ----------------------------------------------------------------------

def _variants(manual: WorldManual) -> list[tuple[Action, str]]:
    """Every control at its extreme / every choice argument, with a plain description."""
    out: list[tuple[Action, str]] = []
    for spec in manual.actions:
        combos: list[tuple[dict, list[str]]] = [({}, [])]
        for p in spec.params:
            if p.choices:
                vals = [(c, f"{p.name}={c}") for c in p.choices[:4]]
            elif p.type == "bool":
                vals = [(True, f"{p.name} on"), (False, f"{p.name} off")]
            elif p.type in ("int", "float"):
                lo = p.min if p.min is not None else 0
                hi = p.max if p.max is not None else lo + 10
                cast = int if p.type == "int" else float
                vals = [(cast(hi), f"{p.name} at its maximum {cast(hi)}"), (cast(lo), f"{p.name} at its minimum {cast(lo)}")]
            else:
                vals = [("", "")]
            combos = [({**c, p.name: v}, d + ([t] if t else [])) for c, d in combos for v, t in vals][:8]
        for args, desc in combos:
            out.append((Action(name=spec.name, args=args), spec.name + (f" ({', '.join(desc)})" if desc else "")))
    return out


def _candidates(manual: WorldManual, stats: Stats) -> list[dict]:
    variants = _variants(manual)
    idle = idle_action(manual)
    active = [(a, d) for a, d in variants if not is_idle(a, manual)]
    out: list[dict] = []
    # 1. residual: controls whose cells are most often mispredicted or least tried
    by_sig: dict[str, list[float]] = defaultdict(list)
    for (s, f, _), cnt in stats.n.items():
        by_sig[s].append(stats.p_err((s, f, _)))
    for a, d in variants:
        s = _arg_sig(a, manual)
        tried = sum(c for (s2, _, _), c in stats.n.items() if s2 == s) // max(1, len(stats.fields))
        worst = max(by_sig.get(s, [0.5]))
        why = (f"it has only been tried {tried} time{'s' if tried != 1 else ''}" if tried < 3
               else f"the current theory still gets {round(100 * worst)}% of its readings wrong in some situations")
        out.append({"kind": "residual", "actions": [a] * 3,
                    "purpose": f"Try something it has never done: use {d} 3 times, because {why}"})
        if idle is not None:
            out.append({"kind": "residual", "actions": [a, idle, a, idle],
                        "purpose": f"Try something it has never done: use {d}, pause, and use it again, because {why}"})
    # 2. falsification: long repeats at extremes, alternating pairs
    for a, d in active:
        out.append({"kind": "falsify", "actions": [a] * MAX_ACTIONS,
                    "purpose": f"Try something it has never done: use {d} {MAX_ACTIONS} times in a row to push "
                               "the system somewhere it has never been"})
    for i, (a, da) in enumerate(active):
        for b, db in active[i + 1:]:
            if a.name == b.name and a.args == b.args:
                continue
            out.append({"kind": "falsify", "actions": [a, b] * (MAX_ACTIONS // 2),
                        "purpose": f"Try something it has never done: alternate {da} and {db} to look for "
                                   "interactions no current rule describes"})
    # 3. delay: act once, then wait k steps
    if idle is not None:
        for a, d in active:
            for k in (3, 5, 7):
                out.append({"kind": "delay", "actions": [a] + [idle] * k,
                            "purpose": f"Try something it has never done: use {d} once, then wait {k} steps to "
                                       "catch effects that arrive late"})
    return out


def novelty_probes(theory: Theory, transitions: list[Transition], manual: WorldManual, start_obs: Observation,
                   n: int = 3, max_actions: int = MAX_ACTIONS) -> list[dict]:
    """Top-`n` probes by expected surprise under `theory`, independent of any rival disagreement.

    Returns dicts {purpose, actions, seed, kind, surprise}; seed None means "continue from start_obs"."""
    if not manual.actions:
        return []
    stats = Stats(theory, transitions, manual)
    scored = []
    for c in _candidates(manual, stats):
        acts = c["actions"][:max_actions]
        if not acts:
            continue
        s = expected_surprise(theory, stats, start_obs, acts)
        scored.append((s, c["kind"], c["purpose"], acts))
    scored.sort(key=lambda x: -x[0])
    out, kinds_seen, purposes = [], set(), set()
    # keep variety: best of each kind first, then the rest by score
    for pass_ in (0, 1):
        for s, kind, purpose, acts in scored:
            if len(out) >= n:
                break
            if purpose in purposes or (pass_ == 0 and kind in kinds_seen):
                continue
            out.append({"purpose": purpose, "actions": acts, "seed": None, "kind": kind, "surprise": round(s, 4)})
            kinds_seen.add(kind)
            purposes.add(purpose)
    out.sort(key=lambda d: -d["surprise"])
    return out


# ---- investigator hook -------------------------------------------------------------------------

def merge(inv: Any, theory: Theory, groups: list[dict], cands: list[dict]) -> list[dict]:
    """Add novelty probes to the investigator's candidate pool.

    Rival disagreement cannot see a mechanism every rival misses, so a share of the budget is reserved:
    when no rivals are open, and on every RESERVE_EVERY-th design otherwise, the pool is the novelty probes
    alone (they still pass the investigator's safety filter); in between they just compete."""
    if not ENABLED:
        return cands
    try:
        start = inv.port.observe()
        found = novelty_probes(theory, inv.transitions, inv.manual, start, n=3)
    except Exception as e:  # exploration must never break the loop
        inv.log.append("error", {"message": f"novelty probes skipped: {e}"})
        return cands
    if not found:
        return cands
    inv._novelty_n = getattr(inv, "_novelty_n", 0) + 1
    picked = [{"purpose": c["purpose"], "seed": c["seed"], "actions": list(c["actions"])} for c in found]
    if not groups:
        return picked  # nothing to discriminate: novelty only (still safety-filtered)
    if inv._novelty_n % RESERVE_EVERY == 0:
        return [c for c in cands if c.get("model")] + picked  # keep paid-for model designs, drop the rest
    return cands + picked
