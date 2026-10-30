import json

from fastapi.testclient import TestClient

from logicscout.server import evidence as E
from logicscout.server.app import create_app


def test_endpoint_tolerates_anything():
    r = TestClient(create_app()).get("/api/evidence")
    assert r.status_code == 200 and isinstance(r.json(), dict)


def test_empty_dirs_omit_everything(tmp_path):
    assert E.build(tmp_path / "data", tmp_path / "docs") == {}


def test_bench_and_anchors(tmp_path):
    for world, arm, ok in (("relay", "full", [True, True, False, False]), ("forge", "full", [True, False]),
                           ("relay", "random_probe", [False, False])):
        d = tmp_path / "bench" / world / arm
        d.mkdir(parents=True)
        (d / "seed-0.json").write_text(json.dumps({"random": 0.0, "idle": 0.0, "cases": [{"success": x} for x in ok]}))
    (tmp_path / "anchors.jsonl").write_text('{"head": "ab"}\nnot json\n')
    out = E.build(tmp_path, tmp_path / "docs")
    assert out["bench"]["arms"]["full"]["n"] == 6
    assert out["bench"]["out_of_family"]["full"]["success"] == 0.5
    lo, hi = out["bench"]["arms"]["full"]["ci"]
    assert 0 <= lo <= 0.5 <= hi <= 1
    assert out["anchors"]["count"] == 1


def test_wilson_empty():
    assert E.wilson(0, 0) == (0.0, 1.0)
