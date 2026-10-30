"""Rover: a simulated inspection rover on a 1-D survey track. PRIVATE (laws hidden)."""
from __future__ import annotations

import random

from logicscout.contracts import (
    JSON, Action, ActionSpec, Case, FieldSpec, Objective, Observation, ParamSpec, ShiftRecord,
    StepResult, WorldManual,
)
from logicscout.worlds.base import World, register

LENGTH = 24
N_SITES = 4
START_ENERGY = 60

_STANDARD: JSON = {
    "heat_threshold": 8.0,   # heat above this triggers lockout
    "passive_cool": 1.0,     # heat shed on any non-drive step
    "cool_amount": 4.0,      # heat shed by `cool`
    "cool_energy": 2,        # energy spent by `cool`
    "lockout_steps": 4,
    "scan_delay": 2,
    "scan_energy": 1,
    "rough_base": 3,         # rough drive energy = rough_base + speed (per step)
}

_VARIANTS: dict[str, JSON] = {
    "standard": {},
    "hot_motors": {"heat_threshold": 6.0, "lockout_steps": 5},
    "weak_radiator": {"passive_cool": 0.5, "cool_amount": 3.0, "cool_energy": 3},
    "slow_sensor": {"scan_delay": 4},
    "rugged": {"rough_base": 5, "heat_threshold": 7.0},
}

OBJECTIVE_ID = "confirm3"


@register
class RoverWorld(World):
    world_id = "rover"

    @classmethod
    def manual(cls) -> WorldManual:
        return WorldManual(
            world_id="rover",
            title="Survey rover",
            domain="robotics / field inspection (simulated)",
            summary="A simulated inspection rover drives along a survey track and scans inspection sites.",
            actions=[
                ActionSpec(name="drive", description="Run the drive motors.", params=[
                    ParamSpec(name="speed", type="int", min=1, max=3, description="motor speed setting"),
                    ParamSpec(name="dir", type="enum", choices=["fwd", "back"], description="direction"),
                ]),
                ActionSpec(name="scan", description="Trigger the inspection instrument."),
                ActionSpec(name="cool", description="Run the motor cooling system."),
                ActionSpec(name="wait", description="Do nothing for one step."),
            ],
            observations=[
                FieldSpec(name="t", type="int", description="step counter"),
                FieldSpec(name="position", type="int", description=f"track position 0..{LENGTH}"),
                FieldSpec(name="next_site", type="int", description="position of the nearest unconfirmed site at or ahead of the rover, -1 if none"),
                FieldSpec(name="energy", type="int", description="battery energy"),
                FieldSpec(name="heat", type="int", description="motor temperature gauge 0..5"),
                FieldSpec(name="locked", type="bool", description="motor controller fault light"),
                FieldSpec(name="terrain", type="str", description="terrain at current position: smooth|rough"),
                FieldSpec(name="sites_confirmed", type="int", description="sites confirmed by the instrument"),
                FieldSpec(name="scan_result", type="str", description="latest instrument report: none|confirmed|blurred|empty"),
            ],
            objectives=[Objective(
                id=OBJECTIVE_ID, text="Confirm 3 inspection sites with energy to spare",
                success="obs.sites_confirmed >= 3 and obs.energy > 0", horizon=45,
            )],
            probe_budget=50,
            lab_seeds=(0, 1000),
            briefing_topics=[
                "planetary rover motor thermal management duty cycle",
                "rover instrument vibration settling time before measurement",
                "wheeled rover energy consumption on rough terrain versus speed",
                "sensor data processing latency in remote inspection robots",
            ],
            layout={"kind": "track", "length": LENGTH, "bind": {
                "position": "position", "sites": "sites", "terrain": "terrain_map",
                "next_site": "next_site", "locked": "locked",
            }},
        )

    @classmethod
    def default_laws(cls, variant: str) -> JSON:
        if variant not in _VARIANTS:
            raise ValueError(f"unknown rover variant {variant!r}")
        return {**_STANDARD, **_VARIANTS[variant]}

    @classmethod
    def variants(cls) -> list[str]:
        return list(_VARIANTS)

    # ---- state ----------------------------------------------------------------------
    def reset(self, seed: int) -> Observation:
        rng = random.Random(f"rover:{seed}")
        self.seed = seed
        self.t = 0
        self.position = 0
        self.energy = START_ENERGY
        self.heat = 0.0
        self.locked_left = 0
        self.moved_last = False
        self.confirmed: set[int] = set()
        self.pending: list[tuple[int, str, int]] = []  # (arrive_t, result, site)
        self.scan_result = "none"
        self.events: list[str] = []
        while True:
            sites = sorted(rng.sample(range(3, 19), N_SITES))
            if all(b - a >= 3 for a, b in zip(sites, sites[1:])):
                break
        self.sites = sites
        self.terrain_map = ["smooth"] * (LENGTH + 1)
        for _ in range(3):
            start = rng.randint(1, LENGTH - 4)
            for p in range(start, start + rng.randint(2, 4)):
                self.terrain_map[p] = "rough"
        return self.observe()

    def _gauge(self) -> int:
        return max(0, min(5, int(self.heat * 5 / self.laws["heat_threshold"])))

    def _next_site(self) -> int:
        ahead = [s for s in self.sites if s >= self.position and s not in self.confirmed]
        return ahead[0] if ahead else -1

    def observe(self) -> Observation:
        return Observation(t=self.t, events=list(self.events), fields={
            "t": self.t, "position": self.position, "next_site": self._next_site(),
            "energy": self.energy, "heat": self._gauge(), "locked": self.locked_left > 0,
            "terrain": self.terrain_map[self.position], "sites_confirmed": len(self.confirmed),
            "scan_result": self.scan_result,
        })

    def act(self, action: Action) -> StepResult:
        L = self.laws
        self.events = []
        err = None
        cost = 0.0
        moved = False
        name, args = action.name, action.args or {}
        if name == "drive":
            speed, d = args.get("speed"), args.get("dir")
            if not isinstance(speed, int) or isinstance(speed, bool) or not 1 <= speed <= 3:
                err = "speed must be an int 1..3"
            elif d not in ("fwd", "back"):
                err = "dir must be fwd or back"
        elif name not in ("scan", "cool", "wait"):
            err = f"unknown action {name!r}"
        if err:
            return StepResult(observation=self.observe(), error=err)

        was_locked = self.locked_left > 0
        if name == "drive":
            if not was_locked and self.energy > 0:
                speed = args["speed"]
                rough = self.terrain_map[self.position] == "rough"
                cost = (L["rough_base"] + speed) if rough else speed
                self.energy -= int(cost)
                step = speed if args["dir"] == "fwd" else -speed
                new = max(0, min(LENGTH, self.position + step))
                moved = new != self.position
                self.position = new
                self.heat += speed * speed
                if self.heat > L["heat_threshold"]:
                    self.locked_left = int(L["lockout_steps"]) + 1
            else:
                self.heat = max(0.0, self.heat - L["passive_cool"])
        elif name == "cool":
            if self.energy > 0:
                self.energy -= int(L["cool_energy"])
                cost = L["cool_energy"]
                self.heat = max(0.0, self.heat - L["cool_amount"])
            else:
                self.heat = max(0.0, self.heat - L["passive_cool"])
        else:
            self.heat = max(0.0, self.heat - L["passive_cool"])
            if name == "scan" and self.energy > 0:
                self.energy -= int(L["scan_energy"])
                cost = L["scan_energy"]
                if self.moved_last:
                    res = "blurred"
                elif self.position in self.sites and self.position not in self.confirmed:
                    res = "confirmed"
                else:
                    res = "empty"
                self.pending.append((self.t + 1 + int(L["scan_delay"]), res, self.position))
        if self.locked_left > 0:
            self.locked_left -= 1
        self.moved_last = moved
        self.t += 1
        arrived = [p for p in self.pending if p[0] <= self.t]
        self.pending = [p for p in self.pending if p[0] > self.t]
        for _, res, site in arrived:
            if res == "confirmed" and site in self.confirmed:
                res = "empty"
            if res == "confirmed":
                self.confirmed.add(site)
            self.scan_result = res
        self.energy = max(0, self.energy)
        return StepResult(observation=self.observe(), cost=float(cost))

    # ---- private ---------------------------------------------------------------------
    @classmethod
    def shift_menu(cls) -> list[dict]:
        return [
            {"id": "cooling_halves", "label": "Motor cooling becomes half as effective"},
            {"id": "lockout_threshold_drops", "label": "Overheat lockout triggers sooner"},
            {"id": "scan_latency_up", "label": "Instrument reports arrive one step later"},
        ]

    def shift(self, seed: int, kind: str | None = None) -> ShiftRecord:
        kinds = ["cooling_halves", "lockout_threshold_drops", "scan_latency_up"]
        kind = kind or kinds[random.Random(f"rover-shift:{seed}").randrange(len(kinds))]
        if kind not in {m["id"] for m in self.shift_menu()}:
            raise ValueError(f"unknown shift kind {kind!r}")
        before = dict(self.laws)
        if kind == "cooling_halves":
            self.laws["passive_cool"] /= 2
            self.laws["cool_amount"] /= 2
            desc = "Motor cooling (passive and active) now sheds half as much heat."
        elif kind == "lockout_threshold_drops":
            self.laws["heat_threshold"] = max(4.0, self.laws["heat_threshold"] - 2)
            desc = "The thermal lockout now triggers at a lower heat level."
        else:
            self.laws["scan_delay"] += 1
            desc = "Instrument reports now arrive one step later."
        changed = [k for k in self.laws if self.laws[k] != before[k]]
        return ShiftRecord(kind=kind, description=desc, before={k: before[k] for k in changed},
                           after={k: self.laws[k] for k in changed}, at_t=self.t)

    def success(self, objective_id: str) -> bool:
        if objective_id != OBJECTIVE_ID:
            raise ValueError(f"unknown objective {objective_id!r}")
        return len(self.confirmed) >= 3 and self.energy > 0

    @classmethod
    def truth(cls, laws: JSON) -> list[str]:
        return [
            f"Each drive adds speed squared heat (speed 3 adds 9); idle steps shed {laws['passive_cool']:g}, "
            f"`cool` sheds {laws['cool_amount']:g} for {laws['cool_energy']} energy.",
            f"Heat above {laws['heat_threshold']:g} locks the motors for {laws['lockout_steps']} steps: "
            "drives silently do nothing.",
            f"Scan reports arrive {laws['scan_delay']} steps after the scan "
            f"(the confirmed counter rises then); a scan costs {laws['scan_energy']} energy.",
            "A scan taken the step right after the rover moved comes back blurred.",
            f"Smooth terrain costs 1 energy per unit distance; rough terrain costs {laws['rough_base']} + speed per drive, "
            "so faster driving on rough ground is cheaper per unit distance (but much hotter).",
        ]

    @classmethod
    def referee_cases(cls) -> list[Case]:
        cases = []
        for i, variant in enumerate(cls.variants()):
            for j in range(2):
                seed = 10000 + 37 * i + 11 * j
                cases.append(Case(case_id=f"rover-{variant}-{seed}", seed=seed, variant=variant,
                                  objective_id=OBJECTIVE_ID))
        return cases
