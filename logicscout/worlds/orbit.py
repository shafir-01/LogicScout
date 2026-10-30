"""Orbit: an Earth-observation payload console with undocumented command semantics. Synthetic."""
from __future__ import annotations

import random

from logicscout.contracts import (
    JSON, Action, ActionSpec, Case, FieldSpec, Objective, Observation, ParamSpec, ShiftRecord,
    StepResult, WorldManual,
)
from logicscout.worlds.base import World, register

_BASE: JSON = {
    "bus_warmup": 2, "gain": 0.25, "warm": 28.0, "cold": 0.0, "band": [14.0, 22.0],
    "cal_window": 6, "cal_cooldown": 4, "pass_period": 12, "pass_len": 4, "pass_offset": 3,
    "capacity": 2,
}
_VARIANTS: dict[str, JSON] = {
    "standard": {},
    "warm_band": {"band": [18.0, 25.0]},
    "short_cal": {"cal_window": 4, "cal_cooldown": 5},
    "fast_pass": {"pass_period": 9, "pass_len": 3, "pass_offset": 7},
    "cool_band": {"band": [9.0, 16.0], "pass_offset": 0},
}


@register
class OrbitWorld(World):
    world_id = "orbit"

    @classmethod
    def manual(cls) -> WorldManual:
        onoff = ParamSpec(name="state", type="enum", choices=["on", "off"])
        return WorldManual(
            world_id="orbit",
            title="Orbit payload console",
            domain="spacecraft operations",
            summary="Command console of an Earth-observation satellite: power, thermal, imaging and downlink.",
            actions=[
                ActionSpec(name="power", params=[ParamSpec(name="unit", type="enum", choices=["bus", "payload"]), onoff],
                           description="Switch a power unit."),
                ActionSpec(name="heater", params=[onoff], description="Switch the detector heater."),
                ActionSpec(name="calibrate", description="Run the detector calibration routine."),
                ActionSpec(name="capture", description="Take an image into onboard storage."),
                ActionSpec(name="downlink", description="Transmit a stored image to the ground."),
                ActionSpec(name="wait", description="Do nothing for one step."),
            ],
            observations=[
                FieldSpec(name="t", type="int", description="Step counter."),
                FieldSpec(name="bus_on", type="bool", description="Spacecraft bus power."),
                FieldSpec(name="payload_on", type="bool", description="Imaging payload power."),
                FieldSpec(name="fault", type="bool", description="Payload fault flag."),
                FieldSpec(name="heater_on", type="bool", description="Detector heater switch."),
                FieldSpec(name="temp", type="float", description="Detector temperature reading."),
                FieldSpec(name="stored", type="int", description="Images in onboard storage."),
                FieldSpec(name="valid_stored", type="int", description="Stored images passing quality check."),
                FieldSpec(name="downlinked", type="int", description="Good images received on the ground."),
            ],
            objectives=[Objective(id="downlink3", text="Downlink 3 valid images",
                                  success="obs.downlinked >= 3", horizon=50)],
            probe_budget=60,
            lab_seeds=(0, 1000),
            briefing_topics=[
                "spacecraft payload power-on sequencing bus",
                "CCD detector temperature stabilization before imaging",
                "ground station pass downlink window LEO",
                "onboard image storage management satellite",
            ],
            layout={
                "kind": "graph",
                "nodes": [{"id": n} for n in ["bus", "payload", "heater", "detector", "storage", "ground"]],
                "edges": [["bus", "payload"], ["heater", "detector"], ["payload", "detector"],
                          ["detector", "storage"], ["storage", "ground"]],
                "bind": {"bus_on": "bus", "payload_on": "payload", "fault": "payload", "heater_on": "heater",
                         "temp": "detector", "stored": "storage", "valid_stored": "storage",
                         "downlinked": "ground"},
            },
        )

    @classmethod
    def default_laws(cls, variant: str) -> JSON:
        if variant not in _VARIANTS:
            raise ValueError(f"unknown orbit variant {variant!r}")
        laws = {**_BASE, **_VARIANTS[variant]}
        laws["band"] = list(laws["band"])
        return laws

    @classmethod
    def variants(cls) -> list[str]:
        return list(_VARIANTS)

    def reset(self, seed: int) -> Observation:
        self.seed = seed
        self.rng = random.Random(seed)
        self.t = 0
        self.phase = self.rng.randrange(1000)
        self.bus_on = self.payload_on = self.fault = self.heater_on = False
        self.bus_steps = 0
        self.temp = round(self.rng.uniform(0.0, 6.0), 1)
        self.last_cal: int | None = None
        self.last_cal_try: int | None = None
        self.images: list[bool] = []
        self.downlinked = 0
        return self.observe()

    def contact(self) -> bool:
        L = self.laws
        return (self.t + self.phase + L["pass_offset"]) % L["pass_period"] < L["pass_len"]

    def capture_ok(self) -> bool:
        lo, hi = self.laws["band"]
        return (self.payload_on and not self.fault and lo <= self.temp <= hi
                and self.last_cal is not None and self.t - self.last_cal <= self.laws["cal_window"])

    def observe(self) -> Observation:
        return Observation(t=self.t, fields={
            "t": self.t, "bus_on": self.bus_on, "payload_on": self.payload_on, "fault": self.fault,
            "heater_on": self.heater_on, "temp": round(self.temp, 1), "stored": len(self.images),
            "valid_stored": sum(self.images), "downlinked": self.downlinked,
        })

    def act(self, action: Action) -> StepResult:
        a, L = action.args, self.laws
        n = action.name
        if n == "power":
            if a.get("unit") not in ("bus", "payload") or a.get("state") not in ("on", "off"):
                return StepResult(observation=self.observe(), error="power needs unit in {bus,payload}, state in {on,off}")
        elif n == "heater":
            if a.get("state") not in ("on", "off"):
                return StepResult(observation=self.observe(), error="heater needs state in {on,off}")
        elif n not in ("calibrate", "capture", "downlink", "wait"):
            return StepResult(observation=self.observe(), error=f"unknown action {n!r}")

        if n == "power" and a["unit"] == "bus":
            if a["state"] == "on" and not self.bus_on:
                self.bus_on, self.bus_steps = True, 0
            elif a["state"] == "off":
                self.bus_on = self.payload_on = self.fault = False
                self.bus_steps = 0
        elif n == "power":
            if a["state"] == "off":
                self.payload_on = False
            elif not self.payload_on and not self.fault:
                if self.bus_on and self.bus_steps >= L["bus_warmup"]:
                    self.payload_on = True
                else:
                    self.fault = True
        elif n == "heater":
            self.heater_on = a["state"] == "on"
        elif n == "calibrate" and self.payload_on and not self.fault:
            if self.last_cal_try is None or self.t - self.last_cal_try >= L["cal_cooldown"]:
                self.last_cal = self.last_cal_try = self.t
        elif n == "capture" and self.payload_on and not self.fault:
            self.images.append(self.capture_ok())
            if len(self.images) > L["capacity"]:
                self.images.pop(0)
        elif n == "downlink" and self.images and self.contact():
            self.downlinked += int(self.images.pop(0))

        target = L["warm"] if (self.heater_on and self.bus_on) else L["cold"]
        self.temp += L["gain"] * (target - self.temp)
        if self.bus_on:
            self.bus_steps += 1
        self.t += 1
        return StepResult(observation=self.observe(), cost=1.0)

    @classmethod
    def shift_menu(cls) -> list[dict]:
        return [
            {"id": "band_moves", "label": "Safe imaging temperature range moves"},
            {"id": "calibration_shortens", "label": "Calibration wears off sooner"},
            {"id": "pass_schedule_shifts", "label": "Ground-station passes move and get shorter"},
        ]

    def shift(self, seed: int, kind: str | None = None) -> ShiftRecord:
        r = random.Random(seed)
        kind = kind or ["band_moves", "calibration_shortens", "pass_schedule_shifts"][r.randrange(3)]
        if kind not in {m["id"] for m in self.shift_menu()}:
            raise ValueError(f"unknown shift kind {kind!r}")
        L = self.laws
        before = {k: (list(v) if isinstance(v, list) else v) for k, v in L.items()}
        if kind == "band_moves":
            d = r.choice([-4.0, 4.0])
            L["band"] = [L["band"][0] + d, L["band"][1] + d]
            desc = f"valid imaging temperature band moved by {d:+.0f}"
        elif kind == "calibration_shortens":
            L["cal_window"] = max(2, L["cal_window"] - 3)
            desc = "calibration stays valid for fewer steps"
        else:
            L["pass_offset"] = (L["pass_offset"] + r.randrange(3, L["pass_period"] - 2)) % L["pass_period"]
            L["pass_len"] = max(2, L["pass_len"] - 1)
            desc = "ground-station pass schedule moved and shortened"
        after = {k: (list(v) if isinstance(v, list) else v) for k, v in L.items()}
        return ShiftRecord(kind=kind, description=desc, before={k: before[k] for k in before if before[k] != after[k]},
                           after={k: after[k] for k in after if before[k] != after[k]}, at_t=self.t)

    def success(self, objective_id: str) -> bool:
        return self.downlinked >= 3

    @classmethod
    def truth(cls, laws: JSON) -> list[str]:
        lo, hi = laws["band"]
        return [
            f"Payload power-on is accepted only after the bus has been on for >= {laws['bus_warmup']} steps; "
            "otherwise the payload faults until the bus is power-cycled.",
            f"Detector temp moves {laws['gain']:.0%} of the way each step toward {laws['warm']} (heater on, bus on) "
            f"or {laws['cold']} (otherwise).",
            f"Captures are valid only with temp in [{lo}, {hi}] and a calibration within the last "
            f"{laws['cal_window']} steps; calibrate is ignored within {laws['cal_cooldown']} steps of the previous one.",
            f"Downlink works only during ground passes: {laws['pass_len']} of every {laws['pass_period']} steps "
            "(phase depends on seed); otherwise silently nothing. Invalid images are discarded on downlink.",
            f"Storage holds {laws['capacity']} images; a capture when full overwrites the oldest image.",
        ]

    @classmethod
    def referee_cases(cls) -> list[Case]:
        out = []
        for i, v in enumerate(cls.variants()):
            for j in range(2):
                seed = 10000 + 37 * i + 11 * j
                out.append(Case(case_id=f"orbit-{v}-{seed}", seed=seed, variant=v, objective_id="downlink3"))
        return out
