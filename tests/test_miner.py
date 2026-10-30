import random
import time

from logicscout import dsl
from logicscout.contracts import (
    Action, ActionSpec, FieldSpec, Objective, Observation, ParamSpec, Theory, WorldManual,
)
from logicscout.scout.miner import mine
from logicscout.theory import accuracy, validate_theory


def _manual(actions, fields):
    return WorldManual(
        world_id="toy", title="Toy", domain="test", summary="toy", actions=actions,
        observations=[FieldSpec(name=n, type=ty) for n, ty in fields],
        objectives=[Objective(id="o", text="o", success="True", horizon=5)], probe_budget=10,
    )


def _roll(manual, law, init, seed, episodes=4, steps=50):
    rng = random.Random(seed)
    out = []
    for _ in range(episodes):
        state, t, pending, mem = dict(init), 0, [], {}
        for _ in range(steps):
            spec = rng.choice(manual.actions)
            args = {p.name: rng.randint(int(p.min), int(p.max)) for p in spec.params}
            a = Action(name=spec.name, args=args)
            before = Observation(t=t, fields=dict(state))
            nxt = law(dict(state), a, t, pending, mem)
            for due, f, v in [p for p in pending if p[0] == t + 1]:
                nxt[f] = v
            pending[:] = [p for p in pending if p[0] > t + 1]
            t += 1
            state = nxt
            out.append((before, a, Observation(t=t, fields=dict(state))))
    return out


def _learn(manual, train, rounds=4):
    theory = Theory(world_id="toy")
    for _ in range(rounds):
        rules = mine(manual, train, theory)
        if not rules:
            break
        r = rules[0].model_copy()
        r.id = f"R{len(theory.rules) + 1}"
        theory.rules = sorted(theory.rules + [r], key=lambda x: x.action != "*")
    return theory


def _check(manual, law, init):
    train = _roll(manual, law, init, seed=1)
    held = _roll(manual, law, init, seed=99)
    theory = _learn(manual, train)
    assert theory.rules
    assert not validate_theory(theory, manual)
    for r in theory.rules:
        assert r.statement and r.source == "probe"
        assert not dsl.validate(r.when)
    assert accuracy(theory, held) >= 0.95, [r.model_dump() for r in theory.rules]
    return theory


WAIT = ActionSpec(name="wait")


def test_periodic_window():
    m = _manual([WAIT, ActionSpec(name="poke")], [("charge", "int"), ("flag", "bool")])

    def law(s, a, t, pending, mem):
        if t % 6 < 2:
            s["charge"] += 3
        return s

    th = _check(m, law, {"charge": 0, "flag": False})
    assert any("%" in r.when for r in th.rules)


def test_delayed_effect():
    m = _manual([WAIT, ActionSpec(name="ping"), ActionSpec(name="clear")], [("echo", "int")])

    def law(s, a, t, pending, mem):
        if a.name == "ping":
            pending.append((t + 3, "echo", 1))
        if a.name == "clear":
            s["echo"] = 0
        return s

    th = _check(m, law, {"echo": 0})
    assert any(r.delay == 2 for r in th.rules)  # lands at t+3 = two steps after the next observation


def test_cooldown():
    m = _manual([WAIT, ActionSpec(name="tap"), ActionSpec(name="boost")], [("speed", "int")])

    def law(s, a, t, pending, mem):
        if a.name == "boost":
            if t - mem.get("last", -100) >= 4:
                s["speed"] += 10
            mem["last"] = t
        return s

    th = _check(m, law, {"speed": 0})
    assert any(r.memory for r in th.rules)


def test_arg_linear_with_cap():
    pump = ActionSpec(name="pump", params=[ParamSpec(name="rate", type="int", min=1, max=6)])
    m = _manual([WAIT, pump], [("level", "int")])

    def law(s, a, t, pending, mem):
        if a.name == "pump":
            s["level"] = min(s["level"] + 2 * a.args["rate"] + 1, 400)
        return s

    th = _check(m, law, {"level": 0})
    assert any("args.rate" in e for r in th.rules for e in r.effects.values())


def test_no_rule_on_persistence():
    m = _manual([WAIT, ActionSpec(name="poke")], [("x", "int"), ("y", "str")])
    data = _roll(m, lambda s, a, t, p, mem: s, {"x": 3, "y": "a"}, seed=5)
    assert mine(m, data, Theory(world_id="toy")) == []


def test_deterministic_ids_and_speed():
    pump = ActionSpec(name="pump", params=[ParamSpec(name="rate", type="int", min=1, max=6)])
    m = _manual([WAIT, pump, ActionSpec(name="boost")], [("level", "int"), ("speed", "int"), ("on", "bool")])

    def law(s, a, t, pending, mem):
        if a.name == "pump":
            s["level"] += a.args["rate"]
        if a.name == "boost" and t - mem.get("last", -100) >= 3:
            s["speed"] += 5
            mem["last"] = t
        if t % 4 == 0:
            s["on"] = not s["on"]
        return s

    data = _roll(m, law, {"level": 0, "speed": 0, "on": False}, seed=3, episodes=4, steps=50)
    t0 = time.perf_counter()
    a = mine(m, data, Theory(world_id="toy"))
    assert time.perf_counter() - t0 < 2.0
    b = mine(m, data, Theory(world_id="toy"))
    assert [r.model_dump() for r in a] == [r.model_dump() for r in b]
    assert [r.id for r in a] == [f"M{i}" for i in range(1, len(a) + 1)]
    assert a and len(a) <= 12
