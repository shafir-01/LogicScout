"""Model-free lookahead controller: beam search over a finite action set inside the learned theory."""
from __future__ import annotations

import ast
import itertools
import json
from typing import Any

from logicscout.contracts import Action, ActionTemplate, Objective, Observation, ParamSpec, Playbook, Theory, WorldManual
from logicscout.dsl import safe_evaluate
from logicscout.theory import Predictor

MAX_PER_ACTION = 24
MAX_TOTAL = 48
SUCCESS = 1000.0


def _spread(lo: float, hi: float, n: int, as_int: bool) -> list:
    if as_int:
        lo_i, hi_i = int(round(lo)), int(round(hi))
        if hi_i - lo_i + 1 <= n:
            return list(range(lo_i, hi_i + 1))
        return sorted({int(round(lo_i + (hi_i - lo_i) * k / (n - 1))) for k in range(n)})
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


def _param_values(p: ParamSpec) -> list:
    if p.type == "enum":
        return list(p.choices or [])
    if p.type == "bool":
        return [False, True]
    if p.type == "int":
        lo = p.min if p.min is not None else 0
        hi = p.max if p.max is not None else lo + 5
        return _spread(lo, hi, 6, True)
    if p.type == "float":
        lo = p.min if p.min is not None else 0.0
        hi = p.max if p.max is not None else lo + 1.0
        return _spread(lo, hi, 3, False)
    return [""]


def _thin(items: list, n: int) -> list:
    if len(items) <= n:
        return items
    return [items[round(k * (len(items) - 1) / (n - 1))] for k in range(n)] if n > 1 else items[:1]


def candidate_actions(manual: WorldManual) -> list[Action]:
    per = max(4, min(MAX_PER_ACTION, MAX_TOTAL // max(len(manual.actions), 1)))
    out: list[Action] = []
    for spec in manual.actions:
        names = [p.name for p in spec.params]
        combos = list(itertools.product(*[_param_values(p) for p in spec.params]))
        out += [Action(name=spec.name, args=dict(zip(names, c))) for c in _thin(combos, per)]
    return out


def _term(node: ast.AST, env: dict) -> float:
    if isinstance(node, ast.BoolOp):
        vals = [_term(v, env) for v in node.values]
        return sum(vals) / len(vals) if isinstance(node.op, ast.And) else max(vals)
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        a = safe_evaluate(ast.unparse(node.left), env)
        b = safe_evaluate(ast.unparse(node.comparators[0]), env)
        num = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b))
        op = node.ops[0]
        if num:
            if isinstance(op, (ast.GtE, ast.Gt)):
                if a >= b:
                    return 1.0 if isinstance(op, ast.GtE) or a > b else 0.95
                return max(a / b, -1.0) if b > 0 else 1.0 / (1.0 + b - a)
            if isinstance(op, (ast.LtE, ast.Lt)):
                if a <= b:
                    if isinstance(op, ast.Lt) and a == b:
                        return 0.95
                    # a satisfied upper bound still prefers slack, so the plan doesn't spend the allowance early
                    return 1.0 - 0.3 * max(a, 0) / b if b > 0 else 1.0
                return b / a if a > 0 and b >= 0 else 1.0 / (1.0 + a - b)
            if isinstance(op, ast.Eq):
                return 1.0 / (1.0 + abs(a - b))
    return 1.0 if safe_evaluate(ast.unparse(node), env) else 0.0


def progress(success_expr: str, obs: Observation, mem: dict) -> float:
    """Heuristic in [0, 1]: how close `obs` is to satisfying the success expression."""
    env = {"obs": obs.fields, "args": {}, "mem": mem, "t": obs.t}
    try:
        tree = ast.parse(success_expr.strip(), mode="eval").body
    except SyntaxError:
        return 0.0
    return float(_term(tree, env))


def _key(obs: Observation, p: Predictor) -> str:
    return json.dumps([obs.fields, p.mem, sorted(map(str, p.pending))], sort_keys=True, default=str)


class PlannerPolicy:
    """Replans every step: beam search of depth `depth` using the theory's predictor."""

    def __init__(self, theory: Theory, manual: WorldManual, objective: Objective, depth: int = 5, beam: int = 24):
        self.theory, self.manual, self.objective = theory, manual, objective
        self.depth, self.beam = depth, beam
        self.candidates = candidate_actions(manual)
        if not self.candidates:
            raise ValueError("manual has no actions to plan with")
        self.pred = Predictor(theory)
        self.last_plan: list[Action] = []

    def reset(self) -> None:
        self.pred = Predictor(self.theory)
        self.last_plan = []

    def _success(self, obs: Observation, mem: dict) -> bool:
        return bool(safe_evaluate(self.objective.success, {"obs": obs.fields, "args": {}, "mem": mem, "t": obs.t}))

    def plan(self, obs: Observation) -> list[Action]:
        root = self.pred.clone()
        beams: list[tuple[tuple[int, ...], Predictor, Observation]] = [((), root, obs)]
        best: tuple[float, tuple[int, ...]] | None = None
        for d in range(self.depth):
            expanded: list[tuple[float, tuple[int, ...], Predictor, Observation]] = []
            seen: set[str] = set()
            for seq, p0, o0 in beams:
                for i, action in enumerate(self.candidates):
                    p = p0.clone()
                    o = Observation(t=o0.t + 1, fields=p.predict(o0, action))
                    p.advance(o)
                    s = seq + (i,)
                    if self._success(o, p.mem):
                        val = SUCCESS - d
                    else:
                        val = progress(self.objective.success, o, p.mem) - 0.001 * d
                    if best is None or (-val, s) < (-best[0], best[1]):
                        best = (val, s)
                    if val < SUCCESS - self.depth:
                        k = _key(o, p)
                        if k not in seen:
                            seen.add(k)
                            expanded.append((val, s, p, o))
            if best is not None and best[0] >= SUCCESS - self.depth:
                break
            expanded.sort(key=lambda e: (-e[0], e[1]))
            beams = [(s, p, o) for _, s, p, o in expanded[: self.beam]]
            if not beams:
                break
        return [self.candidates[i] for i in (best[1] if best else (0,))]

    def next_action(self, obs: Observation) -> Action:
        if self.pred.obs is None or self.pred.obs.t != obs.t or self.pred.obs.fields != obs.fields:
            if self.pred.obs is None or obs.t <= self.pred.obs.t:
                self.pred.reset(obs)
            else:
                self.pred.obs = obs
        self.last_plan = self.plan(obs)
        action = self.last_plan[0]
        self.pred.predict(obs, action)  # stage so after_step can commit memory / delayed effects
        return action

    def after_step(self, obs: Observation) -> None:
        self.pred.advance(obs)

    def as_playbook_stub(self) -> Playbook:
        first = self.candidates[0]
        return Playbook(
            id=f"planner-{self.theory.world_id}-v{self.theory.version}",
            world_id=self.theory.world_id,
            objective_id=self.objective.id,
            theory_version=self.theory.version,
            origin="planner",
            rules=[],
            fallback=ActionTemplate(name=first.name, args={k: _lit(v) for k, v in first.args.items()}),
        )


def _lit(v: Any) -> str:
    return repr(v)
