"""Reality trial: a controller that only works inside a wrong theory is caught on the real system."""
from __future__ import annotations

import pytest

from logicscout import config
from logicscout.contracts import (
    Action, ActionSpec, FieldSpec, ModelCall, Objective, Observation, Playbook, Rule, RunConfig, RunState, ShiftRecord, StepResult,
    Theory, WorldManual,
)
from logicscout.logbook import EVENT_KINDS, Logbook
from logicscout.playbook import PlaybookRunner
from logicscout.sandbox import open_session
from logicscout.scout import mission as mission_mod
from logicscout.scout.mission import MissionControls, run_mission
from logicscout.scout.trial import reality_trial
from logicscout.worlds.base import World, register


@register
class TrialTank(World):
    """Pump adds 2 to the level; waiting does nothing."""

    world_id = "toy_trial"

    @classmethod
    def manual(cls) -> WorldManual:
        return WorldManual(
            world_id="toy_trial", title="Trial tank", domain="test", summary="a tank with a pump",
            actions=[ActionSpec(name="pump"), ActionSpec(name="wait")],
            observations=[FieldSpec(name="level", type="int")],
            objectives=[Objective(id="fill", text="fill to 10", success="obs.level >= 10", horizon=12)],
            probe_budget=20, lab_seeds=(0, 100),
        )

    def reset(self, seed: int) -> Observation:
        self.t, self.level = 0, 0
        return self.observe()

    def observe(self) -> Observation:
        return Observation(t=self.t, fields={"level": getattr(self, "level", 0)})

    def act(self, action: Action) -> StepResult:
        self.t += 1
        if action.name == "pump":
            self.level += self.laws["gain"]
        return StepResult(observation=self.observe())

    @classmethod
    def default_laws(cls, variant: str):
        return {"gain": 2}

    @classmethod
    def variants(cls):
        return ["standard"]

    def shift(self, seed: int) -> ShiftRecord:
        before = dict(self.laws)
        self.laws["gain"] = 1
        return ShiftRecord(kind="gain", description="pump weakened", before=before, after=dict(self.laws), at_t=self.t)

    def success(self, objective_id: str) -> bool:
        return getattr(self, "level", 0) >= 10

    @classmethod
    def truth(cls, laws):
        return [f"pump adds {laws['gain']}"]

    @classmethod
    def referee_cases(cls):
        return []


WAIT_PLAYBOOK = {"rules": [], "fallback": {"name": "wait", "args": {}}}


def _theory(gains: dict[str, int], version: int = 1) -> Theory:
    return Theory(world_id="toy_trial", version=version, rules=[
        Rule(id=f"r_{a}", statement=f"{a} adds {g}", action=a, effects={"level": f"obs.level + {g}"},
             status="supported", confidence=0.9) for a, g in gains.items()])


def _wait_playbook() -> Playbook:
    return Playbook(id="pb-wait", world_id="toy_trial", objective_id="fill", theory_version=1, origin="synthesized",
                    rules=[], fallback={"name": "wait", "args": {}})


class FakeLLM:
    def __init__(self):
        self.on_call = None
        self.calls: list[str] = []

    async def json(self, purpose, system, user, schema=None, tier="fast"):
        self.calls.append(purpose)
        if self.on_call:
            self.on_call(ModelCall(purpose=purpose, tier=tier, model="fake-model", provider="fake", latency_ms=1.0,
                                   prompt_tokens=10, completion_tokens=5, ok=True))
        if purpose == "synthesize_playbook":
            return WAIT_PLAYBOOK  # works only in a theory where waiting fills the tank
        return {"hypotheses": []}


class WrongThenFitInvestigator:
    """First pass misreads the world (believes waiting adds 5); later passes fit each action's mean effect
    from all experience it holds, including transitions handed to it by a reality trial."""

    instances: list["WrongThenFitInvestigator"] = []

    def __init__(self, llm, port, manual, log, priors=None):
        self.port, self.log = port, log
        self.transitions = []
        self.hypotheses = {}
        self.passes = 0
        WrongThenFitInvestigator.instances.append(self)

    async def investigate(self, theory, budget, focus=None, caps=None):
        self.passes += 1
        obs = self.port.reset(0)
        for _ in range(3):
            a = Action(name="pump")
            nxt = self.port.act(a).observation
            self.log.append("probe.step", {"probe_id": f"p{len(self.transitions)}", "action": a.model_dump(),
                                           "observation": nxt.model_dump()})
            self.transitions.append((obs, a, nxt))
            obs = nxt
        if self.passes == 1:
            gains = {"pump": 2, "wait": 5}
        else:
            deltas: dict[str, list[int]] = {}
            for b, a, o in self.transitions:
                deltas.setdefault(a.name, []).append(o.fields["level"] - b.fields["level"])
            gains = {a: round(sum(d) / len(d)) for a, d in deltas.items()}
        new = _theory(gains, theory.version + 1)
        self.log.append("theory.revised", {"theory": new.model_dump(), "diff": {}, "accuracy": 1.0,
                                           "baseline_accuracy": 0.0})
        return new


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SANDBOX_URL", "")
    monkeypatch.setattr(mission_mod, "Investigator", WrongThenFitInvestigator)
    WrongThenFitInvestigator.instances.clear()
    return tmp_path


def _manual_obj():
    m = TrialTank.manual()
    return m, m.objectives[0]


async def test_wrong_theory_is_rejected_by_reality():
    manual, obj = _manual_obj()
    wrong = _theory({"pump": 2, "wait": 5})
    res = await reality_trial(lambda: PlaybookRunner(_wait_playbook()), wrong, lambda: open_session("toy_trial").port,
                              manual, obj, seed=3)
    assert res["predicted_success"] is True and res["real_success"] is False
    assert res["mismatch_rate"] == 1.0 and res["steps"] == obj.horizon
    assert res["accepted"] is False and "predicted success" in res["reason"]
    assert len(res["transitions"]) == obj.horizon


async def test_correct_theory_is_accepted():
    manual, obj = _manual_obj()
    right = _theory({"pump": 2, "wait": 0})
    pump = Playbook(id="pb-pump", world_id="toy_trial", objective_id="fill", theory_version=1, origin="synthesized",
                    rules=[{"when": "obs.level < 10", "do": {"name": "pump", "args": {}}}],
                    fallback={"name": "wait", "args": {}})
    res = await reality_trial(lambda: PlaybookRunner(pump), right, lambda: open_session("toy_trial").port,
                              manual, obj, seed=3)
    assert res["predicted_success"] and res["real_success"] and res["accepted"]
    assert res["mismatch_rate"] == 0.0 and res["steps"] == 5


async def test_truncated_trial_is_inconclusive_on_success():
    manual, obj = _manual_obj()
    right = _theory({"pump": 2, "wait": 0})
    pump = Playbook(id="pb-pump", world_id="toy_trial", objective_id="fill", theory_version=1, origin="synthesized",
                    rules=[{"when": "True", "do": {"name": "pump", "args": {}}}], fallback={"name": "wait", "args": {}})
    res = await reality_trial(lambda: PlaybookRunner(pump), right, lambda: open_session("toy_trial").port,
                              manual, obj, seed=3, max_steps=2)
    assert res["truncated"] and not res["real_success"] and res["accepted"] and res["steps"] == 2


async def test_mission_rejects_then_learns_from_trial(env):
    assert "playbook.trial" in EVENT_KINDS
    cfg = RunConfig(world_id="toy_trial", seed=7, use_briefing=False)
    log, llm = Logbook("t1"), FakeLLM()
    state = RunState(run_id="t1", config=cfg, phase="encounter", live=True)
    out = await run_mission(cfg, log, llm, open_session("toy_trial"), state, MissionControls(),
                            trial_port_factory=lambda: open_session("toy_trial"))
    assert out.phase == "done", [e.data for e in log.events if e.kind == "error"]
    trials = [e.data for e in log.events if e.kind == "playbook.trial"]
    first = trials[0]
    assert first["predicted_success"] and not first["real_success"] and not first["accepted"]
    assert first["seed"] != cfg.seed and first["mismatch_rate"] == 1.0
    assert trials[1]["accepted"] and trials[1]["real_success"] and trials[1]["origin"] == "planner"
    inv = WrongThenFitInvestigator.instances[0]
    assert inv.passes == 2
    assert any(a.name == "wait" for _, a, _ in inv.transitions)  # the failed trial became experience
    wait_rule = next(r for r in out.theory.rules if r.action == "wait")
    assert wait_rule.effects["level"] == "obs.level + 0"
    m = out.metrics
    assert m["trials"]["run"] == 2 and m["trials"]["rejected"] == 1
    probe_steps = sum(1 for e in log.events if e.kind == "probe.step")
    assert m["probes_used"] == probe_steps and m["trials"]["steps"] > 0  # trials have their own allowance, reported apart
    assert all(e["success"] for e in m["episodes"])
    assert Logbook.verify(log.events)


async def test_no_trial_factory_skips_with_note(env):
    cfg = RunConfig(world_id="toy_trial", seed=7, use_briefing=False)
    log = Logbook("t2")
    state = RunState(run_id="t2", config=cfg, phase="encounter", live=True)
    out = await run_mission(cfg, log, FakeLLM(), open_session("toy_trial"), state, MissionControls())
    assert out.phase == "done"
    assert not any(e.kind == "playbook.trial" for e in log.events)
    assert any(e.kind == "note" and "reality trial skipped" in e.data["text"] for e in log.events)
    assert out.metrics["trials"]["skipped"] is True
