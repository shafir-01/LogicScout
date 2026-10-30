import asyncio

from logicscout import safety
from logicscout.contracts import Action, Observation, Rule, Theory
from logicscout.logbook import Logbook
from logicscout.scout.investigator import Investigator
from logicscout.worlds.base import load_all
from tests.test_investigator import MANUAL, ToyPort

SAFE_MANUAL = MANUAL.model_copy(update={"safety": ["obs.level <= 20"]})
PUMP = Rule(id="r1", statement="pump adds twice the rate", action="pump",
            effects={"level": "obs.level + 2 * args.rate"}, status="supported")
THEORY = Theory(world_id="toy", rules=[PUMP])


def obs(level, t=0):
    return Observation(t=t, fields={"t": t, "level": level, "valve": "closed"})


class AlwaysPump:
    def __init__(self):
        self.steps = 0

    def next_action(self, o):
        return Action(name="pump", args={"rate": 5})

    def after_step(self, o):
        self.steps += 1


def test_violations_is_pure_and_lists_broken_limits():
    m = MANUAL.model_copy(update={"safety": ["obs.level <= 20", "obs.valve == 'closed'", "obs.missing > 1"]})
    fields = {"t": 3, "level": 25, "valve": "open"}
    assert safety.violations(m, fields) == ["obs.level <= 20", "obs.valve == 'closed'"]
    assert fields == {"t": 3, "level": 25, "valve": "open"}
    assert safety.violations(m, {"level": 5, "valve": "closed"}) == []  # unknown field is not a violation
    assert safety.violations(MANUAL, fields) == []  # no limits declared
    assert safety.new_violations(m, {"level": 25, "valve": "closed"}, fields) == ["obs.valve == 'closed'"]


def test_guard_blocks_predicted_unsafe_action_and_picks_closest_safe():
    inner = AlwaysPump()
    guard = safety.SafeGuard(inner, THEORY, SAFE_MANUAL)
    a = guard.next_action(obs(5))  # 5 + 10 = 15: safe, passes through
    assert a.args == {"rate": 5} and guard.blocked == 0
    guard.after_step(obs(15, 1))
    a = guard.next_action(obs(15, 1))  # rate 5 would reach 25 > 20; rate 2 (19) is the closest safe pump
    assert a.name == "pump" and a.args == {"rate": 2}
    assert guard.blocked == 1 and guard.blocks[0]["limits"] == ["obs.level <= 20"]
    assert guard.last_why.startswith("safety guard")
    guard.after_step(obs(19, 2))
    a = guard.next_action(obs(19, 2))  # every pump breaks the limit: fall back to a no-op
    assert a.name in ("wait", "toggle") and guard.blocked == 2
    assert inner.steps == 2  # the wrapped policy still sees every step


def test_guard_without_limits_is_transparent():
    guard = safety.SafeGuard(AlwaysPump(), THEORY, MANUAL)
    assert guard.next_action(obs(19)).args == {"rate": 5} and guard.blocked == 0


def test_probe_filter_truncates_at_first_predicted_violation():
    acts = [Action(name="pump", args={"rate": 5})] * 3  # 0 -> 10 -> 20 -> 30
    assert safety.safe_prefix(THEORY, obs(0), acts, SAFE_MANUAL) == 2
    assert not safety.probe_is_safe(THEORY, obs(0), acts, SAFE_MANUAL)
    assert safety.probe_is_safe(THEORY, obs(0), acts[:2], SAFE_MANUAL)
    assert safety.probe_is_safe(Theory(world_id="toy"), obs(0), acts, SAFE_MANUAL)  # blind theory foresees nothing


def test_record_logs_each_new_violation_once():
    log = Logbook("t")
    log.set_phase("control")
    assert safety.record(log, SAFE_MANUAL, obs(15), obs(25, 1)) == ["obs.level <= 20"]
    assert safety.record(log, SAFE_MANUAL, obs(25, 1), obs(27, 2)) == []  # still broken: same violation
    ev = [e for e in log.events if e.kind == "safety.violation"]
    assert len(ev) == 1 and ev[0].data["expr"] == "obs.level <= 20" and ev[0].data["phase"] == "control"
    assert ev[0].data["fields"]["level"] == 25


class SafePort(ToyPort):
    def manual(self):
        return SAFE_MANUAL


def test_investigator_never_runs_a_probe_predicted_unsafe():
    port, log = SafePort(), Logbook("inv")
    inv = Investigator(None, port, SAFE_MANUAL, log)
    start = port.reset(0)
    inv.transitions.append((start, Action(name="wait"), start))  # skip the blind first touch
    asyncio.run(inv.investigate(THEORY, budget=25, caps={"hypothesize": 0, "design_probe": 0, "revise_theory": 0}))
    levels = [e.data["observation"]["fields"]["level"] for e in log.events if e.kind == "probe.step"]
    assert levels and max(levels) <= 20
    assert not [e for e in log.events if e.kind == "safety.violation"]


def test_every_world_declares_valid_limits():
    from logicscout.dsl import validate
    for wid in ("relay", "rover", "orbit", "plant", "gate", "forge"):
        m = load_all()[wid].manual()
        fields = {f.name for f in m.observations}
        assert m.safety, wid
        for expr in m.safety:
            assert validate(expr) == [], (wid, expr)
            assert any(f"obs.{f}" in expr for f in fields), (wid, expr)
