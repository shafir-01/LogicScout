"""Gate world: a real HTTP job-dispatch controller (logicscout.worlds.gate_service)."""
from __future__ import annotations

import random
import uuid

import httpx

from logicscout import config
from logicscout.contracts import (
    JSON, Action, ActionSpec, Case, FieldSpec, Objective, Observation, ParamSpec, ShiftRecord, StepResult,
    WorldManual,
)
from logicscout.worlds.base import World, register
from logicscout.worlds.gate_service import DEFAULT_LAWS

ENDPOINTS = ["status", "create", "arm", "commit", "cancel"]
VARIANTS = {
    "standard": {},
    "tight_bucket": {"capacity": 2},
    "short_window": {"arm_window": 1},
    "single_slot": {"max_armed": 1},
    "slow_refill": {"refill_every": 3, "lockout": 10},
}


class GateUnavailable(RuntimeError):
    pass


@register
class Gate(World):
    world_id = "gate"

    def __init__(self, variant: str = "standard") -> None:
        super().__init__(variant)
        self.ns = f"gate-{uuid.uuid4().hex[:12]}"
        self.base_url = config.GATE_URL.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=10.0, headers={"X-Namespace": self.ns})
        self._admin = {"X-Admin-Token": config.SANDBOX_TOKEN}

    @classmethod
    def manual(cls) -> WorldManual:
        return WorldManual(
            world_id="gate", title="Field station job controller", domain="remote device command API",
            summary="An undocumented HTTP command API of a remote field station that dispatches jobs.",
            actions=[
                ActionSpec(name="call", description="Send one HTTP request to the controller.", params=[
                    ParamSpec(name="endpoint", type="enum", choices=ENDPOINTS,
                              description="status=GET /status, create=POST /jobs, arm/commit/cancel=POST /jobs/{job}/..."),
                    ParamSpec(name="job", type="int", min=0, max=9, description="job id (ignored for status/create)"),
                ]),
                ActionSpec(name="wait", description="Send nothing for one tick."),
            ],
            observations=[
                FieldSpec(name="t", type="int", description="controller clock"),
                FieldSpec(name="last_status", type="int", description="HTTP status of the last request"),
                FieldSpec(name="last_job", type="int", description="id returned by the last successful create (-1 none)"),
                FieldSpec(name="jobs_draft", type="int", description="jobs in draft state"),
                FieldSpec(name="jobs_armed", type="int", description="jobs in armed state"),
                FieldSpec(name="committed", type="int", description="jobs committed so far"),
                FieldSpec(name="locked", type="bool", description="controller refusing requests (423)"),
                FieldSpec(name="lockouts", type="int", description="number of lockouts so far"),
                FieldSpec(name="tokens", type="int", description="request allowance left on the controller's meter"),
                FieldSpec(name="strikes", type="int", description="consecutive refused requests counted toward a lockout"),
                FieldSpec(name="arm_age", type="int", description="ticks since the longest-armed job was armed (-1 none)"),
            ],
            objectives=[Objective(id="commit5", text="Commit 5 jobs without triggering a lockout",
                                  success="obs.committed >= 5 and obs.lockouts == 0", horizon=40)],
            probe_budget=50,
            safety=["obs.lockouts == 0"],  # operator alarm limits (public), not the hidden laws
            briefing_topics=[
                "REST API rate limiting token bucket 429 retry after",
                "two-phase commit arm then execute command timeout expires",
                "API lockout after repeated failed requests 423 locked",
            ],
            layout={"kind": "graph", "nodes": ["client", "gate", "jobs", "device"],
                    "edges": [["client", "gate"], ["gate", "jobs"], ["jobs", "device"]], "bind": {
                        "gate": ["last_status", "locked", "lockouts"], "jobs": ["jobs_draft", "jobs_armed"],
                        "device": ["committed"]}},
        )

    @classmethod
    def default_laws(cls, variant: str) -> JSON:
        return {**DEFAULT_LAWS, **VARIANTS[variant]}

    @classmethod
    def variants(cls) -> list[str]:
        return list(VARIANTS)

    def _post_admin(self, path: str, body: JSON) -> JSON:
        try:
            r = self.client.post(path, json=body, headers=self._admin)
        except httpx.HTTPError as e:
            raise GateUnavailable(f"gate service not reachable at {self.base_url} ({e}); "
                                  "start it with: uv run python -m logicscout.worlds.gate_service") from e
        r.raise_for_status()
        return r.json()

    def _peek(self) -> JSON:
        r = self.client.get("/_admin/peek", headers=self._admin)
        r.raise_for_status()
        return r.json()

    def _obs(self, v: JSON) -> Observation:
        self.t = v.pop("t")
        return Observation(t=self.t, fields=v)

    def reset(self, seed: int) -> Observation:
        self.rng = random.Random(seed)
        return self._obs(self._post_admin("/_admin/reset", {"seed": seed, "laws": self.laws}))

    def observe(self) -> Observation:
        return self._obs(self._peek())

    def act(self, action: Action) -> StepResult:
        if action.name == "wait":
            self.client.post("/tick")
        elif action.name == "call":
            ep = action.args.get("endpoint")
            if ep not in ENDPOINTS:
                return StepResult(observation=self.observe(), error=f"endpoint must be one of {ENDPOINTS}")
            if ep == "status":
                self.client.get("/status")
            elif ep == "create":
                self.client.post("/jobs")
            else:
                job = action.args.get("job")
                if not isinstance(job, int) or not 0 <= job <= 9:
                    return StepResult(observation=self.observe(), error="job must be an int in 0..9")
                self.client.post(f"/jobs/{job}/{ep}")
        else:
            return StepResult(observation=self.observe(), error=f"unknown action {action.name!r}")
        return StepResult(observation=self.observe(), cost=1.0)

    @classmethod
    def shift_menu(cls) -> list[dict]:
        return [
            {"id": "bucket_capacity_drop", "label": "Request bucket holds fewer tokens"},
            {"id": "arm_window_shortens", "label": "Armed state expires almost immediately"},
            {"id": "concurrency_drops", "label": "Only one item can be armed at a time"},
        ]

    def shift(self, seed: int, kind: str | None = None) -> ShiftRecord:
        rng = random.Random(seed)
        kind = kind or rng.choice(["bucket_capacity_drop", "arm_window_shortens", "concurrency_drops"])
        if kind not in {m["id"] for m in self.shift_menu()}:
            raise ValueError(f"unknown shift kind {kind!r}")
        key, new = {
            "bucket_capacity_drop": ("capacity", max(1, self.laws["capacity"] - 2)),
            "arm_window_shortens": ("arm_window", 1),
            "concurrency_drops": ("max_armed", 1),
        }[kind]
        before = dict(self.laws)
        self.laws[key] = new
        try:
            self._post_admin("/_admin/laws", {key: new})
        except httpx.HTTPStatusError:
            pass  # namespace not reset yet; laws apply on next reset
        return ShiftRecord(kind=kind, description=f"{key}: {before[key]} -> {new}", before=before,
                           after=dict(self.laws), at_t=self.t)

    def success(self, objective_id: str) -> bool:
        r = self.client.get("/_admin/success", headers=self._admin)
        r.raise_for_status()
        return bool(r.json().get(objective_id, False))

    @classmethod
    def truth(cls, laws: JSON) -> list[str]:
        return [
            f"Token bucket: capacity {laws['capacity']}, refills 1 token every {laws['refill_every']} ticks; "
            "create/arm/commit/cancel cost 1 token, empty bucket returns 429.",
            f"3 429s without backing off (a wait or GET /status in between) lock the controller for {laws['lockout']} ticks (everything returns 423).",
            "GET /status and waiting cost no tokens; every request ticks the clock once.",
            f"Commit succeeds only within {laws['arm_window']} ticks of arming; a stale arm returns 409 and "
            "the job falls back to draft.",
            f"At most {laws['max_armed']} jobs armed at once; arming another silently disarms the oldest.",
        ]

    @classmethod
    def referee_cases(cls) -> list[Case]:
        seeds = [10001, 10002, 10007, 10013, 10021, 10034]
        cases = [Case(case_id=f"gate-std-{s}", seed=s, objective_id="commit5") for s in seeds]
        cases += [Case(case_id=f"gate-{v}-{10100 + i}", seed=10100 + i, variant=v, objective_id="commit5")
                  for i, v in enumerate(list(VARIANTS)[1:])]
        return cases

    def close(self) -> None:
        self.client.close()
