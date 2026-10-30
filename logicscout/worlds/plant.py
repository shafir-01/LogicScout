"""Water-treatment plant: tank, inlet pump, outlet valve, pressure line. PRIVATE (hidden laws)."""
from __future__ import annotations

import random

from logicscout.contracts import (
    JSON, Action, ActionSpec, Case, FieldSpec, Objective, Observation, ParamSpec, ShiftRecord,
    StepResult, WorldManual,
)
from logicscout.worlds.base import World, register

_VARIANTS: dict[str, JSON] = {
    "standard": {},
    "long_line": {"delay": 3},
    "tight_trip": {"trip_above": 5},
    "strong_drain": {"drain_div": 6},
    "weak_pump": {"pump_gain": 4, "drain_div": 6},
}
_BASE: JSON = {
    "delay": 2,          # pump inflow lands this many steps later
    "pump_gain": 6,      # level units per pump rate unit
    "drain_div": 8,     # drain = level * valve_open // drain_div
    "p_pump": 3,         # pressure = max(0, p_pump*rate - p_valve*valve)
    "p_valve": 2,
    "trip_above": 7,     # pressure above this trips the pump
    "lockout": 4,        # steps forced off after a trip
    "valve_step": 1,     # max valve movement per step
}
OBJ_ID = "hold_band"


@register
class PlantWorld(World):
    world_id = "plant"

    @classmethod
    def manual(cls) -> WorldManual:
        return WorldManual(
            world_id="plant",
            title="Water-treatment tank",
            domain="industrial process control",
            summary="A treatment tank fed by an inlet pump and emptied through an outlet valve on a pressure line.",
            actions=[
                ActionSpec(name="pump", params=[ParamSpec(name="rate", type="int", min=0, max=3)],
                           description="Set the inlet pump rate."),
                ActionSpec(name="valve", params=[ParamSpec(name="open", type="int", min=0, max=2)],
                           description="Set the outlet valve position (actuator assumed instantaneous)."),
                ActionSpec(name="wait", description="Change nothing for one step."),
            ],
            observations=[
                FieldSpec(name="t", type="int", description="Step counter."),
                FieldSpec(name="level", type="int", description="Tank level, 0-100."),
                FieldSpec(name="pressure", type="int", description="Discharge line pressure."),
                FieldSpec(name="pump_rate", type="int", description="Current pump rate."),
                FieldSpec(name="valve_open", type="int", description="Current valve position."),
                FieldSpec(name="tripped", type="bool", description="Pump protection trip active."),
                FieldSpec(name="arriving", type="int",
                          description="Inflow from the pump that will reach the tank on the next step."),
                FieldSpec(name="in_band_streak", type="int",
                          description="Consecutive steps with level between 40 and 60."),
            ],
            objectives=[Objective(
                id=OBJ_ID, text="Hold tank level between 40 and 60 for 10 consecutive steps",
                success="obs.in_band_streak >= 10", horizon=45)],
            probe_budget=50,
            lab_seeds=(0, 1000),
            briefing_topics=[
                "centrifugal pump discharge pressure trip setpoint",
                "tank level control transport delay dead time",
                "control valve rate limit actuator",
            ],
            layout={
                "kind": "graph",
                "nodes": [{"id": n, "label": n.title()} for n in ("inlet", "pump", "tank", "valve", "outlet")],
                "edges": [["inlet", "pump"], ["pump", "tank"], ["tank", "valve"], ["valve", "outlet"]],
                "bind": {"pump": ["pump_rate", "pressure", "tripped", "arriving"], "tank": ["level", "in_band_streak"],
                         "valve": ["valve_open"]},
            },
        )

    @classmethod
    def default_laws(cls, variant: str) -> JSON:
        if variant not in _VARIANTS:
            raise ValueError(f"unknown plant variant {variant!r}")
        return {**_BASE, **_VARIANTS[variant]}

    @classmethod
    def variants(cls) -> list[str]:
        return list(_VARIANTS)

    def reset(self, seed: int) -> Observation:
        self.rng = random.Random(seed)
        self.t = 0
        self.level = self.rng.randint(5, 22) if self.rng.random() < 0.5 else self.rng.randint(78, 95)
        self.pump_rate = 0
        self.valve_open = 0
        self.pressure = 0
        self.lock = 0
        self.streak = 0
        self.pipe = [0] * int(self.laws["delay"])
        self.events: list[str] = []
        return self.observe()

    def observe(self) -> Observation:
        return Observation(t=self.t, events=list(self.events), fields={
            "t": self.t, "level": self.level, "pressure": self.pressure, "pump_rate": self.pump_rate,
            "valve_open": self.valve_open, "tripped": self.lock > 0,
            "arriving": self.pipe[0] if self.pipe else 0, "in_band_streak": self.streak})

    def act(self, action: Action) -> StepResult:
        L = self.laws
        err = None
        if action.name == "pump":
            r = action.args.get("rate")
            if not isinstance(r, int) or isinstance(r, bool) or not 0 <= r <= 3:
                err = "pump.rate must be an int 0-3"
            elif self.lock == 0:
                self.pump_rate = r
        elif action.name == "valve":
            v = action.args.get("open")
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 2:
                err = "valve.open must be an int 0-2"
            else:
                s = int(L["valve_step"])
                self.valve_open += max(-s, min(s, v - self.valve_open))
        elif action.name != "wait":
            err = f"unknown action {action.name!r}"
        if err:
            return StepResult(observation=self.observe(), error=err)

        self.events = []
        if self.lock > 0:
            self.lock -= 1
            self.pump_rate = 0
        self.pressure = max(0, L["p_pump"] * self.pump_rate - L["p_valve"] * self.valve_open)
        if self.pressure > L["trip_above"]:
            self.lock = int(L["lockout"])
            self.pump_rate = 0
            self.events.append("pump trip")
        while len(self.pipe) < int(L["delay"]):
            self.pipe.insert(0, 0)
        while len(self.pipe) > int(L["delay"]):
            self.pipe.pop(0)
        self.pipe.append(L["pump_gain"] * self.pump_rate)
        inflow = self.pipe.pop(0)
        drain = self.level * self.valve_open // L["drain_div"]
        self.level = max(0, min(100, self.level + inflow - drain))
        self.streak = self.streak + 1 if 40 <= self.level <= 60 else 0
        self.t += 1
        return StepResult(observation=self.observe())

    def clone(self) -> PlantWorld:
        w = PlantWorld.__new__(PlantWorld)
        w.__dict__.update(self.__dict__)
        w.laws, w.pipe, w.events = dict(self.laws), list(self.pipe), list(self.events)
        return w

    @classmethod
    def shift_menu(cls) -> list[dict]:
        return [
            {"id": "delay", "label": "Inflow takes one step longer to arrive"},
            {"id": "trip", "label": "Pump trips at a lower pressure"},
            {"id": "drain", "label": "Outlet drains at a different rate"},
        ]

    def shift(self, seed: int, kind: str | None = None) -> ShiftRecord:
        rng = random.Random(seed)
        kind = kind or rng.choice(["delay", "trip", "drain"])
        if kind not in {m["id"] for m in self.shift_menu()}:
            raise ValueError(f"unknown shift kind {kind!r}")
        before = dict(self.laws)
        if kind == "delay":
            self.laws["delay"] += 1
            desc = "inflow transport delay grew by one step"
        elif kind == "trip":
            self.laws["trip_above"] = max(3, self.laws["trip_above"] - 2)
            desc = "pump trip pressure setpoint lowered"
        else:
            self.laws["drain_div"] = 6 if self.laws["drain_div"] >= 8 else 10
            desc = "outlet drain gain changed"
        changed = [k for k in self.laws if self.laws[k] != before[k]]
        return ShiftRecord(kind=kind, description=desc, before={k: before[k] for k in changed},
                           after={k: self.laws[k] for k in changed}, at_t=self.t)

    def success(self, objective_id: str) -> bool:
        if objective_id != OBJ_ID:
            raise ValueError(f"unknown objective {objective_id!r}")
        return self.streak >= 10

    @classmethod
    def truth(cls, laws: JSON) -> list[str]:
        return [
            f"Pump inflow = {laws['pump_gain']} * pump_rate, landing in the tank {laws['delay']} steps later.",
            f"Drain each step = level * valve_open // {laws['drain_div']}; level clamped 0-100.",
            f"Pressure = max(0, {laws['p_pump']}*pump_rate - {laws['p_valve']}*valve_open).",
            f"Pressure above {laws['trip_above']} trips the pump: forced off for {laws['lockout']} steps, commands ignored.",
            f"The valve moves at most {laws['valve_step']} position per step toward the commanded value.",
        ]

    @classmethod
    def referee_cases(cls) -> list[Case]:
        cases = []
        for i, v in enumerate(cls.variants()):
            for j in range(2):
                seed = 10000 + 37 * i + j
                cases.append(Case(case_id=f"plant-{v}-{seed}", seed=seed, variant=v, objective_id=OBJ_ID))
        return cases
