"""End-to-end mission on a toy world: control -> hidden change -> drift -> re-investigation -> recovery.

Test doubles (Fake*) stand in for the model and the investigator; the world, sandbox, theory, playbook,
monitor and mission code are the real ones.
"""
from __future__ import annotations

import json

import pytest

from logicscout import config
from logicscout.contracts import (
    Action, ActionSpec, Case, FieldSpec, ModelCall, Objective, Observation, RefereeReport, Rule, RunConfig, RunState,
    ShiftRecord, StepResult, Theory, WorldManual,
)
from logicscout.logbook import Logbook
from logicscout.sandbox import open_session
from logicscout.scout import mission as mission_mod
from logicscout.scout.mission import MissionControls, run_mission
from logicscout.scout.transfer import MechanismLibrary
from logicscout.worlds.base import World, register


@register
class ToyTank(World):
    world_id = "toy_mission"

    @classmethod
    def manual(cls) -> WorldManual:
        return WorldManual(
            world_id="toy_mission", title="Toy tank", domain="test", summary="a tank with a pump",
            actions=[ActionSpec(name="pump"), ActionSpec(name="wait")],
            observations=[FieldSpec(name="level", type="int")],
            objectives=[Objective(id="fill", text="fill to 10", success="obs.level >= 10", horizon=12)],
            probe_budget=6, lab_seeds=(0, 100),
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
        return [Case(case_id="c1", seed=500, objective_id="fill")]


PUMP_PLAYBOOK = {"rules": [{"when": "obs.level < 10", "do": {"name": "pump", "args": {}}, "why": "fill"}],
                 "fallback": {"name": "wait", "args": {}}}


class FakeLLM:
    def __init__(self, answers=None):
        self.on_call = None
        self.calls: list[str] = []
        self.answers = answers

    async def json(self, purpose, system, user, schema=None, tier="fast"):
        self.calls.append(purpose)
        if self.on_call:
            self.on_call(ModelCall(purpose=purpose, tier=tier, model="fake-model", provider="fake", latency_ms=1.0,
                                   prompt_tokens=10, completion_tokens=5, ok=True))
        if self.answers is not None:
            return self.answers(purpose)
        if purpose == "synthesize_playbook":
            return PUMP_PLAYBOOK
        if purpose == "abstract_mechanisms":
            return {"mechanisms": [{"name": "additive actuator", "signature": "an action adds a fixed amount to a quantity"},
                                   {"name": "pump gain", "signature": "the pump raises level"}]}
        return {"hypotheses": []}


class FakeInvestigator:
    """Estimates the pump gain from its own fresh experiments."""

    instances: list["FakeInvestigator"] = []

    def __init__(self, llm, port, manual, log, priors=None):
        self.port, self.log = port, log
        self.transitions = []
        self.hypotheses = {}
        self.focus_seen = []
        FakeInvestigator.instances.append(self)

    async def investigate(self, theory, budget, focus=None, caps=None):
        self.focus_seen.append(focus)
        obs = self.port.reset(0)
        gains = []
        for i in range(3):
            a = Action(name="pump")
            nxt = self.port.act(a).observation
            self.log.append("probe.step", {"probe_id": f"p{len(self.transitions)}", "action": a.model_dump(),
                                           "observation": nxt.model_dump()})
            self.transitions.append((obs, a, nxt))
            gains.append(nxt.fields["level"] - obs.fields["level"])
            obs = nxt
        g = round(sum(gains) / len(gains))
        new = Theory(world_id=theory.world_id, version=theory.version + 1, parent=theory.version, rules=[
            Rule(id="r1", statement=f"pump adds {g}", action="pump", effects={"level": f"obs.level + {g}"},
                 status="supported", confidence=0.9),
        ])
        self.log.append("theory.revised", {"theory": new.model_dump(), "diff": {}, "accuracy": 1.0,
                                           "baseline_accuracy": 0.0})
        return new


def fake_referee(world_id, theory, playbook, objective_id, run_id, prompt_log=None):
    return RefereeReport(run_id=run_id, world_id=world_id, theory_version=theory.version, playbook_id=playbook.id,
                         cases=[], success_rate=1.0, prediction_accuracy=1.0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SANDBOX_URL", "")
    monkeypatch.setattr(mission_mod, "Investigator", FakeInvestigator)
    FakeInvestigator.instances.clear()
    return tmp_path


def _start(run_id, **cfg):
    c = RunConfig(world_id="toy_mission", seed=7, use_briefing=False, **cfg)
    return c, Logbook(run_id), RunState(run_id=run_id, config=c, phase="encounter", live=True)


async def test_shift_drift_recovery(env):
    cfg, log, state = _start("r1", shift_after=3)
    llm = FakeLLM()
    session = open_session("toy_mission")
    out = await run_mission(cfg, log, llm, session, state, MissionControls(), referee=fake_referee)
    kinds = [e.kind for e in log.events]
    assert out.phase == "done", [e.data for e in log.events if e.kind == "error"]
    for k in ("run.started", "playbook.compiled", "shift.applied", "drift.suspected", "drift.confirmed",
              "recovery.done", "referee.report", "run.finished", "model.call"):
        assert k in kinds, k
    order = [kinds.index(k) for k in ("shift.applied", "drift.suspected", "drift.confirmed", "recovery.done")]
    assert order == sorted(order)
    shift_ev = next(e for e in log.events if e.kind == "shift.applied")
    assert shift_ev.data == {}
    private = json.loads((env / "runs" / "r1" / "private.json").read_text())
    assert private["shifts"][0]["after"] == {"gain": 1}
    inv = FakeInvestigator.instances[0]
    assert inv.focus_seen[0] is None and inv.focus_seen[1]  # re-investigation is focused on the mismatches
    conf = next(e for e in log.events if e.kind == "drift.confirmed")
    assert conf.data["rules_implicated"] == ["r1"]
    m = out.metrics
    assert m["drift"]["recovered"] is True and m["drift"]["detected_after_steps"] <= 3
    assert m["drift"]["probes"] == 3 and m["probes_used"] == 6
    assert m["episodes"][0]["success"] is False and all(e["success"] for e in m["episodes"][1:])
    assert all(e["true_success"] for e in m["episodes"][1:])
    assert m["time_to_competence"] == 6 and m["model_calls"] == len(llm.calls)
    assert out.theory.rules[0].effects["level"] == "obs.level + 1"
    assert out.referee is not None and out.phase == "done" and llm.on_call is None
    assert Logbook.verify(log.events)
    lib = json.loads((env / "library" / "mechanisms.json").read_text())
    assert [x["name"] for x in lib] == ["additive actuator"]  # "pump gain" names this world's controls


async def test_no_shift_runs_four_clean_episodes(env):
    cfg, log, state = _start("r2")
    out = await run_mission(cfg, log, FakeLLM(), open_session("toy_mission"), state, MissionControls(),
                            referee=fake_referee)
    assert out.phase == "done"
    assert len(out.metrics["episodes"]) == 4 and all(e["success"] for e in out.metrics["episodes"])
    assert not any(e.kind.startswith("drift") for e in log.events)


async def test_bad_playbooks_fall_back_to_planner(env):
    cfg, log, state = _start("r3")
    llm = FakeLLM(lambda p: {"rules": [], "fallback": {"name": "wait", "args": {}}})
    out = await run_mission(cfg, log, llm, open_session("toy_mission"), state, MissionControls(), referee=fake_referee)
    assert out.phase == "done"
    assert llm.calls.count("synthesize_playbook") == 3
    assert out.playbook.origin == "planner"
    assert any(e.kind == "note" and "planner" in e.data["text"] for e in log.events)
    assert all(e["success"] for e in out.metrics["episodes"])


async def test_failure_is_reported_not_hidden(env, monkeypatch):
    async def boom(self, theory, budget, focus=None):
        raise RuntimeError("probe rig broke")
    monkeypatch.setattr(FakeInvestigator, "investigate", boom)
    cfg, log, state = _start("r4")
    out = await run_mission(cfg, log, FakeLLM(), open_session("toy_mission"), state, MissionControls())
    assert out.phase == "failed"
    assert [e.kind for e in log.events][-1] == "run.failed"


async def test_stop_ends_gracefully(env):
    cfg, log, state = _start("r5")
    controls = MissionControls()
    controls.stop.set()
    out = await run_mission(cfg, log, FakeLLM(), open_session("toy_mission"), state, controls)
    assert out.phase == "done" and log.events[-1].data.get("stopped") is True


async def test_transfer_library_is_honest_when_empty(tmp_path):
    lib = MechanismLibrary(tmp_path / "lib")
    assert await lib.priors(FakeLLM(), ToyTank.manual()) == []


async def test_transfer_priors_must_fit_new_manual(tmp_path):
    lib = MechanismLibrary(tmp_path / "lib")
    lib.save([{"name": "additive actuator", "signature": "an action adds a fixed amount", "evidence": ["other"]}])

    def answers(purpose):
        return {"hypotheses": [
            {"mechanism": "additive actuator", "statement": "pump adds a fixed amount", "action": "pump",
             "when": "True", "effects": {"level": "obs.level + 2"}},
            {"mechanism": "additive actuator", "statement": "copied from old world", "action": "pump",
             "when": "True", "effects": {"charge": "obs.charge + 1"}},
        ]}
    hyps = await lib.priors(FakeLLM(answers), ToyTank.manual())
    assert len(hyps) == 1 and hyps[0].source == "transfer" and hyps[0].rule.status == "tentative"
