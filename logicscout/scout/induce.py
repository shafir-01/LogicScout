"""Data-driven rule induction: fit simple DSL rules to recorded transitions, one (action, field) at a time.

Generic: it only uses the manual (action/param/field names and types) and the experience itself.
Fitted rules are offered as rival hypotheses; experiments still have to support them.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable

from logicscout.contracts import WorldManual
from logicscout.dsl import safe_evaluate
from logicscout.theory import Transition, _eq

Fn = Callable[[dict, dict, int], Any]
MIN_SAMPLES = 3
MAX_COND_VALUES = 8
PERIODS = range(2, 9)
_VARS = re.compile(r"\b(obs|args|mem|t)\b")


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(round(x, 4))


def _lit(v: Any) -> str:
    return repr(v) if isinstance(v, str) else str(v)


def _mode(xs: list) -> Any:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    try:
        return Counter(xs).most_common(1)[0][0]
    except TypeError:
        return xs[0]


def _safe(fn: Fn) -> Fn:
    def run(o, a, t):
        try:
            return fn(o, a, t)
        except Exception:
            return None
    return run


class _Ctx:
    def __init__(self, manual: WorldManual, samples: list[Transition]):
        self.manual = manual
        self.samples = samples
        self.ftypes = {f.name: f.type for f in manual.observations if f.name != "t"}
        self.numf = [f for f, ty in self.ftypes.items() if ty in ("int", "float")]


def _expressions(ctx: _Ctx, field: str, params: list) -> list[tuple[str, Fn]]:
    S = ctx.samples
    ty = ctx.ftypes[field]
    out: list[tuple[str, Fn]] = [(f"obs.{field}", lambda o, a, t: o.get(field))]
    afters = [s[2].fields.get(field) for s in S]
    c = _mode(afters)
    if c is not None:
        out.append((_lit(c), lambda o, a, t, c=c: c))
    if ty == "bool":
        out.append((f"not obs.{field}", lambda o, a, t: not o.get(field)))
        for p in params:
            for ch in (p.choices or []):
                out.append((f"args.{p.name} == {_lit(ch)}", lambda o, a, t, n=p.name, ch=ch: a.get(n) == ch))
        for g, gty in ctx.ftypes.items():
            if gty == "bool" and g != field:
                out.append((f"obs.{g}", lambda o, a, t, g=g: o.get(g)))
        return out
    if ty == "str":
        for p in params:
            if p.choices:
                out.append((f"args.{p.name}", lambda o, a, t, n=p.name: a.get(n)))
        for g, gty in ctx.ftypes.items():
            if gty == "str" and g != field:
                out.append((f"obs.{g}", lambda o, a, t, g=g: o.get(g)))
        return out
    if ty not in ("int", "float"):
        return out
    deltas = [s[2].fields.get(field) - s[0].fields.get(field) for s in S
              if _num(s[2].fields.get(field)) and _num(s[0].fields.get(field))]
    d = _mode([round(x, 6) for x in deltas])
    lo = min((x for x in afters if _num(x)), default=None)
    hi = max((x for x in afters if _num(x)), default=None)
    if d:
        out.append((f"obs.{field} + {_fmt(d)}", lambda o, a, t, d=d: o[field] + d))
        if lo is not None:
            out.append((f"max(obs.{field} + {_fmt(d)}, {_fmt(lo)})", lambda o, a, t, d=d, lo=lo: max(o[field] + d, lo)))
        if hi is not None:
            out.append((f"min(obs.{field} + {_fmt(d)}, {_fmt(hi)})", lambda o, a, t, d=d, hi=hi: min(o[field] + d, hi)))
    caps = sorted({x for x in deltas if _num(x) and x > 0 and float(x).is_integer()})[:3]
    feats: list[tuple[str, Fn]] = [(f"args.{p.name}", lambda o, a, t, n=p.name: a[n])
                                  for p in params if p.type in ("int", "float")]
    feats += [(f"obs.{g}", lambda o, a, t, g=g: o[g]) for g in ctx.numf if g != field]
    feats.append(("t", lambda o, a, t: t))
    for name, fx in feats:
        out.append((name, fx))
        for k in _ratios(S, field, fx, delta=True):
            sk = "" if k == 1 else ("-" if k == -1 else f"{_fmt(k)} * ")
            if sk == "-":
                out.append((f"obs.{field} - {name}", lambda o, a, t, fx=fx: o[field] - fx(o, a, t)))
            else:
                out.append((f"obs.{field} + {sk}{name}", lambda o, a, t, fx=fx, k=k: o[field] + k * fx(o, a, t)))
        for k in _ratios(S, field, fx, delta=False):
            if k != 1:
                out.append((f"{_fmt(k)} * {name}", lambda o, a, t, fx=fx, k=k: k * fx(o, a, t)))
        if name.startswith("args."):
            for c in caps:  # an effect proportional to the argument but saturating at a capacity
                out.append((f"obs.{field} + min({name}, {_fmt(c)})", lambda o, a, t, fx=fx, c=c: o[field] + min(fx(o, a, t), c)))
                out.append((f"obs.{field} + max({name} - {_fmt(c)}, 0)",
                            lambda o, a, t, fx=fx, c=c: o[field] + max(fx(o, a, t) - c, 0)))
            out.append((f"obs.{field} - min({name}, obs.{field})",
                        lambda o, a, t, fx=fx: o[field] - min(fx(o, a, t), o[field])))
            out.append((f"obs.{field} + min({name}, obs.{field})",
                        lambda o, a, t, fx=fx: o[field] + min(fx(o, a, t), o[field])))
    return [(e, _safe(f)) for e, f in out]


def _ratios(S: list[Transition], field: str, fx: Fn, delta: bool) -> list[float]:
    ks = []
    for b, a, o in S:
        try:
            x = fx(b.fields, a.args, b.t)
            y = o.fields[field] - (b.fields[field] if delta else 0)
        except Exception:
            continue
        if _num(x) and _num(y) and x and y:
            ks.append(round(y / x, 3))
    if not ks:
        return []
    m, c = Counter(ks).most_common(1)[0]
    simple = any(abs(m * q - round(m * q)) < 1e-6 for q in (1, 2, 4))
    return [m] if simple and c >= 2 and c >= 0.25 * len(ks) and abs(m) <= 100 else []


def _conditions(ctx: _Ctx, params: list) -> list[tuple[str, Fn]]:
    S = ctx.samples
    out: list[tuple[str, Fn]] = []
    for p in params:
        if p.choices:
            for ch in p.choices:
                out.append((f"args.{p.name} == {_lit(ch)}", lambda o, a, t, n=p.name, ch=ch: a.get(n) == ch))
        elif p.type in ("int", "float"):
            vals = sorted({s[1].args.get(p.name) for s in S if _num(s[1].args.get(p.name))})
            for v in vals[1:MAX_COND_VALUES]:
                out.append((f"args.{p.name} >= {_fmt(v)}", lambda o, a, t, n=p.name, v=v: a[n] >= v))
    for g, gty in ctx.ftypes.items():
        vals = [s[0].fields.get(g) for s in S]
        if gty == "bool":
            out.append((f"obs.{g}", lambda o, a, t, g=g: bool(o.get(g))))
            continue
        uniq = sorted({v for v in vals if v is not None}, key=lambda v: (str(type(v)), v))
        if gty == "str":
            for v in uniq[:MAX_COND_VALUES]:
                out.append((f"obs.{g} == {_lit(v)}", lambda o, a, t, g=g, v=v: o.get(g) == v))
            continue
        if not all(_num(v) for v in uniq):
            continue
        if not uniq:
            continue
        ends, categorical = (uniq[0], uniq[-1]), len(uniq) <= 4
        if len(uniq) > MAX_COND_VALUES:
            step = len(uniq) / MAX_COND_VALUES
            uniq = [uniq[int(i * step)] for i in range(MAX_COND_VALUES)]
        for v in uniq:
            if categorical or v in ends:  # equality on an arbitrary mid value is usually a coincidence
                out.append((f"obs.{g} == {_fmt(v)}", lambda o, a, t, g=g, v=v: o[g] == v))
            out.append((f"obs.{g} >= {_fmt(v)}", lambda o, a, t, g=g, v=v: o[g] >= v))
            out.append((f"obs.{g} <= {_fmt(v)}", lambda o, a, t, g=g, v=v: o[g] <= v))
    for k in PERIODS:
        for r in range(k):
            out.append((f"(t + 1) % {k} == {r}", lambda o, a, t, k=k, r=r: (t + 1) % k == r))
            if 1 < r:  # a recurring window of r steps out of every k
                out.append((f"t % {k} < {r}", lambda o, a, t, k=k, r=r: t % k < r))
    return [(e, _safe(f)) for e, f in out]


def _correct(fn: Fn, S: list[Transition], field: str) -> list[bool]:
    return [_eq(fn(b.fields, a.args, b.t), o.fields.get(field)) for b, a, o in S]


def fit_field(manual: WorldManual, samples: list[Transition], field: str, params: list) -> list[dict]:
    """Ranked candidate fits for one field: {"expr", "hits", "n"} (best first, deduplicated)."""
    ctx = _Ctx(manual, samples)
    n = len(samples)
    exprs = _expressions(ctx, field, params)
    corr = {e: _correct(f, samples, field) for e, f in exprs}
    fns = dict(exprs)
    scored = sorted(((sum(c), e) for e, c in corr.items()), key=lambda x: -x[0])
    fits = [{"expr": e, "hits": h, "n": n} for h, e in scored[:3]]
    best_h = scored[0][0] if scored else 0
    if best_h < n and n >= MIN_SAMPLES:
        conds = _conditions(ctx, params)
        top = [e for _, e in scored[:4]]
        best = None
        for ce, cf in conds:
            mask = [bool(cf(b.fields, a.args, b.t)) for b, a, _ in samples]
            k = sum(mask)
            if k < 3 or k > n - 2:
                continue
            # residual offset on the condition part, relative to each top expression
            local = dict(corr)
            for e in top:
                res = [(o.fields.get(field) - v) for (b, a, o), m in zip(samples, mask)
                       if m and _num(v := fns[e](b.fields, a.args, b.t)) and _num(o.fields.get(field))]
                c = _mode([round(r, 6) for r in res])
                if c and f"obs.{field}" in e:  # offsets only on the field's own dynamics
                    ex = f"{e} + {_fmt(c)}" if c > 0 else f"{e} - {_fmt(-c)}"
                    if ex not in local:
                        f2 = _safe(lambda o_, a_, t_, e=e, c=c: fns[e](o_, a_, t_) + c)
                        fns[ex] = f2
                        local[ex] = _correct(f2, samples, field)
            in_best = max(local, key=lambda e: sum(c for c, m in zip(local[e], mask) if m))
            out_best = max(corr, key=lambda e: sum(c for c, m in zip(corr[e], mask) if not m))
            in_hits = sum(c for c, m in zip(local[in_best], mask) if m)
            h = in_hits + sum(c for c, m in zip(corr[out_best], mask) if not m)
            if in_best == out_best or in_hits < 3:
                continue
            key = (h, -len(ce))
            if best is None or key > best[0]:
                best = (key, ce, in_best, out_best)
        if best and best[0][0] >= best_h + max(2, 0.1 * n):
            (h, _), ce, ein, eout = best
            fits.insert(0, {"expr": f"({ein}) if {ce} else ({eout})", "hits": h, "n": n})
    seen, out = set(), []
    for f in fits:
        if f["expr"] not in seen:
            seen.add(f["expr"])
            out.append(f)
    return out


def _hits(expr: str, samples: list[Transition], field: str) -> int:
    return sum(_eq(safe_evaluate(expr, {"obs": b.fields, "args": a.args, "mem": {}, "t": b.t}), o.fields.get(field))
               for b, a, o in samples)


def _validated(manual: WorldManual, samples: list[Transition], field: str, params: list) -> list[dict]:
    """Fit on 3/4 of the samples, keep only fits that also beat 'unchanged' on the held-out quarter."""
    if len(samples) < 8:
        return fit_field(manual, samples, field, params)
    train = [x for i, x in enumerate(samples) if i % 4 != 3]
    hold = [x for i, x in enumerate(samples) if i % 4 == 3]
    base = sum(_eq(b.fields.get(field), o.fields.get(field)) for b, _, o in hold)
    out = []
    for f in fit_field(manual, train, field, params):
        h = _hits(f["expr"], hold, field)
        if h > base or (h == base == len(hold)):
            out.append({"expr": f["expr"], "hits": _hits(f["expr"], samples, field), "n": len(samples),
                        "held_out": f"{h}/{len(hold)}"})
    return sorted(out, key=lambda x: -x["hits"])


def induce(manual: WorldManual, transitions: list[Transition], min_gain: int = 2) -> list[dict]:
    """Candidate rules per (action, field) that beat 'unchanged' by at least `min_gain` steps.
    Each item: {"action", "field", "fits": [{"expr", "hits", "n"}...], "unchanged": hits}."""
    out = []
    fields = [f.name for f in manual.observations if f.name != "t"]
    by_action: dict[str, list[Transition]] = {}
    for tr in transitions:
        by_action.setdefault(tr[1].name, []).append(tr)
    specs = {a.name: a for a in manual.actions}
    groups = [("*", "True", transitions, [])]
    for a, S in by_action.items():
        params = specs[a].params if a in specs else []
        groups.append((a, "True", S, params))
        for p in params:  # one sub-population per choice of a small enum argument (e.g. which link)
            if p.choices and 1 < len(p.choices) <= 4:
                for ch in p.choices:
                    sub = [x for x in S if x[1].args.get(p.name) == ch]
                    rest = [q for q in params if q.name != p.name]
                    groups.append((a, f"args.{p.name} == {_lit(ch)}", sub, rest))
    for action, when, samples, params in groups:
        if len(samples) < MIN_SAMPLES:
            continue
        for f in fields:
            same = sum(_eq(b.fields.get(f), o.fields.get(f)) for b, _, o in samples)
            if same == len(samples):
                continue
            fits = _validated(manual, samples, f, params)
            fits = [x for x in fits if x["hits"] >= same + min_gain and not x["expr"] == f"obs.{f}"]
            if fits:
                out.append({"action": action, "when": when, "field": f, "fits": fits, "unchanged": same})
    return out


def change_stats(manual: WorldManual, transitions: list[Transition], limit: int = 40) -> list[str]:
    """Compact per-action, per-field change summary: how often a field changed and its common deltas."""
    lines = []
    by_action: dict[str, list[Transition]] = {}
    for tr in transitions:
        by_action.setdefault(tr[1].name, []).append(tr)
    fields = [f.name for f in manual.observations if f.name != "t"]
    for a, S in sorted(by_action.items()):
        for f in fields:
            ch = [(b.fields.get(f), o.fields.get(f)) for b, _, o in S if not _eq(b.fields.get(f), o.fields.get(f))]
            if not ch:
                continue
            if all(_num(x) and _num(y) for x, y in ch):
                desc = ", ".join(f"{'+' if d > 0 else ''}{_fmt(d)} x{c}" for d, c in
                                 Counter(round(y - x, 4) for x, y in ch).most_common(4))
            else:
                desc = ", ".join(f"{x!r}->{y!r} x{c}" for (x, y), c in Counter(
                    (str(x), str(y)) for x, y in ch).most_common(3))
            lines.append(f"{a}: {f} changed {len(ch)}/{len(S)} steps ({desc})")
    return lines[:limit]
