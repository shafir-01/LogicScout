"""Gate: an independent HTTP job-dispatch controller of a field device (own process, :8790).

Per-namespace state (header X-Namespace). Deterministic logical clock: every request ticks once.
Admin endpoints (/_admin/*) need X-Admin-Token == config.SANDBOX_TOKEN and never tick.
Run: uv run python -m logicscout.worlds.gate_service
"""
from __future__ import annotations

import os
import socket
import threading
import time

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from logicscout import config

MAX_JOBS = 10
DEFAULT_LAWS = {"capacity": 4, "refill_every": 2, "lockout": 6, "arm_window": 3, "max_armed": 2}


class NS:
    def __init__(self, seed: int, laws: dict) -> None:
        self.seed = seed
        self.laws = dict(laws)
        self.t = 0
        self.tokens = max(1, laws["capacity"] - seed % 2)
        self.strikes = 0
        self.lock_until = -1
        self.lockouts = 0
        self.committed = 0
        self.last_status = 200
        self.last_job = -1
        self.jobs: list[dict] = []  # {state, armed_at}

    def view(self) -> dict:
        states = [j["state"] for j in self.jobs]
        return {
            "t": self.t, "last_status": self.last_status, "last_job": self.last_job,
            "jobs_draft": states.count("draft"), "jobs_armed": states.count("armed"),
            "committed": self.committed, "locked": self.t < self.lock_until, "lockouts": self.lockouts,
        }

    def tick(self) -> None:
        self.t += 1
        if self.t % self.laws["refill_every"] == 0:
            self.tokens = min(self.laws["capacity"], self.tokens + 1)

    def spend(self) -> int | None:
        """Charge one token; returns an error status or None."""
        if self.t < self.lock_until:
            return 423
        if self.tokens < 1:
            self.strikes += 1
            if self.strikes >= 3:
                self.strikes = 0
                self.lock_until = self.t + self.laws["lockout"]
                self.lockouts += 1
            return 429
        self.tokens -= 1
        return None


STATE: dict[str, NS] = {}
LOCK = threading.Lock()
app = FastAPI(title="Field station job controller")


def _ns(name: str | None) -> NS:
    if not name or name not in STATE:
        raise HTTPException(404, "unknown namespace")
    return STATE[name]


def _admin(token: str | None) -> None:
    if token != config.SANDBOX_TOKEN:
        raise HTTPException(403, "forbidden")


def _reply(ns: NS, code: int, body: dict | None = None) -> JSONResponse:
    ns.last_status = code
    return JSONResponse({"t": ns.t, **(body or {})}, status_code=code)


def _public(name: str | None, kind: str, job: int | None = None) -> JSONResponse:
    with LOCK:
        ns = _ns(name)
        ns.tick()
        if kind == "status":
            ns.strikes = 0
            if ns.t < ns.lock_until:
                return _reply(ns, 423)
            v = ns.view()
            return _reply(ns, 200, {"jobs": [j["state"] for j in ns.jobs], "committed": v["committed"]})
        if kind == "tick":
            ns.strikes = 0
            return _reply(ns, 200)
        err = ns.spend()
        if err:
            return _reply(ns, err)
        if kind == "create":
            if len(ns.jobs) >= MAX_JOBS:
                return _reply(ns, 409, {"error": "job table full"})
            ns.jobs.append({"state": "draft", "armed_at": -1})
            ns.last_job = len(ns.jobs) - 1
            return _reply(ns, 201, {"id": ns.last_job})
        if job is None or not 0 <= job < len(ns.jobs):
            return _reply(ns, 404, {"error": "no such job"})
        j = ns.jobs[job]
        if kind == "arm":
            if j["state"] not in ("draft", "armed"):
                return _reply(ns, 409)
            armed = sorted((x for x in ns.jobs if x["state"] == "armed" and x is not j), key=lambda x: x["armed_at"])
            while len(armed) >= ns.laws["max_armed"]:
                armed.pop(0)["state"] = "draft"
            j["state"], j["armed_at"] = "armed", ns.t
            return _reply(ns, 200)
        if kind == "commit":
            if j["state"] != "armed":
                return _reply(ns, 409)
            if ns.t - j["armed_at"] > ns.laws["arm_window"]:
                j["state"] = "draft"
                return _reply(ns, 409)
            j["state"] = "committed"
            ns.committed += 1
            return _reply(ns, 200)
        if kind == "cancel":
            if j["state"] not in ("draft", "armed"):
                return _reply(ns, 409)
            j["state"] = "cancelled"
            return _reply(ns, 200)
        return _reply(ns, 400)


@app.get("/status")
def status(x_namespace: str | None = Header(None)):
    return _public(x_namespace, "status")


@app.post("/tick")
def tick(x_namespace: str | None = Header(None)):
    return _public(x_namespace, "tick")


@app.post("/jobs")
def create(x_namespace: str | None = Header(None)):
    return _public(x_namespace, "create")


@app.post("/jobs/{job}/{verb}")
def job_verb(job: int, verb: str, x_namespace: str | None = Header(None)):
    if verb not in ("arm", "commit", "cancel"):
        raise HTTPException(404)
    return _public(x_namespace, verb, job)


class ResetBody(BaseModel):
    seed: int
    laws: dict | None = None


@app.get("/health")
def health():
    return {"ok": True, "namespaces": len(STATE)}


@app.post("/_admin/reset")
def admin_reset(body: ResetBody, x_namespace: str | None = Header(None), x_admin_token: str | None = Header(None)):
    _admin(x_admin_token)
    if not x_namespace:
        raise HTTPException(400, "X-Namespace required")
    with LOCK:
        ns = STATE[x_namespace] = NS(body.seed, {**DEFAULT_LAWS, **(body.laws or {})})
        return ns.view()


@app.post("/_admin/laws")
def admin_laws(laws: dict, x_namespace: str | None = Header(None), x_admin_token: str | None = Header(None)):
    _admin(x_admin_token)
    with LOCK:
        ns = _ns(x_namespace)
        ns.laws.update(laws)
        ns.tokens = min(ns.tokens, ns.laws["capacity"])
        return {"laws": ns.laws}


@app.get("/_admin/peek")
def admin_peek(x_namespace: str | None = Header(None), x_admin_token: str | None = Header(None)):
    _admin(x_admin_token)
    with LOCK:
        return _ns(x_namespace).view()


@app.get("/_admin/success")
def admin_success(x_namespace: str | None = Header(None), x_admin_token: str | None = Header(None)):
    _admin(x_admin_token)
    with LOCK:
        ns = _ns(x_namespace)
        return {"commit5": ns.committed >= 5 and ns.lockouts == 0}


def start_in_thread(port: int = 0) -> str:
    """Start the service in this process (tests). Returns its base URL."""
    import uvicorn

    if not port:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    return f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("LS_GATE_HOST", "127.0.0.1"), port=int(os.getenv("LS_GATE_PORT", "8790")))
