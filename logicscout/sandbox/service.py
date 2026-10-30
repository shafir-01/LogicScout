"""Sandbox HTTP service. Scout endpoints need X-Scout-Token; admin endpoints need X-Admin-Token."""
from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass, field

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException

from logicscout import config
from logicscout.contracts import Action, Observation, ShiftRecord, StepResult, WorldManual
from logicscout.sandbox.session import Session, open_local

TTL_SECONDS = 30 * 60
MAX_SESSIONS = 64


@dataclass
class _Entry:
    session: Session
    scout_token: str
    last: float = field(default_factory=time.monotonic)


def create_app(ttl: float = TTL_SECONDS, max_sessions: int = MAX_SESSIONS) -> FastAPI:
    app = FastAPI(title="LogicScout sandbox")
    sessions: dict[str, _Entry] = {}
    lock = threading.Lock()

    def sweep() -> None:
        now = time.monotonic()
        for sid in [s for s, e in sessions.items() if now - e.last > ttl]:
            del sessions[sid]

    def admin_auth(token: str | None) -> None:
        if not token or not secrets.compare_digest(token, config.SANDBOX_TOKEN):
            raise HTTPException(401, "admin token required")

    def lookup(sid: str) -> _Entry:
        with lock:
            sweep()
            e = sessions.get(sid)
        if e is None:
            raise HTTPException(404, "no such session")
        e.last = time.monotonic()
        return e

    def scout(sid: str, token: str | None) -> Session:
        e = lookup(sid)
        if not token or not secrets.compare_digest(token, e.scout_token):
            raise HTTPException(401, "scout token required")
        return e.session

    def admin(sid: str, token: str | None) -> Session:
        admin_auth(token)
        return lookup(sid).session

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "sessions": len(sessions)}

    @app.post("/sessions")
    def create(body: dict = Body(...), x_admin_token: str | None = Header(None)) -> dict:
        admin_auth(x_admin_token)
        with lock:
            sweep()
            if len(sessions) >= max_sessions:
                raise HTTPException(429, "too many sessions")
        try:
            s = open_local(body["world_id"], body.get("variant", "standard"))
        except KeyError as e:
            raise HTTPException(404, str(e.args[0])) from e
        token = secrets.token_urlsafe(24)
        with lock:
            sessions[s.id] = _Entry(s, token)
        return {"session_id": s.id, "scout_token": token}

    @app.delete("/s/{sid}")
    def close(sid: str, x_admin_token: str | None = Header(None)) -> dict:
        admin(sid, x_admin_token)
        sessions.pop(sid, None)
        return {"closed": True}

    @app.get("/s/{sid}/manual")
    def manual(sid: str, x_scout_token: str | None = Header(None)) -> WorldManual:
        return scout(sid, x_scout_token).port.manual()

    @app.post("/s/{sid}/reset")
    def reset(sid: str, body: dict = Body(...), x_scout_token: str | None = Header(None)) -> Observation:
        port = scout(sid, x_scout_token).port
        try:
            return port.reset(int(body["seed"]))
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/s/{sid}/observe")
    def observe(sid: str, x_scout_token: str | None = Header(None)) -> Observation:
        return scout(sid, x_scout_token).port.observe()

    @app.post("/s/{sid}/act")
    def act(sid: str, body: dict = Body(...), x_scout_token: str | None = Header(None)) -> StepResult:
        port = scout(sid, x_scout_token).port
        try:
            action = Action.model_validate(body["action"])
        except Exception as e:
            raise HTTPException(400, f"bad action: {e}") from e
        return port.act(action)

    @app.post("/s/{sid}/admin/shift")
    def shift(sid: str, body: dict = Body(...), x_admin_token: str | None = Header(None)) -> ShiftRecord:
        try:
            return admin(sid, x_admin_token).admin.shift(int(body["seed"]), body.get("kind"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/s/{sid}/admin/success")
    def success(sid: str, body: dict = Body(...), x_admin_token: str | None = Header(None)) -> dict:
        return {"success": admin(sid, x_admin_token).admin.success(body["objective_id"])}

    @app.get("/s/{sid}/admin/truth")
    def truth(sid: str, x_admin_token: str | None = Header(None)) -> dict:
        return {"truth": admin(sid, x_admin_token).admin.truth()}

    @app.get("/s/{sid}/admin/laws")
    def laws(sid: str, x_admin_token: str | None = Header(None)) -> dict:
        return {"laws": admin(sid, x_admin_token).admin.laws()}

    @app.get("/s/{sid}/admin/steps")
    def steps(sid: str, x_admin_token: str | None = Header(None)) -> dict:
        return {"steps": admin(sid, x_admin_token).admin.steps}

    app.state.sessions = sessions
    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host=os.getenv("LS_SANDBOX_HOST", "127.0.0.1"), port=int(os.getenv("LS_SANDBOX_PORT", "8791")))
