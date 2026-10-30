"""Metrics that cannot hide failures: changed-value accuracy, open-loop rollouts, goal-field accuracy."""
from logicscout.contracts import Action, Observation, RefereeReport, Rule, Theory
from logicscout.referee.referee import consequence_metrics, report_digest
from logicscout.theory import (
    accuracy, changed_accuracy, field_accuracy, goal_fields, persistence_accuracy, rollout_accuracy,
)


def quiet_world(n: int = 40):
    """Fields a..i never change; `wait` does nothing; every 10th step `bump` raises `level` by 1.
    So ~97% of (step, field) pairs are unchanged."""
    fields = {**{c: 0 for c in "abcdefghi"}, "level": 0}
    out, t = [], 0
    for i in range(n):
        before = Observation(t=t, fields=dict(fields))
        act = Action(name="bump" if i % 10 == 9 else "wait")
        if act.name == "bump":
            fields["level"] += 1
        t += 1
        out.append((before, act, Observation(t=t, fields=dict(fields))))
    return out


CORRECT = Theory(world_id="toy", rules=[
    Rule(id="bump", statement="bump raises level", action="bump", effects={"level": "obs.level + 1"})])
LAZY = Theory(world_id="toy")


def test_persistence_scores_high_plain_but_zero_on_changes():
    tr = quiet_world()
    assert persistence_accuracy(tr) > 0.9
    assert accuracy(LAZY, tr) > 0.9
    assert changed_accuracy(LAZY, tr) == 0.0
    assert field_accuracy(LAZY, tr, ["level"]) == 0.9  # 36/40 steps level is unchanged


def test_correct_theory_scores_one_everywhere():
    tr = quiet_world()
    assert accuracy(CORRECT, tr) == 1.0
    assert changed_accuracy(CORRECT, tr) == 1.0
    assert field_accuracy(CORRECT, tr, ["level"]) == 1.0
    assert rollout_accuracy(CORRECT, [tr], horizon=5) == {k: 1.0 for k in range(1, 6)}


def delayed_world(n: int = 30):
    """`ship` sets `arrived` two steps later; every other step is `wait`."""
    out, t, arrived, due = [], 0, False, None
    for i in range(n):
        before = Observation(t=t, fields={"arrived": arrived})
        act = Action(name="ship" if i % 6 == 0 else "wait")
        t += 1
        if act.name == "ship":
            arrived, due = False, t + 2
        if due is not None and t >= due:
            arrived, due = True, None
        out.append((before, act, Observation(t=t, fields={"arrived": arrived})))
    return out


def test_rollout_decays_for_wrong_delayed_rule():
    tr = delayed_world()
    right = Theory(world_id="toy", rules=[
        Rule(id="go", statement="", action="ship", effects={"arrived": "False"}),
        Rule(id="land", statement="", action="ship", delay=2, effects={"arrived": "True"})])
    wrong = Theory(world_id="toy", rules=[  # believes the ship lands immediately and never resets
        Rule(id="land", statement="", action="ship", effects={"arrived": "True"})])
    assert rollout_accuracy(right, [tr], horizon=5) == {k: 1.0 for k in range(1, 6)}
    r = rollout_accuracy(wrong, [tr], horizon=5)
    assert r[1] > r[5] and r[5] < 1.0
    assert changed_accuracy(wrong, tr) < changed_accuracy(right, tr) == 1.0


def test_goal_fields_parsed_from_success_expression():
    assert goal_fields("obs.delivered >= 6 and obs.battery > 0.1 and obs.delivered < 9") == ["delivered", "battery"]


def test_consequence_metrics_and_digest_stability():
    tr = quiet_world()
    m = consequence_metrics(LAZY, [tr], "obs.level >= 3")
    assert m["changed_accuracy"] == 0.0 and m["changed_baseline"] == 0.0
    assert m["n_changed"] == 4 and m["n_transitions"] == 40
    assert m["goal_field_accuracy"] == 0.9
    assert m["rollout_accuracy"][1] > m["rollout_accuracy"][5]
    # A report without the new optional fields keeps the digest it had before they existed.
    base = dict(run_id="r", world_id="w", theory_version=0, playbook_id="p", cases=[], success_rate=0.0,
                prediction_accuracy=0.5)
    plain = RefereeReport(**base)
    assert report_digest(plain) == report_digest(RefereeReport.model_validate(plain.model_dump()))
    rich = RefereeReport(**base, **m)
    assert report_digest(rich) != report_digest(plain)
    assert RefereeReport.model_validate_json(rich.model_dump_json()).rollout_accuracy == rich.rollout_accuracy
