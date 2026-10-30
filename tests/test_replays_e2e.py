"""End-to-end check of the bundled replays served over the real API."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from logicscout.logbook import Event, Logbook
from logicscout.server import app as appmod

REPLAYS = Path(__file__).resolve().parent.parent / "data" / "replays"
NAMES = sorted(p.name for p in REPLAYS.iterdir() if p.is_dir())


@pytest.fixture(scope="module")
def client():
    appmod.REPLAY_SPEED = 1e9
    appmod.REPLAY_MAX_GAP = 0.0
    return TestClient(appmod.create_app()) if hasattr(appmod, "create_app") else TestClient(appmod.app)


def parse_sse(text: str) -> list[Event]:
    out = []
    for block in text.split("\n\n"):
        data = [ln[5:].strip() for ln in block.splitlines() if ln.startswith("data:")]
        if data:
            d = json.loads(data[0])
            d.pop("replay", None)
            out.append(Event.model_validate(d))
    return out


def test_replays_present():
    assert NAMES


def test_list(client):
    r = client.get("/api/replays")
    assert r.status_code == 200
    listed = {x["name"] for x in r.json()}
    assert set(NAMES) <= listed


@pytest.mark.parametrize("name", NAMES)
def test_replay_state_and_debrief(client, name):
    r = client.get(f"/api/replays/{name}")
    assert r.status_code == 200
    j = r.json()
    assert j["state"] and j["debrief"]
    assert j["debrief"].get("hidden_laws")


@pytest.mark.parametrize("name", NAMES)
def test_replay_events(client, name):
    r = client.get(f"/api/replays/{name}/events")
    assert r.status_code == 200
    events = parse_sse(r.text)
    assert events
    assert Logbook.verify(events)
    kinds = {e.kind for e in events}
    assert {"shift.applied", "drift.confirmed"} <= kinds
    if name == "relay-recovery":
        assert {"recovery.done", "referee.report"} <= kinds
