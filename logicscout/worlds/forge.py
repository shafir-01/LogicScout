"""Forge: procedurally generated unknown systems. PRIVATE (hidden laws).

A seed composes 3-5 mechanisms (logicscout/worlds/mechanisms.py) over neutral components, so no one
has seen the system before a run. Variant "standard" = seed 1; variant "g<seed>" = any seed.
Each instance carries its own manual: `world.manual()` on an instance returns the per-variant manual
(an instance attribute shadows the classmethod); `ForgeWorld.manual_for(variant)` does the same.
"""
from __future__ import annotations

import copy
import math
import random
import re
from functools import lru_cache

from logicscout.contracts import (
    JSON, Action, ActionSpec, Case, FieldSpec, Objective, Observation, ParamSpec, ShiftRecord,
    StepResult, WorldManual,
)
from logicscout.worlds.base import World, register
from logicscout.worlds.mechanisms import LEVELS, SHIFT_LABELS, SINCE_CAP, action_list, describe, generate_laws, mutate

OBJ_ID = "reach"
STANDARD_SEED = 1
_FIELD_TYPES = {"ready": "bool"}
_CAL_BEAM = 48


VARIANT_RE = re.compile(r"^g\d{1,6}$")


def variant_seed(variant: str) -> int:
    if variant == "standard":
        return STANDARD_SEED
    if isinstance(variant, str) and VARIANT_RE.match(variant):
        return int(variant[1:])
    raise ValueError(f"unknown forge variant {variant!r}; use 'standard' or 'g<seed>'")


class _Sim:
    """Plain-Python state machine for one generated system (fast; used by the world and calibration)."""

    __slots__ = ("L", "t", "f", "res", "cd", "lock", "since", "pipe")

    def __init__(self, L: JSON) -> None:
        self.L = L

    def reset(self, seed: int) -> None:
        L, F = self.L, self.L["names"]["fields"]
        rng = random.Random(seed)
        self.t = 0
        self.f = {k: 0 for k in F}
        self.f["out"] = rng.randint(0, 2)
        if "set" in F:
            self.f["set"] = rng.randint(0, LEVELS - 1)
        if "ready" in F:
            self.f["ready"] = True
        if "last" in F:
            self.f["last"] = -1
        self.res = L.get("res_max", 0)
        if "gauge" in F:
            self.f["gauge"] = self.res // L["gauge_step"]
        self.cd = self.lock = 0
        self.since = SINCE_CAP
        self.pipe = [0] * self._d()

    def _d(self) -> int:
        return int(self.L.get("delay_steps", 0)) if "delay" in self.L["mechanisms"] else 0

    def clone(self) -> _Sim:
        s = _Sim.__new__(_Sim)
        s.L, s.t, s.res, s.cd, s.lock, s.since = self.L, self.t, self.res, self.cd, self.lock, self.since
        s.f, s.pipe = dict(self.f), list(self.pipe)
        return s

    def key(self) -> tuple:
        return (tuple(sorted(self.f.items())), self.res, self.cd, self.lock, self.since, tuple(self.pipe),
                self.t % self.L.get("window_period", 1))

    def step(self, role: str, level: int = 0) -> None:
        L, m, f = self.L, self.L["mechanisms"], self.f
        gates = role == "P"
        if "window" in m:
            gates = gates and self.t % L["window_period"] < L["window_open"]
        if "cooldown" in m:
            gates = gates and self.cd == 0
        if "threshold" in m:
            gates = gates and self.lock == 0
        if "ordering" in m:
            gates = gates and self.since < L["order_within"]
        if "resource" in m:
            gates = gates and self.res >= L["res_cost"]
        gain = L["gain"] + (L["bonus"] * f["set"] if "control" in m else 0)
        cap = "capacity" in m
        tgt = "buf" if cap else "out"

        d = self._d()
        while len(self.pipe) < d:
            self.pipe.insert(0, 0)
        while len(self.pipe) > d:
            landed_extra = self.pipe.pop(0)
            if self.pipe:
                self.pipe[0] += landed_extra
        landed = 0
        if d:
            landed = self.pipe.pop(0)
            self.pipe.append(gain if gates else 0)
        elif gates:
            landed = gain

        if role == "transfer":
            f["out"] += f["buf"]
            f["buf"] = 0
        if role == "decoy":
            f["out"] = max(0, f["out"] - 1)
        f[tgt] = min(L["cap"], f[tgt] + landed) if cap else f[tgt] + landed

        if "cooldown" in m:
            self.cd = L["cooldown_steps"] if gates else max(0, self.cd - 1)
        if "ordering" in m:
            self.since = 0 if role == "A" else min(self.since + 1, SINCE_CAP)
        if "resource" in m:
            self.res = min(L["res_max"], self.res - (L["res_cost"] if gates else 0) + L["res_regen"])
            f["gauge"] = self.res // L["gauge_step"]
        if "threshold" in m:
            f["heat"] = max(0, f["heat"] - 1) + (L["heat_per_use"] if gates else 0)
            if self.lock == 0 and f["heat"] > L["heat_limit"]:
                self.lock = L["lockout_steps"]
            else:
                self.lock = max(0, self.lock - 1)
            f["ready"] = self.lock == 0
        if role == "tune":
            if L["control_mode"] == "inverted":
                f["set"] = LEVELS - 1 - level
            else:
                f["set"] += (level > f["set"]) - (level < f["set"])
        if "uses" in f:
            f["uses"] += role == "P"
        if "idle" in f:
            f["idle"] = f["idle"] + 1 if role == "hold" else 0
        if "moves" in f:
            f["moves"] += role != "hold"
        if "last" in f:
            f["last"] = self.L["names"]["order"].index(role)
        self.t += 1

    def potential(self) -> float:
        return self.f["out"] + self.f.get("buf", 0) + sum(self.pipe)


def _moves(L: JSON) -> list[tuple[str, int]]:
    out = []
    for r in L["names"]["order"]:
        out += [(r, lv) for lv in range(LEVELS)] if r == "tune" else [(r, 0)]
    return out


def beam_best(sim: _Sim, horizon: int, width: int = _CAL_BEAM) -> int:
    """Best `out` a beam search over the TRUE laws reaches within `horizon` steps."""
    moves = _moves(sim.L)
    beam, best = [sim], sim.f["out"]
    for _ in range(horizon):
        seen: dict[tuple, _Sim] = {}
        for s in beam:
            for role, lv in moves:
                n = s.clone()
                n.step(role, lv)
                seen.setdefault(n.key(), n)
        beam = sorted(seen.values(), key=lambda s: (s.potential(), s.f["out"]), reverse=True)[:width]
        best = max(best, max(s.f["out"] for s in beam))
    return best


@lru_cache(maxsize=256)
def _generate(seed: int) -> tuple[str, WorldManual]:
    import json

    rng = random.Random(seed * 7 + 3)
    horizon = rng.randint(24, 36)
    for attempt in range(50):  # reject systems where spamming the producer already reaches the target
        L = generate_laws(seed, attempt)
        worst = min(beam_best(_start(L, s, 0), horizon) for s in range(4))
        target = max(4, math.ceil(0.8 * worst))
        if spam_best(L, horizon) < target:
            break
    else:
        raise RuntimeError(f"forge seed {seed}: no system resists producer spam")
    return json.dumps(L), _build_manual(seed, L, target, horizon)


def _start(L: JSON, seed: int, out: int | None = None) -> _Sim:
    sim = _Sim(L)
    sim.reset(seed)
    if out is not None:
        sim.f["out"] = out
    return sim


def spam_best(L: JSON, horizon: int) -> int:
    """Best `out` from using only the producer, over every possible start (output 2, each setting)."""
    best = 0
    for lv in range(LEVELS if "control" in L["mechanisms"] else 1):
        sim = _start(L, 0, 2)
        if "set" in sim.f:
            sim.f["set"] = lv
        for _ in range(horizon):
            sim.step("P")
        best = max(best, sim.f["out"])
    return best


def _build_manual(seed: int, L: JSON, target: int, horizon: int) -> WorldManual:
    N, F = L["names"], L["names"]["fields"]
    actions = []
    for r in N["order"]:
        params = [ParamSpec(name="level", type="int", min=0, max=LEVELS - 1)] if r == "tune" else []
        actions.append(ActionSpec(name=N[r], params=params, description=f"Operate control '{N[r]}'."))
    desc = {"out": "Main reading (the objective counts this).", "last": "Code of the last control used."}
    obs = [FieldSpec(name="t", type="int", description="Step counter.")] + [
        FieldSpec(name=v, type=_FIELD_TYPES.get(k, "int"), description=desc.get(k, "Instrument reading."))
        for k, v in F.items()]
    comps = ["intake", "core", "stage", "sink"]
    bind = {"core": [F[k] for k in ("set", "heat", "ready", "uses", "last") if k in F],
            "intake": [F[k] for k in ("gauge", "idle", "moves") if k in F],
            "stage": [F["buf"]] if "buf" in F else [], "sink": [F["out"]]}
    return WorldManual(
        world_id="forge",
        title=f"Unknown system #{seed}",
        domain="Generated",
        summary="A machine assembled from unlabeled components; nobody has documented how it behaves.",
        actions=actions,
        observations=obs,
        objectives=[Objective(id=OBJ_ID, text=f"Reach {F['out']} >= {target} within {horizon} steps",
                              success=f"obs.{F['out']} >= {target}", horizon=horizon)],
        probe_budget=60,
        lab_seeds=(0, 1000),
        briefing_topics=[],
        layout={"kind": "graph", "nodes": [{"id": c, "label": c.title()} for c in comps],
                "edges": [["intake", "core"], ["core", "stage"], ["stage", "sink"]], "bind": bind},
    )


@register
class ForgeWorld(World):
    world_id = "forge"

    def __init__(self, variant: str = "standard") -> None:
        super().__init__(variant)
        self.seed = variant_seed(variant)
        self.instance_manual: WorldManual = self.manual_for(variant)
        self.manual = lambda: self.instance_manual  # type: ignore[method-assign]  # shadows the classmethod
        obj = self.instance_manual.objectives[0]
        self.target = int(obj.success.rsplit(">=", 1)[1])
        self.sim = _Sim(self.laws)
        self.roles = {self.laws["names"][r]: r for r in self.laws["names"]["order"]}
        self.reset(0)

    # ---- public --------------------------------------------------------------------------
    @classmethod
    def manual(cls) -> WorldManual:
        return cls.manual_for("standard")

    @classmethod
    def manual_for(cls, variant: str) -> WorldManual:
        return _generate(variant_seed(variant))[1].model_copy(deep=True)

    @classmethod
    def generate(cls, seed: int) -> ForgeWorld:
        return cls(f"g{seed}")

    def reset(self, seed: int) -> Observation:
        self.rng = random.Random(seed)
        self.sim.reset(seed)
        self.t = 0
        return self.observe()

    def observe(self) -> Observation:
        F = self.laws["names"]["fields"]
        return Observation(t=self.sim.t, fields={"t": self.sim.t, **{F[k]: v for k, v in self.sim.f.items()}})

    def act(self, action: Action) -> StepResult:
        role = self.roles.get(action.name)
        if role is None:
            return StepResult(observation=self.observe(), error=f"unknown action {action.name!r}")
        level = 0
        if role == "tune":
            level = action.args.get("level")
            if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level < LEVELS:
                return StepResult(observation=self.observe(), error=f"{action.name}.level must be an int 0-{LEVELS - 1}")
        self.sim.step(role, level)
        self.t = self.sim.t
        return StepResult(observation=self.observe())

    def clone(self) -> ForgeWorld:
        w = ForgeWorld.__new__(ForgeWorld)
        w.__dict__.update(self.__dict__)
        w.laws = copy.deepcopy(self.laws)
        w.sim = self.sim.clone()
        w.sim.L = w.laws
        w.manual = lambda: w.instance_manual
        return w

    # ---- private -------------------------------------------------------------------------
    @classmethod
    def default_laws(cls, variant: str) -> JSON:
        import json

        return json.loads(_generate(variant_seed(variant))[0])

    @classmethod
    def variants(cls) -> list[str]:
        return ["standard"]

    @classmethod
    def shift_menu(cls) -> list[dict]:
        return [{"id": k, "label": v} for k, v in SHIFT_LABELS.items()]

    def shift(self, seed: int, kind: str | None = None) -> ShiftRecord:
        """`kind` is honoured when this generated system has that mechanism; otherwise one it has is chosen."""
        before = copy.deepcopy(self.laws)
        kind, desc = mutate(self.laws, random.Random(seed), kind)
        changed = [k for k in self.laws if self.laws[k] != before[k]]
        return ShiftRecord(kind=kind, description=desc, before={k: before[k] for k in changed},
                           after={k: self.laws[k] for k in changed}, at_t=self.t)

    def success(self, objective_id: str) -> bool:
        if objective_id != OBJ_ID:
            raise ValueError(f"unknown objective {objective_id!r}")
        return self.sim.f["out"] >= self.target

    @classmethod
    def truth(cls, laws: JSON) -> list[str]:
        return describe(laws)

    @classmethod
    def referee_cases(cls) -> list[Case]:
        return cls.referee_cases_for("standard")

    @classmethod
    def referee_cases_for(cls, variant: str) -> list[Case]:
        variant_seed(variant)
        return [Case(case_id=f"forge-{variant}-{s}", seed=s, variant=variant, objective_id=OBJ_ID)
                for s in (10001, 10002, 10003, 10004, 10005, 10006)]


__all__ = ["ForgeWorld", "OBJ_ID", "action_list", "beam_best", "spam_best", "variant_seed", "VARIANT_RE"]
