"""Bench CLI. Examples:

uv run python -m logicscout.bench --world relay --objective bulk8 --seeds 8 --arms no_model,tabular,random,idle \
    --out data/bench/scale
uv run python -m logicscout.bench --world forge --variants g101-g120 --seeds 1 --arms no_model,tabular,random,idle \
    --out data/bench/scale
uv run python -m logicscout.bench --world forge --variants g101-g106 --arms full,model_only --dry-run

Arms that never call the model (no_model, tabular, random, idle) run without NEBIUS_API_KEY.
Per-seed JSON: <out>/<world>/<arm>/[<variant>/]seed-<i>.json; aggregate tables: <out>/summary.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

from logicscout import config
from logicscout.bench.baselines import ARMS, NO_CALL_ARMS, SHIFT_AFTER, ArmContext, estimate_calls, run_arm
from logicscout.bench.stats import summary_md
from logicscout.referee.referee import cases_for, manual_of, world_class


def ensure_gate(world_id: str) -> None:
    if world_id != "gate":
        return
    import httpx

    try:
        httpx.get(config.GATE_URL.rstrip("/") + "/", timeout=2.0)
    except httpx.HTTPError:
        from logicscout.worlds import gate_service

        config.GATE_URL = gate_service.start_in_thread()
        print(f"gate service was not running; started in-process at {config.GATE_URL}")


def parse_variants(spec: str | None) -> list[str]:
    """'standard', 'g101,g105' or a range 'g101-g120'."""
    if not spec:
        return ["standard"]
    out: list[str] = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        if "-" in part and part.startswith("g"):
            a, b = part.split("-", 1)
            out += [f"g{i}" for i in range(int(a[1:]), int(b.lstrip("g")) + 1)]
        else:
            out.append(part)
    return out


def write_results(out: Path, md: Path | None = None) -> Path:
    md = md or Path(out) / "summary.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("# LogicScout bench summary\n\n" + summary_md(Path(out)), encoding="utf-8")
    return md


async def main_async(args: argparse.Namespace) -> int:
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        print(f"unknown arms {unknown}; known: {ARMS}", file=sys.stderr)
        return 2
    variants = parse_variants(args.variants)
    ensure_gate(args.world)
    cls = world_class(args.world)
    manual = manual_of(cls, variants[0])
    objective_id = args.objective or manual.objectives[0].id
    n_cases = min(args.max_cases, len(cases_for(cls, objective_id, variants[0])))
    if "full" in arms and "reasoning_control" in arms:  # reasoning_control reuses the full arm's theory
        arms = ["full"] + [a for a in arms if a != "full"]
    est = {a: estimate_calls(a, manual, n_cases, args.max_steps) for a in arms}
    if "reasoning_control" in arms and "full" not in arms:
        est["reasoning_control"] += estimate_calls("full", manual, n_cases, args.max_steps)
    runs = len(variants) * args.seeds
    print(f"bench: world={args.world} objective={objective_id} variants={len(variants)} seeds={args.seeds} arms={arms}")
    print(f"estimated model calls (upper, rough): {est} per run; total ~{sum(est.values()) * runs}")
    if args.dry_run:
        return 0
    if not set(arms) <= NO_CALL_ARMS and not config.NEBIUS_API_KEY:
        print("NEBIUS_API_KEY is not set. Arms other than no_model/tabular/random/idle make real Nemotron calls "
              "(add it to .env).", file=sys.stderr)
        return 2
    out = Path(args.out)
    shift_after = None if args.shift_after < 0 else args.shift_after
    spent = 0
    for variant in variants:
        for i in range(args.first_index, args.first_index + args.seeds):
            cache: dict = {}
            for arm in arms:
                if args.call_cap is not None and spent + est[arm] > args.call_cap:
                    print(f"[{variant} {arm} seed {i}] skipped: {spent} model calls spent, cap {args.call_cap}")
                    continue
                base = out / args.world / arm / ("" if variant == "standard" else variant)
                d = base / f"seed-{i}"
                d.mkdir(parents=True, exist_ok=True)
                ctx = ArmContext(world_id=args.world, arm=arm, objective_id=objective_id, seed=args.base_seed + i,
                                 index=i, out=d, max_cases=args.max_cases, max_steps=args.max_steps, cache=cache,
                                 variant=variant, shift_after=shift_after, use_briefing=not args.no_briefing)
                t0 = time.perf_counter()
                print(f"[{variant} {arm} seed {i}] running...", flush=True)
                try:
                    row = await run_arm(arm, ctx)
                except Exception as e:
                    row = {"status": "crash", "errors": [f"{type(e).__name__}: {e}"],
                           "traceback": traceback.format_exc()}
                row = {"world": args.world, "variant": variant, "arm": arm, "seed": i, "lab_seed": ctx.seed,
                       "objective_id": objective_id, "shift_after": shift_after,
                       "elapsed_s": round(time.perf_counter() - t0, 1), **row}
                spent += row.get("model_calls") or 0
                (base / f"seed-{i}.json").write_text(json.dumps(row, indent=1, default=str), encoding="utf-8")
                print(f"[{variant} {arm} seed {i}] {row.get('status')} "
                      f"successes={row.get('successes')}/{row.get('n_cases')} calls={row.get('model_calls')} "
                      f"tokens={row.get('tokens')}", flush=True)
    print(f"wrote {write_results(out, Path(args.results) if args.results else None)}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m logicscout.bench", description="LogicScout bench")
    p.add_argument("--world", default="relay")
    p.add_argument("--objective", default=None)
    p.add_argument("--variants", default=None, help="forge systems: 'g101-g120' or 'g101,g107' (default standard)")
    p.add_argument("--seeds", type=int, default=2)
    p.add_argument("--base-seed", type=int, default=7, help="first lab seed; seed i uses base+i")
    p.add_argument("--first-index", type=int, default=0, help="first seed index (to split a run across processes)")
    p.add_argument("--arms", default="full,no_model,model_only,tabular,random,idle")
    p.add_argument("--shift-after", type=int, default=SHIFT_AFTER,
                   help="hidden change after N control steps in mission arms; -1 = none")
    p.add_argument("--no-briefing", action="store_true", help="skip public-knowledge priors in mission arms")
    p.add_argument("--out", default="data/bench")
    p.add_argument("--results", default=None, help="aggregate markdown (default <out>/summary.md)")
    p.add_argument("--max-cases", type=int, default=2, help="referee cases for per-step model arms")
    p.add_argument("--max-steps", type=int, default=25, help="step cap per case for per-step model arms")
    p.add_argument("--call-cap", type=int, default=None,
                   help="skip a run unless spent calls + its estimate stay within this many real model calls")
    p.add_argument("--dry-run", action="store_true", help="print the plan and call estimate, run nothing")
    p.add_argument("--report-only", action="store_true", help="rebuild the summary from existing JSON")
    args = p.parse_args()
    if args.report_only:
        print(f"wrote {write_results(Path(args.out), Path(args.results) if args.results else None)}")
        return
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
