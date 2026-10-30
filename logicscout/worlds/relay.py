"""Relay: a vessel forwards queued messages to shore via a solar buoy or a satellite uplink."""
from __future__ import annotations

import random

from logicscout.contracts import (
    JSON, Action, ActionSpec, Case, FieldSpec, Objective, Observation, ParamSpec,
    ShiftRecord, StepResult, WorldManual,
)
from logicscout.worlds.base import World, register

_VARIANTS: dict[str, JSON] = {
    "standard": {"period": 6, "window": 2, "buoy_cap": 2, "sat_latency": 2},
    "longwave": {"period": 8, "window": 3, "buoy_cap": 1, "sat_latency": 3},
    "storm": {"period": 5, "window": 1, "buoy_cap": 3, "sat_latency": 4},
    "calm": {"period": 7, "window": 2, "buoy_cap": 2, "sat_latency": 1},
}
_COMMON: JSON = {
    "battery_max": 4, "recharge_every": 3, "sat_cost": 3, "vessel_energy": 10,
    "arrival_every": 3, "lifo": True,
}


@register
class RelayWorld(World):
    world_id = "relay"

    @classmethod
    def manual(cls) -> WorldManual:
        return WorldManual(
            world_id="relay",
            title="Maritime message relay",
            domain="remote maritime communications",
            summary="A vessel holds a queue of outbound messages and can forward them to shore over two links.",
            actions=[
                ActionSpec(name="send", description="Forward messages from the vessel queue over a chosen link.",
                           params=[ParamSpec(name="via", type="enum", choices=["buoy", "sat"],
                                             description="Link to use: solar buoy relay or satellite uplink."),
                                   ParamSpec(name="n", type="int", min=1, max=3,
                                             description="How many messages to forward.")]),
                ActionSpec(name="prioritize", description="Ask the vessel's message handler to prioritize."),
                ActionSpec(name="wait", description="Do nothing this step."),
            ],
            observations=[
                FieldSpec(name="t", type="int", description="Step counter."),
                FieldSpec(name="queue", type="int", description="Messages waiting on the vessel."),
                FieldSpec(name="priority_waiting", type="int", description="Priority messages waiting on the vessel."),
                FieldSpec(name="next_deadline", type="int",
                          description="Steps left until the earliest waiting priority deadline (-1 if none)."),
                FieldSpec(name="vessel_energy", type="int", description="Vessel transmit energy."),
                FieldSpec(name="buoy_signal", type="int", description="Buoy status indicator (small integer, higher is stronger)."),
                FieldSpec(name="delivered", type="int", description="Messages confirmed at shore."),
                FieldSpec(name="priority_delivered", type="int",
                          description="Priority messages confirmed at shore by their deadline."),
                FieldSpec(name="lost", type="int", description="Messages that never reached shore."),
            ],
            objectives=[
                Objective(id="bulk8", text="Deliver 8 messages to shore while losing at most 2",
                          success="obs.delivered >= 8 and obs.lost <= 2", horizon=40),
                Objective(id="priority5", text="Deliver 5 priority messages to shore before their deadlines",
                          success="obs.priority_delivered >= 5", horizon=40),
            ],
            probe_budget=50,
            lab_seeds=(0, 1000),
            briefing_topics=[
                "store and forward messaging queue order FIFO",
                "satellite uplink message latency maritime",
                "ocean buoy solar battery transmit duty cycle low power",
            ],
            layout={
                "kind": "graph",
                "nodes": [
                    {"id": "vessel", "label": "Vessel", "x": 0.1, "y": 0.5},
                    {"id": "buoy", "label": "Solar buoy", "x": 0.5, "y": 0.75},
                    {"id": "sat", "label": "Satellite", "x": 0.5, "y": 0.15},
                    {"id": "shore", "label": "Shore", "x": 0.9, "y": 0.5},
                ],
                "edges": [
                    {"from": "vessel", "to": "buoy", "label": "send buoy"},
                    {"from": "vessel", "to": "sat", "label": "send sat"},
                    {"from": "buoy", "to": "shore", "label": "relay"},
                    {"from": "sat", "to": "shore", "label": "downlink"},
                ],
                "bind": {
                    "queue": "vessel", "priority_waiting": "vessel", "next_deadline": "vessel",
                    "vessel_energy": "sat", "buoy_signal": "buoy",
                    "delivered": "shore", "priority_delivered": "shore", "lost": "shore",
                },
            },
        )

    @classmethod
    def default_laws(cls, variant: str) -> JSON:
        if variant not in _VARIANTS:
            raise ValueError(f"unknown relay variant {variant!r}")
        return {**_COMMON, **_VARIANTS[variant]}

    @classmethod
    def variants(cls) -> list[str]:
        return list(_VARIANTS)

    def reset(self, seed: int) -> Observation:
        self.rng = random.Random(seed)
        self.t = 0
        self._next_id = 0
        self.queue: list[JSON] = []
        msgs = [self._msg(True, self.rng.randint(12, 30)) for _ in range(6)]
        msgs += [self._msg(False, self.rng.randint(30, 60)) for _ in range(6)]
        self.rng.shuffle(msgs)
        self.queue = msgs
        self.battery = self.laws["battery_max"]
        self.energy = self.laws["vessel_energy"]
        self.in_flight: list[tuple[int, JSON]] = []
        self.delivered = self.priority_delivered = self.lost = 0
        self.prioritized_last = False
        return self.observe()

    def _msg(self, priority: bool, deadline: int) -> JSON:
        self._next_id += 1
        return {"id": self._next_id, "priority": priority, "deadline": deadline}

    def observe(self) -> Observation:
        pri = [m["deadline"] for m in self.queue if m["priority"]]
        bm = self.laws["battery_max"]
        signal = 0 if self.battery <= 0 else min(3, -(-self.battery * 3 // bm))
        return Observation(t=self.t, fields={
            "t": self.t, "queue": len(self.queue), "priority_waiting": len(pri),
            "next_deadline": (min(pri) - self.t) if pri else -1,
            "vessel_energy": self.energy, "buoy_signal": signal,
            "delivered": self.delivered, "priority_delivered": self.priority_delivered, "lost": self.lost,
        })

    def _take(self, n: int, ordered: bool) -> list[JSON]:
        if ordered:
            order = sorted(self.queue, key=lambda m: (not m["priority"], m["deadline"], m["id"]))
        elif self.laws["lifo"]:
            order = list(reversed(self.queue))
        else:
            order = list(self.queue)
        picked = order[:n]
        ids = {m["id"] for m in picked}
        self.queue = [m for m in self.queue if m["id"] not in ids]
        return picked

    def _land(self, m: JSON, at: int) -> None:
        self.delivered += 1
        if m["priority"] and at <= m["deadline"]:
            self.priority_delivered += 1

    def act(self, action: Action) -> StepResult:
        name, args = action.name, action.args
        if name not in {"send", "prioritize", "wait"}:
            return StepResult(observation=self.observe(), error=f"unknown action {name!r}")
        if name == "send":
            via, n = args.get("via"), args.get("n")
            if via not in {"buoy", "sat"}:
                return StepResult(observation=self.observe(), error="via must be 'buoy' or 'sat'")
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 3:
                return StepResult(observation=self.observe(), error="n must be an integer 1-3")
        L, t, cost = self.laws, self.t, 0.0
        ordered = self.prioritized_last
        self.prioritized_last = name == "prioritize"
        if name == "send":
            msgs = self._take(n, ordered)
            if via == "buoy":
                open_ = t % L["period"] < L["window"]
                for i, m in enumerate(msgs):
                    if open_ and i < L["buoy_cap"] and self.battery > 0:
                        self.battery -= 1
                        self._land(m, t)
                    else:
                        self.lost += 1
            else:
                for m in msgs:
                    if self.energy >= L["sat_cost"]:
                        self.energy -= L["sat_cost"]
                        cost += L["sat_cost"]
                        self.in_flight.append((t + L["sat_latency"], m))
                    else:
                        self.lost += 1
        self.t = t = t + 1
        landed = [m for at, m in self.in_flight if at <= t]
        self.in_flight = [(at, m) for at, m in self.in_flight if at > t]
        for m in landed:
            self._land(m, t)
        if t % L["recharge_every"] == 0:
            self.battery = min(L["battery_max"], self.battery + 1)
        if t % L["arrival_every"] == 0:
            self.queue.append(self._msg(False, t + self.rng.randint(20, 40)))
        expired = [m for m in self.queue if m["deadline"] < t]
        if expired:
            self.lost += len(expired)
            self.queue = [m for m in self.queue if m["deadline"] >= t]
        return StepResult(observation=self.observe(), cost=cost)

    @classmethod
    def shift_menu(cls) -> list[dict]:
        return [
            {"id": "window_period", "label": "Contact window becomes longer and less frequent"},
            {"id": "sat_latency", "label": "Satellite route gets slower"},
            {"id": "buoy_capacity", "label": "Buoy can carry fewer messages at once"},
        ]

    def shift(self, seed: int, kind: str | None = None) -> ShiftRecord:
        kind = kind or ["window_period", "sat_latency", "buoy_capacity"][seed % 3]
        if kind not in {m["id"] for m in self.shift_menu()}:
            raise ValueError(f"unknown shift kind {kind!r}")
        key = {"window_period": "period", "sat_latency": "sat_latency", "buoy_capacity": "buoy_cap"}[kind]
        before = self.laws[key]
        after = {"period": before * 3 // 2, "sat_latency": before + 2, "buoy_cap": max(1, before - 1)}[key]
        if after == before:
            after = before + 1
        self.laws[key] = after
        return ShiftRecord(kind=kind, description=f"{key} changed from {before} to {after}",
                           before={key: before}, after={key: after}, at_t=self.t)

    def success(self, objective_id: str) -> bool:
        if objective_id == "priority5":
            return self.priority_delivered >= 5
        if objective_id == "bulk8":
            return self.delivered >= 8 and self.lost <= 2
        raise ValueError(f"unknown objective {objective_id!r}")

    @classmethod
    def truth(cls, laws: JSON) -> list[str]:
        return [
            f"The buoy link only works when t mod {laws['period']} is below {laws['window']}; "
            "sends outside that window are silently lost.",
            f"The buoy carries at most {laws['buoy_cap']} messages per send; extra messages are lost.",
            f"The buoy battery holds {laws['battery_max']} sends, each message costs 1, it recovers 1 every "
            f"{laws['recharge_every']} steps; at 0 messages are lost. buoy_signal is a coarse 0-3 battery gauge.",
            f"Satellite sends always work but cost {laws['sat_cost']} vessel energy per message "
            f"(start {laws['vessel_energy']}) and arrive {laws['sat_latency']} steps later.",
            "The queue is served newest-first (LIFO) unless prioritize was used on the previous step, "
            "in which case priority messages with the earliest deadline go first.",
            f"A new routine message arrives every {laws['arrival_every']} steps; queued messages past their "
            "deadline are dropped and counted as lost.",
        ]

    @classmethod
    def referee_cases(cls) -> list[Case]:
        cases = []
        for i, v in enumerate(cls.variants()):
            for j, obj in enumerate(["priority5", "bulk8"]):
                seed = 10000 + 101 * i + 7 * j
                cases.append(Case(case_id=f"relay-{v}-{obj}-{seed}", seed=seed, variant=v, objective_id=obj))
        return cases
