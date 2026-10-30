"""Where does the language model add value over code-side rule fitting?

Runs the investigation phase only (no control) on relay, orbit, gate and a few out-of-family forge systems,
with the same probe budget in three modes:
  induction  code-side rule fitting and mining only, every model call refused (zero calls)
  model      model hypotheses only, code-side fitting and mining switched off
  both       the normal investigator

Each final theory is scored on held-out play the investigator never saw:
  * referee transitions (uniformly random actions from the referee's standard cases): accuracy and
    accuracy on state-changing (step, field) pairs
  * per-law checks (relay, orbit, gate): held-out episodes are played on the hidden world while privileged
    referee code tags every transition that exercises a given law; a law counts as captured on a transition
    when the theory predicts every field that law moves.

Usage:
  uv run python scripts/model_value.py --dry           # estimate model calls, no calls made
  uv run python scripts/model_value.py --modes induction            # zero calls
  uv run python scripts/model_value.py --worlds relay,orbit --modes model,both --seeds 0
Results: data/model_value/<world>-<variant>-<mode>-s<seed>.json and data/model_value/summary.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import zlib
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from logicscout import config  # noqa: E402
from logicscout.contracts import Action, Observation, Theory  # noqa: E402
from logicscout.logbook import Logbook  # noqa: E402
from logicscout.referee.referee import (  # noqa: E402
    cases_for, collect_transitions, manual_of, random_action, world_class,
)
from logicscout.scout import investigator as inv_mod  # noqa: E402
from logicscout.scout.investigator import Investigator  # noqa: E402
from logicscout.theory import _replay, accuracy, changed_accuracy, compare, persistence_accuracy  # noqa: E402

OUT = ROOT / "data" / "model_value"
MODES = ("induction", "model", "both")
CALL_BUDGET = 80  # hard ceiling on provider calls for one invocation of this script
CALLS_PER_RUN = sum(inv_mod.CALL_CAPS.values())  # per investigate(), before transient retries
HELD_OUT_EPISODES = 24
EPISODE_STEPS = 30
HELD_OUT_SEED0 = 30000  # outside every lab seed range


# ---- model access ----------------------------------------------------------------------------------

class NullLLM:
    async def json(self, purpose, system, user, schema=None, tier="fast"):
        from logicscout.llm.nemotron import LLMError

        raise LLMError(f"model disabled for this run: {purpose}")


class BudgetLLM:
    """Real model behind a global call ceiling shared by every run in this process."""

    def __init__(self, inner, counter: dict[str, int], ceiling: int) -> None:
        self.inner, self.counter, self.ceiling = inner, counter, ceiling

    async def json(self, purpose, system, user, schema=None, tier="fast"):
        from logicscout.llm.nemotron import LLMError

        if self.counter["calls"] >= self.ceiling - 3:  # leave room for one call's internal retries
            raise LLMError(f"call ceiling reached: {purpose}")
        return await self.inner.json(purpose, system, user, schema=schema, tier=tier)


# ---- per-law checkers (privileged referee code: reads hidden state) ---------------------------------

Tag = tuple[str, list[str]]


def relay_tags(w, a: Action) -> list[Tag]:
    L, t, out = w.laws, w.t, []
    queue = w.queue
    if a.name == "send":
        take = min(int(a.args["n"]), len(queue))
        if a.args["via"] == "buoy" and take:
            open_ = t % L["period"] < L["window"]
            if not open_ or (take <= L["buoy_cap"] and w.battery >= take):
                out.append(("buoy contact window", ["delivered", "lost"]))
            elif take > L["buoy_cap"]:
                out.append(("buoy capacity per send", ["delivered", "lost"]))
            else:
                out.append(("buoy battery", ["delivered", "lost"]))
        if a.args["via"] == "sat" and take:
            out.append(("satellite energy cost", ["vessel_energy"]))
        pri = sum(m["priority"] for m in queue)
        if take and 0 < pri < len(queue):
            if w.prioritized_last:
                out.append(("prioritize reorders queue", ["priority_waiting"]))
            else:
                out.append(("newest-first queue order", ["priority_waiting"]))
    if any(at <= t + 1 for at, _ in w.in_flight):
        out.append(("satellite delivery latency", ["delivered"]))
    if (t + 1) % L["arrival_every"] == 0:
        out.append(("periodic arrivals", ["queue"]))
    if (t + 1) % L["recharge_every"] == 0 and w.battery < L["battery_max"]:
        out.append(("buoy recharge", ["buoy_signal"]))
    return out


def orbit_tags(w, a: Action) -> list[Tag]:
    out: list[Tag] = [("lagged temperature", ["temp"])]
    args = a.args
    if a.name == "power" and args.get("unit") == "payload" and args.get("state") == "on" \
            and not w.payload_on and not w.fault:
        out.append(("bus warm-up before payload", ["payload_on", "fault"]))
    if a.name == "power" and args.get("unit") == "bus" and args.get("state") == "off" and (w.payload_on or w.fault):
        out.append(("bus off clears payload", ["payload_on", "fault"]))
    if a.name == "capture" and w.payload_on and not w.fault:
        out.append(("capture validity (band, calibration)", ["valid_stored"]))
        if len(w.images) >= w.laws["capacity"]:
            out.append(("storage overwrite", ["stored", "valid_stored"]))
    if a.name == "downlink" and w.images:
        out.append(("downlink only in passes", ["downlinked", "stored"]))
    return out


def gate_tags(w, a: Action) -> list[Tag]:
    from logicscout.worlds import gate_service

    ns = gate_service.STATE[w.ns]
    L, t1, out = ns.laws, ns.t + 1, []
    ep = a.args.get("endpoint") if a.name == "call" else None
    costly = ep in ("create", "arm", "commit", "cancel")
    locked = t1 < ns.lock_until
    tokens_after_refill = min(L["capacity"], ns.tokens + 1) if t1 % L["refill_every"] == 0 else ns.tokens
    if t1 % L["refill_every"] == 0 and ns.tokens < L["capacity"]:
        out.append(("token refill", ["tokens"]))
    if costly and locked:
        out.append(("lockout refuses requests", ["last_status", "locked"]))
    if costly and not locked and tokens_after_refill < 1:
        if ns.strikes == 2:
            out.append(("three strikes lockout", ["locked", "lockouts", "strikes"]))
        else:
            out.append(("empty bucket returns 429", ["last_status", "strikes"]))
    if not costly and ns.strikes > 0:
        out.append(("backing off clears strikes", ["strikes"]))
    if costly and not locked and tokens_after_refill >= 1:
        out.append(("token cost per request", ["tokens"]))
        job = a.args.get("job")
        if ep in ("arm", "commit") and isinstance(job, int) and 0 <= job < len(ns.jobs):
            j = ns.jobs[job]
            if ep == "commit" and j["state"] == "armed":
                if t1 - j["armed_at"] <= L["arm_window"]:
                    out.append(("commit within arm window", ["committed", "jobs_armed"]))
                else:
                    out.append(("stale arm falls back to draft", ["committed", "jobs_armed", "jobs_draft"]))
            if ep == "arm" and j["state"] == "draft":
                armed = sum(x["state"] == "armed" for x in ns.jobs)
                if armed >= L["max_armed"]:
                    out.append(("arming evicts the oldest", ["jobs_armed", "jobs_draft"]))
    return out


TAGGERS: dict[str, Callable] = {"relay": relay_tags, "orbit": orbit_tags, "gate": gate_tags}


def A(name: str, **args) -> Action:
    return Action(name=name, args=args)


def scripted(world_id: str, rng: random.Random, obs: Observation, k: int) -> Action:
    """A loose operator script so held-out play reaches the deeper laws (random play rarely does)."""
    f = obs.fields
    if world_id == "relay":
        return rng.choice([A("send", via="buoy", n=rng.randint(1, 3)), A("send", via="sat", n=rng.randint(1, 2)),
                           A("prioritize"), A("send", via="buoy", n=1), A("wait")])
    if world_id == "orbit":
        seq = [A("power", unit="bus", state="on"), A("wait"), A("wait"),
               A("power", unit="payload", state="on"), A("heater", state="on"), A("wait"), A("calibrate"), A("capture"),
               A("capture"), A("capture"), A("downlink"), A("calibrate"), A("capture"), A("downlink"),
               A("downlink"), A("wait"), A("downlink"), A("heater", state="off"), A("capture"),
               A("power", unit="bus", state="off")]
        return seq[k % len(seq)]
    if world_id == "gate":
        last = max(0, f.get("last_job", 0))
        return rng.choice([A("call", endpoint="create"), A("call", endpoint="arm", job=rng.randint(0, last)),
                           A("call", endpoint="commit", job=rng.randint(0, last)), A("wait"),
                           A("call", endpoint="arm", job=last), A("call", endpoint="commit", job=last),
                           A("call", endpoint="status")])
    raise KeyError(world_id)


def held_out_episodes(world_id: str) -> list[list[tuple[Observation, Action, Observation, list[Tag]]]]:
    cls = world_class(world_id)
    tagger = TAGGERS[world_id]
    episodes = []
    for e in range(HELD_OUT_EPISODES):
        world = cls("standard")
        manual = manual_of(cls, "standard", world)
        rng = random.Random(HELD_OUT_SEED0 + e)
        obs = world.reset(HELD_OUT_SEED0 + e)
        ep = []
        for k in range(EPISODE_STEPS):
            if e % 2 == 0 or rng.random() < 0.3:
                a = random_action(manual.actions, rng)
            else:
                a = scripted(world_id, rng, obs, k)
            tags = tagger(world, a)
            res = world.act(a)
            if res.error:
                continue
            ep.append((obs, a, res.observation, tags))
            obs = res.observation
            if res.done:
                break
        if hasattr(world, "close"):
            world.close()
        episodes.append(ep)
    return episodes


def law_scores(theory: Theory, episodes) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, int]] = {}
    for ep in episodes:
        trans = [(b, a, o) for b, a, o, _ in ep]
        for (b, a, o, tags), (_, p, _) in zip(ep, _replay(theory, trans)):
            for law, fields in tags:
                s = stats.setdefault(law, {"n": 0, "theory": 0, "persistence": 0})
                s["n"] += 1
                want = {k: o.fields[k] for k in fields}
                s["theory"] += not compare({k: p.get(k) for k in fields}, want)
                s["persistence"] += not compare({k: b.fields.get(k) for k in fields}, want)
    return {law: {"n": s["n"], "accuracy": round(s["theory"] / s["n"], 3),
                  "persistence": round(s["persistence"] / s["n"], 3)} for law, s in sorted(stats.items())}


# ---- runs -------------------------------------------------------------------------------------------

def referee_transitions(world_id: str, variant: str):
    cls = world_class(world_id)
    obj = cls.manual_for(variant).objectives[0].id if hasattr(cls, "manual_for") and variant != "standard" \
        else cls.manual().objectives[0].id
    objs = {c.objective_id for c in (cls.referee_cases_for(variant) if hasattr(cls, "referee_cases_for")
                                      else cls.referee_cases())}
    trans = []
    for o in sorted(objs | {obj}):
        for c in cases_for(cls, o, variant):
            if c.variant == variant:
                trans.append(collect_transitions(cls, c))
    return trans


def flat_scores(theory: Theory, episodes: list[list]) -> dict[str, float]:
    acc = [accuracy(theory, ep) for ep in episodes if ep]
    ch = [changed_accuracy(theory, ep) for ep in episodes if ep]
    per = [persistence_accuracy(ep) for ep in episodes if ep]
    return {"accuracy": round(sum(acc) / len(acc), 4), "changed_accuracy": round(sum(ch) / len(ch), 4),
            "persistence_accuracy": round(sum(per) / len(per), 4), "episodes": len(acc)}


async def run_one(world_id: str, variant: str, mode: str, seed: int, counter: dict[str, int],
                  laws_eps: dict[str, list]) -> dict[str, Any]:
    from logicscout.sandbox import open_session

    calls: list = []
    if mode == "induction":
        llm = NullLLM()
    else:
        from logicscout.llm import Nemotron

        def on_call(c):
            calls.append(c)
            counter["calls"] += 1

        llm = BudgetLLM(Nemotron(on_call=on_call), counter, CALL_BUDGET)
    session = open_session(world_id, variant)
    manual = session.port.manual()
    run_id = f"mv-{world_id}-{variant}-{mode}-s{seed}"
    inv = Investigator(llm, session.port, manual, Logbook(run_id), [], use_induction=(mode != "model"))
    if seed:
        inv._rng = random.Random(zlib.crc32(manual.world_id.encode()) + 1_000_003 * seed)
    t0 = time.perf_counter()
    err = None
    try:
        theory = await inv.investigate(Theory(world_id=manual.world_id), manual.probe_budget)
    except Exception as e:  # a crashed run still reports, with an empty theory
        err = f"{type(e).__name__}: {e}"
        theory = Theory(world_id=manual.world_id)
    wall = time.perf_counter() - t0
    out: dict[str, Any] = {
        "world": world_id, "variant": variant, "mode": mode, "seed": seed, "probe_budget": manual.probe_budget,
        "probes_used": inv.probes_used, "lab_steps": session.admin.steps, "wall_s": round(wall, 1),
        "model_calls": len(calls), "failed_calls": sum(not c.ok for c in calls),
        "tokens": sum((c.prompt_tokens or 0) + (c.completion_tokens or 0) for c in calls),
        "rules": len(theory.rules), "error": err,
        "referee": flat_scores(theory, referee_transitions(world_id, variant)),
        "theory": theory.model_dump(),
    }
    if world_id in laws_eps:
        out["laws"] = law_scores(theory, laws_eps[world_id])
        out["held_out_play"] = flat_scores(theory, [[(b, a, o) for b, a, o, _ in ep] for ep in laws_eps[world_id]])
    close = getattr(getattr(session.admin, "_world", None), "close", None)
    if close:
        close()
    return out


def ensure_gate() -> None:
    """A private in-process gate service (its namespaces are also readable by the law checkers)."""
    from logicscout.worlds import gate_service

    config.GATE_URL = gate_service.start_in_thread()


def summarize() -> dict[str, Any]:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT.glob("*-s*.json"))]
    cells: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = f"{r['world']}/{r['variant']}"
        c = cells.setdefault(key, {}).setdefault(r["mode"], {"runs": 0, "accuracy": [], "changed_accuracy": [],
                                                              "model_calls": 0, "laws": {}})
        c["runs"] += 1
        c["accuracy"].append(r["referee"]["accuracy"])
        c["changed_accuracy"].append(r["referee"]["changed_accuracy"])
        c["persistence_accuracy"] = r["referee"]["persistence_accuracy"]
        c["model_calls"] += r["model_calls"]
        for law, s in (r.get("laws") or {}).items():
            c["laws"].setdefault(law, []).append(s["accuracy"])
            c.setdefault("law_n", {})[law] = s["n"]
            c.setdefault("law_persistence", {})[law] = s["persistence"]
    for world in cells.values():
        for c in world.values():
            for k in ("accuracy", "changed_accuracy"):
                c[k + "_mean"] = round(sum(c[k]) / len(c[k]), 3)
            c["laws_mean"] = {law: round(sum(v) / len(v), 3) for law, v in c["laws"].items()}
    summary = {"cells": cells, "total_model_calls": sum(r["model_calls"] for r in rows), "runs": len(rows)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", default="relay,orbit,gate")
    ap.add_argument("--forge", default="", help="out-of-family forge variants, e.g. x101,x202")
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.summary_only:
        print(json.dumps(summarize(), indent=1)[:4000])
        return
    config.SANDBOX_URL = ""
    targets = [(w, "standard") for w in args.worlds.split(",") if w]
    targets += [("forge", v) for v in args.forge.split(",") if v]
    modes = [m for m in args.modes.split(",") if m]
    seeds = [int(s) for s in args.seeds.split(",") if s]
    jobs = [(w, v, m, s) for w, v in targets for m in modes for s in seeds]
    est = sum(CALLS_PER_RUN for _, _, m, _ in jobs if m != "induction")
    print(f"{len(jobs)} runs; at most ~{est} model calls before retries (ceiling {CALL_BUDGET})")
    if args.dry:
        return
    if any(w == "gate" for w, _ in targets):
        ensure_gate()
    laws_eps = {w: held_out_episodes(w) for w, _ in targets if w in TAGGERS}
    counter = {"calls": 0}

    async def go(job):
        w, v, m, s = job
        r = await run_one(w, v, m, s, counter, laws_eps)
        (OUT / f"{w}-{v}-{m}-s{s}.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
        print(f"{w}/{v} {m} s{s}: acc {r['referee']['accuracy']} changed {r['referee']['changed_accuracy']} "
              f"calls {r['model_calls']} probes {r['probes_used']} err {r['error']}", flush=True)

    await asyncio.gather(*(go(j) for j in jobs))
    print(f"total model calls this invocation: {counter['calls']}")
    summarize()


if __name__ == "__main__":
    asyncio.run(main())
