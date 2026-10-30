"""Operator safety limits: checked on every real observation, enforced on predictions before acting.

A world's manual may declare `safety`: DSL boolean expressions over obs.* that must always hold (the
plant's alarm limits, published to the operator like any real installation's). They are not the hidden
laws. Two uses:

- measurement: `violations(manual, fields)` lists the limits a reading breaks (pure; the referee uses it);
- prevention: `SafeGuard` wraps a control policy and `safe_prefix` truncates experiments, both using the
  scout's learned theory to predict the next reading. Prevention is only as good as that theory: a limit
  the theory cannot foresee is not blocked, which is why real breaches are still logged and counted.
"""
from __future__ import annotations

from typing import Any

from logicscout.contracts import Action, Observation, Theory, WorldManual
from logicscout.dsl import safe_evaluate
from logicscout.theory import Predictor

NOOP_NAMES = ("wait", "hold", "idle", "noop", "status")


def violations(manual: WorldManual, obs_fields: dict | Observation) -> list[str]:
    """Safety expressions that evaluate to a definite falsy value on `obs_fields`.
    An expression that cannot be evaluated (missing field, unknown prediction) is not a violation."""
    fields = obs_fields.fields if isinstance(obs_fields, Observation) else (obs_fields or {})
    env = {"obs": fields, "args": {}, "mem": {}, "t": fields.get("t")}
    out = []
    for expr in getattr(manual, "safety", None) or []:
        v = safe_evaluate(expr, env)
        if v is not None and not v:
            out.append(expr)
    return out


def new_violations(manual: WorldManual, before: dict | Observation, after: dict | Observation) -> list[str]:
    """Limits broken in `after` that held (or were unknown) in `before`."""
    held = set(violations(manual, before))
    return [e for e in violations(manual, after) if e not in held]


def _rollout(theory: Theory, start: Observation, actions: list[Action]) -> list[dict]:
    p = Predictor(theory)
    p.reset(start)
    obs, out = start, []
    for a in actions:
        fields = p.predict(obs, a)
        fields["t"] = obs.t + 1
        obs = Observation(t=obs.t + 1, fields=fields)
        p.advance(obs)
        out.append(fields)
    return out


def safe_prefix(theory: Theory, start_obs: Observation, actions: list[Action], manual: WorldManual) -> int:
    """How many leading actions the theory predicts keep every limit that holds at the start."""
    if not getattr(manual, "safety", None) or not actions:
        return len(actions)
    try:
        preds = _rollout(theory, start_obs, actions)
    except Exception:
        return len(actions)
    before = start_obs.fields
    for i, fields in enumerate(preds):
        if new_violations(manual, before, fields):
            return i
        before = fields
    return len(actions)


def probe_is_safe(theory: Theory, start_obs: Observation, actions: list[Action], manual: WorldManual) -> bool:
    """True when the theory predicts no limit is newly broken anywhere along the experiment."""
    return safe_prefix(theory, start_obs, actions, manual) == len(actions)


def record(log: Any, manual: WorldManual, before: dict | Observation, after: dict | Observation) -> list[str]:
    """Log each limit newly broken by a real step as a `safety.violation` event; returns those limits."""
    fields = after.fields if isinstance(after, Observation) else after
    broken = new_violations(manual, before, after)
    for expr in broken:
        log.append("safety.violation", {"fields": dict(fields), "expr": expr, "phase": log.phase})
    return broken


def _distance(a: Action, b: Action, manual: WorldManual) -> float:
    if a.name != b.name:
        return 5.0 if b.name in NOOP_NAMES else 10.0
    spec = {p.name: p for s in manual.actions if s.name == a.name for p in s.params}
    d = 0.0
    for k in set(a.args) | set(b.args):
        x, y = a.args.get(k), b.args.get(k)
        if x == y:
            continue
        p = spec.get(k)
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
            span = (p.max - p.min) if p is not None and p.max is not None and p.min is not None else 0
            d += abs(x - y) / span if span else 1.0
        else:
            d += 1.0
    return d


class SafeGuard:
    """Policy wrapper: before each action, predict the next reading with the learned theory; if the
    action is predicted to break a limit, substitute the closest candidate predicted to break fewer
    (ideally none). The original action is kept when nothing better is predicted."""

    def __init__(self, policy: Any, theory: Theory, manual: WorldManual,
                 candidates: list[Action] | None = None) -> None:
        self.policy, self.theory, self.manual = policy, theory, manual
        if candidates is None:
            from logicscout.planner import candidate_actions
            candidates = candidate_actions(manual)
        self.candidates = list(candidates)
        self.pred = Predictor(theory)
        self.blocked = 0
        self.blocks: list[dict] = []
        self._why: str | None = None

    def __getattr__(self, name: str) -> Any:  # last_plan, playbook, ... of the wrapped policy
        if name == "policy":
            raise AttributeError(name)
        return getattr(self.policy, name)

    @property
    def last_why(self) -> str:
        return self._why or getattr(self.policy, "last_why", "")

    def reset(self) -> None:
        self.pred = Predictor(self.theory)
        if hasattr(self.policy, "reset"):
            self.policy.reset()

    def _sync(self, obs: Observation) -> None:
        if self.pred.obs is None or obs.t <= self.pred.obs.t:
            self.pred.reset(obs)
        else:
            self.pred.obs = obs

    def _risk(self, obs: Observation, action: Action) -> list[str]:
        try:
            return new_violations(self.manual, obs.fields, self.pred.clone().predict(obs, action))
        except Exception:
            return []

    def next_action(self, obs: Observation) -> Action:
        self._sync(obs)
        self._why = None
        action = self.policy.next_action(obs)
        if getattr(self.manual, "safety", None):
            risk = self._risk(obs, action)
            if risk:
                best: tuple[int, float, int] | None = None
                for i, c in enumerate(self.candidates):
                    n = len(self._risk(obs, c))
                    key = (n, _distance(action, c, self.manual), i)
                    if n < len(risk) and (best is None or key < best):
                        best = key
                if best is not None:
                    chosen = self.candidates[best[2]]
                    self.blocked += 1
                    self.blocks.append({"t": obs.t, "blocked": action.model_dump(), "chosen": chosen.model_dump(),
                                        "limits": risk})
                    self._why = f"safety guard: {action.name} predicted to break {risk[0]}"
                    action = chosen
        try:
            self.pred.predict(obs, action)  # staged; after_step commits memory / delayed effects
        except Exception:
            pass
        return action

    def after_step(self, obs: Observation) -> None:
        try:
            self.pred.advance(obs)
        except Exception:
            self.pred.reset(obs)
        self.policy.after_step(obs)
