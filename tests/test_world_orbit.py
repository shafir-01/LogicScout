import random
import re

from logicscout.contracts import Action
from logicscout.worlds.orbit import OrbitWorld


def oracle(w: OrbitWorld) -> Action:
    L = w.laws
    lo, hi = L["band"]
    if w.fault:
        return Action(name="power", args={"unit": "bus", "state": "off"})
    if not w.bus_on:
        return Action(name="power", args={"unit": "bus", "state": "on"})
    if w.images and w.contact():
        return Action(name="downlink")
    if w.payload_on and len(w.images) < L["capacity"] and lo <= w.temp <= hi and w.last_cal is not None             and w.t - w.last_cal <= L["cal_window"]:
        return Action(name="capture")
    if not w.heater_on and w.temp < lo + 1.5:
        return Action(name="heater", args={"state": "on"})
    if w.heater_on and w.temp > hi - 1.5:
        return Action(name="heater", args={"state": "off"})
    if not w.payload_on:
        if w.bus_steps >= L["bus_warmup"]:
            return Action(name="power", args={"unit": "payload", "state": "on"})
        return Action(name="wait")
    if len(w.images) < L["capacity"] and lo <= w.temp <= hi:
        cal_ok = w.last_cal is not None and w.t - w.last_cal <= L["cal_window"]
        if cal_ok:
            return Action(name="capture")
        if w.last_cal_try is None or w.t - w.last_cal_try >= L["cal_cooldown"]:
            return Action(name="calibrate")
    return Action(name="wait")


def run(w, seed, policy, horizon=50):
    w.reset(seed)
    for _ in range(horizon):
        w.act(policy(w))
        if w.success("downlink3"):
            return True
    return False


def random_policy(rng):
    acts = [Action(name="power", args={"unit": u, "state": s}) for u in ("bus", "payload") for s in ("on", "off")]
    acts += [Action(name="heater", args={"state": s}) for s in ("on", "off")]
    acts += [Action(name=n) for n in ("calibrate", "capture", "downlink", "wait")]
    return lambda w: rng.choice(acts)


def test_determinism():
    traces = []
    for _ in range(2):
        w, rng = OrbitWorld(), random.Random(5)
        pol = random_policy(rng)
        w.reset(42)
        traces.append([w.act(pol(w)).observation.fields for _ in range(40)])
    assert traces[0] == traces[1]


def test_oracle_all_variants():
    for v in OrbitWorld.variants():
        wins = sum(run(OrbitWorld(v), s, oracle) for s in range(20))
        assert wins / 20 > 0.8, (v, wins)
    for c in OrbitWorld.referee_cases():
        assert c.seed >= 10000
        assert run(OrbitWorld(c.variant), c.seed, oracle), c.case_id


def test_random_rarely_succeeds():
    wins = sum(run(OrbitWorld(), s, random_policy(random.Random(s))) for s in range(20))
    assert wins / 20 < 0.3


def test_shift_survives_reset_and_changes_behaviour():
    kinds = set()
    for sd in range(12):
        w = OrbitWorld()
        before = repr(w.laws)
        rec = w.shift(sd)
        kinds.add(rec.kind)
        w.reset(3)
        assert repr(w.laws) != before and rec.after
    assert len(kinds) >= 3
    # band shift changes capture validity for the same action sequence
    seqs = []
    for shifted in (False, True):
        w = OrbitWorld()
        if shifted:
            w.laws["band"] = [w.laws["band"][0] + 4, w.laws["band"][1] + 4]
        w.reset(1)
        obs = [w.act(oracle(w)).observation.fields for _ in range(30)]
        seqs.append(obs)
    assert seqs[0] != seqs[1]


def test_manual_has_no_law_numbers():
    m = OrbitWorld.manual()
    text = " ".join([m.summary] + [a.description for a in m.actions] + [f.description for f in m.observations])
    assert not re.search(r"\d", text)
    assert len(m.observations) <= 10
    assert len(OrbitWorld.variants()) >= 4
