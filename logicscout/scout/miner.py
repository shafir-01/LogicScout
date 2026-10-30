"""Deterministic candidate-rule miner: data-grounded rivals for the investigator.

Looks only at the manual and recorded transitions. For each (field, action, delay) it fits simple
templates to what the current theory gets wrong, guards them with one discovered condition (another
field, an argument, time periodicity or a cooldown), and keeps only candidates that raise held-out
accuracy when added to the theory and replayed through theory.Predictor.
"""
from __future__ import annotations

import keyword
import re
import time
import zlib
from collections import Counter
from itertools import combinations
from typing import Any, Callable

from logicscout import dsl
from logicscout.contracts import Rule, Theory, WorldManual
from logicscout.theory import Predictor, Transition, _eq, _same, validate_theory

MAX_DELAY = 4
PERIODS = range(2, 13)
COOLDOWNS = range(2, 9)
MAX_THRESHOLDS = 6
MAX_EQ_VALUES = 6
MIN_TRAIN_GAIN = 2
MIN_HELDOUT_GAIN = 2  # held-out (step, field) pairs a candidate must fix beyond the current theory
STRONG_TRAIN_GAIN = 4  # ...or 1 held-out pair when the training gain is at least this
VERIFY = 40  # candidates replayed through the Predictor
TIME_BUDGET = 1.6
FAR = -1000

Fn = Callable[[dict, dict, int], Any]


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _fmt(x: Any) -> str:
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return repr(x)
    if float(x).is_integer():
        return str(int(x))
    return repr(round(float(x), 4))


def _snap(x: float) -> float:
    r = round(x)
    return int(r) if abs(x - r) < 1e-6 else round(x, 4)


def _ref(root: str, name: str) -> str:
    if name.isidentifier() and not keyword.iskeyword(name) and not name.startswith("_"):
        return f"{root}.{name}"
    return f"{root}[{name!r}]"


def _heldout(i: int) -> bool:
    return zlib.crc32(f"split{i}".encode()) % 10 < 3


def _safe(fn: Fn) -> Fn:
    def run(o, a, t):
        try:
            return fn(o, a, t)
        except Exception:
            return None
    return run


def _mask(bits) -> int:
    m = 0
    for k, b in enumerate(bits):
        if b:
            m |= 1 << k
    return m


class _Data:
    def __init__(self, manual: WorldManual, transitions: list[Transition], theory: Theory):
        self.manual = manual
        self.tr = transitions
        self.n = len(transitions)
        self.ftypes = {f.name: f.type for f in manual.observations if f.name != "t"}
        self.ep: list[int] = []
        prev = None
        e = -1
        for b, _, o in transitions:
            if prev is None or b.t != prev.t or not _same(b.fields, prev.fields):
                e += 1
            self.ep.append(e)
            prev = o
        self.test = [_heldout(i) for i in range(self.n)]
        self.base = _predictions(theory, transitions)
        self.ok = [{f: _eq(p.get(f), o.fields.get(f)) for f in o.fields if f != "t"}
                   for p, (_, _, o) in zip(self.base, transitions)]


def _predictions(theory: Theory, transitions: list[Transition]) -> list[dict]:
    out: list[dict] = []
    pred: Predictor | None = None
    prev = None
    for b, a, o in transitions:
        if pred is None or prev is None or b.t != prev.t or not _same(b.fields, prev.fields):
            pred = Predictor(theory)
            pred.reset(b)
        try:
            out.append(pred.predict(b, a))
            pred.advance(o)
        except Exception:
            out.append(dict(b.fields))
        prev = o
    return out


def _heldout_correct(theory: Theory, d: _Data) -> int:
    n = 0
    for i, (p, (_, _, o)) in enumerate(zip(_predictions(theory, d.tr), d.tr)):
        if d.test[i]:
            n += sum(1 for f, v in o.fields.items() if f != "t" and _eq(p.get(f), v))
    return n


# ---------------------------------------------------------------------------------- templates

def _effects(d: _Data, field: str, pos: list[tuple[int, int]], resid: list[int], params) -> list[tuple[str, Fn, int]]:
    """Candidate next-value expressions for `field`, fitted on residual positions (train, base wrong)."""
    tr = d.tr
    fr = _ref("obs", field)
    ys = [tr[pos[k][1]][2].fields.get(field) for k in resid]
    befores = [tr[pos[k][0]][0] for k in resid]
    argses = [tr[pos[k][0]][1].args for k in resid]
    out: list[tuple[str, Fn, int]] = []
    ty = d.ftypes.get(field)

    def top(vals, n=2, min_count=2):
        vals = [v for v in vals if v is not None and _scalar(v)]
        return [v for v, c in Counter(vals).most_common(n) if c >= min_count]

    for c in top(ys, 3):
        out.append((_fmt(c), lambda o, a, t, c=c: c, 1))
    if ty == "bool" or all(isinstance(y, bool) for y in ys if y is not None):
        out.append((f"not {fr}", lambda o, a, t: not o.get(field), 2))
    numeric = [(b.fields.get(field), y) for b, y in zip(befores, ys) if _num(b.fields.get(field)) and _num(y)]
    linear: list[tuple[str, Fn]] = []
    if numeric:
        for c in top([_snap(y - x) for x, y in numeric]):
            if c != 0:
                linear.append((f"{fr} + {_fmt(c)}" if c > 0 else f"{fr} - {_fmt(-c)}",
                               lambda o, a, t, c=c: o[field] + c))
        for c in top([_snap(y / x) for x, y in numeric if x != 0]):
            if c not in (0, 1):
                linear.append((f"{fr} * {_fmt(c)}", lambda o, a, t, c=c: o[field] * c))
    for p in params:
        if p.type not in ("int", "float"):
            if p.choices or p.type == "str":
                if sum(1 for a, y in zip(argses, ys) if a.get(p.name) == y) >= 2:
                    ar = _ref("args", p.name)
                    out.append((ar, lambda o, a, t, n=p.name: a[n], 2))
            continue
        ar = _ref("args", p.name)
        for direct in (False, True):
            pts = []
            for b, a, y in zip(befores, argses, ys):
                x, v = b.fields.get(field), a.get(p.name)
                if _num(v) and _num(y) and (direct or _num(x)):
                    pts.append((v, y if direct else y - x))
            fits: Counter = Counter()
            for (a1, y1), (a2, y2) in list(combinations(pts, 2))[:80]:
                if a1 != a2:
                    k = _snap((y2 - y1) / (a2 - a1))
                    fits[(k, _snap(y1 - k * a1))] += 1
            for (k, c), _ in fits.most_common(2):
                if k == 0:
                    continue
                term = ar if k == 1 else f"{_fmt(k)} * {ar}"
                head = term if direct else f"{fr} + {term}"
                expr = head if c == 0 else (f"{head} + {_fmt(c)}" if c > 0 else f"{head} - {_fmt(-c)}")
                fn = (lambda o, a, t, n=p.name, k=k, c=c: k * a[n] + c) if direct else \
                     (lambda o, a, t, n=p.name, k=k, c=c: o[field] + k * a[n] + c)
                linear.append((expr, fn))
    for g, gty in d.ftypes.items():
        if g == field:
            continue
        gr = _ref("obs", g)
        if gty in ("int", "float") and numeric:
            diffs = [_snap(y - b.fields[g]) for b, y in zip(befores, ys) if _num(y) and _num(b.fields.get(g))]
            for c in top(diffs, 1):
                expr = gr if c == 0 else (f"{gr} + {_fmt(c)}" if c > 0 else f"{gr} - {_fmt(-c)}")
                linear.append((expr, lambda o, a, t, g=g, c=c: o[g] + c))
        elif gty in ("str", "bool") and sum(1 for b, y in zip(befores, ys) if b.fields.get(g) == y) >= 2:
            out.append((gr, lambda o, a, t, g=g: o.get(g), 2))
    out += [(e, f, 2) for e, f in linear]
    allys = [tr[j][2].fields.get(field) for i, j in pos if not d.test[j]]
    nums = [y for y in allys if _num(y)]
    if nums and linear:
        hi, lo = max(nums), min(nums)
        for e, f in linear[:4]:
            if nums.count(hi) >= 2:
                out.append((f"min({e}, {_fmt(hi)})", lambda o, a, t, f=f, hi=hi: min(f(o, a, t), hi), 3))
            if nums.count(lo) >= 2:
                out.append((f"max({e}, {_fmt(lo)})", lambda o, a, t, f=f, lo=lo: max(f(o, a, t), lo), 3))
    seen, uniq = set(), []
    for e, f, cx in out:
        if e not in seen:
            seen.add(e)
            uniq.append((e, _safe(f), cx))
    return uniq


# ---------------------------------------------------------------------------------- conditions

def _conditions(d: _Data, pos: list[tuple[int, int]], params, action: str) -> list[tuple[str, int, int, str]]:
    """(dsl, mask over positions, complexity, kind) guards evaluated on the BEFORE state."""
    tr = d.tr
    out: list[tuple[str, int, int, str]] = [("True", (1 << len(pos)) - 1, 0, "always")]

    def add_feature(ref: str, vals: list):
        if not all(_scalar(v) for v in vals):
            return
        distinct = sorted({v for v in vals if v is not None}, key=lambda v: (type(v).__name__, v))
        if len(distinct) < 2:
            return
        if len(distinct) <= MAX_EQ_VALUES:
            for v in distinct:
                out.append((f"{ref} == {_fmt(v)}", _mask(x == v and type(x) is type(v) for x in vals), 1, "eq"))
                if len(distinct) > 2:
                    out.append((f"{ref} != {_fmt(v)}", _mask(not (x == v and type(x) is type(v)) for x in vals),
                                1, "eq"))
        nums = [v for v in distinct if _num(v)]
        if len(nums) >= 2:
            mids = [(a + b) / 2 for a, b in zip(nums, nums[1:])]
            step = max(1, len(mids) // MAX_THRESHOLDS)
            for th in mids[::step][:MAX_THRESHOLDS + 1]:
                th = _snap(th)
                out.append((f"{ref} > {_fmt(th)}", _mask(_num(x) and x > th for x in vals), 1, "cmp"))
                out.append((f"{ref} <= {_fmt(th)}", _mask(_num(x) and x <= th for x in vals), 1, "cmp"))

    for g in d.ftypes:
        add_feature(_ref("obs", g), [tr[i][0].fields.get(g) for i, _ in pos])
    if action != "*":
        for p in params:
            add_feature(_ref("args", p.name), [tr[i][1].args.get(p.name) for i, _ in pos])
    return out


def _cooldowns(d: _Data, pos: list[tuple[int, int]], action: str) -> list[tuple[str, int, int, str, int]]:
    """Masks for 'at least k steps since the last <action>' (attempt / effective-use semantics)."""
    tr = d.tr
    index = {i: k for k, (i, _) in enumerate(pos)}
    out = []
    for k in COOLDOWNS:
        for success in (False, True):
            bits = [False] * len(pos)
            last, ep = None, -1
            for i, (b, a, _) in enumerate(tr):
                if d.ep[i] != ep:
                    ep, last = d.ep[i], None
                if a.name != action:
                    continue
                ok = last is None or b.t - last >= k
                if i in index:
                    bits[index[i]] = ok
                if ok or not success:
                    last = b.t
            out.append(("success" if success else "attempt", _mask(bits), 3, "cool", k))
    return out


# ---------------------------------------------------------------------------------- mining

def _statement(field: str, action: str, expr: str, guard: str, delay: int) -> str:
    where = "every step" if action == "*" else f"'{action}'"
    lag = f", taking effect {delay} step{'s' if delay > 1 else ''} later" if delay else ""
    return f"After {where}{guard}, {field} becomes {expr}{lag} (mined from experience)"


def _build(field: str, action: str, delay: int, expr: str, cond: tuple) -> Rule:
    kind = "delay" if delay else "transition"
    guard = ""
    when = "True"
    memory: dict[str, str] = {}
    effect = expr
    ckind = cond[3]
    if ckind == "cool":
        sem, k = cond[0], cond[4]
        var = re.sub(r"\W", "_", f"mined_{action}_{'ok' + str(k) if sem == 'success' else 'last'}")
        mv = _ref("mem", var)
        ready = f"t - ({mv} if {mv} is not None else {FAR}) >= {k}"
        effect = f"({expr}) if {ready} else {_ref('obs', field)}"
        memory = {var: f"t if {ready} else {mv}" if sem == "success" else "t"}
        kind = "precondition"
        guard = f" when at least {k} steps have passed since the last " + \
                ("effective " if sem == "success" else "") + f"'{action}'"
    elif ckind == "always":
        pass
    else:
        when = cond[0]
        if ckind == "periodic":
            kind = "periodic"
            guard = f" on steps where {when}"
        else:
            guard = f" when {when}"
    return Rule(id="M?", statement=_statement(field, action, expr, guard, delay), kind=kind, action=action,
                when=when, effects={field: effect}, memory=memory, delay=delay, status="tentative",
                confidence=0.5, source="probe")


def _periodic(pos: list[tuple[int, int]], d: _Data, gain_bits: tuple[int, int, int]) -> list[tuple[str, int, int, str]]:
    """Best residue window per period for this effect: residues where it beats the theory on train."""
    C, B, TR = gain_bits
    ts = [d.tr[i][0].t for i, _ in pos]
    out = []
    for p in PERIODS:
        keep = []
        for r in range(p):
            m = _mask(t % p == r for t in ts) & TR
            if m and (C & m).bit_count() > (B & m).bit_count():
                keep.append(r)
        if not keep or len(keep) == p:
            continue
        if keep == list(range(len(keep))):
            expr, cx = f"t % {p} < {len(keep)}", 2
        elif keep == list(range(keep[0], p)):
            expr, cx = f"t % {p} >= {keep[0]}", 2
        else:
            expr, cx = f"t % {p} in [{', '.join(map(str, keep))}]", 2 + len(keep)
        out.append((expr, _mask(t % p in keep for t in ts), cx, "periodic"))
    return out


def mine(manual: WorldManual, transitions: list[Transition], theory: Theory, max_rules: int = 12) -> list[Rule]:
    """Data-grounded candidate rules that improve held-out accuracy over `theory`, ranked by gain."""
    start = time.perf_counter()
    if len(transitions) < 6:
        return []
    d = _Data(manual, transitions, theory)
    if not any(d.test) or all(d.test):
        return []
    params = {a.name: a.params for a in manual.actions}
    actions = ["*"] + [a.name for a in manual.actions]
    fields = [f for f in d.ftypes]
    pool: list[tuple] = []
    for action in actions:
        for delay in range(0, MAX_DELAY + 1 if action != "*" else 1):
            pos = [(i, i + delay) for i in range(d.n)
                   if (action == "*" or d.tr[i][1].name == action) and i + delay < d.n and d.ep[i + delay] == d.ep[i]]
            if len(pos) < 3:
                continue
            TR = _mask(not d.test[j] for _, j in pos)
            TE = _mask(d.test[j] for _, j in pos)
            conds = None
            for field in fields:
                okv = [d.ok[j].get(field, True) for _, j in pos]
                B = _mask(okv)
                resid = [k for k, (_, j) in enumerate(pos) if not okv[k] and not d.test[j]]
                if len(resid) < MIN_TRAIN_GAIN:
                    continue
                if conds is None:
                    conds = _conditions(d, pos, params.get(action, []), action)
                    cools = _cooldowns(d, pos, action) if action != "*" and delay == 0 else []
                for expr, fn, ecx in _effects(d, field, pos, resid, params.get(action, [])):
                    C = _mask(_eq(fn(d.tr[i][0].fields, d.tr[i][1].args, d.tr[i][0].t), d.tr[j][2].fields.get(field))
                              for i, j in pos)
                    if (C & ~B & TR).bit_count() < MIN_TRAIN_GAIN:
                        continue
                    best = []
                    for cond in conds + _periodic(pos, d, (C, B, TR)) + cools:
                        K = cond[1]
                        g_tr = (K & C & TR).bit_count() - (K & B & TR).bit_count()
                        if g_tr < MIN_TRAIN_GAIN:
                            continue
                        g_te = (K & C & TE).bit_count() - (K & B & TE).bit_count()
                        best.append((g_tr, g_te, -(ecx + cond[2] + delay), cond))
                    best.sort(key=lambda x: (-x[0], -x[2]))
                    for g_tr, g_te, ncx, cond in best[:2]:
                        pool.append((g_te, g_tr, ncx, field, action, delay, expr, cond))
            if time.perf_counter() - start > TIME_BUDGET / 2:
                break
    pool.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3], x[4], x[5], x[6], x[7][0]))
    base_correct = _heldout_correct(theory, d)
    kept: list[tuple[int, int, Rule]] = []
    seen: set = set()
    for g_te, g_tr, ncx, field, action, delay, expr, cond in pool[:VERIFY]:
        if time.perf_counter() - start > TIME_BUDGET:
            break
        need = 1 if g_tr >= STRONG_TRAIN_GAIN else MIN_HELDOUT_GAIN
        if g_te < need:
            continue
        rule = _build(field, action, delay, expr, cond)
        sig = (rule.action, rule.when, tuple(rule.effects.items()), tuple(rule.memory.items()), rule.delay)
        if sig in seen or _invalid(rule, theory, manual):
            continue
        seen.add(sig)
        cand = theory.model_copy(deep=True)
        cand.rules = sorted(cand.rules + [rule], key=lambda r: r.action != "*")
        gain = _heldout_correct(cand, d) - base_correct
        if gain >= need:
            kept.append((gain, ncx, rule))
    kept.sort(key=lambda x: (-x[0], -x[1]))
    # equally good rivals for the same (field, action, delay) are indistinguishable on data: keep the simplest
    distinct, slots = [], set()
    for gain, ncx, rule in kept:
        slot = (tuple(rule.effects), rule.action, rule.delay, gain)
        if slot not in slots:
            slots.add(slot)
            distinct.append((gain, ncx, rule))
    out = []
    for n, (gain, _, rule) in enumerate(distinct[:max_rules], 1):
        rule.id = f"M{n}"
        rule.confidence = round(min(0.9, 0.5 + gain / max(1, sum(d.test) * len(fields))), 3)
        out.append(rule)
    return out


def _invalid(rule: Rule, theory: Theory, manual: WorldManual) -> bool:
    exprs = [rule.when, *rule.effects.values(), *rule.memory.values()]
    if any(dsl.validate(e) for e in exprs):
        return True
    t = theory.model_copy(deep=True)
    t.rules = [r for r in t.rules if r.id != rule.id] + [rule]
    return bool(validate_theory(t, manual))
