"""Sessions: the boundary between hidden worlds and the scout.

The scout receives only `Session.port` (manual/reset/observe/act). `Session.admin` is for the
mission runner, referee and debrief, and must never be handed to scout code.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from logicscout import config
from logicscout.contracts import JSON, Action, Observation, ParamSpec, ShiftRecord, StepResult, WorldManual, WorldPort
from logicscout.worlds.base import World, load_all


class SandboxAdmin:
    """Privileged handle on a hidden world."""

    world_class: type[World]
    steps: int

    def shift(self, seed: int) -> ShiftRecord:
        raise NotImplementedError

    def success(self, objective_id: str) -> bool:
        raise NotImplementedError

    def truth(self) -> list[str]:
        raise NotImplementedError

    def laws(self) -> JSON:
        raise NotImplementedError


@dataclass
class Session:
    id: str
    world_id: str
    port: WorldPort
    admin: SandboxAdmin


def _find_world(world_id: str) -> type[World]:
    from logicscout.worlds.base import REGISTRY

    if world_id not in REGISTRY:
        try:
            load_all()
        except ImportError:
            pass
    if world_id not in REGISTRY:
        raise KeyError(f"unknown world {world_id!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[world_id]


def check_action(manual: WorldManual, action: Action) -> str | None:
    spec = next((a for a in manual.actions if a.name == action.name), None)
    if spec is None:
        return f"unknown action {action.name!r}; valid: {[a.name for a in manual.actions]}"
    names = {p.name for p in spec.params}
    for extra in sorted(set(action.args) - names):
        return f"unexpected argument {extra!r} for {action.name}"
    for p in spec.params:
        if p.name not in action.args:
            return f"missing argument {p.name!r} for {action.name}"
        err = _check_param(p, action.args[p.name])
        if err:
            return f"{action.name}.{p.name}: {err}"
    return None


def _check_param(p: ParamSpec, v: Any) -> str | None:
    if p.type == "bool":
        return None if isinstance(v, bool) else "expected bool"
    if p.type in ("int", "float"):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"expected {p.type}"
        if p.type == "int" and isinstance(v, float) and not v.is_integer():
            return "expected int"
        if p.min is not None and v < p.min:
            return f"below minimum {p.min}"
        if p.max is not None and v > p.max:
            return f"above maximum {p.max}"
        return None
    if not isinstance(v, str):
        return "expected string"
    if p.type == "enum" and p.choices is not None and v not in p.choices:
        return f"must be one of {p.choices}"
    return None


class LocalPort:
    """In-process port. Holds the world only inside closures: no attribute leads to it."""

    __slots__ = ("manual", "reset", "observe", "act")

    def __init__(self, world: World, counter: dict[str, int]) -> None:
        manual_ = world.manual()

        def reset(seed: int) -> Observation:
            lo, hi = manual_.lab_seeds
            if not (lo <= seed <= hi):
                raise ValueError(f"seed {seed} outside lab seeds {manual_.lab_seeds}")
            return world.reset(seed)

        def act(action: Action) -> StepResult:
            err = check_action(manual_, action)
            if err:
                return StepResult(observation=world.observe(), error=err)
            counter["steps"] += 1
            return world.act(action)

        self.manual = lambda: manual_
        self.reset = reset
        self.observe = lambda: world.observe()
        self.act = act


class LocalAdmin(SandboxAdmin):
    def __init__(self, world: World, counter: dict[str, int]) -> None:
        self._world = world
        self._counter = counter
        self.world_class = type(world)

    @property
    def steps(self) -> int:
        return self._counter["steps"]

    def shift(self, seed: int) -> ShiftRecord:
        return self._world.shift(seed)

    def success(self, objective_id: str) -> bool:
        return self._world.success(objective_id)

    def truth(self) -> list[str]:
        return self.world_class.truth(self._world.laws)

    def laws(self) -> JSON:
        return dict(self._world.laws)


def open_local(world_id: str, variant: str = "standard") -> Session:
    world = _find_world(world_id)(variant)
    counter = {"steps": 0}
    return Session(uuid.uuid4().hex[:12], world_id, LocalPort(world, counter), LocalAdmin(world, counter))


# ---- HTTP mode -------------------------------------------------------------------------


class _Http:
    def __init__(self, base: str, sid: str, headers: dict[str, str], client: httpx.Client | None = None) -> None:
        self._c = client or httpx.Client(base_url=base, timeout=30.0)
        self._p = f"/s/{sid}"
        self._h = headers

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        r = self._c.request(method, self._p + path, headers=self._h, **kw)
        if r.status_code in (400, 422):
            raise ValueError(r.json().get("detail", r.text))
        r.raise_for_status()
        return r.json()


class HttpPort(_Http):
    def manual(self) -> WorldManual:
        return WorldManual.model_validate(self._call("GET", "/manual"))

    def reset(self, seed: int) -> Observation:
        return Observation.model_validate(self._call("POST", "/reset", json={"seed": seed}))

    def observe(self) -> Observation:
        return Observation.model_validate(self._call("GET", "/observe"))

    def act(self, action: Action) -> StepResult:
        return StepResult.model_validate(self._call("POST", "/act", json={"action": action.model_dump()}))


class HttpAdmin(_Http, SandboxAdmin):
    def __init__(self, base: str, sid: str, headers: dict[str, str], world_id: str, client: httpx.Client | None = None):
        super().__init__(base, sid, headers, client)
        self.world_class = _find_world(world_id)

    @property
    def steps(self) -> int:
        return self._call("GET", "/admin/steps")["steps"]

    def shift(self, seed: int) -> ShiftRecord:
        return ShiftRecord.model_validate(self._call("POST", "/admin/shift", json={"seed": seed}))

    def success(self, objective_id: str) -> bool:
        return self._call("POST", "/admin/success", json={"objective_id": objective_id})["success"]

    def truth(self) -> list[str]:
        return self._call("GET", "/admin/truth")["truth"]

    def laws(self) -> JSON:
        return self._call("GET", "/admin/laws")["laws"]


def open_http(url: str, world_id: str, variant: str = "standard", client: httpx.Client | None = None) -> Session:
    c = client or httpx.Client(base_url=url, timeout=30.0)
    r = c.post("/sessions", json={"world_id": world_id, "variant": variant}, headers={"X-Admin-Token": config.SANDBOX_TOKEN})
    if r.status_code >= 400:
        raise RuntimeError(f"sandbox refused session: {r.status_code} {r.text}")
    d = r.json()
    sid = d["session_id"]
    port = HttpPort(url, sid, {"X-Scout-Token": d["scout_token"]}, c)
    admin = HttpAdmin(url, sid, {"X-Admin-Token": config.SANDBOX_TOKEN}, world_id, c)
    return Session(sid, world_id, port, admin)


def open_session(world_id: str, variant: str = "standard") -> Session:
    if config.SANDBOX_URL:
        return open_http(config.SANDBOX_URL, world_id, variant)
    return open_local(world_id, variant)
