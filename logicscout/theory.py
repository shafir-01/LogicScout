"""Executable theories: one-step-ahead prediction, scoring against observed transitions, validation."""
from __future__ import annotations

import copy
import math
from typing import Any

from logicscout.contracts import Action, Mismatch, Observation, Rule, Theory, WorldManual
from logicscout.dsl import DSLError, evaluate, validate

Transition = tuple[Observation, Action, Observation]

ACTIVE = ("tentative", "supported")
_FAILED = object()


def _env(obs: Observation, args: dict, mem: dict) -> dict:
    return {"obs": obs.fields, "args": args or {}, "mem": mem, "t": obs.t}


def _try(expr: str, env: dict) -> Any:
    try:
        return evaluate(expr, env)
    except DSLError:
        return _FAILED


class Predictor:
    """Runs a theory one step ahead of the real world.

    predict(obs, action) -> full next fields; advance(observed) commits the step (memory updates,
    delayed effects) and syncs to what really happened.
    """

    def __init__(self, theory: Theory):
        self.theory = theory
        self.rules = [r for r in theory.rules if r.status in ACTIVE]
        self.mem: dict = copy.deepcopy(theory.memory)
        self.pending: list[tuple[int, str, Any, str]] = []  # (due_t, field, value, rule_id)
        self.obs: Observation | None = None
        self.last_rules: dict[str, list[str]] = {}
        self.fired: list[str] = []
        self._staged: tuple[int, dict, list] | None = None

    def reset(self, obs: Observation) -> None:
        self.mem = copy.deepcopy(self.theory.memory)
        self.pending = []
        self.obs = obs
        self.last_rules = {}
        self.fired = []
        self._staged = None

    def clone(self) -> "Predictor":
        p = Predictor.__new__(Predictor)
        p.theory, p.rules = self.theory, self.rules
        p.mem = copy.deepcopy(self.mem)
        p.pending = list(self.pending)
        p.obs = self.obs
        p.last_rules = {}
        p.fired = []
        p._staged = None
        return p

    def predict(self, obs: Observation, action: Action) -> dict:
        env = _env(obs, action.args, self.mem)
        nxt = copy.deepcopy(obs.fields)
        next_t = obs.t + 1
        sources: dict[str, list[str]] = {}
        new_mem: dict = {}
        queued: list[tuple[int, str, Any, str]] = []
        fired: list[str] = []
        for due, field, value, rid in self.pending:
            if due <= next_t:
                nxt[field] = value
                sources.setdefault(field, []).append(rid)
        for rule in self.rules:
            if rule.action != "*" and rule.action != action.name:
                continue
            cond = _try(rule.when, env)
            if cond is _FAILED or not cond:
                continue
            fired.append(rule.id)
            for field, expr in rule.effects.items():
                v = _try(expr, env)
                v = None if v is _FAILED else v
                if rule.delay > 0:
                    queued.append((next_t + rule.delay, field, v, rule.id))
                else:
                    nxt[field] = v
                    sources.setdefault(field, []).append(rule.id)
            for var, expr in rule.memory.items():
                v = _try(expr, env)
                new_mem[var] = None if v is _FAILED else v
        self.last_rules = sources
        self.fired = fired
        self._staged = (next_t, new_mem, queued)
        return nxt

    def advance(self, observed: Observation) -> None:
        if self._staged is not None:
            _, new_mem, queued = self._staged
            self.mem.update(new_mem)
            self.pending.extend(queued)
        self.pending = [p for p in self.pending if p[0] > observed.t]
        self.obs = observed
        self._staged = None


def _eq(p: Any, o: Any) -> bool:
    if isinstance(p, bool) or isinstance(o, bool):
        return isinstance(p, bool) and isinstance(o, bool) and p is o
    if isinstance(p, (int, float)) and isinstance(o, (int, float)):
        if math.isnan(p) or math.isnan(o):
            return False
        return abs(p - o) <= 1e-6 or abs(p - o) <= 0.02 * max(abs(p), abs(o))
    if isinstance(p, (list, tuple)) and isinstance(o, (list, tuple)):
        return len(p) == len(o) and all(_eq(a, b) for a, b in zip(p, o))
    if isinstance(p, dict) and isinstance(o, dict):
        return p.keys() == o.keys() and all(_eq(p[k], o[k]) for k in p)
    return p == o


def _within(p: Any, o: Any, band: float | None) -> bool:
    if band is None or isinstance(p, bool) or isinstance(o, bool):
        return False
    if not (isinstance(p, (int, float)) and isinstance(o, (int, float))) or math.isnan(p) or math.isnan(o):
        return False
    return abs(p - o) <= band


def compare(predicted: dict, observed: dict, sources: dict[str, list[str]] | None = None,
            tol: dict[str, float] | None = None) -> list[Mismatch]:
    """Mismatches over observed fields (excluding `t`). A missing or None prediction is a mismatch
    unless the observed value is also None. `tol` (optional) gives per-field absolute tolerances for
    numeric fields (see logicscout.noise); without it the comparison is unchanged."""
    out = []
    for field, o in observed.items():
        if field == "t":
            continue
        p = predicted.get(field)
        if not _eq(p, o) and not (tol and _within(p, o, tol.get(field))):
            out.append(Mismatch(field=field, predicted=p, observed=o, rule_ids=list((sources or {}).get(field, []))))
    return out


def _replay(theory: Theory, transitions: list[Transition]):
    """Yield (predictor, predicted_fields, observed_after) per transition, restarting per episode."""
    pred: Predictor | None = None
    prev: Observation | None = None
    for before, action, after in transitions:
        if pred is None or prev is None or before.t != prev.t or not _same(before.fields, prev.fields):
            pred = Predictor(theory)
            pred.reset(before)
        p = pred.predict(before, action)
        yield pred, p, after
        pred.advance(after)
        prev = after


def _same(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)


def _score(pairs) -> float:
    total = correct = 0
    for predicted, observed in pairs:
        fields = [f for f in observed if f != "t"]
        total += len(fields)
        correct += len(fields) - len(compare(predicted, observed))
    return correct / total if total else 0.0


def accuracy(theory: Theory, transitions: list[Transition]) -> float:
    """Fraction of (step, field) pairs predicted correctly, excluding `t`."""
    return _score((p, after.fields) for _, p, after in _replay(theory, transitions))


def persistence_accuracy(transitions: list[Transition]) -> float:
    """Baseline: predict that nothing changes."""
    return _score((before.fields, after.fields) for before, _, after in transitions)


# ---- metrics that cannot hide failures ------------------------------------------------------------

def changed_pairs(transitions: list[Transition]) -> list[tuple[int, str]]:
    """(step index, field) pairs whose observed value changed from before to after (excluding `t`)."""
    return [(i, f) for i, (before, _, after) in enumerate(transitions) for f in after.fields
            if f != "t" and not _eq(before.fields.get(f), after.fields[f])]


def _masked(theory: Theory, transitions: list[Transition], keep) -> tuple[int, int]:
    """(correct, total) over (step, field) pairs where keep(i, before, after, field) is true."""
    correct = total = 0
    for i, ((before, _, after), (_, p, _)) in enumerate(zip(transitions, _replay(theory, transitions))):
        for f, o in after.fields.items():
            if f == "t" or not keep(i, before, after, f):
                continue
            total += 1
            correct += int(_eq(p.get(f), o))
    return correct, total


def changed_counts(theory: Theory, transitions: list[Transition]) -> tuple[int, int]:
    return _masked(theory, transitions, lambda i, b, a, f: not _eq(b.fields.get(f), a.fields[f]))


def changed_accuracy(theory: Theory, transitions: list[Transition]) -> float:
    """Accuracy only over (step, field) pairs whose value actually changed. Predicting "nothing changes"
    scores 0 here by construction, so a lazy theory cannot hide behind quiet steps."""
    c, n = changed_counts(theory, transitions)
    return c / n if n else 0.0


def field_counts(theory: Theory, transitions: list[Transition], fields) -> tuple[int, int]:
    keep = set(fields)
    return _masked(theory, transitions, lambda i, b, a, f: f in keep)


def field_accuracy(theory: Theory, transitions: list[Transition], fields) -> float:
    """Accuracy restricted to the given fields (e.g. the fields the goal is defined over)."""
    c, n = field_counts(theory, transitions, fields)
    return c / n if n else 0.0


def goal_fields(success_expr: str) -> list[str]:
    """Observation fields named in an objective's success expression (obs.<name>)."""
    import re

    return list(dict.fromkeys(re.findall(r"\bobs\.([A-Za-z_]\w*)", success_expr or "")))


def rollout_counts(theory: Theory, episodes: list[list[Transition]], horizon: int = 5) -> dict[int, tuple[int, int]]:
    """Open-loop rollouts. From every real starting point of each episode (the predictor having tracked
    truth up to there, so latent memory and delayed effects are real), predict k steps ahead by feeding
    the theory's own predictions back in, under the actions really taken. Score step k against the real
    observation k steps later. Returns {k: (correct, total)}."""
    out = {k: (0, 0) for k in range(1, horizon + 1)}
    for ep in episodes:
        if not ep:
            continue
        tracker = Predictor(theory)
        tracker.reset(ep[0][0])
        for i in range(len(ep)):
            sim = tracker.clone()
            obs = ep[i][0]
            for k in range(1, horizon + 1):
                j = i + k - 1
                if j >= len(ep):
                    break
                _, action, real_after = ep[j]
                p = sim.predict(obs, action)
                c, n = out[k]
                fields = [f for f in real_after.fields if f != "t"]
                out[k] = (c + len(fields) - len(compare(p, real_after.fields)), n + len(fields))
                obs = Observation(t=obs.t + 1, fields=p)
                sim.advance(obs)
            before, action, after = ep[i]
            tracker.predict(before, action)
            tracker.advance(after)
    return out


def rollout_accuracy(theory: Theory, episodes: list[list[Transition]], horizon: int = 5) -> dict[int, float]:
    """{k: accuracy of the k-step open-loop prediction}, k = 1..horizon (see rollout_counts)."""
    return {k: (c / n if n else 0.0) for k, (c, n) in rollout_counts(theory, episodes, horizon).items()}


def rule_stats(theory: Theory, transitions: list[Transition]) -> dict[str, dict[str, int]]:
    """Per rule: how often its effect was the final word on a field (`fired`) and how often it was right."""
    stats = {r.id: {"fired": 0, "correct": 0} for r in theory.rules}
    for pred, p, after in _replay(theory, transitions):
        for field, rids in pred.last_rules.items():
            if field not in after.fields or not rids:
                continue
            s = stats.setdefault(rids[-1], {"fired": 0, "correct": 0})
            s["fired"] += 1
            s["correct"] += int(_eq(p.get(field), after.fields[field]))
    return stats


def validate_theory(theory: Theory, manual: WorldManual) -> list[str]:
    errors: list[str] = []
    actions = {a.name for a in manual.actions}
    fields = {f.name for f in manual.observations}
    seen: set[str] = set()
    for r in theory.rules:
        tag = f"rule {r.id}"
        if r.id in seen:
            errors.append(f"{tag}: duplicate id")
        seen.add(r.id)
        if r.action != "*" and r.action not in actions:
            errors.append(f"{tag}: unknown action {r.action!r}")
        if r.delay < 0:
            errors.append(f"{tag}: negative delay")
        errors += [f"{tag} when: {e}" for e in validate(r.when)]
        for field, expr in r.effects.items():
            if field not in fields:
                errors.append(f"{tag}: effect on unknown field {field!r}")
            errors += [f"{tag} effect {field}: {e}" for e in validate(expr)]
        for var, expr in r.memory.items():
            errors += [f"{tag} memory {var}: {e}" for e in validate(expr)]
    return errors


_SIG = ("action", "when", "effects", "memory", "delay", "status", "kind", "statement")


def diff(old: Theory | None, new: Theory) -> dict:
    """Rule-level difference between two theory versions."""
    o = {r.id: r for r in (old.rules if old else [])}
    n = {r.id: r for r in new.rules}

    def sig(r: Rule) -> dict:
        return r.model_dump(include=set(_SIG))

    return {
        "added": [i for i in n if i not in o],
        "removed": [i for i in o if i not in n],
        "changed": [i for i in n if i in o and sig(n[i]) != sig(o[i])],
        "memory_changed": (old.memory if old else {}) != new.memory,
    }
