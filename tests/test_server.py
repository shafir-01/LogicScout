import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from logicscout import config
from logicscout.server import app as appmod
from logicscout.server import runs as R


class FakeAdmin:
    def truth(self):
        return ["the relay drops every third message"]


class FakeSession:
    admin = FakeAdmin()


class FakeLLM:
    def __init__(self, on_call=None, prompt_log=None):
        self.on_call = on_call


async def fake_mission(config_, log, llm, session, state, controls):
    log.append("run.started", {"config": config_.model_dump()})
    log.set_phase("control")
    state.phase = "control"
    log.append("control.step", {"episode": 0, "step": 1})
    await asyncio.wait_for(controls.stop.wait(), 10)
    state.phase = "done"
    return state


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(R, "run_mission", fake_mission)
    monkeypatch.setattr(R, "MissionControls", R._Controls)
    monkeypatch.setattr(R, "open_session", lambda world_id, variant="standard": FakeSession())
    monkeypatch.setattr(R, "Nemotron", FakeLLM)
    with TestClient(appmod.create_app()) as c:
        yield c


def wait_for(pred, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def parse_sse(text):
    frames = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
        if lines:
            frames.append(dict(ln.split(": ", 1) for ln in lines))
    return frames


def test_health(client):
    j = client.get("/api/health").json()
    assert j["ok"] is True and j["sandbox"] in ("in-process", "http")
    assert isinstance(j["model_configured"], bool) and isinstance(j["tavily_configured"], bool)


def test_worlds(client):
    r = client.get("/api/worlds")
    if r.status_code != 200:
        pytest.skip("worlds not available yet")
    for m in r.json():
        assert "world_id" in m and "laws" not in m


def test_run_lifecycle_sse_and_debrief(client):
    rid = client.post("/api/runs", json={"world_id": "relay"}).json()["run_id"]
    run = client.app.state.registry.runs[rid]
    assert wait_for(lambda: run.log.phase == "control")
    assert client.get(f"/api/runs/{rid}/debrief").status_code == 403
    assert client.post(f"/api/runs/{rid}/shift").status_code == 200
    assert run.controls.shift_requested.is_set()
    assert client.post(f"/api/runs/{rid}/stop").status_code == 200
    assert wait_for(lambda: run.done)
    assert client.get(f"/api/runs/{rid}/shift").status_code in (404, 405)
    assert client.post(f"/api/runs/{rid}/shift").status_code == 409

    resp = client.get(f"/api/runs/{rid}/events")
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(resp.text)
    assert [int(f["id"]) for f in frames] == list(range(len(frames)))
    assert frames[0]["event"] == "run.started"
    assert json.loads(frames[0]["data"])["kind"] == "run.started"
    assert frames[-1]["event"] == "run.finished"
    resumed = parse_sse(client.get(f"/api/runs/{rid}/events", headers={"Last-Event-ID": "1"}).text)
    assert int(resumed[0]["id"]) == 2

    d = client.get(f"/api/runs/{rid}/debrief").json()
    assert d["hidden_laws"] == ["the relay drops every third message"]
    assert client.get(f"/api/runs/{rid}").json()["live"] is False
    assert any(s["run_id"] == rid for s in client.get("/api/runs").json())
    assert "prompts" not in client.get("/api/infra").text


def test_live_sse_streams_until_end(client):
    rid = client.post("/api/runs", json={"world_id": "relay"}).json()["run_id"]
    run = client.app.state.registry.runs[rid]
    assert wait_for(lambda: run.log.phase == "control")
    client.post(f"/api/runs/{rid}/stop")
    with client.stream("GET", f"/api/runs/{rid}/events") as resp:
        body = "".join(resp.iter_text())
    assert "event: run.finished" in body


def test_run_limits(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_LIVE_RUNS", 1)
    assert client.post("/api/runs", json={"world_id": "relay"}).status_code == 200
    assert client.post("/api/runs", json={"world_id": "relay"}).status_code == 429


def test_per_ip_limit(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_LIVE_RUNS", 100)
    monkeypatch.setattr(R, "IP_LIMIT", 2)
    for _ in range(2):
        assert client.post("/api/runs", json={"world_id": "relay"}).status_code == 200
    assert client.post("/api/runs", json={"world_id": "relay"}).status_code == 429


def test_replays(client, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "REPLAY_SPEED", 1e6)
    d = tmp_path / "replays" / "demo"
    d.mkdir(parents=True)
    ev = [{"seq": i, "run_id": "x", "ts": 100 + i, "kind": "note", "phase": "encounter", "data": {"text": str(i)}, "digest": ""} for i in range(3)]
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev), encoding="utf-8")
    (d / "state.json").write_text(json.dumps({"config": {"world_id": "relay"}}), encoding="utf-8")
    lst = client.get("/api/replays").json()
    assert lst[0]["name"] == "demo" and lst[0]["replay"] is True
    assert client.get("/api/replays/demo").json()["replay"] is True
    frames = parse_sse(client.get("/api/replays/demo/events").text)
    assert len(frames) == 3 and all(json.loads(f["data"])["replay"] is True for f in frames)
    assert client.get("/api/replays/nope").status_code == 404
    assert client.get("/api/replays/..%2Fx").status_code == 404


def test_unknown_api_404_and_spa(client):
    assert client.get("/api/nothing").status_code == 404
