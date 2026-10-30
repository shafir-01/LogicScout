"""End-to-end smoke test against a live LogicScout server.

usage: python scripts/smoke.py <base_url> [--live]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logicscout.contracts import Event  # noqa: E402
from logicscout.logbook import Logbook  # noqa: E402

LEAK_KEYS = {"laws", "law", "hidden", "hidden_laws", "truth", "secret", "shifts", "shift_records", "rules"}
SPA_ROUTES = ["/run/abc123", "/replay/demo", "/infra"]
Result = tuple[str, bool, str]


def _leaks(obj, path="") -> list[str]:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in LEAK_KEYS:
                found.append(f"{path}/{k}")
            found += _leaks(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _leaks(v, f"{path}[{i}]")
    return found


def _check(results: list[Result], name: str, fn: Callable[[], str | None]) -> None:
    try:
        results.append((name, True, fn() or ""))
    except Exception as e:  # noqa: BLE001
        results.append((name, False, f"{type(e).__name__}: {e}"[:200]))


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run_static_checks(c: httpx.Client) -> list[Result]:
    res: list[Result] = []
    worlds: list[dict] = []

    def health():
        r = c.get("/api/health")
        _expect(r.status_code == 200 and r.json().get("ok") is True, f"status {r.status_code} {r.text[:80]}")
        return f"v{r.json().get('version')}"

    def worlds_check():
        r = c.get("/api/worlds")
        _expect(r.status_code == 200, f"status {r.status_code}")
        worlds.extend(r.json())
        _expect(len(worlds) >= 5, f"only {len(worlds)} worlds")
        for w in worlds:
            for k in ("actions", "observations", "objectives"):
                _expect(bool(w.get(k)), f"{w.get('world_id')} missing {k}")
            bad = _leaks(w)
            _expect(not bad, f"{w.get('world_id')} leaks {bad}")
        return f"{len(worlds)} worlds"

    def shifts():
        _expect(bool(worlds), "no worlds loaded")
        for w in worlds:
            r = c.get(f"/api/worlds/{w['world_id']}/shifts")
            _expect(r.status_code == 200 and isinstance(r.json(), list) and bool(r.json()),
                    f"{w['world_id']} -> {r.status_code}")
        _expect(c.get("/api/worlds/nope/shifts").status_code == 404, "unknown world not 404")

    def replays():
        r = c.get("/api/replays")
        _expect(r.status_code == 200 and isinstance(r.json(), list), f"status {r.status_code}")
        return f"{len(r.json())} replays"

    def infra():
        r = c.get("/api/infra")
        j = r.json()
        _expect(r.status_code == 200 and "model_calls" in j and "models" in j, f"status {r.status_code}")

    def index():
        r = c.get("/")
        _expect(r.status_code == 200, f"status {r.status_code} {r.text[:80]}")
        _expect("text/html" in r.headers.get("content-type", ""), "not html")
        _expect('id="root"' in r.text or "id='root'" in r.text, "no #root")

    def spa():
        for p in SPA_ROUTES:
            r = c.get(p)
            _expect(r.status_code == 200 and 'id="root"' in r.text, f"{p} -> {r.status_code}")

    def api404():
        _expect(c.get("/api/nope").status_code == 404, "unknown api not 404")
        _expect(c.get("/api/runs/does-not-exist/debrief").status_code == 404, "debrief for unknown run not 404")

    for name, fn in [("health", health), ("worlds", worlds_check), ("shifts", shifts), ("replays", replays),
                     ("infra", infra), ("static index", index), ("spa routes", spa), ("api 404s", api404)]:
        _check(res, name, fn)
    return res


def run_live_checks(c: httpx.Client, budget_s: float = 120.0) -> list[Result]:
    res: list[Result] = []
    state: dict = {}

    def start():
        r = c.post("/api/runs", json={"world_id": "relay", "use_briefing": False, "probe_budget": 20})
        _expect(r.status_code == 200, f"status {r.status_code} {r.text[:120]}")
        state["id"] = r.json()["run_id"]
        return state["id"]

    _check(res, "live: start run", start)
    if "id" not in state:
        return res
    rid = state["id"]

    def debrief_live():
        r = c.get(f"/api/runs/{rid}/debrief")
        _expect(r.status_code == 403, f"expected 403, got {r.status_code}")

    _check(res, "live: debrief 403", debrief_live)

    events: list[Event] = []
    framing: list[str] = []
    deadline = time.time() + budget_s
    try:
        with c.stream("GET", f"/api/runs/{rid}/events", timeout=httpx.Timeout(30.0, read=30.0)) as r:
            _expect(r.status_code == 200, f"events status {r.status_code}")
            _expect("text/event-stream" in r.headers.get("content-type", ""), "bad content-type")
            cur: dict[str, str] = {}
            for line in r.iter_lines():
                if time.time() > deadline:
                    break
                if line == "":
                    if cur:
                        if {"id", "event", "data"} <= cur.keys():
                            try:
                                ev = Event.model_validate(json.loads(cur["data"]))
                                if cur["id"] != str(ev.seq) or cur["event"] != ev.kind:
                                    framing.append(f"mismatch id/event at {cur['id']}")
                                events.append(ev)
                            except Exception as e:  # noqa: BLE001
                                framing.append(f"bad data: {e}")
                        else:
                            framing.append(f"incomplete frame {sorted(cur)}")
                    cur = {}
                    if events and events[-1].kind in ("run.finished", "run.failed"):
                        break
                elif line.startswith(":"):
                    continue
                elif ":" in line:
                    k, v = line.split(":", 1)
                    cur[k] = v.lstrip(" ")
    except (httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        framing.append(f"stream error {type(e).__name__}")
    except AssertionError as e:
        framing.append(str(e))

    def f_framing():
        _expect(len(events) > 0, "no events received")
        _expect(not framing, "; ".join(framing[:3]))
        return f"{len(events)} events"

    def f_seq():
        seqs = [e.seq for e in events]
        _expect(bool(seqs) and all(b > a for a, b in zip(seqs, seqs[1:])), "seq not strictly increasing")

    def f_chain():
        _expect(bool(events), "no events")
        _expect(Logbook.verify(events), "digest chain broken")

    def f_model():
        calls = [e.data.get("model", "") for e in events if e.kind == "model.call"]
        _expect(bool(calls), "no model.call events seen")
        bad = [m for m in calls if not str(m).startswith("nvidia/")]
        _expect(not bad, f"non-nvidia models {set(bad)}")
        return f"{len(calls)} calls, {calls[0]}"

    _check(res, "live: sse framing", f_framing)
    _check(res, "live: seq monotonic", f_seq)
    _check(res, "live: digest chain", f_chain)
    _check(res, "live: nvidia model id", f_model)

    def stop():
        r = c.post(f"/api/runs/{rid}/stop")
        _expect(r.status_code in (200, 409), f"status {r.status_code}")
        return "stopped" if r.status_code == 200 else "already finished"

    _check(res, "live: stop", stop)
    return res


def report(results: list[Result]) -> int:
    w = max(len(n) for n, _, _ in results)
    for n, ok, d in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n.ljust(w)}  {d}")
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    with httpx.Client(base_url=args[0].rstrip("/"), timeout=20.0) as c:
        results = run_static_checks(c)
        if "--live" in argv:
            results += run_live_checks(c)
    return report(results)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
