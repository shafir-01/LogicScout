"""Robust control: plan against every theory still consistent with experience, not one best guess."""
from logicscout.contracts import (Action, ActionSpec, FieldSpec, Hypothesis, Objective, Observation, Rule, Theory,
                                  WorldManual)
from logicscout.planner import PlannerPolicy, RobustPlannerPolicy, goal_fields
from logicscout.scout.rivals import disagreement, plausible_theories, robust_policy


def manual():
    return WorldManual(world_id="tank", title="Tank", domain="test", summary="a tank",
                       actions=[ActionSpec(name="fill"), ActionSpec(name="boost"), ActionSpec(name="wait")],
                       observations=[FieldSpec(name="level", type="int"), FieldSpec(name="hot", type="bool")],
                       objectives=[Objective(id="o", text="fill to 4", success="obs.level >= 4", horizon=12)],
                       probe_budget=10)


FILL = Rule(id="fill", statement="fill adds 1", action="fill", effects={"level": "obs.level + 1"}, status="supported")
# both boost rules agree whenever the tank is cold (all that was ever tested) ...
BOOST_A = Rule(id="boostA", statement="boost adds 3", action="boost", effects={"level": "obs.level + 3"},
               status="supported")
# ... but this rival says a hot tank dumps its contents on boost: an untested condition
BOOST_B = Rule(id="boostB", statement="boost adds 3 unless hot, then empties", action="boost",
               effects={"level": "0 if obs.hot else obs.level + 3"})


def theory_a():
    return Theory(world_id="tank", rules=[FILL.model_copy(), BOOST_A.model_copy()])


def theory_b():
    b = BOOST_B.model_copy()
    b.status = "supported"
    return Theory(world_id="tank", rules=[FILL.model_copy(), b])


def experience():
    """Cold-tank experience only: boost always added 3, fill always added 1."""
    out, lv = [], 0
    for i, (name, d) in enumerate([("fill", 1), ("boost", 3), ("wait", 0), ("boost", 3), ("fill", 1)] * 2):
        out.append((Observation(t=i, fields={"level": lv, "hot": False}), Action(name=name),
                    Observation(t=i + 1, fields={"level": lv + d, "hot": False})))
        lv += d
    return out


def hyps():
    return {
        "h1": Hypothesis(id="h1", statement=BOOST_A.statement, rule=BOOST_A, rivals=["h2"], status="supported"),
        "h2": Hypothesis(id="h2", statement=BOOST_B.statement, rule=BOOST_B, rivals=["h1"], status="supported"),
    }


def test_plausible_theories_keeps_equivalent_rival():
    ths = plausible_theories(theory_a(), hyps(), experience())
    assert len(ths) == 2
    assert {r.id for r in ths[1].rules} == {"fill", "boostB"}
    # a refuted rival is not plausible
    h = hyps()
    h["h2"].status = "refuted"
    assert len(plausible_theories(theory_a(), h, experience())) == 1


def test_plausible_theories_drops_rival_that_explains_less():
    bad = Rule(id="boostC", statement="boost adds 1", action="boost", effects={"level": "obs.level + 1"})
    h = hyps()
    h["h3"] = Hypothesis(id="h3", statement=bad.statement, rule=bad, rivals=["h1"], status="open")
    ids = [{r.id for r in t.rules} for t in plausible_theories(theory_a(), h, experience())]
    assert {"fill", "boostC"} not in ids


def test_disagreement_on_untested_condition():
    hot = Observation(t=0, fields={"level": 1, "hot": True})
    cold = Observation(t=0, fields={"level": 1, "hot": False})
    assert disagreement([theory_a(), theory_b()], hot, Action(name="boost")) == ["level"]
    assert disagreement([theory_a(), theory_b()], cold, Action(name="boost")) == []
    assert disagreement([theory_a(), theory_b()], hot, Action(name="fill")) == []
    assert goal_fields("obs.level >= 4 and obs['hot'] == False") == {"level", "hot"}


def test_robust_planner_avoids_action_the_theories_disagree_on():
    m, obj = manual(), manual().objectives[0]
    hot = Observation(t=0, fields={"level": 1, "hot": True})
    # the single best guess (theory A) boosts straight to the goal
    assert PlannerPolicy(theory_a(), m, obj).next_action(hot).name == "boost"
    robust = RobustPlannerPolicy([theory_a(), theory_b()], m, obj)
    a = robust.next_action(hot)
    assert a.name == "fill"
    assert robust.last_disagreement == []
    # it still reaches the goal by the safe route (in both theories, since they agree on fill)
    obs = hot
    for _ in range(6):
        robust.after_step(obs := Observation(t=obs.t + 1, fields={"level": obs.fields["level"] + 1, "hot": True}))
        if obs.fields["level"] >= 4:
            break
        assert robust.next_action(obs).name == "fill"
    assert obs.fields["level"] >= 4


def test_robust_planner_prefers_agreement_on_ties():
    # when cold, both theories agree on boost: no reason to avoid it
    m, obj = manual(), manual().objectives[0]
    robust = RobustPlannerPolicy([theory_a(), theory_b()], m, obj)
    assert robust.next_action(Observation(t=0, fields={"level": 1, "hot": False})).name == "boost"
    assert robust.last_disagreement == []


def test_single_theory_equals_planner():
    m, obj = manual(), manual().objectives[0]
    for fields in ({"level": 0, "hot": False}, {"level": 1, "hot": True}, {"level": 3, "hot": False}):
        obs = Observation(t=0, fields=fields)
        p, r = PlannerPolicy(theory_a(), m, obj), RobustPlannerPolicy([theory_a()], m, obj)
        for _ in range(3):
            a, b = p.next_action(obs), r.next_action(obs)
            assert a == b and p.last_plan == r.last_plan
            obs = Observation(t=obs.t + 1, fields={"level": obs.fields["level"] + 1, "hot": obs.fields["hot"]})
            p.after_step(obs)
            r.after_step(obs)
    assert r.as_playbook_stub().origin == "planner"


def test_robust_policy_helper_only_swaps_when_uncertain():
    class Inv:
        hypotheses, transitions, _replaces = hyps(), experience(), {}
    m, obj = manual(), manual().objectives[0]
    base = PlannerPolicy(theory_a(), m, obj)
    assert isinstance(robust_policy(base, theory_a(), Inv(), m, obj), RobustPlannerPolicy)
    Inv.hypotheses = {k: v for k, v in hyps().items() if k == "h1"}
    assert robust_policy(base, theory_a(), Inv(), m, obj) is base
