import ast
from pathlib import Path

from logicscout.contracts import (
    Action, ActionSpec, FieldSpec, Hypothesis, Objective, Observation, ParamSpec, Rule, StepResult, Theory,
    WorldManual,
)
from logicscout.logbook import Logbook
from logicscout.scout.investigator import Investigator
from logicscout.theory import accuracy, persistence_accuracy

MANUAL = WorldManual(
    world_id="toy",
    title="Toy tank",
    domain="test",
    summary="A tank with a pump and a valve.",
    actions=[
        ActionSpec(name="pump", params=[ParamSpec(name="rate", type="int", min=1, max=5)]),
        ActionSpec(name="toggle"),
        ActionSpec(name="wait"),
    ],
    observations=[FieldSpec(name="level", type="int"), FieldSpec(name="valve", type="str")],
    objectives=[Objective(id="fill", text="Fill the tank", success="obs.level >= 50", horizon=30)],
    probe_budget=30,
    lab_seeds=(0, 100),
)


class ToyPort:
    """Hidden laws: pump adds 2*rate to level; toggle flips the valve; wait does nothing."""

    def __init__(self):
        self.acts = 0
        self.reset(0)

    def manual(self):
        return MANUAL

    def reset(self, seed):
        assert MANUAL.lab_seeds[0] <= seed < MANUAL.lab_seeds[1]
        self.t, self.level, self.valve = 0, seed % 5, "closed"
        return self.observe()

    def observe(self):
        return Observation(t=self.t, fields={"level": self.level, "valve": self.valve})

    def act(self, action):
        self.acts += 1
        if action.name == "pump":
            self.level += 2 * action.args["rate"]
        elif action.name == "toggle":
            self.valve = "open" if self.valve == "closed" else "closed"
        elif action.name != "wait":
            return StepResult(observation=self.observe(), error="unknown action")
        self.t += 1
        return StepResult(observation=self.observe())


RIVALS = {
    "questions": [
        {"question": "How much does pump raise the level?", "rivals": [
            {"statement": "pump adds rate", "action": "pump", "when": "True",
             "effects": {"level": "obs.level + args.rate"}},
            {"statement": "pump adds twice the rate", "action": "pump", "when": "True",
             "effects": {"level": "obs.level + 2 * args.rate"}},
            {"statement": "pump sets a bogus field", "action": "pump", "when": "True",
             "effects": {"pressure": "1"}},
        ]},
        {"question": "What does toggle do to the valve?", "rivals": [
            {"statement": "toggle flips the valve", "action": "toggle", "when": "True",
             "effects": {"valve": "'open' if obs.valve == 'closed' else 'closed'"}},
            {"statement": "toggle always opens the valve", "action": "toggle", "when": "True",
             "effects": {"valve": "'open'"}},
        ]},
    ],
    "unknowns": ["does anything drain the tank?"],
}


class FakeLLM:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def json(self, purpose, system, user, schema=None, tier="fast"):
        self.calls.append((purpose, tier, user))
        if self.fail:
            raise RuntimeError("model unavailable")
        if purpose == "hypothesize":
            return RIVALS if len([c for c in self.calls if c[0] == "hypothesize"]) == 1 else {"questions": []}
        if purpose == "design_probe":
            return {"probes": [
                {"purpose": "pump then toggle twice", "seed": None, "actions": [
                    {"name": "pump", "args": {"rate": 3}}, {"name": "toggle"}, {"name": "toggle"}]},
                {"purpose": "just wait", "seed": 3, "actions": [{"name": "wait"}]},
                {"purpose": "unknown control", "seed": None, "actions": [{"name": "explode"}]},
            ]}
        if purpose == "revise_theory":
            return {"rules": []}
        raise AssertionError(purpose)


def kinds(log):
    return [e.kind for e in log.events]


async def test_investigation_learns_and_refutes():
    port, llm, log = ToyPort(), FakeLLM(), Logbook("t1")
    inv = Investigator(llm, port, MANUAL, log)
    theory = await inv.investigate(Theory(world_id="toy"), budget=30)

    assert inv.probes_used <= 30 and port.acts == inv.probes_used
    k = kinds(log)
    assert "probe.designed" in k and "probe.step" in k and "theory.revised" in k
    first = next(e for e in log.events if e.kind == "probe.designed")
    assert first.data["probe"]["purpose"].startswith("First touch")

    # the invalid rival was dropped, not tested
    assert any(e.kind == "note" and "pressure" in e.data["text"] for e in log.events)
    assert all(h.rule.effects.keys() <= {"level", "valve"} for h in inv.hypotheses.values())

    by_stmt = {h.statement: h for h in inv.hypotheses.values()}
    assert by_stmt["pump adds twice the rate"].status == "supported"
    assert by_stmt["pump adds rate"].status == "refuted"
    assert by_stmt["toggle flips the valve"].status == "supported"
    assert by_stmt["toggle always opens the valve"].status == "refuted"
    refuted = [e for e in log.events if e.kind == "hypothesis.refuted"]
    assert any("saw" in e.data["reason"] for e in refuted)

    designed = [e.data for e in log.events if e.kind == "probe.designed"][1:]
    assert designed and designed[0]["probe"]["score"] > 0 and designed[0]["alternatives"]
    assert designed[0]["probe"]["predictions"]

    active = [r for r in theory.rules if r.status == "supported"]
    assert {r.statement for r in active} == {"pump adds twice the rate", "toggle flips the valve"}
    assert all(r.evidence for r in active)
    ids = [r.id for r in theory.rules]
    assert len(ids) == len(set(ids))
    acc = accuracy(theory, inv.transitions)
    assert acc > persistence_accuracy(inv.transitions)
    assert acc >= 0.97
    assert theory.version >= 1 and theory.parent == theory.version - 1


async def test_info_score_prefers_discriminating_probe():
    port, llm, log = ToyPort(), FakeLLM(), Logbook("t2")
    inv = Investigator(llm, port, MANUAL, log)
    await inv.investigate(Theory(world_id="toy"), budget=12)
    d = [e.data for e in log.events if e.kind == "probe.designed"][1]
    assert d["probe"]["purpose"] == "pump then toggle twice"
    assert all(a["score"] <= d["probe"]["score"] for a in d["alternatives"])
    assert inv.probes_used <= 12


async def test_llm_failure_still_explores_within_budget():
    port, llm, log = ToyPort(), FakeLLM(fail=True), Logbook("t3")
    inv = Investigator(llm, port, MANUAL, log)
    theory = await inv.investigate(Theory(world_id="toy"), budget=15)
    assert inv.probes_used == 15 == port.acts
    assert "error" in kinds(log)
    # no model rules are fabricated; only rules fitted to experience and then supported by a probe
    assert all("fits" in r.statement and r.status == "supported" for r in theory.rules)
    assert all(r.evidence for r in theory.rules)


async def test_priors_are_tested():
    prior = Hypothesis(id="b1", statement="pumps add one unit per rate", source="briefing",
                       rule=Rule(id="X", statement="pumps add one unit per rate", action="pump",
                                 effects={"level": "obs.level + args.rate"}, source="briefing"))
    port, llm, log = ToyPort(), FakeLLM(), Logbook("t4")
    inv = Investigator(llm, port, MANUAL, log, priors=[prior])
    await inv.investigate(Theory(world_id="toy"), budget=20)
    p = inv.hypotheses["b1"]
    assert p.status == "refuted"
    hyp_prompt = next(c[2] for c in llm.calls if c[0] == "hypothesize")
    assert "UNVERIFIED" in hyp_prompt


def test_no_forbidden_imports():
    root = Path(__file__).resolve().parent.parent / "logicscout" / "scout"
    for name in ("investigator.py", "prompts.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for m in mods:
            assert not m.startswith(("logicscout.worlds", "logicscout.referee", "logicscout.sandbox")), m
