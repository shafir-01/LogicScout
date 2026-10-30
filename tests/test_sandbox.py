from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from logicscout import config
from logicscout.contracts import (
    Action, ActionSpec, Case, FieldSpec, Objective, Observation, ParamSpec, ShiftRecord, StepResult, WorldManual,
)
from logicscout.sandbox import open_session
from logicscout.sandbox.service import create_app
from logicscout.sandbox.session import open_http
from logicscout.worlds.base import World, register


@register
class ToyWorld(World):
    world_id = "toy_test"

    @classmethod
    def manual(cls) -> WorldManual:
        return WorldManual(
            world_id="toy_test", title="Toy", domain="test", summary="a counter",
            actions=[
                ActionSpec(name="add", params=[ParamSpec(name="n", type="int", min=0, max=5)]),
                ActionSpec(name="noop"),
            ],
            observations=[FieldSpec(name="total", type="int")],
            objectives=[Objective(id="ten", text="reach 10", success="obs.total >= 10", horizon=20)],
            probe_budget=10, lab_seeds=(0, 10),
        )

    def reset(self, seed: int) -> Observation:
        self.t = 0
        self.total = seed
        return self.observe()

    def observe(self) -> Observation:
        return Observation(t=self.t, fields={"total": getattr(self, "total", 0)})

    def act(self, action: Action) -> StepResult:
        self.t += 1
        if action.name == "add":
            self.total = getattr(self, "total", 0) + action.args["n"] * self.laws["gain"]
        return StepResult(observation=self.observe())

    @classmethod
    def default_laws(cls, variant: str):
        return {"gain": 1 if variant == "standard" else 3}

    @classmethod
    def variants(cls):
        return ["standard", "boosted"]

    def shift(self, seed: int) -> ShiftRecord:
        before = dict(self.laws)
        self.laws["gain"] = 2 + seed
        return ShiftRecord(kind="gain", description="gain changed", before=before, after=dict(self.laws), at_t=self.t)

    def success(self, objective_id: str) -> bool:
        return getattr(self, "total", 0) >= 10

    @classmethod
    def truth(cls, laws):
        return [f"add multiplies by {laws['gain']}"]

    @classmethod
    def referee_cases(cls):
        return [Case(case_id="c", seed=50, objective_id="ten")]


def exercise(session):
    port, admin = session.port, session.admin
    assert port.manual().world_id == "toy_test"
    assert port.reset(3).fields["total"] == 3
    assert port.act(Action(name="add", args={"n": 2})).observation.fields["total"] == 5
    for bad in (Action(name="nope"), Action(name="add", args={"n": 99}), Action(name="add"), Action(name="add", args={"n": "x"})):
        r = port.act(bad)
        assert r.error and r.observation.fields["total"] == 5
    with pytest.raises(ValueError):
        port.reset(11)
    rec = admin.shift(1)
    assert rec.after["gain"] == 3
    port.reset(0)
    assert port.act(Action(name="add", args={"n": 2})).observation.fields["total"] == 6  # shift survived reset
    assert admin.success("ten") is False
    assert admin.laws()["gain"] == 3
    assert admin.truth() == ["add multiplies by 3"]
    assert admin.steps == 2


def test_local_session():
    exercise(open_session("toy_test"))


def test_variant():
    s = open_session("toy_test", "boosted")
    assert s.admin.laws()["gain"] == 3


def test_unknown_world():
    with pytest.raises(KeyError):
        open_session("does_not_exist")


def test_http_end_to_end():
    app = create_app()
    client = TestClient(app, base_url="http://sandbox")
    session = open_http("http://sandbox", "toy_test", client=client)
    exercise(session)


def test_http_tokens():
    app = create_app()
    c = TestClient(app)
    assert c.post("/sessions", json={"world_id": "toy_test"}).status_code == 401
    admin_h = {"X-Admin-Token": config.SANDBOX_TOKEN}
    d = c.post("/sessions", json={"world_id": "toy_test"}, headers=admin_h).json()
    sid, tok = d["session_id"], d["scout_token"]
    assert c.get(f"/s/{sid}/manual").status_code == 401
    assert c.get(f"/s/{sid}/manual", headers={"X-Scout-Token": "wrong"}).status_code == 401
    assert c.get(f"/s/{sid}/manual", headers={"X-Scout-Token": tok}).status_code == 200
    for path in ("laws", "truth"):
        assert c.get(f"/s/{sid}/admin/{path}", headers={"X-Scout-Token": tok}).status_code == 401
        assert c.get(f"/s/{sid}/admin/{path}").status_code == 401
        assert c.get(f"/s/{sid}/admin/{path}", headers=admin_h).status_code == 200
    assert c.post(f"/s/{sid}/admin/shift", json={"seed": 1}, headers={"X-Scout-Token": tok}).status_code == 401
    assert c.post(f"/s/{sid}/reset", json={"seed": 999}, headers={"X-Scout-Token": tok}).status_code == 400
    assert c.post("/sessions", json={"world_id": "nope"}, headers=admin_h).status_code == 404


def test_session_cap_and_ttl():
    admin_h = {"X-Admin-Token": config.SANDBOX_TOKEN}
    c = TestClient(create_app(max_sessions=1))
    assert c.post("/sessions", json={"world_id": "toy_test"}, headers=admin_h).status_code == 200
    assert c.post("/sessions", json={"world_id": "toy_test"}, headers=admin_h).status_code == 429
    c = TestClient(create_app(ttl=-1))
    d = c.post("/sessions", json={"world_id": "toy_test"}, headers=admin_h).json()
    assert c.get(f"/s/{d['session_id']}/manual", headers={"X-Scout-Token": d["scout_token"]}).status_code == 404
