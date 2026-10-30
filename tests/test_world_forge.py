import random
import re

import pytest

from logicscout.contracts import Action
from logicscout.referee.referee import random_action
from logicscout.theory import accuracy, persistence_accuracy, validate_theory
from logicscout.worlds.forge import OBJ_ID, ForgeWorld
from logicscout.worlds.mechanisms import MECHANISMS, reference_theory

SEEDS = range(1, 37)


def candidates(w: ForgeWorld) -> list[Action]:
    out = []
    for a in w.manual().actions:
        out += [Action(name=a.name, args={"level": lv}) for lv in range(4)] if a.params else [Action(name=a.name)]
    return out


def oracle(w: ForgeWorld, horizon: int, width: int = 48) -> bool:
    """Beam search over the TRUE simulator (clones of the world), then execute the best plan."""
    acts = candidates(w)

    def value(s: ForgeWorld) -> tuple:
        return (s.sim.f["out"] + s.sim.f.get("buf", 0) + sum(s.sim.pipe), s.sim.f["out"])

    beam = [(w.clone(), [])]
    best = None
    for _ in range(horizon):
        seen = {}
        for s, plan in beam:
            for a in acts:
                n = s.clone()
                n.act(a)
                seen.setdefault(n.sim.key(), (n, plan + [a]))
                if n.success(OBJ_ID) and best is None:
                    best = plan + [a]
        if best:
            break
        beam = sorted(seen.values(), key=lambda x: value(x[0]), reverse=True)[:width]
    for a in best or []:
        w.act(a)
    return w.success(OBJ_ID)


def run_random(w: ForgeWorld, horizon: int, seed: int) -> bool:
    rng = random.Random(seed)
    for _ in range(horizon):
        w.act(random_action(w.manual().actions, rng))
        if w.success(OBJ_ID):
            return True
    return False


def trace(w: ForgeWorld, seed: int, n: int = 40) -> list[dict]:
    w.reset(seed)
    rng = random.Random(1)
    return [w.act(random_action(w.manual().actions, rng)).observation.fields for _ in range(n)]


def test_determinism_and_shape():
    for s in SEEDS:
        a, b = ForgeWorld.generate(s), ForgeWorld(f"g{s}")
        assert a.laws == b.laws and a.manual() == b.manual()
        assert trace(a, 3) == trace(b, 3)
        m = a.manual()
        assert 3 <= len(m.actions) <= 5 and 5 <= len(m.observations) - 1 <= 8
        assert 3 <= len(a.laws["mechanisms"]) <= 5 and set(a.laws["mechanisms"]) <= set(MECHANISMS)
        assert m.title == f"Unknown system #{s}" and m.domain == "Generated" and m.briefing_topics == []
    assert ForgeWorld("standard").laws == ForgeWorld("g1").laws
    assert len({ForgeWorld.manual_for(f"g{s}").model_dump_json() for s in SEEDS}) == len(SEEDS)
    with pytest.raises(ValueError):
        ForgeWorld("bogus")


def test_oracle_succeeds_random_fails():
    oracle_wins = random_wins = n = 0
    for s in SEEDS:
        h = ForgeWorld.manual_for(f"g{s}").objectives[0].horizon
        for c in ForgeWorld.referee_cases_for(f"g{s}")[:2]:
            w = ForgeWorld(c.variant)
            w.reset(c.seed)
            oracle_wins += oracle(w, h)
            w.reset(c.seed)
            random_wins += run_random(w, h, c.seed)
            n += 1
    print(f"oracle {oracle_wins}/{n}  random {random_wins}/{n}")
    assert oracle_wins / n >= 0.95
    assert random_wins / n <= 0.15


def test_reference_theory_predicts_transitions():
    worst = 1.0
    for s in SEEDS:
        w = ForgeWorld.generate(s)
        theory = reference_theory(w.laws)
        assert validate_theory(theory, w.manual()) == []
        rng = random.Random(s)
        tr = []
        for ep in range(4):
            obs = w.reset(ep)
            for _ in range(40):
                a = rng.choice(candidates(w)) if ep < 2 else random_action(w.manual().actions, rng)
                r = w.act(a)
                tr.append((obs, a, r.observation))
                obs = r.observation
        acc = accuracy(theory, tr)
        worst = min(worst, acc)
        assert acc >= 0.95, (s, w.laws["mechanisms"], acc)
        assert acc > persistence_accuracy(tr)
    print(f"reference theory worst accuracy {worst:.3f}")


def test_shift_survives_reset_and_changes_behaviour():
    changed = 0
    for s in SEEDS:
        w = ForgeWorld.generate(s)
        base = trace(w, 3)
        rec = w.shift(s)
        assert rec.before != rec.after and rec.kind in w.laws["mechanisms"]
        w.reset(5)
        assert w.laws != ForgeWorld.generate(s).laws
        changed += base != trace(w, 3)
    assert changed / len(SEEDS) >= 0.6, changed


def test_manual_has_no_law_parameters():
    words = re.compile(r"delay|cooldown|window|capacity|reservoir|precondition|invert|threshold|lockout|"
                       r"heat|rate.limit|regen|cost|mechanism", re.I)
    for s in SEEDS:
        m = ForgeWorld.manual_for(f"g{s}")
        laws = ForgeWorld.default_laws(f"g{s}")
        text = m.model_dump_json()
        assert not words.search(text), (s, words.search(text))
        for k, v in laws.items():
            if k not in ("names", "mechanisms"):
                assert k not in text, (s, k)
        assert all(sentence not in text for sentence in ForgeWorld.truth(laws))


def test_instance_manual_reaches_the_port():
    from logicscout.sandbox.session import open_local

    s = open_local("forge", "g7")
    assert s.port.manual() == ForgeWorld.manual_for("g7") != ForgeWorld.manual()
    assert ForgeWorld("g7").instance_manual == ForgeWorld.manual_for("g7")
    assert all(c.seed > 1000 and c.variant == "g7" for c in ForgeWorld.referee_cases_for("g7"))


def test_producer_spam_never_reaches_target():
    for s in SEEDS:
        w = ForgeWorld.generate(s)
        P = w.laws["names"]["P"]
        h = w.manual().objectives[0].horizon
        for c in w.referee_cases_for(f"g{s}"):
            w.reset(c.seed)
            for _ in range(h):
                w.act(Action(name=P))
            assert not w.success(OBJ_ID), (s, c.seed, w.laws["mechanisms"])


def test_shift_kind_from_menu():
    ids = {m["id"] for m in ForgeWorld.shift_menu()}
    assert ids == set(MECHANISMS)
    w = ForgeWorld.generate(3)
    mech = w.laws["mechanisms"][0]
    assert w.shift(0, mech).kind == mech
    absent = next(iter(ids - set(w.laws["mechanisms"])))
    assert w.shift(0, absent).kind in w.laws["mechanisms"]


def test_server_variant_validation_and_forge_new():
    from fastapi.testclient import TestClient

    from logicscout.server import runs as R
    from logicscout.server.app import create_app

    R.check_variant("forge", "g42")
    R.check_variant("plant", "standard")
    for wid, v in (("forge", "g1234567"), ("forge", "x1"), ("plant", "g4"), ("plant", "long_line")):
        with pytest.raises(ValueError):
            R.check_variant(wid, v)
    c = TestClient(create_app())
    r = c.get("/api/forge/new").json()
    assert re.fullmatch(r"g\d{1,6}", r["variant"]) and r["manual"]["world_id"] == "forge"
    assert r["manual"] == ForgeWorld.manual_for(r["variant"]).model_dump(mode="json")
    assert any(m["world_id"] == "forge" and m["title"] == "Unknown system #1" for m in c.get("/api/worlds").json())
    assert c.post("/api/runs", json={"world_id": "plant", "variant": "g5"}).status_code == 400
