import time

from logicscout.contracts import (Action, ActionSpec, ActionTemplate, FieldSpec, Objective, Observation, ParamSpec,
                                  Playbook, PlaybookRule, Rule, Theory, WorldManual)
from logicscout.planner import PlannerPolicy, candidate_actions, progress
from logicscout.playbook import PlaybookRunner, Policy, simulate, validate_playbook

GOAL = Objective(id="ten", text="count to 10 with the lamp on", success="obs.count >= 10 and obs.lamp == 'on'", horizon=12)


def manual():
    return WorldManual(world_id="counter", title="Counter", domain="test", summary="a counter",
                       actions=[ActionSpec(name="inc", params=[ParamSpec(name="n", type="int", min=1, max=3)]),
                                ActionSpec(name="dec"),
                                ActionSpec(name="lamp", params=[ParamSpec(name="to", type="enum", choices=["on", "off"])]),
                                ActionSpec(name="wait")],
                       observations=[FieldSpec(name="count", type="int"), FieldSpec(name="lamp", type="str")],
                       objectives=[GOAL], probe_budget=10)


def theory():
    return Theory(world_id="counter", version=3, rules=[
        Rule(id="inc", statement="", action="inc", when="obs.lamp == 'on'", effects={"count": "obs.count + args.n"}),
        Rule(id="dec", statement="", action="dec", effects={"count": "obs.count - 1"}),
        Rule(id="lamp", statement="", action="lamp", delay=1, effects={"lamp": "args.to"}),
    ])


START = Observation(t=0, fields={"count": 0, "lamp": "off"})


def playbook(**kw):
    base = dict(id="pb", world_id="counter", objective_id="ten", theory_version=3, memory={"steps": 0},
                updates={"steps": "mem.steps + 1"},
                rules=[PlaybookRule(when="obs.lamp != 'on' and mem.steps == 0", do=ActionTemplate(name="lamp", args={"to": "'on'"})),
                       PlaybookRule(when="obs.lamp == 'on'", do=ActionTemplate(name="inc", args={"n": "min(3, 10 - obs.count)"}))],
                fallback=ActionTemplate(name="wait"))
    base.update(kw)
    return Playbook(**base)


def test_runner_and_simulate():
    r = PlaybookRunner(playbook())
    assert isinstance(r, Policy)
    a = r.next_action(START)
    assert a == Action(name="lamp", args={"to": "on"}) and r.last_rule == 0
    r.after_step(START)
    assert r.mem["steps"] == 1
    res = simulate(PlaybookRunner(playbook()), theory(), START, GOAL.success, GOAL.horizon)
    assert res["success"] and res["steps"] == 6  # lamp, wait (delay), inc 3 x 4 ... 3+3+3+1
    assert res["trace"][0]["action"]["name"] == "lamp"
    assert res["trace"][-1]["predicted"]["count"] == 10


def test_simulate_failure():
    pb = playbook(rules=[], fallback=ActionTemplate(name="dec"))
    res = simulate(PlaybookRunner(pb), theory(), START, GOAL.success, 5)
    assert not res["success"] and res["steps"] == 5 and len(res["trace"]) == 5


def test_validate_playbook():
    assert validate_playbook(playbook(), manual()) == []
    bad = playbook(rules=[PlaybookRule(when="obs.__x", do=ActionTemplate(name="inc", args={"n": "7"})),
                          PlaybookRule(when="True", do=ActionTemplate(name="lamp", args={"to": "'dim'"})),
                          PlaybookRule(when="True", do=ActionTemplate(name="fly")),
                          PlaybookRule(when="True", do=ActionTemplate(name="inc", args={"m": "1"}))],
                   updates={"x": "import os"})
    errs = validate_playbook(bad, manual())
    for needle in ["__x", "outside", "dim", "fly", "missing arg 'n'", "no arg 'm'", "update x"]:
        assert any(needle in e for e in errs), (needle, errs)


def test_candidates_and_progress():
    c = candidate_actions(manual())
    assert Action(name="inc", args={"n": 3}) in c and Action(name="lamp", args={"to": "on"}) in c
    assert Action(name="wait") in c
    half = Observation(t=0, fields={"count": 5, "lamp": "off"})
    assert abs(progress(GOAL.success, half, {}) - 0.25) < 1e-9


def test_planner_reaches_goal():
    pol = PlannerPolicy(theory(), manual(), GOAL, depth=5, beam=24)
    t0 = time.time()
    res = simulate(pol, theory(), START, GOAL.success, GOAL.horizon)
    assert res["success"] and res["steps"] <= 7
    assert time.time() - t0 < 5
    stub = pol.as_playbook_stub()
    assert stub.origin == "planner" and stub.rules == [] and validate_playbook(stub, manual()) == []


def test_planner_deterministic():
    a = PlannerPolicy(theory(), manual(), GOAL).next_action(START)
    b = PlannerPolicy(theory(), manual(), GOAL).next_action(START)
    assert a == b == Action(name="lamp", args={"to": "on"})
