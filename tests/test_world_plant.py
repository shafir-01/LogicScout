import random
import re

from logicscout.contracts import Action
from logicscout.worlds.plant import OBJ_ID, PlantWorld

HORIZON = 45
CANDIDATES = [Action(name="wait")] + [Action(name="pump", args={"rate": r}) for r in range(4)] + [
    Action(name="valve", args={"open": v}) for v in range(3)]


def _plan_action(w: PlantWorld, v: int, p: int) -> Action:
    if w.valve_open != v:
        return Action(name="valve", args={"open": v})
    if w.pump_rate != p and not w.lock:
        return Action(name="pump", args={"rate": p})
    return Action(name="wait")


def _rollout(w: PlantWorld, v: int, p: int, n: int = 30) -> tuple:
    s, best = w.clone(), w.streak
    for _ in range(n):
        s.act(_plan_action(s, v, p))
        best = max(best, s.streak)
        if best >= 10:
            break
    return (best, -abs(s.level - 50))


def oracle(w: PlantWorld) -> bool:
    for _ in range(HORIZON):
        if w.success(OBJ_ID):
            return True
        v, p = max(((v, p) for v in range(3) for p in range(4)), key=lambda vp: _rollout(w, *vp))
        w.act(_plan_action(w, v, p))
    return w.success(OBJ_ID)


def run_random(w: PlantWorld, seed: int) -> bool:
    rng = random.Random(seed)
    for _ in range(HORIZON):
        w.act(rng.choice(CANDIDATES))
        if w.success(OBJ_ID):
            return True
    return False


def trace(w, seed, n=30):
    w.reset(seed)
    rng = random.Random(1)
    return [w.act(rng.choice(CANDIDATES)).observation.fields for _ in range(n)]


def test_determinism():
    assert trace(PlantWorld(), 5) == trace(PlantWorld(), 5)


def test_shift_survives_reset_and_changes_behaviour():
    changed = 0
    for s in range(6):
        w = PlantWorld()
        base = trace(w, 3)
        rec = w.shift(s)
        assert rec.before != rec.after
        after = trace(w, 3)
        assert w.laws != PlantWorld().laws
        changed += base != after
    assert changed >= 4


def test_random_rarely_succeeds():
    wins = 0
    for s in range(20):
        w = PlantWorld()
        w.reset(s)
        wins += run_random(w, s)
    assert wins / 20 < 0.3


def test_oracle_succeeds_every_variant():
    for v in PlantWorld.variants():
        wins = 0
        for s in range(10):
            w = PlantWorld(v)
            w.reset(10000 + s)
            wins += oracle(w)
        assert wins / 10 > 0.8, (v, wins)


def test_trip_and_rate_limit():
    w = PlantWorld()
    w.reset(0)
    assert w.act(Action(name="valve", args={"open": 2})).observation.fields["valve_open"] == 1
    w.reset(0)
    obs = w.act(Action(name="pump", args={"rate": 3})).observation.fields
    assert obs["tripped"] and obs["pump_rate"] == 0


def test_manual_has_no_law_numbers():
    m = PlantWorld.manual()
    text = m.summary + " ".join(a.description for a in m.actions) + " ".join(f.description for f in m.observations)
    laws = PlantWorld.default_laws("standard")
    nums = set(re.findall(r"\d+", text))
    assert not {str(laws[k]) for k in ("pump_gain", "trip_above", "lockout", "drain_div")} & nums
    assert len(m.observations) <= 8 and all(c.seed >= 10000 for c in PlantWorld.referee_cases())
