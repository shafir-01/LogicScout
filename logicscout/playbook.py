"""Playbooks: compiled controllers that run without the model, and simulation inside a learned theory."""
from __future__ import annotations

import ast
import copy
from typing import Any, Protocol, runtime_checkable

from logicscout.contracts import Action, ActionTemplate, Observation, Playbook, Theory, WorldManual
from logicscout.dsl import safe_evaluate, validate
from logicscout.theory import Predictor


@runtime_checkable
class Policy(Protocol):
    def next_action(self, obs: Observation) -> Action: ...
    def after_step(self, obs: Observation) -> None: ...


def _env(obs: Observation, mem: dict) -> dict:
    return {"obs": obs.fields, "args": {}, "mem": mem, "t": obs.t}


def render(template: ActionTemplate, env: dict) -> Action:
    return Action(name=template.name, args={k: safe_evaluate(v, env) for k, v in template.args.items()})


class PlaybookRunner:
    """First rule whose `when` holds fires; otherwise the fallback. `updates` run after each step."""

    def __init__(self, playbook: Playbook):
        self.playbook = playbook
        self.reset()

    def reset(self) -> None:
        self.mem: dict = copy.deepcopy(self.playbook.memory)
        self.last_rule: int | None = None  # index of the rule that fired, None = fallback

    @property
    def last_why(self) -> str:
        if self.last_rule is None:
            return "fallback"
        return self.playbook.rules[self.last_rule].why or self.playbook.rules[self.last_rule].when

    def next_action(self, obs: Observation) -> Action:
        env = _env(obs, self.mem)
        for i, rule in enumerate(self.playbook.rules):
            if safe_evaluate(rule.when, env):
                self.last_rule = i
                return render(rule.do, env)
        self.last_rule = None
        return render(self.playbook.fallback, env)

    def after_step(self, obs: Observation) -> None:
        if not self.playbook.updates:
            return
        env = _env(obs, self.mem)
        new = {k: safe_evaluate(v, env) for k, v in self.playbook.updates.items()}
        self.mem.update(new)


def _literal(expr: str) -> tuple[bool, Any]:
    try:
        return True, ast.literal_eval(expr.strip())
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False, None


def _check_template(tpl: ActionTemplate, manual: WorldManual, where: str) -> list[str]:
    specs = {a.name: a for a in manual.actions}
    if tpl.name not in specs:
        return [f"{where}: unknown action {tpl.name!r}"]
    errors: list[str] = []
    params = {p.name: p for p in specs[tpl.name].params}
    for name in params:
        if name not in tpl.args:
            errors.append(f"{where}: action {tpl.name} missing arg {name!r}")
    for name, expr in tpl.args.items():
        if name not in params:
            errors.append(f"{where}: action {tpl.name} has no arg {name!r}")
            continue
        errs = validate(expr)
        errors += [f"{where} arg {name}: {e}" for e in errs]
        ok, val = _literal(expr) if not errs else (False, None)
        if not ok:
            continue
        p = params[name]
        if p.type == "enum" and p.choices is not None and val not in p.choices:
            errors.append(f"{where} arg {name}: {val!r} not in {p.choices}")
        elif p.type in ("int", "float"):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                errors.append(f"{where} arg {name}: expected {p.type}, got {val!r}")
            elif p.type == "int" and isinstance(val, float) and not val.is_integer():
                errors.append(f"{where} arg {name}: expected int, got {val!r}")
            elif (p.min is not None and val < p.min) or (p.max is not None and val > p.max):
                errors.append(f"{where} arg {name}: {val!r} outside [{p.min}, {p.max}]")
        elif p.type == "bool" and not isinstance(val, bool):
            errors.append(f"{where} arg {name}: expected bool, got {val!r}")
        elif p.type == "str" and not isinstance(val, str):
            errors.append(f"{where} arg {name}: expected str, got {val!r}")
    return errors


def quote_enum_literals(pb: Playbook, manual: WorldManual) -> Playbook:
    """Models often write an enum choice bare (create) where the DSL needs a string ('create')."""
    specs = {a.name: {p.name: p for p in a.params} for a in manual.actions}
    for tpl in [r.do for r in pb.rules] + [pb.fallback]:
        params = specs.get(tpl.name, {})
        for arg, expr in tpl.args.items():
            p = params.get(arg)
            if p and p.choices and expr.strip() in p.choices:
                tpl.args[arg] = repr(expr.strip())
    return pb


def validate_playbook(pb: Playbook, manual: WorldManual) -> list[str]:
    quote_enum_literals(pb, manual)
    errors: list[str] = []
    for i, rule in enumerate(pb.rules):
        errors += [f"rule {i} when: {e}" for e in validate(rule.when)]
        errors += _check_template(rule.do, manual, f"rule {i}")
    errors += _check_template(pb.fallback, manual, "fallback")
    for var, expr in pb.updates.items():
        errors += [f"update {var}: {e}" for e in validate(expr)]
    return errors


def simulate(policy: Policy, theory: Theory, start: Observation, success_expr: str, horizon: int) -> dict:
    """Run `policy` inside the learned theory (no real world). Pass a fresh policy."""
    pred = Predictor(theory)
    pred.reset(start)
    obs = start
    trace: list[dict] = []

    def ok(o: Observation) -> bool:
        return bool(safe_evaluate(success_expr, {"obs": o.fields, "args": {}, "mem": pred.mem, "t": o.t}))

    if ok(obs):
        return {"success": True, "steps": 0, "trace": trace}
    for step in range(1, horizon + 1):
        action = policy.next_action(obs)
        fields = pred.predict(obs, action)
        obs = Observation(t=obs.t + 1, fields=fields)
        pred.advance(obs)
        policy.after_step(obs)
        trace.append({"action": action.model_dump(), "predicted": fields})
        if ok(obs):
            return {"success": True, "steps": step, "trace": trace}
    return {"success": False, "steps": horizon, "trace": trace}
