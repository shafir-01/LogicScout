from logicscout.anchor import anchor, verify
from logicscout.logbook import Logbook


def _mk(tmp_path, n=5):
    d = tmp_path / "run"
    d.mkdir()
    lb = Logbook("r1", d / "events.jsonl")
    for i in range(n):
        lb.append("note", {"text": f"e{i}"})
    return d, tmp_path / "anchors.jsonl"


def test_ok_and_unanchored(tmp_path):
    d, ap = _mk(tmp_path)
    r = verify(d, ap)
    assert r["chain_ok"] and not r["anchored"] and not r["ok"]
    a = anchor(d, ap)
    assert a["n_events"] == 5 and verify(d, ap)["ok"]


def test_tamper_fails(tmp_path):
    d, ap = _mk(tmp_path)
    anchor(d, ap)
    f = d / "events.jsonl"
    f.write_text(f.read_text().replace("e2", "eX"), encoding="utf-8")
    r = verify(d, ap)
    assert not r["ok"] and not r["chain_ok"]


def test_rewritten_chain_fails_anchor(tmp_path):
    d, ap = _mk(tmp_path)
    anchor(d, ap)
    (d / "events.jsonl").unlink()
    lb = Logbook("r1", d / "events.jsonl")
    for i in range(5):
        lb.append("note", {"text": f"forged{i}"})
    r = verify(d, ap)
    assert r["chain_ok"] and not r["anchor_ok"] and not r["ok"]


def test_truncate_fails(tmp_path):
    d, ap = _mk(tmp_path)
    anchor(d, ap)
    f = d / "events.jsonl"
    f.write_text("".join(f.read_text().splitlines(True)[:3]), encoding="utf-8")
    r = verify(d, ap)
    assert r["chain_ok"] and not r["anchor_ok"] and not r["ok"]


def test_growth_after_anchor_ok(tmp_path):
    d, ap = _mk(tmp_path, 3)
    anchor(d, ap)
    lb = Logbook("r1", d / "events.jsonl")
    lb.events = Logbook.load(d / "events.jsonl")
    lb.append("note", {"text": "more"})
    assert verify(d, ap)["ok"]
