"""Ask the theory: predict what a sequence of actions will do, optionally test it on a fresh sandbox session."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from logicscout import export
from logicscout.contracts import Action, Observation, WorldManual
from logicscout.logbook import Logbook
from logicscout.sandbox.session import check_action
from logicscout.server import runs as R
from logicscout.theory import Predictor, _eq

MAX_ACTIONS = 12
RATE_LIMIT = 20
RATE_WINDOW = 60.0


class WhatIf(BaseModel):
    actions: list[Action] = Field(default_factory=list)
    seed: int | None = None
    test: bool = False


def _manual(world_id: str) -> WorldManual:
    from logicscout.worlds.base import load_all
    worlds = load_all()
    if world_id not in worlds:
        raise HTTPException(404, "world not found")
    return worlds[world_id].manual()


def router(reg: R.RunRegistry) -> APIRouter:
    api = APIRouter()
    hits: dict[str, list[float]] = {}

    def limit(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        h = [t for t in hits.get(ip, []) if now - t < RATE_WINDOW]
        if len(h) >= RATE_LIMIT:
            hits[ip] = h
            raise HTTPException(429, "too many requests; slow down")
        hits[ip] = h + [now]

    def state(run_id: str):
        if not R.ID_RE.match(run_id):
            raise HTTPException(404, "not found")
        st = reg.state(run_id)
        if not st:
            raise HTTPException(404, "run not found")
        return st

    @api.post("/api/runs/{run_id}/whatif")
    def whatif(run_id: str, body: WhatIf, request: Request):
        limit(request)
        st = state(run_id)
        if not st.theory:
            raise HTTPException(409, "no theory yet")
        if not body.actions:
            raise HTTPException(400, "give at least one action")
        if len(body.actions) > MAX_ACTIONS:
            raise HTTPException(400, f"at most {MAX_ACTIONS} actions")
        manual = _manual(st.config.world_id)
        for i, a in enumerate(body.actions):
            err = check_action(manual, a)
            if err:
                raise HTTPException(400, f"step {i + 1}: {err}")
        seed = st.config.seed if body.seed is None else body.seed
        lo, hi = manual.lab_seeds
        if not lo <= seed <= hi:
            raise HTTPException(400, f"seed must be within lab seeds {lo}..{hi}")
        session = R._deps()[2](st.config.world_id)
        start = session.port.reset(seed)
        pred = Predictor(st.theory)
        pred.reset(start)
        obs, predicted = start, []
        for a in body.actions:
            fields = pred.predict(obs, a)
            predicted.append(fields)
            obs = Observation(t=obs.t + 1, fields=fields)
            pred.advance(obs)
        out: dict = {"seed": seed, "start": start.fields, "predicted": predicted, "theory_version": st.theory.version}
        if body.test:
            observed, matches, total, ok = [], [], 0, 0
            for a, p in zip(body.actions, predicted):
                res = session.port.act(a)
                o = res.observation.fields
                m = {f: _eq(p.get(f), v) for f, v in o.items() if f != "t"}
                observed.append(o)
                matches.append(m)
                total += len(m)
                ok += sum(m.values())
            out.update(observed=observed, match=matches, match_rate=ok / total if total else 0.0)
        return out

    def _bundle(run_id: str):
        st = state(run_id)
        path = R.runs_dir() / run_id / "events.jsonl"
        run = reg.runs.get(run_id)
        events = list(run.log.events) if run else (Logbook.load(path) if path.exists() else [])
        return st, _manual(st.config.world_id), events

    @api.get("/api/runs/{run_id}/export/manual.md")
    def export_manual(run_id: str):
        st, manual, events = _bundle(run_id)
        if not st.theory:
            raise HTTPException(409, "no theory yet")
        text = export.manual_md(manual, st.theory, st.playbook, st.referee, events)
        return PlainTextResponse(text, media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="{manual.world_id}-manual.md"'})

    @api.get("/api/runs/{run_id}/export/controller.py")
    def export_controller(run_id: str):
        st, manual, _ = _bundle(run_id)
        if not st.playbook:
            raise HTTPException(409, "no playbook yet")
        try:
            text = export.controller_py(manual, st.playbook)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return PlainTextResponse(text, media_type="text/x-python",
                                 headers={"Content-Disposition": f'attachment; filename="{manual.world_id}-controller.py"'})

    return api
