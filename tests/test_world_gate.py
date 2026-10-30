import random

import pytest

from logicscout import config
from logicscout.contracts import Action
from logicscout.worlds import gate_service


@pytest.fixture(scope="module", autouse=True)
def service():
    url = gate_service.start_in_thread()
    old = config.GATE_URL
    config.GATE_URL = url
    yield url
    config.GATE_URL = old


def make(variant="standard"):
    from logicscout.worlds.gate import Gate
    return Gate(variant)


def call(ep, job=0):
    return Action(name="call", args={"endpoint": ep, "job": job})


def oracle(w, seed):
    """Law-aware controller: mirrors the token bucket, one job at a time."""
    L = w.laws
    obs = w.reset(seed)
    tokens = max(1, L["capacity"] - seed % 2)
    stage, job = "create", -1
    for _ in range(40):
        t1 = obs.t + 1
        if t1 % L["refill_every"] == 0:
            tokens = min(L["capacity"], tokens + 1)
        need = 1
        if stage == "arm" and (t1 + 1) % L["refill_every"] != 0:
            need = 2
        if tokens < need:
            obs = w.act(Action(name="wait")).observation
            continue
        tokens -= 1
        a = call("create") if stage == "create" else call(stage, job)
        obs = w.act(a).observation
        f = obs.fields
        if stage == "create" and f["last_status"] == 201:
            job, stage = f["last_job"], "arm"
        elif stage == "arm" and f["last_status"] == 200:
            stage = "commit"
        elif stage == "commit":
            stage = "create" if f["last_status"] == 200 else "arm"
        if f["committed"] >= 5:
            break
    return w.success("commit5")


def test_roundtrip_and_status_free():
    w = make()
    o = w.reset(3)
    assert o.t == 0 and o.fields["committed"] == 0
    for _ in range(10):
        o = w.act(call("status")).observation
    assert o.fields["last_status"] == 200 and o.t == 10 and not o.fields["locked"]
    o = w.act(call("create")).observation
    assert o.fields["last_status"] == 201 and o.fields["jobs_draft"] == 1


def test_rate_limit_lockout():
    w = make()
    w.reset(0)
    codes = [w.act(call("create")).observation.fields["last_status"] for _ in range(14)]
    assert 429 in codes and 423 in codes
    assert w.observe().fields["lockouts"] == 1


def test_oldest_disarmed_and_stale_arm():
    w = make()
    w.reset(0)
    for _ in range(3):
        w.act(call("create"))
    for _ in range(3):
        w.act(Action(name="wait"))
    w.act(call("arm", 0))
    w.act(call("arm", 1))
    o = w.act(call("arm", 2)).observation
    assert o.fields["jobs_armed"] == 2 and o.fields["last_status"] == 200
    for _ in range(4):
        w.act(Action(name="wait"))
    o = w.act(call("commit", 2)).observation
    assert o.fields["last_status"] == 409 and o.fields["committed"] == 0


def test_determinism():
    def trace():
        w = make()
        w.reset(5)
        rng = random.Random(1)
        out = []
        for _ in range(30):
            a = call(rng.choice(gate_service_endpoints()), rng.randint(0, 3)) if rng.random() < .8 else Action(name="wait")
            out.append(w.act(a).observation.model_dump())
        return out
    assert trace() == trace()


def gate_service_endpoints():
    from logicscout.worlds.gate import ENDPOINTS
    return ENDPOINTS


def test_shift_survives_reset():
    w = make()
    w.reset(1)
    for s in range(20):
        before = dict(w.laws)
        rec = w.shift(s)
        assert rec.before == before and rec.after != before
        w.reset(2)
        assert w.laws == rec.after
        w.laws = make().laws
    kinds = {make().shift(s).kind for s in range(30)}
    assert len(kinds) >= 3


def test_namespaces_isolated():
    a, b = make(), make()
    a.reset(0)
    b.reset(0)
    a.act(call("create"))
    assert b.observe().fields["jobs_draft"] == 0 and a.observe().fields["jobs_draft"] == 1


def test_random_policy_rarely_succeeds():
    wins = 0
    for s in range(20):
        w = make()
        w.reset(s)
        rng = random.Random(s)
        for _ in range(40):
            if rng.random() < 0.2:
                w.act(Action(name="wait"))
            else:
                w.act(call(rng.choice(gate_service_endpoints()), rng.randint(0, 9)))
        wins += w.success("commit5")
    assert wins <= 2


@pytest.mark.parametrize("variant", ["standard", "tight_bucket", "short_window", "single_slot", "slow_refill"])
def test_oracle_succeeds(variant):
    from logicscout.worlds.gate import Gate
    seeds = [c.seed for c in Gate.referee_cases()] + list(range(10))
    wins = sum(oracle(make(variant), s) for s in seeds)
    assert wins / len(seeds) > 0.8


def test_unreachable_raises():
    from logicscout.worlds.gate import Gate, GateUnavailable
    old = config.GATE_URL
    config.GATE_URL = "http://127.0.0.1:1"
    try:
        with pytest.raises(GateUnavailable):
            Gate().reset(0)
    finally:
        config.GATE_URL = old


def test_manual_has_no_laws():
    from logicscout.worlds.gate import Gate
    text = Gate.manual().model_dump_json().lower()
    for word in ("token bucket", "window", "oldest", "capacity", "refill"):
        assert word not in text.split("briefing_topics")[0]


def test_meter_fields_observable():
    from logicscout.worlds.gate import Gate
    w = Gate()
    o = w.reset(0)
    assert {"tokens", "strikes", "arm_age"} <= set(o.fields) and o.fields["arm_age"] == -1
    w.close()
