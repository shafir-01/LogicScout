from logicscout.contracts import Action, ActionSpec, FieldSpec, Objective, Observation, ParamSpec, Rule, Theory, WorldManual
from logicscout.theory import Predictor, accuracy, compare, diff, persistence_accuracy, rule_stats, validate_theory


def ob(t, **f):
    return Observation(t=t, fields=f)


def toy_theory():
    return Theory(world_id="toy", memory={"presses": 0}, rules=[
        Rule(id="inc", statement="inc adds n", action="inc", effects={"count": "obs.count + args.n"}),
        Rule(id="cap", statement="count capped", action="*", when="obs.count >= 9", effects={"count": "9"}),
        Rule(id="press", statement="press counts; door opens on 3rd", action="press",
             memory={"presses": "mem.presses + 1"},
             effects={"door": "'open' if mem.presses + 1 >= 3 else obs.door"}),
        Rule(id="ship", statement="ship arrives 2 later", action="ship", delay=2, effects={"arrived": "True"}),
        Rule(id="dead", statement="refuted", action="*", status="refuted", effects={"count": "-1"}),
    ])


def manual():
    return WorldManual(world_id="toy", title="Toy", domain="test", summary="toy",
                       actions=[ActionSpec(name="inc", params=[ParamSpec(name="n", type="int", min=1, max=3)]),
                                ActionSpec(name="press"), ActionSpec(name="ship"), ActionSpec(name="wait")],
                       observations=[FieldSpec(name="count", type="int"), FieldSpec(name="door", type="str"),
                                     FieldSpec(name="arrived", type="bool")],
                       objectives=[Objective(id="o", text="reach 9", success="obs.count >= 9", horizon=10)],
                       probe_budget=10)


def run(theory, start, actions):
    """Roll the predictor forward on its own predictions; return list of predicted field dicts."""
    p = Predictor(theory)
    p.reset(start)
    obs, out = start, []
    for a in actions:
        f = p.predict(obs, a)
        obs = Observation(t=obs.t + 1, fields=f)
        p.advance(obs)
        out.append(f)
    return out, p


def test_effects_override_and_persistence():
    th = toy_theory()
    p = Predictor(th)
    s = ob(0, count=9, door="closed", arrived=False)
    p.reset(s)
    f = p.predict(s, Action(name="inc", args={"n": 2}))
    assert f == {"count": 9, "door": "closed", "arrived": False}
    assert p.last_rules["count"] == ["inc", "cap"]


def test_memory_and_delay():
    th = toy_theory()
    s = ob(0, count=0, door="closed", arrived=False)
    acts = [Action(name="press"), Action(name="ship"), Action(name="press"), Action(name="wait"), Action(name="press")]
    out, p = run(th, s, acts)
    assert [o["door"] for o in out] == ["closed", "closed", "closed", "closed", "open"]
    assert [o["arrived"] for o in out] == [False, False, False, True, True]
    assert p.mem["presses"] == 3


def test_advance_syncs_to_truth():
    th = toy_theory()
    p = Predictor(th)
    s = ob(0, count=1, door="closed", arrived=False)
    p.reset(s)
    p.predict(s, Action(name="inc", args={"n": 1}))
    real = ob(1, count=5, door="closed", arrived=False)
    p.advance(real)
    assert p.predict(real, Action(name="inc", args={"n": 1}))["count"] == 6


def test_failed_expression_is_mismatch():
    th = Theory(world_id="toy", rules=[Rule(id="r", statement="", effects={"count": "obs.nope + 1"})])
    p = Predictor(th)
    s = ob(0, count=1)
    p.reset(s)
    f = p.predict(s, Action(name="wait"))
    assert f["count"] is None
    ms = compare(f, {"count": 1}, p.last_rules)
    assert len(ms) == 1 and ms[0].rule_ids == ["r"]


def test_compare_tolerance():
    assert compare({"x": 100.0, "s": "a", "b": True, "t": 1}, {"x": 101.5, "s": "a", "b": True, "t": 9}) == []
    assert len(compare({"x": 100.0, "b": 1}, {"x": 103.0, "b": True})) == 2
    assert compare({"x": 0.0}, {"x": 1e-7}) == []
    assert len(compare({}, {"x": 1})) == 1


def synthetic():
    """True world: inc adds n (cap 9). Two episodes."""
    trs, obs = [], ob(0, count=0, door="closed", arrived=False)
    for k, n in enumerate([1, 2, 3, 3, 1]):
        nxt = ob(obs.t + 1, count=min(obs.fields["count"] + n, 9), door="closed", arrived=False)
        trs.append((obs, Action(name="inc", args={"n": n}), nxt))
        obs = nxt
    obs = ob(0, count=5, door="closed", arrived=False)
    nxt = ob(1, count=7, door="closed", arrived=False)
    trs.append((obs, Action(name="inc", args={"n": 2}), nxt))
    return trs


def test_accuracy_beats_persistence():
    trs = synthetic()
    th = Theory(world_id="toy", rules=[
        Rule(id="inc", statement="", action="inc", effects={"count": "min(obs.count + args.n, 9)"})])
    assert accuracy(th, trs) == 1.0
    assert persistence_accuracy(trs) < 1.0
    assert accuracy(Theory(world_id="toy"), trs) == persistence_accuracy(trs)
    stats = rule_stats(th, trs)
    assert stats["inc"]["fired"] == 6 and stats["inc"]["correct"] == 6


def test_validate_theory_and_diff():
    th = toy_theory()
    assert validate_theory(th, manual()) == []
    bad = th.model_copy(deep=True)
    bad.rules.append(Rule(id="x", statement="", action="fly", when="obs.__x", effects={"ghost": "1"}))
    errs = validate_theory(bad, manual())
    assert any("fly" in e for e in errs) and any("ghost" in e for e in errs) and any("when" in e for e in errs)
    new = th.model_copy(deep=True)
    new.rules[0].effects = {"count": "obs.count + 2 * args.n"}
    new.rules.pop()
    new.rules.append(Rule(id="z", statement=""))
    d = diff(th, new)
    assert d["added"] == ["z"] and d["removed"] == ["dead"] and d["changed"] == ["inc"]
