"""Uncertainty that survives into control: the set of theories still consistent with experience.

When a rival rule predicts everything seen so far as well as the rule the theory adopted, the scout has
not identified which one is true. Instead of acting on one best guess, control keeps every such variant
and plans against all of them (see planner.RobustPlannerPolicy).
"""
from __future__ import annotations

import json
from typing import Any

from logicscout.contracts import Action, Hypothesis, Observation, Theory
from logicscout.theory import Predictor, Transition, _eq, accuracy

LIVE = ("open", "supported")
MARGIN = 0.01  # accuracy gap on recent experience still treated as "behaviourally equivalent so far"
WINDOW = 80  # recent transitions used to judge equivalence


def _sig(t: Theory) -> str:
    return json.dumps([r.model_dump(include={"action", "when", "effects", "memory", "delay"})
                       for r in t.rules if r.status in ("tentative", "supported")], sort_keys=True, default=str)


def _variant(theory: Theory, h: Hypothesis, targets: list[str]) -> Theory:
    """`theory` with the rules in `targets` swapped for the rival's rule (at the first target's position,
    so rule order, which decides which effect has the final word, is preserved)."""
    v = theory.model_copy(deep=True)
    pos = next(i for i, r in enumerate(v.rules) if r.id in targets)
    rule = h.rule.model_copy(deep=True)
    rule.status = "tentative"
    rules = [r for r in v.rules if r.id not in targets and r.id != rule.id]
    rules.insert(min(pos, len(rules)), rule)
    v.rules = rules
    v.note = f"rival variant: {h.id} in place of {', '.join(targets)}"
    return v


def plausible_theories(theory: Theory, hypotheses: dict[str, Hypothesis] | list[Hypothesis],
                       transitions: list[Transition], k: int = 4, replaces: dict[str, str | None] | None = None,
                       margin: float = MARGIN, window: int = WINDOW) -> list[Theory]:
    """The current theory plus up to k-1 variants in which a still-open or supported rival replaces the
    active rule it competes with, keeping only variants whose accuracy on recent experience is within
    `margin` of the best (they explain what has been seen equally well, yet may act differently)."""
    hyps = hypotheses if isinstance(hypotheses, dict) else {h.id: h for h in hypotheses}
    active = {r.id for r in theory.rules if r.status in ("tentative", "supported")}
    by_rule = {h.rule.id: h for h in hyps.values()}
    variants: list[Theory] = []
    seen = {_sig(theory)}
    for h in hyps.values():
        if h.status not in LIVE or h.rule.id in active:
            continue
        targets = [hyps[j].rule.id for j in h.rivals if j in hyps and hyps[j].rule.id in active]
        rep = (replaces or {}).get(h.id)
        if rep in active and rep not in targets:
            targets.append(rep)
        # a rival of an adopted rule may be listed only on the adopted hypothesis' side
        targets += [rid for rid, o in by_rule.items() if rid in active and h.id in o.rivals and rid not in targets]
        if not targets:
            continue
        v = _variant(theory, h, targets)
        s = _sig(v)
        if s not in seen:
            seen.add(s)
            variants.append(v)
    if not variants:
        return [theory]
    recent = transitions[-window:] if window else list(transitions)
    if not recent:
        return [theory]

    def acc(t: Theory) -> float:
        try:
            return accuracy(t, recent)
        except Exception:
            return -1.0

    base = acc(theory)
    scored = sorted(((acc(v), i, v) for i, v in enumerate(variants)), key=lambda e: (-e[0], e[1]))
    best = max(base, scored[0][0])
    keep = [v for a, _, v in scored if a >= best - margin]
    return [theory] + keep[: max(0, k - 1)]


def disagreement(theories: list[Theory], obs: Observation, action: Action,
                 predictors: list[Predictor] | None = None) -> list[str]:
    """Fields whose next value the theories predict differently for `action` from `obs`. Pass live
    predictors (one per theory, synced to `obs`) to carry memory and delayed effects; they are cloned."""
    preds = []
    for i, th in enumerate(theories):
        if predictors is not None and i < len(predictors):
            p = predictors[i].clone()
        else:
            p = Predictor(th)
            p.reset(obs)
        preds.append(p.predict(obs, action))
    if len(preds) < 2:
        return []
    fields = sorted({f for p in preds for f in p if f != "t"})
    return [f for f in fields if any(not _eq(preds[0].get(f), q.get(f)) for q in preds[1:])]


def robust_policy(policy: Any, theory: Theory, inv: Any, manual, objective) -> Any:
    """Swap a planner policy for the robust one when more than one theory is still plausible."""
    try:
        ths = plausible_theories(theory, inv.hypotheses, inv.transitions, k=2, replaces=getattr(inv, "_replaces", None))
    except Exception:
        return policy
    if len(ths) < 2:
        return policy
    from logicscout.planner import RobustPlannerPolicy
    return RobustPlannerPolicy(ths, manual, objective, depth=4, beam=12)
