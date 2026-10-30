"""FastAPI app: runs, SSE event streams, replays, debrief, infra stats, static frontend."""
from __future__ import annotations

import asyncio
import json
import statistics
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from logicscout import config
from logicscout.contracts import Event, RunConfig
from logicscout.logbook import Logbook
from logicscout.server import runs as R

VERSION = "0.1.0"
HEARTBEAT_S = 15.0
REPLAY_SPEED = 8.0
REPLAY_MAX_GAP = 0.5
DIST = config.ROOT / "web" / "dist"


def _sse(ev: Event, replay: bool = False) -> str:
    payload = ev.model_dump()
    if replay:
        payload["replay"] = True
    return f"id: {ev.seq}\nevent: {ev.kind}\ndata: {json.dumps(payload, default=str)}\n\n"


def _headers() -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _last_id(request: Request) -> int:
    try:
        return int(request.headers.get("last-event-id", "-1"))
    except ValueError:
        return -1


def _check_id(name: str) -> str:
    if not R.ID_RE.match(name):
        raise HTTPException(404, "not found")
    return name


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 1)


def infra_stats() -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {}
    lat: list[float] = []
    calls = errors = ptok = ctok = 0
    providers: set[str] = set()
    queries = sources = 0
    root = R.runs_dir()
    for f in (root.glob("*/events.jsonl") if root.exists() else []):
        try:
            events = Logbook.load(f)
        except Exception:
            continue
        for e in events:
            if e.kind == "model.call":
                d = e.data
                calls += 1
                errors += 0 if d.get("ok", True) else 1
                lat.append(float(d.get("latency_ms") or 0))
                ptok += d.get("prompt_tokens") or 0
                ctok += d.get("completion_tokens") or 0
                providers.add(str(d.get("provider", "")))
                m = models.setdefault(str(d.get("model", "?")), {"calls": 0, "tiers": set()})
                m["calls"] += 1
                m["tiers"].add(d.get("tier"))
            elif e.kind == "briefing.query":
                queries += 1
            elif e.kind == "briefing.source":
                sources += 1
    return {
        "providers": sorted(p for p in providers if p),
        "models": [{"id": k, "calls": v["calls"], "tiers": sorted(t for t in v["tiers"] if t)} for k, v in models.items()],
        "model_calls": calls,
        "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "mean": round(statistics.fmean(lat), 1) if lat else None},
        "tokens": {"prompt": ptok, "completion": ctok},
        "error_rate": round(errors / calls, 4) if calls else 0.0,
        "tavily": {"queries": queries, "sources": sources, "configured": bool(config.TAVILY_API_KEY)},
    }


def create_app() -> FastAPI:
    app = FastAPI(title="LogicScout", version=VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"], allow_headers=["*"],
    )
    reg = R.RunRegistry()
    app.state.registry = reg

    @app.get("/api/health")
    def health():
        return {
            "ok": True, "version": VERSION,
            "model_configured": bool(config.NEBIUS_API_KEY and config.MODEL_DEEP and config.MODEL_FAST),
            "tavily_configured": bool(config.TAVILY_API_KEY),
            "sandbox": "http" if config.SANDBOX_URL else "in-process",
        }

    @app.get("/api/worlds")
    def worlds():
        from logicscout.worlds.base import load_all
        return [cls.manual().model_dump() for cls in load_all().values()]

    @app.get("/api/forge/new")
    def forge_new():
        import secrets

        from logicscout.worlds.forge import ForgeWorld
        variant = f"g{secrets.randbelow(999_999) + 1}"
        return {"variant": variant, "manual": ForgeWorld.manual_for(variant).model_dump()}

    @app.get("/api/worlds/{world_id}/shifts")
    def world_shifts(world_id: str):
        menu = R.shift_menu(world_id)
        if menu is None:
            raise HTTPException(404, "unknown world")
        return menu

    # ---- runs ----------------------------------------------------------------------
    @app.post("/api/runs")
    async def create_run(cfg: RunConfig, request: Request):
        ip = request.client.host if request.client else "unknown"
        if reg.live_count() >= config.MAX_LIVE_RUNS:
            raise HTTPException(429, "too many live runs; try again shortly")
        if not reg.check_ip(ip):
            raise HTTPException(429, "run limit reached for this address; try again later")
        try:
            run = reg.create(cfg, ip)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, f"cannot start run: {e}")
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        return {"run_id": run.run_id}

    @app.get("/api/runs")
    def list_runs():
        return reg.list()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        st = reg.state(_check_id(run_id))
        if not st:
            raise HTTPException(404, "run not found")
        return st

    async def _stream(run: R.Run, last: int) -> AsyncIterator[str]:
        q = run.log.subscribe()
        try:
            sent = last
            for ev in list(run.log.events):
                if ev.seq > sent:
                    sent = ev.seq
                    yield _sse(ev)
            while not run.done or not q.empty():
                try:
                    ev = await asyncio.wait_for(q.get(), HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if ev is None:
                    break
                if ev.seq > sent:
                    sent = ev.seq
                    yield _sse(ev)
        finally:
            run.log.unsubscribe(q)

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request):
        _check_id(run_id)
        last = _last_id(request)
        run = reg.runs.get(run_id)
        if run:
            gen = _stream(run, last)
        else:
            path = R.runs_dir() / run_id / "events.jsonl"
            if not path.exists():
                raise HTTPException(404, "run not found")

            async def disk() -> AsyncIterator[str]:
                for ev in Logbook.load(path):
                    if ev.seq > last:
                        yield _sse(ev)
            gen = disk()
        return StreamingResponse(gen, media_type="text/event-stream", headers=_headers())

    @app.post("/api/runs/{run_id}/shift")
    async def shift(run_id: str, request: Request):
        run = reg.runs.get(_check_id(run_id))
        if not run:
            raise HTTPException(404, "run not found")
        if run.done or run.log.phase != "control":
            raise HTTPException(409, "a hidden change can only be triggered during the control phase")
        kind = None
        if await request.body():
            try:
                kind = (await request.json() or {}).get("kind")
            except (ValueError, AttributeError):
                raise HTTPException(400, "body must be JSON like {\"kind\": \"...\"}")
        if kind is not None:
            world_id = run.state.config.world_id
            ids = {m["id"] for m in (R.shift_menu(world_id) or [])}
            if world_id and kind not in ids:
                raise HTTPException(400, f"unknown hidden change {kind!r}")
        run.controls.shift_kind = kind
        run.controls.shift_requested.set()
        return {"ok": True}

    @app.post("/api/runs/{run_id}/stop")
    def stop(run_id: str):
        run = reg.runs.get(_check_id(run_id))
        if not run:
            raise HTTPException(404, "run not found")
        if run.done:
            raise HTTPException(409, "run already finished")
        run.controls.stop.set()
        return {"ok": True}

    @app.get("/api/runs/{run_id}/debrief")
    def debrief(run_id: str):
        _check_id(run_id)
        run = reg.runs.get(run_id)
        if run and not run.done:
            raise HTTPException(403, "debrief is available only after the run has finished")
        d = R.runs_dir() / run_id
        if not (d / "state.json").exists():
            raise HTTPException(404, "run not found")
        return R.debrief_from_disk(d)

    # ---- replays -------------------------------------------------------------------
    def replay_dir(name: str) -> Path:
        d = R.replays_dir() / _check_id(name)
        if not (d / "events.jsonl").exists():
            raise HTTPException(404, "replay not found")
        return d

    @app.get("/api/replays")
    def list_replays():
        out = []
        root = R.replays_dir()
        for d in sorted(p for p in (root.iterdir() if root.exists() else []) if (p / "events.jsonl").exists()):
            st = R.read_json(d / "state.json") or {}
            out.append({
                "name": d.name, "replay": True,
                "world_id": (st.get("config") or {}).get("world_id"),
                "started_at": st.get("started_at"),
                "success_rate": (st.get("referee") or {}).get("success_rate"),
            })
        return out

    @app.get("/api/replays/{name}")
    def get_replay(name: str):
        d = replay_dir(name)
        st = R.read_json(d / "state.json") or {}
        return {"name": name, "replay": True, "state": {**st, "live": False}, "debrief": R.read_json(d / "debrief.json")}

    @app.get("/api/replays/{name}/events")
    async def replay_events(name: str, request: Request):
        d = replay_dir(name)
        last = _last_id(request)
        events = [e for e in Logbook.load(d / "events.jsonl") if e.seq > last]

        async def gen() -> AsyncIterator[str]:
            prev = None
            for ev in events:
                if prev is not None:
                    await asyncio.sleep(min(max(ev.ts - prev, 0) / REPLAY_SPEED, REPLAY_MAX_GAP))
                prev = ev.ts
                yield _sse(ev, replay=True)
        return StreamingResponse(gen(), media_type="text/event-stream", headers=_headers())

    @app.get("/api/infra")
    def infra():
        return infra_stats()

    from logicscout.server.whatif import router as _whatif
    app.include_router(_whatif(reg))

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
    def api_404(rest: str):
        return JSONResponse({"detail": "not found"}, status_code=404)

    # ---- static frontend -----------------------------------------------------------
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        index = DIST / "index.html"
        if not index.exists():
            return JSONResponse({"detail": "frontend not built (web/dist missing)"}, status_code=404)
        target = (DIST / path).resolve()
        if path and target.is_file() and DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(index)

    return app


app = create_app()
