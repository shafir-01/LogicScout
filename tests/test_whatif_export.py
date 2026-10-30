import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from logicscout import config
from logicscout.contracts import (
    ActionTemplate, Observation, Playbook, PlaybookRule, Rule, RunConfig, RunState, Theory,
)
from logicscout.export import controller_py, manual_md
from logicscout.playbook import PlaybookRunner
from logicscout.sandbox import open_session
from logicscout.server import app as appmod
from logicscout.server import runs as R
from logicscout.worlds.base import load_all

THEORY = Theory(world_id="relay", version=3, rules=[
    Rule(id="r1", statement="Waiting changes nothing about losses.", action="wait", effects={"lost": "obs.lost"},
         status="supported", confidence=0.9, evidence=[4, 5]),
    Rule(id="r2", statement="Sending may drain energy.", action="send", effects={"vessel_energy": "obs.vessel_energy - 1"}),
], unknowns=["what the buoy signal depends on"])

PLAYBOOK = Playbook(
    id="pb1", world_id="relay", objective_id="priority5", theory_version=3,
    memory={"sent": 0}, updates={"sent": "mem.sent + 1"},
    rules=[
        PlaybookRule(when="mem.sent % 4 == 3", do=ActionTemplate(name="prioritize"), why="re-sort"),
        PlaybookRule(when="obs.queue > 0", do=ActionTemplate(
            name="send", args={"via": "'sat' if t % 3 == 0 else 'buoy'", "n": "max(1, min(obs.queue, 3))"})),
    ],
    fallback=ActionTemplate(name="wait"),
)


@pytest.fixture()
def manual():
    return load_all()["relay"].manual()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    st = RunState(run_id="abc", config=RunConfig(world_id="relay", seed=7), phase="done", live=False,
                  theory=THEORY, playbook=PLAYBOOK)
    d = tmp_path / "runs" / "abc"
    d.mkdir(parents=True)
    (d / "state.json").write_text(st.model_dump_json(), encoding="utf-8")
    with TestClient(appmod.create_app()) as c:
        yield c


def test_whatif_predict_and_test(client):
    acts = [{"name": "wait"}, {"name": "send", "args": {"via": "buoy", "n": 1}}]
    j = client.post("/api/runs/abc/whatif", json={"actions": acts}).json()
    assert len(j["predicted"]) == 2 and "observed" not in j
    j = client.post("/api/runs/abc/whatif", json={"actions": acts, "test": True}).json()
    assert len(j["observed"]) == 2 and 0 <= j["match_rate"] <= 1
    assert all(isinstance(v, bool) for m in j["match"] for v in m.values())
    assert "laws" not in json.dumps(j)


def test_whatif_rejects_bad_input(client):
    assert client.post("/api/runs/abc/whatif", json={"actions": [{"name": "explode"}]}).status_code == 400
    assert client.post("/api/runs/abc/whatif", json={"actions": [{"name": "wait"}] * 13}).status_code == 400
    assert client.post("/api/runs/abc/whatif", json={"actions": [{"name": "wait"}], "seed": 99999}).status_code == 400
    assert client.post("/api/runs/nope/whatif", json={"actions": [{"name": "wait"}]}).status_code == 404


def test_exports_served(client):
    md = client.get("/api/runs/abc/export/manual.md")
    assert md.status_code == 200 and "Waiting changes nothing" in md.text and "Otherwise" in md.text
    py = client.get("/api/runs/abc/export/controller.py")
    assert py.status_code == 200 and "def next_action" in py.text


def test_manual_is_deterministic(manual):
    a = manual_md(manual, THEORY, PLAYBOOK, None)
    assert a == manual_md(manual, THEORY, PLAYBOOK, None)
    assert "Unconfirmed: Sending may drain energy." in a and "evidence: 2" in a


def test_controller_matches_runner(manual, tmp_path):
    src = controller_py(manual, PLAYBOOK)
    (tmp_path / "controller.py").write_text(src, encoding="utf-8")
    port = open_session("relay").port
    obs = port.reset(7)
    runner = PlaybookRunner(PLAYBOOK)
    observations, expected = [], []
    for _ in range(25):
        observations.append(obs.model_dump())
        a = runner.next_action(obs)
        expected.append(a.model_dump())
        obs = port.act(a).observation
        runner.after_step(obs)
    observations.append(obs.model_dump())
    driver = (
        "import json, sys, controller\n"
        "obs = json.load(sys.stdin); out = []\n"
        "for o, nxt in zip(obs, obs[1:]):\n"
        "    out.append(controller.next_action(o)); controller.after_step(nxt)\n"
        "print(json.dumps(out))\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(tmp_path)!r})\n" + driver],
                       input=json.dumps(observations), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == expected
    demo = subprocess.run([sys.executable, "-I", str(tmp_path / "controller.py")], capture_output=True, text=True,
                          timeout=60, env={"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert demo.returncode == 0 and "LS_SANDBOX_URL" in demo.stdout


def test_controller_rejects_invalid_playbook(manual):
    bad = PLAYBOOK.model_copy(update={"fallback": ActionTemplate(name="explode")})
    with pytest.raises(ValueError):
        controller_py(manual, bad)
