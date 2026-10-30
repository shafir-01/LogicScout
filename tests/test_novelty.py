import asyncio

from logicscout.contracts import Action, Observation, Rule, Theory
from logicscout.logbook import Logbook
from logicscout.scout import novelty
from logicscout.scout.investigator import Investigator
from logicscout.scout.novelty import Stats, expected_surprise, novelty_probes

from tests.test_investigator import MANUAL, ToyPort


def _transitions(actions):
    port = ToyPort()
    obs = port.reset(0)
    out = []
    for a in actions:
        nxt = port.act(a).observation
        out.append((obs, a, nxt))
        obs = nxt
    return out, obs


PUMP = Action(name="pump", args={"rate": 5})
WAIT = Action(name="wait")
TOGGLE = Action(name="toggle")
GOOD = Theory(world_id="toy", rules=[
    Rule(id="R1", statement="s", action="pump", effects={"level": "obs.level + 2 * args.rate"}),
    Rule(id="R2", statement="s", action="toggle", effects={"valve": "'open' if obs.valve == 'closed' else 'closed'"}),
])


def test_probes_are_plain_english_and_valid():
    tr, last = _transitions([WAIT, WAIT, WAIT, TOGGLE])
    probes = novelty_probes(Theory(world_id="toy"), tr, MANUAL, last, n=3)
    assert 1 <= len(probes) <= 3
    names = {a.name for a in MANUAL.actions}
    for p in probes:
        assert p["purpose"].startswith("Try something it has never done: ")
        assert p["seed"] is None
        assert 0 < len(p["actions"]) <= novelty.MAX_ACTIONS
        assert all(a.name in names for a in p["actions"])
    surprises = [p["surprise"] for p in probes]
    assert surprises == sorted(surprises, reverse=True)


def test_untried_control_scores_higher_than_well_known_one():
    # pump never tried; wait tried many times and predicted perfectly by the empty theory
    tr, last = _transitions([WAIT] * 12)
    th = Theory(world_id="toy")
    stats = Stats(th, tr, MANUAL)
    assert expected_surprise(th, stats, last, [PUMP] * 3) > expected_surprise(th, stats, last, [WAIT] * 3)
    best = novelty_probes(th, tr, MANUAL, last, n=1)[0]
    assert any(a.name != "wait" for a in best["actions"])


def test_residuals_drive_scores_where_theory_is_wrong():
    tr, last = _transitions([PUMP, WAIT, PUMP, WAIT, TOGGLE, WAIT, PUMP, TOGGLE] * 2)
    wrong = Theory(world_id="toy", rules=[Rule(id="R1", statement="s", action="pump", effects={"level": "obs.level + 1"}),
                                          GOOD.rules[1]])
    s_good = Stats(GOOD, tr, MANUAL)
    s_wrong = Stats(wrong, tr, MANUAL)
    assert expected_surprise(wrong, s_wrong, last, [PUMP] * 3) > expected_surprise(GOOD, s_good, last, [PUMP] * 3)


def test_delay_and_falsification_kinds_present():
    tr, last = _transitions([PUMP, TOGGLE, WAIT])
    found = novelty_probes(GOOD, tr, MANUAL, last, n=20)
    kinds = {p["kind"] for p in found}
    assert {"residual", "falsify", "delay"} <= kinds
    delay = next(p for p in found if p["kind"] == "delay")
    assert delay["actions"][0].name != "wait" and all(a.name == "wait" for a in delay["actions"][1:])


def test_deterministic():
    tr, last = _transitions([PUMP, WAIT, TOGGLE])
    a = novelty_probes(GOOD, tr, MANUAL, last)
    b = novelty_probes(GOOD, tr, MANUAL, last)
    assert [(p["purpose"], [x.model_dump() for x in p["actions"]]) for p in a] == \
           [(p["purpose"], [x.model_dump() for x in p["actions"]]) for p in b]


class _NoLLM:
    async def json(self, *a, **k):
        raise RuntimeError("no model in tests")


def _run(enabled):
    novelty.ENABLED = enabled
    try:
        port = ToyPort()
        log = Logbook("t-novelty")
        inv = Investigator(_NoLLM(), port, MANUAL, log)
        asyncio.run(inv.investigate(Theory(world_id="toy"), 30))
        return [e.data["probe"]["purpose"] for e in log.events if e.kind == "probe.designed"], inv
    finally:
        novelty.ENABLED = True


def test_investigator_uses_novelty_probes_and_respects_switch():
    on, inv = _run(True)
    assert any(p.startswith("Try something it has never done") for p in on)
    assert inv.probes_used <= 30
    off, _ = _run(False)
    assert not any(p.startswith("Try something it has never done") for p in off)


def test_merge_never_breaks_on_errors():
    class Broken:
        def observe(self):
            raise RuntimeError("down")

    class Inv:
        port = Broken()
        transitions = []
        manual = MANUAL
        log = Logbook("t")

    cands = [{"purpose": "x", "seed": None, "actions": [WAIT]}]
    assert novelty.merge(Inv(), GOOD, [], cands) == cands
