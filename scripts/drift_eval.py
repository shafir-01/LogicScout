"""Offline evaluation of the drift monitor. No model calls: theories are learned by the code-only
investigator (every model call fails at once), controllers are the theory planner.

For each world configuration the script learns one theory, then runs the control loop the mission runs
(predict, act, compare, feed the monitor) under four conditions:
  stationary  no hidden change; every alarm is a false alarm
  abrupt      one hidden change of each kind in the world's shift menu at control step SHIFT_AT
  gradual     the same kind of change applied again every GRADUAL_EVERY steps (small repeated steps)
  harmless    abrupt changes after which every observation equals the unchanged run; an alarm is wrong
After a confirmed alarm the monitor is reset on the same theory (the mission would re-investigate) and
counting continues, so false alarms are counted per 100 control steps.

    uv run python scripts/drift_eval.py                 # current monitor
    uv run python scripts/drift_eval.py --monitor PATH  # another monitor module (before/after comparison)
    uv run python scripts/drift_eval.py --no-filter     # skip the mission's display-step filter
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logicscout.contracts import Mismatch, Observation, Theory, WorldManual  # noqa: E402
from logicscout.logbook import Logbook  # noqa: E402
from logicscout.sandbox.session import open_local  # noqa: E402
from logicscout.scout.investigator import Investigator  # noqa: E402
from logicscout.scout.mission import episode_seeds, goal_met, objective_of  # noqa: E402
from logicscout.scout.synth import PlannerPolicy  # noqa: E402
from logicscout.theory import Predictor, compare  # noqa: E402

STEPS = 160  # control steps per run
SHIFT_AT = 50  # control step of the (first) hidden change
GRADUAL_EVERY = 20
GRADUAL_TIMES = 4
CONFIGS = ([("relay", "standard", "priority5"), ("relay", "standard", "bulk8"), ("plant", "standard", None)]
           + [("forge", f"g{s}", None) for s in (1, 2, 3, 4, 5, 6)])
RUN_SEEDS = (0, 1, 2, 3)


class NullLLM:
    async def json(self, purpose, system, user, schema=None, tier="fast"):
        from logicscout.llm.nemotron import LLMError

        raise LLMError(f"model disabled: {purpose}")


def load_monitor(path: str | None):
    if not path:
        from logicscout.scout.monitor import DriftMonitor
        return DriftMonitor
    spec = importlib.util.spec_from_file_location("monitor_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DriftMonitor


def learn(world: str, variant: str) -> tuple[Theory, Investigator, WorldManual]:
    s = open_local(world, variant)
    manual = s.port.manual()
    inv = Investigator(NullLLM(), s.port, manual, Logbook("drift-eval"), [])
    theory = asyncio.run(inv.investigate(Theory(world_id=manual.world_id), manual.probe_budget))
    return theory, inv, manual


def spacing_filter(manual: WorldManual, transitions: list) -> Any:
    """The mission's display-step filter (Mission.within_resolution), reproduced to measure its effect."""
    floats = {f.name for f in manual.observations if f.type == "float"}

    def within(m: Mismatch) -> bool:
        p, o = m.predicted, m.observed
        if not all(isinstance(x, float) or (isinstance(x, int) and not isinstance(x, bool)) for x in (p, o)):
            return False
        if m.field not in floats:
            return False
        vals = sorted({round(float(a.fields.get(m.field)), 6) for a, _, _ in transitions[-80:]
                       if isinstance(a.fields.get(m.field), (int, float))})
        steps = [b - a for a, b in zip(vals, vals[1:]) if b - a > 1e-9]
        return bool(steps) and abs(p - o) <= min(steps) + 1e-9
    return within


def run(Monitor, world: str, variant: str, obj_id: str | None, seed: int, learned, schedule: list[tuple[int, str]],
        use_filter: bool) -> dict[str, Any]:
    theory, inv, manual = learned
    objective = objective_of(manual, obj_id)
    s = open_local(world, variant)
    transitions = list(inv.transitions)
    within = spacing_filter(manual, transitions) if use_filter else (lambda m: False)
    mon = Monitor(theory)
    mon.calibrate(inv.residuals(theory))
    seeds = episode_seeds(manual, manual.lab_seeds[0] + 3 * seed, 64)
    schedule = sorted(schedule)
    applied: list[dict] = []
    alarms: list[int] = []
    suspected: list[int] = []
    filtered = 0
    trace: list[dict] = []
    step = 0
    for ep_seed in seeds:
        if step >= STEPS:
            break
        obs = s.port.reset(ep_seed)
        policy = PlannerPolicy(theory, manual, objective)
        pred = Predictor(theory)
        pred.reset(obs)
        for _ in range(objective.horizon):
            while schedule and schedule[0][0] <= step:
                at, kind = schedule.pop(0)
                rec = s.admin.shift(seed * 31 + len(applied), kind=kind)
                applied.append({"at": at, "kind": rec.kind, "changed": rec.after})
            action = policy.next_action(obs)
            predicted = pred.predict(obs, action)
            res = s.port.act(action)
            new = res.observation
            mism = compare(predicted, new.fields, pred.last_rules)
            rules = {f: list(r[-1:]) for f, r in pred.last_rules.items()}
            pred.advance(new)
            policy.after_step(new)
            transitions.append((obs, action, new))
            wrong = {m.field for m in mism}
            correct = [k for f in new.fields if f != "t" and f not in wrong for k in (rules.get(f) or [f"field:{f}"])]
            kept = [m for m in mism if not within(m)]
            filtered += len(mism) - len(kept)
            st = mon.observe(kept, correct)
            trace.append(new.fields)
            if st == "suspected":
                suspected.append(step)
            if st == "confirmed":
                alarms.append(step)
                mon.reset(theory)
                mon.calibrate(inv.residuals(theory))
            obs = new
            step += 1
            if step >= STEPS or goal_met(objective, obs) or res.done:
                break
    return {"alarms": alarms, "suspected": suspected, "applied": applied, "filtered": filtered,
            "steps": step, "trace": trace}


def summarise(rows: list[dict], kind: str) -> dict[str, Any]:
    if kind == "stationary":
        steps = sum(r["steps"] for r in rows)
        fa = sum(len(r["alarms"]) for r in rows)
        return {"runs": len(rows), "steps": steps, "false_alarms": fa,
                "false_alarms_per_100_steps": round(100 * fa / max(1, steps), 2),
                "runs_with_false_alarm": sum(1 for r in rows if r["alarms"])}
    det, delays, early = 0, [], 0
    for r in rows:
        first = r["applied"][0]["at"] if r["applied"] else SHIFT_AT
        pre = [a for a in r["alarms"] if a < first]
        early += len(pre)
        post = [a for a in r["alarms"] if a >= first]
        if post:
            det += 1
            delays.append(post[0] - first + 1)
    n = len(rows)
    out = {"runs": n, "detected": det, "missed": n - det, "detection_rate": round(det / n, 3) if n else None,
           "false_alarms_before_change": early}
    if delays:
        out.update(delay_median=statistics.median(delays), delay_mean=round(statistics.mean(delays), 1),
                   delay_max=max(delays))
    if kind == "harmless":
        out = {"runs": n, "alarmed": det, "alarm_rate": round(det / n, 3) if n else None}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", default=None, help="path to a monitor module (default: logicscout.scout.monitor)")
    ap.add_argument("--no-filter", action="store_true", help="feed every mismatch, without the display-step filter")
    ap.add_argument("--out", default=None, help="write the summary JSON here")
    ap.add_argument("--quick", action="store_true", help="fewer seeds (smoke test)")
    a = ap.parse_args()
    Monitor = load_monitor(a.monitor)
    seeds = RUN_SEEDS[:1] if a.quick else RUN_SEEDS
    t0 = time.time()
    by: dict[str, list[dict]] = {"stationary": [], "abrupt": [], "gradual": [], "harmless": []}
    per_world: dict[str, dict[str, list[dict]]] = {}
    per_kind: dict[str, list[dict]] = {}
    filtered_post = 0
    for world, variant, obj in CONFIGS:
        learned = learn(world, variant)
        menu = [m["id"] for m in open_local(world, variant).admin.world_class.shift_menu()]
        if world == "forge":
            from logicscout.worlds.forge import ForgeWorld
            have = set(ForgeWorld.default_laws(variant)["mechanisms"])
            menu = [k for k in menu if k in have]
        w = per_world.setdefault(world, {"stationary": [], "abrupt": [], "gradual": [], "harmless": []})
        for seed in seeds:
            base = run(Monitor, world, variant, obj, seed, learned, [], not a.no_filter)
            by["stationary"].append(base)
            w["stationary"].append(base)
            for kind in menu:
                r = run(Monitor, world, variant, obj, seed, learned, [(SHIFT_AT, kind)], not a.no_filter)
                same = r["trace"][SHIFT_AT:] == base["trace"][SHIFT_AT:len(r["trace"])]
                cond = "harmless" if same else "abrupt"
                by[cond].append(r)
                w[cond].append(r)
                if cond == "abrupt":
                    per_kind.setdefault(f"{world}:{kind}", []).append(r)
                    filtered_post += r["filtered"] - base["filtered"]
                g = run(Monitor, world, variant, obj, seed, learned,
                        [(SHIFT_AT + i * GRADUAL_EVERY, kind) for i in range(GRADUAL_TIMES)], not a.no_filter)
                if g["trace"][SHIFT_AT:] != base["trace"][SHIFT_AT:len(g["trace"])]:
                    by["gradual"].append(g)
                    w["gradual"].append(g)
        print(f"{world}/{variant}/{obj}: done ({time.time() - t0:.0f}s)", file=sys.stderr)
    out = {
        "monitor": a.monitor or "logicscout.scout.monitor",
        "filter": not a.no_filter,
        "steps_per_run": STEPS, "shift_at": SHIFT_AT, "gradual_every": GRADUAL_EVERY, "gradual_times": GRADUAL_TIMES,
        "overall": {k: summarise(v, k) for k, v in by.items()},
        "per_world": {wd: {k: summarise(v, k) for k, v in d.items() if v} for wd, d in per_world.items()},
        "per_kind": {k: summarise(v, "abrupt") for k, v in sorted(per_kind.items())},
        "mismatches_hidden_by_filter_after_change": filtered_post,
        "seconds": round(time.time() - t0, 1),
    }
    text = json.dumps(out, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
