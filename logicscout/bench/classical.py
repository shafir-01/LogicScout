"""Classical system-identification comparators: no model, no hypotheses, same probe budget.

Both learners see exactly what the no-model scout is allowed to see: `manual.probe_budget` interaction
steps on lab seeds (random + coverage exploration, resets every RESET_EVERY steps), then they control the
held-out referee cases by beam search inside what they learned, scored by the same referee.

- TreeModel: per observation field a small CART tree (depth <= 4) over (obs fields, action one-hot,
  action args, t mod k for k in 2..8). Integer/bool fields: classification, each leaf predicts either the
  most common next value or the most common delta (whichever fits its samples better). Real-valued
  fields: regression on the delta (leaf mean).
- KNNModel: k=3 nearest-neighbour transition model over z-normalised (obs, action) features; predicts
  the neighbours' most common delta (mean delta for real-valued fields, majority value for bools).

Privileged bench code (like the referee): nothing here is imported by the scout.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from logicscout.contracts import Action, Objective, Observation, Playbook, Theory, WorldManual
from logicscout.dsl import safe_evaluate
from logicscout.planner import SUCCESS, candidate_actions, progress
from logicscout.theory import _eq

Transition = tuple[Observation, Action, Observation]
RESET_EVERY = 8
MAX_DEPTH = 4
MIN_LEAF = 2
MAX_THRESHOLDS = 12
K_NEIGHBOURS = 3
T_MODS = range(2, 9)


# ---- features ------------------------------------------------------------------------------------

def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    return None


class Featurizer:
    """(obs, action) -> fixed-length numeric vector; names kept for inspection."""

    def __init__(self, manual: WorldManual, fields: list[str]) -> None:
        self.fields = fields
        self.actions = [a.name for a in manual.actions]
        self.params: list[tuple[str, str, list | None]] = []  # (action, param, enum choices)
        for a in manual.actions:
            for p in a.params:
                self.params.append((a.name, p.name, list(p.choices) if (p.type == "enum" or p.choices) else None))
        self.names: list[str] = list(fields) + [f"act={n}" for n in self.actions]
        for an, pn, ch in self.params:
            self.names += [f"{an}.{pn}={c}" for c in ch] if ch else [f"{an}.{pn}"]
        self.names += [f"t%{k}" for k in T_MODS]
        self.n_obs = len(fields)
        self.n_act = len(self.actions)

    def obs_part(self, obs: Observation) -> list[float]:
        out = []
        for f in self.fields:
            x = _num(obs.fields.get(f))
            out.append(0.0 if x is None else x)
        return out

    def action_part(self, action: Action) -> list[float]:
        out = [1.0 if action.name == n else 0.0 for n in self.actions]
        for an, pn, ch in self.params:
            v = action.args.get(pn) if action.name == an else None
            if ch:
                out += [1.0 if v == c else 0.0 for c in ch]
            else:
                x = _num(v)
                out.append(0.0 if x is None else x)
        return out

    def vector(self, obs: Observation, action: Action) -> list[float]:
        t = obs.t if obs.t is not None else int(obs.fields.get("t", 0) or 0)
        return self.obs_part(obs) + self.action_part(action) + [float(t % k) for k in T_MODS]


def _field_kinds(transitions: list[Transition]) -> dict[str, str]:
    """field -> "bool" | "int" | "real" | "other" from the values seen."""
    kinds: dict[str, str] = {}
    for before, _, after in transitions:
        for o in (before, after):
            for f, v in o.fields.items():
                if f == "t":
                    continue
                k = ("bool" if isinstance(v, bool) else "int" if isinstance(v, int)
                     else "real" if isinstance(v, float) and not float(v).is_integer() else
                     "int" if isinstance(v, float) else "other")
                prev = kinds.get(f)
                if prev is None or prev == k:
                    kinds[f] = k
                elif {prev, k} == {"int", "real"}:
                    kinds[f] = "real"
                else:
                    kinds[f] = "other"
    return kinds


def _apply(kind: str, before: Any, mode: str, value: Any) -> Any:
    """Turn a leaf prediction (mode "abs" or "delta") into the next field value."""
    if mode == "abs" or kind in ("bool", "other"):
        return value
    b = _num(before)
    if b is None:
        return value
    out = b + value
    return int(round(out)) if kind == "int" else round(out, 6)


# ---- CART-lite -------------------------------------------------------------------------------------

def _gini(labels: list) -> float:
    n = len(labels)
    if not n:
        return 0.0
    return 1.0 - sum((c / n) ** 2 for c in Counter(labels).values())


def _sse(vals: list[float]) -> float:
    if not vals:
        return 0.0
    m = sum(vals) / len(vals)
    return sum((v - m) ** 2 for v in vals)


class _Node:
    __slots__ = ("feat", "thr", "left", "right", "mode", "value")

    def __init__(self) -> None:
        self.feat: int | None = None
        self.thr = 0.0
        self.left: _Node | None = None
        self.right: _Node | None = None
        self.mode = "abs"
        self.value: Any = None


class FieldTree:
    """CART for one field. rows: (x, before_value, after_value)."""

    def __init__(self, kind: str, max_depth: int = MAX_DEPTH) -> None:
        self.kind, self.max_depth = kind, max_depth
        self.root = _Node()

    def _targets(self, rows):
        if self.kind == "real":
            return [float(_num(a) - _num(b)) if _num(a) is not None and _num(b) is not None else 0.0
                    for _, b, a in rows]
        return None

    def _impurity(self, rows) -> float:
        if self.kind == "real":
            return _sse(self._targets(rows))
        abs_l = [_hashable(a) for _, _, a in rows]
        if self.kind in ("bool", "other"):
            return len(rows) * _gini(abs_l)
        delta_l = [_delta_label(b, a) for _, b, a in rows]
        return len(rows) * min(_gini(abs_l), _gini(delta_l))

    def _leaf(self, node: _Node, rows) -> None:
        if not rows:
            node.mode, node.value = "delta", 0
            return
        if self.kind == "real":
            d = self._targets(rows)
            node.mode, node.value = "delta", sum(d) / len(d)
            return
        abs_c = Counter(_hashable(a) for _, _, a in rows).most_common(1)[0]
        if self.kind in ("bool", "other"):
            node.mode, node.value = "abs", _unhash(abs_c[0])
            return
        del_c = Counter(_delta_label(b, a) for _, b, a in rows).most_common(1)[0]
        if del_c[1] >= abs_c[1]:
            node.mode, node.value = "delta", del_c[0]
        else:
            node.mode, node.value = "abs", _unhash(abs_c[0])

    def fit(self, rows: list[tuple[list[float], Any, Any]]) -> FieldTree:
        self._grow(self.root, rows, 0)
        return self

    def _grow(self, node: _Node, rows, depth: int) -> None:
        self._leaf(node, rows)
        if depth >= self.max_depth or len(rows) < 2 * MIN_LEAF:
            return
        base = self._impurity(rows)
        if base <= 1e-12:
            return
        best = None
        n_feat = len(rows[0][0])
        for j in range(n_feat):
            vals = sorted({r[0][j] for r in rows})
            if len(vals) < 2:
                continue
            mids = [(a + b) / 2 for a, b in zip(vals, vals[1:])]
            if len(mids) > MAX_THRESHOLDS:
                mids = [mids[round(i * (len(mids) - 1) / (MAX_THRESHOLDS - 1))] for i in range(MAX_THRESHOLDS)]
            for thr in mids:
                left = [r for r in rows if r[0][j] <= thr]
                right = [r for r in rows if r[0][j] > thr]
                if len(left) < MIN_LEAF or len(right) < MIN_LEAF:
                    continue
                imp = self._impurity(left) + self._impurity(right)
                if best is None or imp < best[0] - 1e-12:
                    best = (imp, j, thr, left, right)
        if best is None or best[0] >= base - 1e-9:
            return
        _, node.feat, node.thr, left, right = best
        node.left, node.right = _Node(), _Node()
        self._grow(node.left, left, depth + 1)
        self._grow(node.right, right, depth + 1)

    def predict(self, x: list[float], before: Any) -> Any:
        node = self.root
        while node.feat is not None:
            node = node.left if x[node.feat] <= node.thr else node.right
        return _apply(self.kind, before, node.mode, node.value)

    def depth(self) -> int:
        def d(n: _Node) -> int:
            return 0 if n.feat is None else 1 + max(d(n.left), d(n.right))
        return d(self.root)


def _hashable(v: Any) -> Any:
    return ("__f", round(v, 6)) if isinstance(v, float) else v


def _unhash(v: Any) -> Any:
    return v[1] if isinstance(v, tuple) and len(v) == 2 and v[0] == "__f" else v


def _delta_label(before: Any, after: Any) -> Any:
    b, a = _num(before), _num(after)
    if a is None or b is None or isinstance(after, bool):
        return ("__na",)
    return int(round(a - b)) if float(a - b).is_integer() else round(a - b, 6)


class _Base:
    def __init__(self, manual: WorldManual) -> None:
        self.manual = manual
        self.fields: list[str] = []
        self.kinds: dict[str, str] = {}
        self.feat: Featurizer | None = None

    def _prep(self, transitions: list[Transition]) -> None:
        if not transitions:
            raise ValueError("no transitions to learn from")
        self.fields = sorted(f for f in transitions[0][2].fields if f != "t")
        self.kinds = _field_kinds(transitions)
        self.feat = Featurizer(self.manual, self.fields)


class TreeModel(_Base):
    """One CART-lite tree per observation field."""

    def __init__(self, manual: WorldManual, max_depth: int = MAX_DEPTH) -> None:
        super().__init__(manual)
        self.max_depth = min(max_depth, MAX_DEPTH)
        self.trees: dict[str, FieldTree] = {}

    def fit(self, transitions: list[Transition]) -> TreeModel:
        self._prep(transitions)
        xs = [self.feat.vector(b, a) for b, a, _ in transitions]
        for f in self.fields:
            rows = [(x, b.fields.get(f), af.fields.get(f)) for x, (b, _, af) in zip(xs, transitions)]
            self.trees[f] = FieldTree(self.kinds.get(f, "other"), self.max_depth).fit(rows)
        return self

    def predict(self, obs: Observation, action: Action) -> dict:
        x = self.feat.vector(obs, action)
        out = {f: tree.predict(x, obs.fields.get(f)) for f, tree in self.trees.items()}
        out["t"] = (obs.t or 0) + 1
        return out


class KNNModel(_Base):
    """k-nearest-neighbour transition model over z-normalised (obs, action) features."""

    def __init__(self, manual: WorldManual, k: int = K_NEIGHBOURS) -> None:
        super().__init__(manual)
        self.k = k
        self.data: list[tuple[list[float], Observation, Observation]] = []
        self.mu: list[float] = []
        self.sd: list[float] = []

    def _x(self, obs: Observation, action: Action) -> list[float]:
        f = self.feat
        raw = f.obs_part(obs) + f.action_part(action)
        return [(v - m) / s for v, m, s in zip(raw, self.mu, self.sd)]

    def fit(self, transitions: list[Transition]) -> KNNModel:
        self._prep(transitions)
        raws = [self.feat.obs_part(b) + self.feat.action_part(a) for b, a, _ in transitions]
        dim = len(raws[0])
        self.mu = [sum(r[j] for r in raws) / len(raws) for j in range(dim)]
        self.sd = []
        for j in range(dim):
            var = sum((r[j] - self.mu[j]) ** 2 for r in raws) / len(raws)
            self.sd.append(math.sqrt(var) if var > 1e-12 else 1.0)
        self.data = [(self._x(b, a), b, af) for b, a, af in transitions]
        return self

    def neighbours(self, obs: Observation, action: Action) -> list[tuple[Observation, Observation]]:
        x = self._x(obs, action)
        scored = sorted(((sum((p - q) ** 2 for p, q in zip(x, d)), i) for i, (d, _, _) in enumerate(self.data)))
        return [(self.data[i][1], self.data[i][2]) for _, i in scored[: self.k]]

    def predict(self, obs: Observation, action: Action) -> dict:
        nb = self.neighbours(obs, action)
        out: dict[str, Any] = {}
        for f in self.fields:
            kind, cur = self.kinds.get(f, "other"), obs.fields.get(f)
            if kind in ("bool", "other"):
                out[f] = _unhash(Counter(_hashable(a.fields.get(f)) for _, a in nb).most_common(1)[0][0])
            elif kind == "real":
                ds = [_num(a.fields.get(f)) - _num(b.fields.get(f)) for b, a in nb
                      if _num(a.fields.get(f)) is not None and _num(b.fields.get(f)) is not None]
                out[f] = _apply(kind, cur, "delta", sum(ds) / len(ds) if ds else 0.0)
            else:
                lab = Counter(_delta_label(b.fields.get(f), a.fields.get(f)) for b, a in nb).most_common(1)[0][0]
                out[f] = _apply(kind, cur, "delta", 0 if isinstance(lab, tuple) else lab)
        out["t"] = (obs.t or 0) + 1
        return out


# ---- exploration (matched budget, no model) ---------------------------------------------------------

def explore(port, manual: WorldManual, seed: int, budget: int | None = None, log=None) -> list[Transition]:
    """Random + coverage exploration on lab seeds: half the steps take the least-tried candidate action
    (planner grid), half a uniformly random admissible action; reset to a fresh lab seed every RESET_EVERY."""
    rng = random.Random(seed * 131 + 17)
    from logicscout.referee.referee import random_action

    budget = manual.probe_budget if budget is None else budget
    cands = candidate_actions(manual)
    tried = [0] * len(cands)
    lo, hi = manual.lab_seeds
    out: list[Transition] = []
    obs = None
    probe_n = 0
    for i in range(budget):
        if obs is None or i % RESET_EVERY == 0:
            s = rng.randrange(lo, hi)
            probe_n += 1
            if log is not None:
                log.append("probe.designed", {"probe": {"id": f"cp{probe_n}", "purpose": "classical exploration",
                                                        "seed": s, "hypotheses": [], "actions": []}})
            obs = port.reset(s)
        if i % 2 == 0:
            m = min(tried)
            idx = rng.choice([j for j, c in enumerate(tried) if c == m])
            tried[idx] += 1
            a = cands[idx]
        else:
            a = random_action(manual.actions, rng)
        res = port.act(a)
        if log is not None:
            log.append("probe.step", {"probe_id": f"cp{probe_n}", "action": a.model_dump(),
                                      "observation": res.observation.model_dump()})
        out.append((obs, a, res.observation))
        obs = res.observation
    return out


# ---- control ------------------------------------------------------------------------------------------

class ModelBeamPolicy:
    """Replans every step: beam search of depth `depth` inside a learned transition model, scored with
    planner.progress on the objective's success expression (same objective shaping the scout's planner uses)."""

    def __init__(self, model, manual: WorldManual, objective: Objective, depth: int = 4, beam: int = 16) -> None:
        self.model, self.manual, self.objective = model, manual, objective
        self.depth, self.beam = depth, beam
        self.candidates = candidate_actions(manual)
        if not self.candidates:
            raise ValueError("manual has no actions to plan with")
        self._cache: dict[tuple, dict] = {}
        self.last_plan: list[Action] = []

    def _succ(self, obs: Observation) -> bool:
        try:
            return bool(safe_evaluate(self.objective.success, {"obs": obs.fields, "args": {}, "mem": {}, "t": obs.t}))
        except Exception:
            return False

    def _step(self, obs: Observation, i: int) -> Observation:
        key = (obs.t, tuple(sorted((k, _hashable(v)) for k, v in obs.fields.items())), i)
        hit = self._cache.get(key)
        if hit is None:
            hit = self.model.predict(obs, self.candidates[i])
            if len(self._cache) > 50000:
                self._cache.clear()
            self._cache[key] = hit
        return Observation(t=(obs.t or 0) + 1, fields=dict(hit))

    def next_action(self, obs: Observation) -> Action:
        beams: list[tuple[tuple[int, ...], Observation]] = [((), obs)]
        best: tuple[float, tuple[int, ...]] | None = None
        for d in range(self.depth):
            expanded: list[tuple[float, tuple[int, ...], Observation]] = []
            seen: set = set()
            for seq, o0 in beams:
                for i in range(len(self.candidates)):
                    o = self._step(o0, i)
                    s = seq + (i,)
                    val = SUCCESS - d if self._succ(o) else progress(self.objective.success, o, {}) - 0.001 * d
                    if best is None or (-val, s) < (-best[0], best[1]):
                        best = (val, s)
                    k = tuple(sorted((kk, _hashable(v)) for kk, v in o.fields.items() if kk != "t"))
                    if val < SUCCESS - self.depth and k not in seen:
                        seen.add(k)
                        expanded.append((val, s, o))
            if best is not None and best[0] >= SUCCESS - self.depth:
                break
            expanded.sort(key=lambda e: (-e[0], e[1]))
            beams = [(s, o) for _, s, o in expanded[: self.beam]]
            if not beams:
                break
        self.last_plan = [self.candidates[i] for i in (best[1] if best else (0,))]
        return self.last_plan[0]

    def after_step(self, obs: Observation) -> None:
        pass


# ---- held-out prediction metrics ---------------------------------------------------------------------

def prediction_metrics(model, episodes: list[list[Transition]]) -> dict[str, Any]:
    """One-step accuracy over (step, field) pairs (excluding t, same tolerance as the referee), plus
    accuracy on the pairs whose value actually changed (persistence scores 0 there)."""
    c = n = cc = cn = pc = 0
    for ep in episodes:
        for before, action, after in ep:
            p = model.predict(before, action)
            for f, o in after.fields.items():
                if f == "t":
                    continue
                ok = _eq(p.get(f), o)
                n += 1
                c += ok
                pc += _eq(before.fields.get(f), o)
                if not _eq(before.fields.get(f), o):
                    cn += 1
                    cc += ok
    return {"prediction_accuracy": round(c / n, 4) if n else 0.0,
            "persistence_accuracy": round(pc / n, 4) if n else 0.0,
            "changed_accuracy": round(cc / cn, 4) if cn else 0.0, "n_pairs": n, "n_changed": cn}


def held_out_episodes(world_id: str, objective_id: str, variant: str = "standard") -> list[list[Transition]]:
    from logicscout.referee.referee import cases_for, collect_transitions, world_class

    cls = world_class(world_id)
    return [tr for c in cases_for(cls, objective_id, variant) if (tr := collect_transitions(cls, c))]


# ---- one full offline run -----------------------------------------------------------------------------

MODELS: dict[str, Callable[[WorldManual], Any]] = {"tree": TreeModel, "knn": KNNModel}


def run_classical(kind: str, world_id: str, objective_id: str, seed: int, variant: str = "standard",
                  run_id: str | None = None, depth: int = 4, beam: int = 16) -> dict[str, Any]:
    """Explore (matched budget) -> fit -> referee-scored control + held-out one-step prediction."""
    from logicscout.logbook import Logbook
    from logicscout.referee.referee import evaluate
    from logicscout.sandbox import open_session

    run_id = run_id or f"classical-{world_id}-{variant}-{kind}-s{seed}"
    t0 = time.perf_counter()
    port = open_session(world_id, variant).port
    manual = port.manual()
    log = Logbook(run_id)
    tr = explore(port, manual, seed, log=log)
    model = MODELS[kind](manual).fit(tr)
    pm = prediction_metrics(model, held_out_episodes(world_id, objective_id, variant))

    def make_policy(world, m, objective):
        return ModelBeamPolicy(model, m, objective, depth=depth, beam=beam)

    stub = Playbook(id=f"classical-{kind}", world_id=world_id, objective_id=objective_id, theory_version=0,
                    origin="planner", rules=[], fallback={"name": manual.actions[0].name, "args": {}})
    report = evaluate(world_id, Theory(world_id=world_id), stub, objective_id, run_id, None, list(log.events),
                      variant=variant, make_policy=make_policy)
    return {
        "status": "ok", "arm": kind, "world_id": world_id, "variant": variant, "seed": seed,
        "wall_s": round(time.perf_counter() - t0, 1), "model_calls": 0, "tokens": 0,
        "probes_used": len(tr), "success": report.success_rate,
        "random": report.baselines.get("random"), "idle": report.baselines.get("idle"),
        "cases": [c.model_dump() for c in report.cases],
        "n_cases": len(report.cases), "successes": sum(bool(c.success) for c in report.cases),
        **pm,
        "leakage_checks": {k: v for k, v in report.leakage_checks.items() if k != "no_law_text_in_prompts"},
        "note": "prediction metrics: one-step, on the referee's held-out random-policy transitions",
    }


# ---- bench arms ----------------------------------------------------------------------------------------

def _arm(kind: str):
    async def run(ctx) -> dict[str, Any]:
        return await asyncio.to_thread(run_classical, kind, ctx.world_id, ctx.objective_id, ctx.seed,
                                       getattr(ctx, "variant", "standard"), ctx.run_id)
    run.__name__ = f"arm_{kind}"
    return run


def arms() -> dict[str, Callable]:
    """{"tree": async fn(ctx: ArmContext) -> dict, "knn": ...}; same signature as the bench's arm functions."""
    return {"tree": _arm("tree"), "knn": _arm("knn")}


__all__ = ["TreeModel", "KNNModel", "FieldTree", "ModelBeamPolicy", "explore", "prediction_metrics",
           "held_out_episodes", "run_classical", "arms"]
