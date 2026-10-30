"""Bench statistics: Wilson intervals and per-arm aggregation of per-seed JSON rows."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n (n=0 gives the uninformative 0..1)."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k} n={n}")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def load_rows(out: Path) -> list[dict[str, Any]]:
    rows = []
    for f in sorted(Path(out).rglob("seed-*.json")):
        try:
            rows.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per (world, arm): runs, held-out cases, successes, rate, Wilson CI, calls, tokens per success."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["world"], r["arm"]), []).append(r)
    out = []
    for (world, arm), rs in sorted(groups.items()):
        ok = [r for r in rs if r.get("status") == "ok" and "n_cases" in r]
        n = sum(r["n_cases"] for r in ok)
        k = sum(r["successes"] for r in ok)
        lo, hi = wilson(k, n)
        calls = sum(r.get("model_calls") or 0 for r in ok)
        tokens = sum(r.get("tokens") or 0 for r in ok)
        out.append({
            "world": world, "arm": arm, "runs": len(rs), "runs_ok": len(ok),
            "systems": len({r.get("variant", "standard") for r in ok}),
            "n_cases": n, "successes": k, "rate": k / n if n else None, "ci_low": lo, "ci_high": hi,
            "model_calls": calls, "tokens": tokens,
            "tokens_per_success": tokens / k if k else None, "calls_per_success": calls / k if k else None,
            "probes_mean": _mean([r.get("probes_used") for r in ok]),
            "pred_acc_mean": _mean([r.get("prediction_accuracy") for r in ok]),
            "persistence_mean": _mean([r.get("persistence_accuracy") for r in ok]),
        })
    return out


def drift_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        d = r.get("drift_metrics")
        if r.get("status") == "ok" and d:
            groups.setdefault((r["world"], r["arm"]), []).append(d)
    out = []
    for (world, arm), ds in sorted(groups.items()):
        shifted = [d for d in ds if d["shift_applied"]]
        det = [d for d in shifted if d["detected"]]
        rec = [d for d in shifted if d["recovered"]]
        out.append({
            "world": world, "arm": arm, "runs": len(ds), "shifted": len(shifted),
            "false_alarms": sum(d["false_alarms_before_shift"] for d in ds),
            "runs_with_false_alarm": sum(d["false_alarms_before_shift"] > 0 for d in ds),
            "steps_before_shift": sum(d["control_steps_before_shift"] for d in ds),
            "detected": len(det), "detect_ci": wilson(len(det), len(shifted)),
            "delay_median": _median([d["detection_delay_steps"] for d in det]),
            "delays": sorted(d["detection_delay_steps"] for d in det),
            "recovered": len(rec), "recover_ci": wilson(len(rec), len(shifted)),
            "recovery_median": _median([d["recovery_steps"] for d in rec if d["recovery_steps"] is not None]),
        })
    return out


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def _median(xs: list) -> float | None:
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    m = len(xs) // 2
    return float(xs[m]) if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _f(v: Any, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def arm_table(rows: list[dict[str, Any]]) -> str:
    lines = ["| world | arm | runs (ok) | systems | held-out cases n | successes | rate | 95% Wilson CI | "
             "probes (mean) | pred acc / persistence | model calls | tokens | tokens per success |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in aggregate(rows):
        lines.append(
            f"| {a['world']} | {a['arm']} | {a['runs']} ({a['runs_ok']}) | {a['systems']} | {a['n_cases']} | "
            f"{a['successes']} | {_f(a['rate'])} | [{a['ci_low']:.2f}, {a['ci_high']:.2f}] | {_f(a['probes_mean'], 0)} | "
            f"{_f(a['pred_acc_mean'])} / {_f(a['persistence_mean'])} | {a['model_calls']} | {a['tokens']:,} | "
            f"{_f(a['tokens_per_success'], 0) if a['tokens'] else '0'} |")
    return "\n".join(lines)


def drift_table(rows: list[dict[str, Any]]) -> str:
    lines = ["| world | arm | runs | change applied | false alarms before change (runs with any) | control steps "
             "before change | detected (95% CI) | detection delay, steps (median; all) | recovered (95% CI) | "
             "recovery time, steps (median) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for d in drift_summary(rows):
        lines.append(
            f"| {d['world']} | {d['arm']} | {d['runs']} | {d['shifted']} | {d['false_alarms']} ({d['runs_with_false_alarm']}) | "
            f"{d['steps_before_shift']} | {d['detected']}/{d['shifted']} [{d['detect_ci'][0]:.2f}, {d['detect_ci'][1]:.2f}] | "
            f"{_f(d['delay_median'], 1)}; {d['delays']} | {d['recovered']}/{d['shifted']} "
            f"[{d['recover_ci'][0]:.2f}, {d['recover_ci'][1]:.2f}] | {_f(d['recovery_median'], 1)} |")
    return "\n".join(lines)


def seed_table(rows: list[dict[str, Any]]) -> str:
    lines = ["| world | system | arm | seed | status | successes / n | probes | model calls | tokens | playbook | "
             "detected / delay / recovered |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["world"], r.get("variant", ""), r["arm"], r["seed"])):
        d = r.get("drift_metrics") or {}
        dr = (f"{'yes' if d.get('detected') else 'no'} / {_f(d.get('detection_delay_steps'))} / "
              f"{'yes' if d.get('recovered') else 'no'}") if d.get("shift_applied") else "-"
        lines.append(f"| {r['world']} | {r.get('variant', 'standard')} | {r['arm']} | {r['seed']} | {r.get('status')} | "
                     f"{r.get('successes', '-')} / {r.get('n_cases', '-')} | {_f(r.get('probes_used'))} | "
                     f"{_f(r.get('model_calls'))} | {_f(r.get('tokens'))} | {r.get('playbook_origin') or '-'} | {dr} |")
    return "\n".join(lines)


def summary_md(out: Path) -> str:
    rows = load_rows(out)
    rows = [r for r in rows if "n_cases" in r or r.get("status") != "ok"]
    return "\n\n".join(["## Per-arm", arm_table(rows), "## Hidden change", drift_table(rows),
                        "## Per-seed rows", seed_table(rows)]) + "\n"
