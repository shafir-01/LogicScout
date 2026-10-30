from logicscout.contracts import Action, ActionSpec, FieldSpec, Objective, Observation, ParamSpec, WorldManual
from logicscout.scout.induce import change_stats, induce

MANUAL = WorldManual(
    world_id="toy", title="Toy", domain="test", summary="A counter.",
    actions=[ActionSpec(name="push", params=[ParamSpec(name="n", type="int", min=1, max=3)]), ActionSpec(name="wait")],
    observations=[FieldSpec(name="t", type="int"), FieldSpec(name="x", type="int")],
    objectives=[Objective(id="o", text="x high", success="obs.x >= 9", horizon=10)],
    probe_budget=20, lab_seeds=(0, 10),
)


def _world():
    """Hidden law: push adds min(n, 2) but only on steps where t % 4 < 2; wait does nothing."""
    out, x = [], 0
    seq = [("push", n) for n in (3, 1, 2, 3, 1, 2, 2, 3, 1, 3, 2, 1, 3, 2, 1, 3)] + [("wait", 0)] * 4
    for t, (name, n) in enumerate(seq):
        b = Observation(t=t, fields={"t": t, "x": x})
        a = Action(name=name, args={"n": n} if name == "push" else {})
        if name == "push" and t % 4 < 2:
            x += min(n, 2)
        out.append((b, a, Observation(t=t + 1, fields={"t": t + 1, "x": x})))
    return out


def test_induce_finds_capacity_and_window():
    cands = induce(MANUAL, _world())
    push = [c for c in cands if c["action"] == "push" and c["field"] == "x"]
    assert push, cands
    best = push[0]["fits"][0]
    assert "min(args.n, 2)" in best["expr"] and "t % 4 < 2" in best["expr"]
    assert best["hits"] == best["n"]


def test_change_stats_are_compact():
    lines = change_stats(MANUAL, _world())
    assert lines and all(line.startswith("push: x changed") for line in lines)
