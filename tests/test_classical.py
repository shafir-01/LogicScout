import asyncio
import types

from logicscout.bench import classical
from logicscout.bench.classical import FieldTree, KNNModel, ModelBeamPolicy, TreeModel, arms, explore
from logicscout.contracts import Action, ActionSpec, Objective, Observation, ParamSpec, WorldManual


def _manual() -> WorldManual:
    return WorldManual(
        world_id="toy", title="toy", domain="toy", summary="counter", lab_seeds=(0, 100), probe_budget=40,
        actions=[ActionSpec(name="add", description="add n", params=[ParamSpec(name="n", type="int", min=1, max=3)]),
                 ActionSpec(name="reset_x", description="x to 0"), ActionSpec(name="wait", description="nothing")],
        observations=[], objectives=[Objective(id="reach", text="x >= 9", success="obs.x >= 9", horizon=10)],
    )


def _step(obs: Observation, a: Action) -> Observation:
    x, flag = obs.fields["x"], obs.fields["flag"]
    if a.name == "add":
        x += a.args["n"]
    elif a.name == "reset_x":
        x = 0
    return Observation(t=obs.t + 1, fields={"t": obs.t + 1, "x": x, "flag": not flag if a.name == "wait" else flag})


class ToyPort:
    def __init__(self) -> None:
        self._m = _manual()
        self.obs = None

    def manual(self):
        return self._m

    def reset(self, seed):
        self.obs = Observation(t=0, fields={"t": 0, "x": seed % 5, "flag": False})
        return self.obs

    def act(self, a):
        self.obs = _step(self.obs, a)
        return types.SimpleNamespace(observation=self.obs, error=None)


def _data(n=40):
    port = ToyPort()
    return explore(port, port.manual(), seed=0, budget=n)


def test_explore_matches_budget_and_covers_actions():
    tr = _data(40)
    assert len(tr) == 40
    assert {a.name for _, a, _ in tr} == {"add", "reset_x", "wait"}


def test_tree_learns_counter_and_respects_depth():
    m = TreeModel(_manual()).fit(_data(60))
    assert all(t.depth() <= 4 for t in m.trees.values())
    o = Observation(t=3, fields={"t": 3, "x": 2, "flag": False})
    assert m.predict(o, Action(name="add", args={"n": 3}))["x"] == 5
    assert m.predict(o, Action(name="reset_x"))["x"] == 0
    assert m.predict(o, Action(name="wait"))["flag"] is True


def test_knn_predicts_deltas():
    m = KNNModel(_manual()).fit(_data(60))
    o = Observation(t=3, fields={"t": 3, "x": 4, "flag": False})
    assert m.predict(o, Action(name="add", args={"n": 2}))["x"] == 6


def test_field_tree_regression_on_real_values():
    rows = [([float(i), 0.0], float(i), float(i) + 0.5) for i in range(10)]
    tree = FieldTree("real").fit(rows)
    assert abs(tree.predict([3.0, 0.0], 3.0) - 3.5) < 1e-9


def test_beam_policy_reaches_goal_in_learned_model():
    manual = _manual()
    model = TreeModel(manual).fit(_data(60))
    pol = ModelBeamPolicy(model, manual, manual.objectives[0], depth=4, beam=8)
    obs = Observation(t=0, fields={"t": 0, "x": 0, "flag": False})
    for _ in range(manual.objectives[0].horizon):
        if obs.fields["x"] >= 9:
            break
        obs = _step(obs, pol.next_action(obs))
        pol.after_step(obs)
    assert obs.fields["x"] >= 9


def test_arms_signature_and_offline_run(monkeypatch):
    seen = {}

    def fake(kind, world_id, objective_id, seed, variant="standard", run_id=None, **kw):
        seen.update(kind=kind, world=world_id, variant=variant, run_id=run_id)
        return {"status": "ok", "model_calls": 0}

    monkeypatch.setattr(classical, "run_classical", fake)
    a = arms()
    assert set(a) == {"tree", "knn"}
    ctx = types.SimpleNamespace(world_id="plant", objective_id="hold_band", seed=3, variant="standard",
                                run_id="bench-plant-tree-s0")
    out = asyncio.run(a["tree"](ctx))
    assert out["model_calls"] == 0 and seen["kind"] == "tree" and seen["run_id"] == "bench-plant-tree-s0"


def test_run_classical_on_real_world_is_model_free():
    r = classical.run_classical("tree", "plant", "hold_band", 0)
    assert r["status"] == "ok" and r["model_calls"] == 0
    assert r["probes_used"] == 50
    assert 0.0 <= r["prediction_accuracy"] <= 1.0
    assert r["leakage_checks"]["referee_cases_unseen"]
