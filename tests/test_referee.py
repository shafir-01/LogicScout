import json
import random

from logicscout.contracts import (
    ActionSpec,
    ActionTemplate,
    Case,
    FieldSpec,
    Objective,
    Observation,
    Playbook,
    PlaybookRule,
    Rule,
    ShiftRecord,
    StepResult,
    Theory,
    WorldManual,
)
from logicscout.logbook import Logbook
from logicscout.referee import audit, evaluate, report_digest
from logicscout.worlds.base import World


class ToyWorld(World):
    world_id = "toy"

    @classmethod
    def manual(cls):
        return WorldManual(
            world_id="toy", title="Toy counter", domain="test", summary="A counter.",
            actions=[ActionSpec(name="inc"), ActionSpec(name="wait")],
            observations=[FieldSpec(name="t", type="int"), FieldSpec(name="x", type="int")],
            objectives=[Objective(id="reach5", text="Get x to 5", success="obs.x >= 5", horizon=10)],
            probe_budget=10, lab_seeds=(0, 1000),
        )

    @classmethod
    def default_laws(cls, variant):
        return {"standard": {"step_size": 2}, "big": {"step_size": 3}}[variant]

    @classmethod
    def variants(cls):
        return ["standard", "big"]

    def reset(self, seed):
        self.rng = random.Random(seed)
        self.t, self.x = 0, 0
        return self.observe()

    def observe(self):
        return Observation(t=self.t, fields={"t": self.t, "x": self.x})

    def act(self, action):
        if action.name not in ("inc", "wait"):
            return StepResult(observation=self.observe(), error="unknown action")
        if action.name == "inc":
            self.x += self.laws["step_size"]
        self.t += 1
        return StepResult(observation=self.observe(), cost=1.0 if action.name == "inc" else 0.0)

    def shift(self, seed):
        self.laws["step_size"] += 1
        return ShiftRecord(kind="step", description="step changed", before={}, after={}, at_t=self.t)

    def success(self, objective_id):
        return self.x >= 5

    @classmethod
    def truth(cls, laws):
        return [f"Each inc adds exactly {laws['step_size']} to the counter x."]

    @classmethod
    def referee_cases(cls):
        return [Case(case_id=f"toy-{v}-{s}", seed=s, variant=v, objective_id="reach5")
                for v in cls.variants() for s in (10000, 10001)]


THEORY = Theory(world_id="toy", version=3, rules=[
    Rule(id="r1", statement="inc adds 2", action="inc", effects={"x": "obs.x + 2"}, status="supported"),
])


def playbook(rules=True):
    return Playbook(
        id="pb-1", world_id="toy", objective_id="reach5", theory_version=3,
        rules=[PlaybookRule(when="obs.x < 5", do=ActionTemplate(name="inc"))] if rules else [],
        fallback=ActionTemplate(name="wait"),
    )


def clean_events():
    log = Logbook("run-1")
    log.append("run.started", {"config": {"world_id": "toy", "seed": 7}})
    log.append("probe.designed", {"probe": {"id": "p1", "seed": 3, "actions": []}})
    log.append("probe.step", {"probe_id": "p1", "action": {"name": "inc"}, "observation": {}})
    return log.events


def write_log(path, prompts):
    path.write_text("\n".join(json.dumps({"purpose": "probe", "system": "s", "user": u}) for u in prompts),
                    encoding="utf-8")
    return path


def run(tmp_path, pb=None, prompts=("Observation: x=4. Propose a rule.",), events=None):
    log = write_log(tmp_path / "prompts.jsonl", prompts)
    return evaluate("toy", THEORY, pb or playbook(), "reach5", "run-1", prompt_log=log,
                    events=clean_events() if events is None else events, world_cls=ToyWorld)


def test_success_is_ground_truth_and_cases_are_opaque(tmp_path):
    r = run(tmp_path)
    assert [c.case_id for c in r.cases] == ["case-0", "case-1", "case-2", "case-3"]
    assert r.success_rate == 1.0
    assert all(c.success for c in r.cases)
    assert [c.steps for c in r.cases] == [3, 3, 2, 2]  # standard needs 3 incs, the held-out variant 2
    idle = run(tmp_path, pb=playbook(rules=False))
    assert idle.success_rate == 0.0
    assert all(c.steps == 10 for c in idle.cases)


def test_baselines_and_prediction(tmp_path):
    r = run(tmp_path)
    assert r.baselines["idle"] == 0.0
    assert 0.0 <= r.baselines["random"] <= 1.0
    assert 0.0 <= r.baselines["persistence_accuracy"] < 1.0
    # theory is exact on standard and wrong on inc steps in the held-out variant
    assert r.baselines["persistence_accuracy"] < r.prediction_accuracy < 1.0
    checks = {k: v for k, v in r.leakage_checks.items() if k != "scout_imports_clean"}  # that one scans the repo
    assert all(checks.values()), r.notes


def test_audit_catches_planted_law_text(tmp_path):
    for planted in ("The tuning has step_size: 2 here.",
                    "Hint: each inc adds exactly 3 to the counter x.",
                    'laws={"step size": 3}'):
        r = run(tmp_path, prompts=("clean prompt", planted))
        assert r.leakage_checks["no_law_text_in_prompts"] is False, planted
        assert any("prompt line 2" in n for n in r.notes)


def test_missing_inputs_are_unverified_not_passed(tmp_path):
    r = evaluate("toy", THEORY, playbook(), "reach5", "run-1", world_cls=ToyWorld)
    assert r.leakage_checks["no_law_text_in_prompts"] is False
    assert r.leakage_checks["events_digest_ok"] is False
    assert r.leakage_checks["referee_cases_unseen"] is False
    assert sum("unverified" in n for n in r.notes) == 3


def test_referee_seed_use_and_tampering_are_caught(tmp_path):
    ev = clean_events()
    log = Logbook("run-1")
    log.append("probe.designed", {"probe": {"id": "p1", "seed": 10001, "actions": []}})
    r = run(tmp_path, events=log.events)
    assert r.leakage_checks["referee_cases_unseen"] is False
    ev[1] = ev[1].model_copy(update={"data": {"probe": {"id": "p1", "seed": 4}}})
    assert run(tmp_path, events=ev).leakage_checks["events_digest_ok"] is False


def test_digest_stable_and_sensitive(tmp_path):
    a, b = run(tmp_path), run(tmp_path)
    assert a.digest == b.digest == report_digest(a)
    assert report_digest(a.model_copy(update={"success_rate": 0.5})) != a.digest


def test_crashing_controller_is_a_failed_case(tmp_path):
    def boom(world, manual, objective):
        raise RuntimeError("bad playbook")

    log = write_log(tmp_path / "p.jsonl", ["x"])
    r = evaluate("toy", THEORY, playbook(), "reach5", "run-1", prompt_log=log, events=clean_events(),
                 world_cls=ToyWorld, make_policy=boom)
    assert r.success_rate == 0.0 and "controller error" in r.cases[0].note


def test_import_scan_flags_forbidden_imports(tmp_path):
    pkg = tmp_path / "logicscout"
    (pkg / "scout").mkdir(parents=True)
    (pkg / "scout" / "bad.py").write_text("from logicscout.worlds.relay import RelayWorld\nx = admin.truth()\n")
    (pkg / "llm").mkdir()
    (pkg / "llm" / "ok.py").write_text("from logicscout.contracts import Theory\n")
    ok, notes = audit.scout_imports_clean(pkg)
    assert not ok and len(notes) == 2
    ok, _ = audit.scout_imports_clean(tmp_path / "missing")
    assert ok


def test_model_echo_of_its_own_discovery_is_not_a_leak(tmp_path):
    log = tmp_path / "echo.jsonl"
    log.write_text("\n".join([
        json.dumps({"user": "probe results: x went 0 -> 2", "response_text": '{"rule": "step_size: 2"}'}),
        json.dumps({"user": "current theory: step_size: 2. Plan next probe."}),
    ]), encoding="utf-8")
    ok, notes = audit.no_law_text_in_prompts(log, ToyWorld.truth({"step_size": 2}), [{"step_size": 2}],
                                             ToyWorld.manual())
    assert ok, notes
