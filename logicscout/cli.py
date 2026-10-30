"""Command line: `logicscout run --world relay ...` runs a full mission in-process; `logicscout worlds` lists worlds."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid

from logicscout import config
from logicscout.contracts import Event, RunConfig, RunState


def _short(v, n: int = 90) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str, separators=(",", ":"))
    return s if len(s) <= n else s[: n - 3] + "..."


def format_event(ev: Event) -> str | None:
    d, k = ev.data, ev.kind
    if k == "phase":
        line = f"== {d['phase']} =="
    elif k == "control.step":
        miss = ",".join(m["field"] for m in d.get("mismatches", [])) or "-"
        a = d["action"]
        line = f"ep{d['episode']} #{d['step']:<3} {a['name']}{_short(a.get('args') or '')} -> {_short(d['observation']['fields'], 70)} miss:{miss}"
    elif k == "probe.step":
        line = f"probe {d.get('probe_id')} {_short(d.get('action'), 50)} -> {_short(d.get('observation', {}).get('fields'), 60)}"
    elif k == "model.call":
        line = f"model {d['purpose']} [{d['tier']}] {d['model']} {d['latency_ms']:.0f}ms ok={d['ok']}"
    elif k == "theory.revised":
        th = d.get("theory", {})
        line = f"theory v{th.get('version')} rules={len(th.get('rules', []))} acc={d.get('accuracy')} base={d.get('baseline_accuracy')}"
    elif k == "playbook.compiled":
        pb = d["playbook"]
        line = f"playbook {pb['id']} origin={pb['origin']} rules={len(pb['rules'])} simulated={d['simulated']}"
    elif k == "referee.report":
        r = d["report"]
        line = f"referee success={r['success_rate']:.2f} accuracy={r['prediction_accuracy']:.2f} baselines={r['baselines']}"
    elif k in ("run.started",):
        line = f"run started: {d['manual']['title']}"
    elif k in ("run.finished", "run.failed"):
        line = f"{k}: {_short(d.get('metrics'), 400)}"
    elif k == "hypothesis.proposed":
        line = f"hypothesis {d['hypothesis']['id']}: {_short(d['hypothesis']['statement'])}"
    elif k == "note":
        line = f"note: {d.get('text')}"
    elif k == "error":
        line = f"ERROR: {d.get('message')}"
    else:
        line = f"{k} {_short(d, 120)}"
    return f"[{ev.seq:>4}] {line}"


async def _run(args: argparse.Namespace) -> int:
    from logicscout.llm import Nemotron
    from logicscout.logbook import Logbook
    from logicscout.referee import evaluate
    from logicscout.sandbox import open_session
    from logicscout.scout.mission import MissionControls, run_mission

    if not config.NEBIUS_API_KEY:
        print("NEBIUS_API_KEY is not set; add it to .env (see .env.example)", file=sys.stderr)
        return 2
    run_id = f"{args.world}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    run_dir = config.DATA_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_log = run_dir / "prompts.jsonl"
    log = Logbook(run_id, run_dir / "events.jsonl")
    llm = Nemotron(prompt_log=prompt_log)
    session = open_session(args.world)
    cfg = RunConfig(world_id=args.world, objective_id=args.objective, seed=args.seed, use_briefing=not args.no_briefing,
                    use_transfer=args.transfer, probe_budget=args.budget, shift_after=args.shift_after)
    state = RunState(run_id=run_id, config=cfg, phase="encounter", live=True, started_at=time.time())
    q = log.subscribe()

    async def printer() -> None:
        while (ev := await q.get()) is not None:
            line = format_event(ev)
            if line:
                print(line, flush=True)

    task = asyncio.create_task(printer())
    await run_mission(cfg, log, llm, session, state, MissionControls(), prompt_log=prompt_log, referee=evaluate)
    log.close()
    await task
    print(f"run {run_id}: phase={state.phase}; log at {run_dir}")
    return 0 if state.phase == "done" else 1


def _worlds() -> int:
    from logicscout.worlds.base import load_all

    for wid, cls in sorted(load_all().items()):
        m = cls.manual()
        objs = ", ".join(o.id for o in m.objectives)
        print(f"{wid:<10} {m.title} [{m.domain}] budget={m.probe_budget} objectives: {objs}")
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="logicscout")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a full mission in-process")
    r.add_argument("--world", required=True)
    r.add_argument("--objective", default=None)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--shift-after", type=int, default=None)
    r.add_argument("--no-briefing", action="store_true")
    r.add_argument("--transfer", action="store_true")
    r.add_argument("--budget", type=int, default=None)
    sub.add_parser("worlds", help="list available worlds")
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(asyncio.run(_run(args)) if args.cmd == "run" else _worlds())


if __name__ == "__main__":
    main()
