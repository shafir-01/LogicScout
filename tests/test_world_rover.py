import random
import re

import pytest

from logicscout.contracts import Action
from logicscout.worlds.rover import OBJECTIVE_ID, RoverWorld

HORIZON = RoverWorld.manual().objectives[0].horizon


def oracle_action(w: RoverWorld) -> Action:
    L = w.laws
    target = w._next_site()
    pending_sites = {p[2] for p in w.pending if p[1] == "confirmed"}
    if len(w.confirmed) + len(pending_sites) >= 3 or target < 0:
        return Action(name="wait")
    if w.position == target and target not in pending_sites:
        if w.moved_last:
            return Action(name="cool") if w.heat > 0 else Action(name="wait")
        return Action(name="scan")
    if w.position == target:  # scanned, waiting is wasteful: skip ahead to next site
        ahead = [s for s in w.sites if s > w.position and s not in w.confirmed]
        target = ahead[0]
    dist = target - w.position
    if w.locked_left > 0:
        return Action(name="cool")
    want = min(2, dist)
    if w.heat + want * want > L["heat_threshold"]:
        return Action(name="cool")
    return Action(name="drive", args={"speed": want, "dir": "fwd"})


def run(policy, seed, variant="standard"):
    w = RoverWorld(variant)
    w.reset(seed)
    for _ in range(HORIZON):
        w.act(policy(w))
        if w.success(OBJECTIVE_ID):
            return True
    return False


def test_determinism():
    def trace(seed):
        w = RoverWorld()
        w.reset(seed)
        rng = random.Random(1)
        out = []
        for _ in range(40):
            out.append(w.act(random_action(rng)).observation.fields)
        return out
    assert trace(5) == trace(5)


def random_action(rng):
    n = rng.choice(["drive", "drive", "scan", "cool", "wait"])
    if n == "drive":
        return Action(name="drive", args={"speed": rng.randint(1, 3), "dir": rng.choice(["fwd", "back"])})
    return Action(name=n)


def test_random_rarely_succeeds():
    wins = 0
    for seed in range(20):
        rng = random.Random(seed)
        wins += run(lambda w: random_action(rng), seed)
    assert wins / 20 < 0.3


@pytest.mark.parametrize("variant", RoverWorld.variants())
def test_oracle_succeeds(variant):
    seeds = [c.seed for c in RoverWorld.referee_cases()] + list(range(20))
    wins = sum(run(oracle_action, s, variant) for s in seeds)
    assert wins / len(seeds) > 0.8


def test_shift_survives_reset_and_changes_behaviour():
    for seed in range(6):
        w = RoverWorld()
        w.reset(3)
        rec = w.shift(seed)
        assert rec.before != rec.after
        laws = dict(w.laws)
        w.reset(3)
        assert w.laws == laws
        base = RoverWorld()
        base.reset(3)
        acts = [Action(name="drive", args={"speed": 2, "dir": "fwd"})] * 2 + [Action(name="cool")] \
            + [Action(name="drive", args={"speed": 2, "dir": "fwd"})] * 2 + [Action(name="cool"), Action(name="scan")] \
            + [Action(name="wait")] * 4
        assert [w.act(a).observation.fields for a in acts] != [base.act(a).observation.fields for a in acts]


def test_manual_has_no_law_numbers():
    text = RoverWorld.manual().model_dump_json()
    for v in ("8.0", "lockout", "squared", "blurred after", "delay"):
        assert v not in text
    assert not re.search(r"\bthreshold\b", text)


def test_referee_cases_and_errors():
    cases = RoverWorld.referee_cases()
    assert len(cases) >= 6 and all(c.seed >= 10000 for c in cases)
    assert len(RoverWorld.variants()) >= 4
    w = RoverWorld()
    w.reset(0)
    assert w.act(Action(name="drive", args={"speed": 5, "dir": "fwd"})).error
    assert w.act(Action(name="fly")).error
    assert RoverWorld.truth(w.laws)
