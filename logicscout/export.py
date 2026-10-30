"""Deterministic exports from a finished run: a human operating manual and a standalone controller."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from logicscout import dsl
from logicscout.contracts import Event, Playbook, RefereeReport, Theory, WorldManual
from logicscout.playbook import validate_playbook


def _code(s: str) -> str:
    return f"`{s}`"


def _template(tpl) -> str:
    if not tpl.args:
        return tpl.name
    return f"{tpl.name}(" + ", ".join(f"{k}={v}" for k, v in tpl.args.items()) + ")"


def _rule_dsl(r) -> str:
    parts = [f"action={r.action}", f"when={r.when}"]
    if r.effects:
        parts.append("effects={" + ", ".join(f"{k}: {v}" for k, v in r.effects.items()) + "}")
    if r.memory:
        parts.append("memory={" + ", ".join(f"{k}: {v}" for k, v in r.memory.items()) + "}")
    if r.delay:
        parts.append(f"delay={r.delay}")
    return "; ".join(parts)


def manual_md(
    manual: WorldManual,
    theory: Theory | None,
    playbook: Playbook | None,
    referee: RefereeReport | None,
    events: list[Event] | None = None,
) -> str:
    events = events or []
    out = [f"# {manual.title}: operating manual", "", f"_Written by LogicScout from experiments on `{manual.world_id}`. {manual.summary}_", ""]
    out += ["## Controls", ""]
    for a in manual.actions:
        params = ", ".join(
            f"{p.name}: {p.type}" + (f" {p.choices}" if p.choices else "")
            + (f" [{p.min:g}..{p.max:g}]" if p.min is not None and p.max is not None else "")
            for p in a.params
        )
        out.append(f"- **{a.name}**({params})" + (f": {a.description}" if a.description else ""))
    out += ["", "## Readings", ""]
    for f in manual.observations:
        out.append(f"- **{f.name}** ({f.type})" + (f": {f.description}" if f.description else ""))

    out += ["", "## How it behaves", ""]
    rules = [r for r in (theory.rules if theory else []) if r.status == "supported"]
    if not rules:
        out.append("No rule has been confirmed by experiment yet.")
    for i, r in enumerate(rules, 1):
        out += [
            f"{i}. {r.statement}",
            f"   - rule: {_code(_rule_dsl(r))}",
            f"   - evidence: {len(r.evidence)} observation(s); confidence {r.confidence:.0%}; source: {r.source}",
        ]
    if theory and theory.memory:
        out += ["", "Hidden state the manual tracks: " + ", ".join(f"{k} (starts at {v!r})" for k, v in theory.memory.items())]

    out += ["", "## Known unknowns", ""]
    tentative = [r for r in (theory.rules if theory else []) if r.status == "tentative"]
    unknowns = list(theory.unknowns if theory else []) + [f"Unconfirmed: {r.statement}" for r in tentative]
    out += [f"- {u}" for u in unknowns] or ["- None recorded."]

    out += ["", "## Hidden change", ""]
    confirmed = [e for e in events if e.kind == "drift.confirmed"]
    recovered = [e for e in events if e.kind == "recovery.done"]
    if not confirmed:
        out.append("No hidden change was detected during this run.")
    for e in confirmed:
        rids = e.data.get("rules_implicated") or []
        out.append(f"- Detected at logbook entry {e.seq}; rules implicated: {', '.join(rids) or 'unspecified'}.")
    for e in recovered:
        out.append(f"- Recovered after {e.data.get('steps_down', '?')} step(s) using {e.data.get('probes_used', '?')} probe(s).")

    out += ["", "## Playbook", ""]
    if not playbook:
        out.append("No playbook compiled.")
    else:
        obj = next((o for o in manual.objectives if o.id == playbook.objective_id), None)
        if obj:
            out += [f"Goal: {obj.text} (done when {_code(obj.success)}, within {obj.horizon} steps).", ""]
        for i, pr in enumerate(playbook.rules, 1):
            why = f": {pr.why}" if pr.why else ""
            out.append(f"{i}. When {_code(pr.when)} → do {_code(_template(pr.do))}{why}")
        out.append(f"{len(playbook.rules) + 1}. Otherwise → do {_code(_template(playbook.fallback))}")
        if playbook.updates:
            out += ["", "After every step, remember: " + ", ".join(f"{k} = {_code(v)}" for k, v in playbook.updates.items())]

    out += ["", "## Referee", ""]
    if not referee:
        out.append("Not refereed.")
    else:
        wins = sum(c.success for c in referee.cases)
        out.append(f"- Held-out success: {wins}/{len(referee.cases)} ({referee.success_rate:.0%})")
        out.append(f"- Prediction accuracy on held-out transitions: {referee.prediction_accuracy:.0%}")
        for name, v in referee.baselines.items():
            out.append(f"- Baseline {name}: {v:.0%}")
    return "\n".join(out) + "\n"


def _dsl_runtime() -> str:
    src = Path(dsl.__file__).read_text(encoding="utf-8")
    src = src.split("DSL_GUIDE =", 1)[0]
    body = src.split('"""', 2)[2]  # drop module docstring
    return body.replace("from __future__ import annotations\n", "", 1).strip() + "\n"


_CONTROLLER = '''"""Standalone controller compiled by LogicScout for world {world_id!r}, objective {objective_id!r}.

Stdlib only. next_action(obs) -> {{"name", "args"}}; call after_step(obs) after each step.
Run directly with LS_SANDBOX_URL (and LS_SANDBOX_TOKEN) set to drive the LogicScout sandbox.
"""
from __future__ import annotations

import copy
import os
import urllib.request

# ---- safe expression evaluator (subset of the LogicScout DSL) ----
{runtime}
# ---- compiled playbook ----
PLAYBOOK = json_loads({playbook!r})
WORLD_ID = {world_id!r}
SUCCESS = {success!r}
HORIZON = {horizon!r}
LAB_SEED = {seed!r}

_mem = copy.deepcopy(PLAYBOOK["memory"])


def reset() -> None:
    global _mem
    _mem = copy.deepcopy(PLAYBOOK["memory"])


def _split(obs: dict) -> tuple[dict, int]:
    if "fields" in obs and isinstance(obs["fields"], dict):
        return obs["fields"], int(obs.get("t", 0))
    return obs, int(obs.get("t", 0) or 0)


def _ev(expr: str, env: dict):
    try:
        return evaluate(expr, env)
    except DSLError:
        return None


def _render(tpl: dict, env: dict) -> dict:
    return {{"name": tpl["name"], "args": {{k: _ev(v, env) for k, v in tpl["args"].items()}}}}


def next_action(obs: dict) -> dict:
    fields, t = _split(obs)
    env = {{"obs": fields, "args": {{}}, "mem": _mem, "t": t}}
    for rule in PLAYBOOK["rules"]:
        if _ev(rule["when"], env):
            return _render(rule["do"], env)
    return _render(PLAYBOOK["fallback"], env)


def after_step(obs: dict) -> None:
    if not PLAYBOOK["updates"]:
        return
    fields, t = _split(obs)
    env = {{"obs": fields, "args": {{}}, "mem": _mem, "t": t}}
    _mem.update({{k: _ev(v, env) for k, v in PLAYBOOK["updates"].items()}})


def _http(base: str, method: str, path: str, body=None, headers=None):
    req = urllib.request.Request(base.rstrip("/") + path, method=method,
                                 data=None if body is None else json_dumps(body).encode(),
                                 headers={{"Content-Type": "application/json", **(headers or {{}})}})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json_loads(r.read().decode())


def main() -> None:
    base = os.environ.get("LS_SANDBOX_URL")
    if not base:
        print("Set LS_SANDBOX_URL (and LS_SANDBOX_TOKEN) to drive the LogicScout sandbox.")
        return
    s = _http(base, "POST", "/sessions", {{"world_id": WORLD_ID}}, {{"X-Admin-Token": os.environ.get("LS_SANDBOX_TOKEN", "")}})
    h = {{"X-Scout-Token": s["scout_token"]}}
    p = "/s/" + s["session_id"]
    obs = _http(base, "POST", p + "/reset", {{"seed": int(os.environ.get("LS_SEED", LAB_SEED))}}, h)
    reset()
    for step in range(1, HORIZON + 1):
        action = next_action(obs)
        obs = _http(base, "POST", p + "/act", {{"action": action}}, h)["observation"]
        after_step(obs)
        print(step, action, obs["fields"])
        if _ev(SUCCESS, {{"obs": obs["fields"], "args": {{}}, "mem": _mem, "t": obs["t"]}}):
            print("goal reached in", step, "steps")
            return
    print("goal not reached within", HORIZON, "steps")


if __name__ == "__main__":
    main()
'''


def controller_py(manual: WorldManual, playbook: Playbook) -> str:
    errors = validate_playbook(playbook, manual)
    if errors:
        raise ValueError("playbook does not validate: " + "; ".join(errors[:5]))
    obj = next((o for o in manual.objectives if o.id == playbook.objective_id), manual.objectives[0])
    pb: dict[str, Any] = playbook.model_dump(include={"memory", "updates", "rules", "fallback"})
    runtime = _dsl_runtime() + "\nfrom json import dumps as json_dumps, loads as json_loads\n"
    return _CONTROLLER.format(
        world_id=manual.world_id, objective_id=playbook.objective_id, runtime=runtime,
        playbook=json.dumps(pb), success=obj.success, horizon=obj.horizon, seed=manual.lab_seeds[0],
    )
