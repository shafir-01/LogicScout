from logicscout.contracts import Mismatch, Rule, Theory
from logicscout.scout.monitor import DriftMonitor


def theory() -> Theory:
    return Theory(world_id="w", rules=[
        Rule(id="r1", statement="pump raises level", status="supported", confidence=0.9),
        Rule(id="r2", statement="weak guess", status="tentative", confidence=0.2),
    ])


def miss(field="level", rules=("r1",)) -> Mismatch:
    return Mismatch(field=field, predicted=1, observed=2, rule_ids=list(rules))


def test_no_false_alarm_on_stable_stream():
    m = DriftMonitor(theory())
    assert all(m.observe([]) == "ok" for _ in range(200))


def test_detects_consistent_new_mismatch_quickly():
    m = DriftMonitor(theory())
    for _ in range(20):
        m.observe([])
    statuses = [m.observe([miss()]) for _ in range(4)]
    assert statuses[0] == "suspected"
    assert "confirmed" in statuses[:3]
    assert m.rules_implicated and m.rules_implicated[0] == "r1"


def test_weak_rule_needs_more_evidence_than_strong_rule():
    strong, weak = DriftMonitor(theory(), warmup=0), DriftMonitor(theory(), warmup=0)

    def steps_to_confirm(mon, rid):
        for i in range(1, 30):
            if mon.observe([miss(rules=(rid,))]) == "confirmed":
                return i
        return 99
    assert steps_to_confirm(strong, "r1") <= steps_to_confirm(weak, "r2") <= 5


def test_single_glitch_is_not_confirmed():
    m = DriftMonitor(theory())
    for _ in range(10):
        m.observe([])
    assert m.observe([miss()]) == "suspected"
    statuses = [m.observe([]) for _ in range(15)]
    assert "confirmed" not in statuses
    assert statuses[-1] == "ok"


def test_chronic_error_present_from_the_start_is_baseline_not_drift():
    m = DriftMonitor(theory())
    for _ in range(30):
        m.observe([miss(field="noise", rules=())])
    assert m.status != "confirmed"


def test_uncovered_field_keyed_by_field_and_reset():
    m = DriftMonitor(theory(), warmup=0)
    for _ in range(5):
        st = m.observe([miss(field="temp", rules=())])
    assert st == "confirmed" and m.rules_implicated == ["field:temp"]
    m.reset(theory())
    assert m.status == "ok" and m.observe([]) == "ok"


def _stream(m, rate_fail, n, start=0):
    """r2 is checked every step and fails on a fixed pattern with the given rate; r1 is always right."""
    out = []
    for i in range(start, start + n):
        bad = (i * rate_fail) % 1 + rate_fail >= 1
        out.append(m.observe([miss(rules=("r2",))] if bad else [], ["r1"] + ([] if bad else ["r2"])))
    return out


def test_slow_detector_quiet_on_stationary_chronic_error():
    m = DriftMonitor(theory())
    assert "confirmed" not in _stream(m, 0.2, 300)


def test_slow_detector_catches_rising_failure_rate_of_an_unreliable_rule():
    m = DriftMonitor(theory())
    assert "confirmed" not in _stream(m, 0.2, 40)
    assert "confirmed" in _stream(m, 0.7, 60, start=40)
    assert m.rules_implicated[0] == "r2"


def test_reference_level_is_frozen_after_the_reference_period():
    m = DriftMonitor(theory(), reference=10)
    _stream(m, 0.2, 30)
    frozen = m.baseline
    _stream(m, 0.4, 3, start=30)
    assert m.baseline == frozen
