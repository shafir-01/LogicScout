import random
import re

from logicscout.contracts import Action
from logicscout.worlds.relay import RelayWorld

HORIZON = 40


def run(world, policy, seed, objective="priority5"):
    obs = world.reset(seed)
    trace = [obs.fields]
    for _ in range(HORIZON):
        if world.success(objective):
            break
        obs = world.act(policy(world, obs)).observation
        trace.append(obs.fields)
    return world.success(objective), trace


def random_policy(seed):
    rng = random.Random(seed + 555)

    def pol(world, obs):
        k = rng.choice(["send", "prioritize", "wait"])
        if k == "send":
            return Action(name="send", args={"via": rng.choice(["buoy", "sat"]), "n": rng.randint(1, 3)})
        return Action(name=k)
    return pol


def oracle(world, obs):
    L, f = world.laws, obs.fields
    t = f["t"]
    is_open = lambda s: s % L["period"] < L["window"]  # noqa: E731
    if f["priority_waiting"] == 0:
        return Action(name="wait")
    if world.prioritized_last:
        n = min(L["buoy_cap"], f["priority_waiting"], 3)
        if is_open(t) and f["buoy_signal"] > 0:
            return Action(name="send", args={"via": "buoy", "n": n})
        if f["vessel_energy"] >= L["sat_cost"]:
            k = min(3, f["vessel_energy"] // L["sat_cost"], f["priority_waiting"])
            return Action(name="send", args={"via": "sat", "n": k})
    if is_open(t + 1) or f["vessel_energy"] >= L["sat_cost"]:
        return Action(name="prioritize")
    return Action(name="wait")


def test_determinism():
    a = run(RelayWorld(), random_policy(3), 42)[1]
    b = run(RelayWorld(), random_policy(3), 42)[1]
    assert a == b


def test_random_rarely_succeeds():
    wins = sum(run(RelayWorld(), random_policy(s), s)[0] for s in range(20))
    assert wins / 20 < 0.3


def test_oracle_succeeds_every_variant():
    for v in RelayWorld.variants():
        wins = sum(run(RelayWorld(v), oracle, s)[0] for s in range(10000, 10020))
        assert wins / 20 > 0.8, v


def test_shift_survives_reset_and_changes_behaviour():
    for seed in range(3):
        w = RelayWorld()
        base = run(w, random_policy(1), 5)[1]
        rec = w.shift(seed)
        assert rec.before != rec.after
        assert w.laws[next(iter(rec.after))] == next(iter(rec.after.values()))
        w.reset(5)
        assert w.laws[next(iter(rec.after))] == next(iter(rec.after.values()))
    w = RelayWorld()
    probe = [Action(name="send", args={"via": "buoy", "n": 1})] * 12
    def seq(world):
        world.reset(1)
        return [world.act(a).observation.fields["delivered"] for a in probe]
    before = seq(w)
    w.shift(0)
    assert seq(w) != before
    assert base


def test_manual_has_no_law_numbers():
    m = RelayWorld.manual()
    text = " ".join([m.summary] + [a.description for a in m.actions]
                    + [p.description for a in m.actions for p in a.params]
                    + [f.description for f in m.observations] + m.briefing_topics)
    for word in ("lifo", "newest", "capacity", "logicscout"):
        assert word not in text.lower()
    controls = " ".join([a.description for a in m.actions] + [f.description for f in m.observations])
    for word in ("window", "latency", "battery", "period"):
        assert word not in controls.lower()
    assert not re.search(r"\b[2-9]\b", controls)


def test_referee_cases():
    cases = RelayWorld.referee_cases()
    assert len(cases) >= 6 and all(c.seed >= 10000 for c in cases)
    assert {c.variant for c in cases} - {"standard"}
