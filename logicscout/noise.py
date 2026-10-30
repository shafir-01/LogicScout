"""Noisy readings: estimate per-field measurement noise from experience, score theories with per-field
tolerances, and a wrapper port that adds seeded sensor noise to any world (for testing, not for the scout).

The default comparison in `theory.compare` stays exact-ish (1e-6 absolute or 2% relative). Here the
tolerance is per field and comes from the data: a field whose readings jitter gets a band proportional
to its own estimated noise, a clean field gets none.
"""
from __future__ import annotations

import math
import statistics
import zlib
from typing import Any

from logicscout.contracts import Action, Observation, StepResult, Theory, WorldManual
from logicscout.theory import Transition, _replay, compare

_Q = 0.25  # quantile of |delta| used by the persistence estimator
_Z_Q = 0.3186  # z with 2*Phi(z) - 1 = _Q (quantile of a half-normal)
_MIN_PAIRS = 5  # repeated-context residuals needed before that estimator is trusted
_EXACT_FRAC = 0.10  # this share of exactly-unchanged steps means the field reads cleanly


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def _numeric_fields(transitions: list[Transition]) -> list[str]:
    seen: dict[str, bool] = {}
    for _, _, after in transitions:
        for f, v in after.fields.items():
            if f != "t":
                seen[f] = seen.get(f, True) and _num(v)
    return [f for f, ok in seen.items() if ok]


def _ctx_key(before: Observation, action: Action) -> str:
    fields = {k: (round(v, 6) if _num(v) else v) for k, v in before.fields.items() if k != "t"}
    return repr((action.name, sorted((action.args or {}).items()), sorted(fields.items(), key=lambda x: x[0])))


def _context_sigmas(transitions: list[Transition], fields: list[str]) -> dict[str, tuple[float, int]]:
    """Pooled within-group std of the next reading over repeated identical (obs, action) contexts.
    Returns {field: (sigma, degrees of freedom)}."""
    groups: dict[str, list[dict]] = {}
    for before, action, after in transitions:
        groups.setdefault(_ctx_key(before, action), []).append(after.fields)
    out: dict[str, tuple[float, int]] = {}
    for f in fields:
        ss, dof = 0.0, 0
        for afters in groups.values():
            xs = [a[f] for a in afters if _num(a.get(f))]
            if len(xs) < 2:
                continue
            m = sum(xs) / len(xs)
            ss += sum((x - m) ** 2 for x in xs)
            dof += len(xs) - 1
        if dof:
            out[f] = (math.sqrt(ss / dof), dof)
    return out


_MIN_GROUP = 8  # steps under one action needed for a per-action persistence estimate


def _quietest_sigma(transitions: list[Transition], field: str) -> float:
    """Persistence estimate pooled across actions: the median of the all-steps estimate and one estimate
    per action with enough steps. Actions under which the field should not move (e.g. 'wait') pull it
    toward the pure noise; the median keeps one small, lucky group from dragging it too low."""
    by_action: dict[str, list[Transition]] = {}
    for tr in transitions:
        by_action.setdefault(tr[1].name, []).append(tr)
    ests = [_persistence_sigma(S, field) for S in by_action.values() if len(S) >= _MIN_GROUP]
    whole = _persistence_sigma(transitions, field)
    return statistics.median([whole, *ests]) if whole > 0 else 0.0


def _persistence_sigma(transitions: list[Transition], field: str) -> float:
    """Noise from step-to-step deltas. If enough steps leave the reading exactly unchanged the field is
    clean (sigma 0). Otherwise the smallest deltas are taken to be quiet steps, where the delta is the
    difference of two noisy readings (std sqrt(2) * sigma); a low quantile of |delta| is inverted through
    the half-normal. Biased low when the field changes on most steps by less than the noise."""
    ds = [abs(a.fields[field] - b.fields[field]) for b, _, a in transitions
          if _num(b.fields.get(field)) and _num(a.fields.get(field))]
    if not ds:
        return 0.0
    if sum(d <= 1e-9 for d in ds) >= _EXACT_FRAC * len(ds):
        return 0.0
    ds.sort()
    q = ds[min(len(ds) - 1, int(_Q * len(ds)))]
    return q / (_Z_Q * math.sqrt(2))


def estimate_noise(transitions: list[Transition]) -> dict[str, float]:
    """{numeric field: estimated per-reading noise std}. Uses repeated identical (obs, action) contexts
    when there are enough of them (they isolate noise from dynamics), else persistence residuals."""
    fields = _numeric_fields(transitions)
    ctx = _context_sigmas(transitions, fields)
    out = {}
    for f in fields:
        if f in ctx and ctx[f][1] >= _MIN_PAIRS:
            out[f] = ctx[f][0]
        else:
            out[f] = _quietest_sigma(transitions, f)
    return {f: round(s, 6) for f, s in out.items()}


def tolerances(sigmas: dict[str, float], k: float = 2.0) -> dict[str, float]:
    """Per-field absolute tolerance. A prediction computed from a noisy reading, compared with another
    noisy reading, has residual std about sqrt(2) * sigma, so the band is k * sqrt(2) * sigma."""
    return {f: k * math.sqrt(2) * s for f, s in sigmas.items() if s > 0}


def noisy_accuracy(theory: Theory, transitions: list[Transition], tol: dict[str, float] | None) -> float:
    """Like theory.accuracy, but numeric fields within their per-field tolerance count as correct."""
    total = correct = 0
    for _, p, after in _replay(theory, transitions):
        fields = [f for f in after.fields if f != "t"]
        total += len(fields)
        correct += len(fields) - len(compare(p, after.fields, tol=tol))
    return correct / total if total else 0.0


def noisy_persistence(transitions: list[Transition], tol: dict[str, float] | None) -> float:
    """Persistence baseline ('nothing changes') under the same per-field tolerances."""
    total = correct = 0
    for before, _, after in transitions:
        fields = [f for f in after.fields if f != "t"]
        total += len(fields)
        correct += len(fields) - len(compare(before.fields, after.fields, tol=tol))
    return correct / total if total else 0.0


class NoisyPort:
    """Wraps a WorldPort and adds zero-mean Gaussian noise (std `sigma`) to every numeric observation
    field except `t`. The world itself is untouched; only the readings are noisy. Noise is a pure function
    of (noise seed, episode seed, t, field), so the same reading is returned however often it is observed
    and a run is exactly reproducible."""

    def __init__(self, port: Any, sigma: float, seed: int = 0, fields: list[str] | None = None) -> None:
        self._port = port
        self.sigma = float(sigma)
        self.seed = int(seed)
        self.fields = set(fields) if fields else None
        self._episode = 0

    def manual(self) -> WorldManual:
        return self._port.manual()

    def _noise(self, t: int, field: str) -> float:
        import random

        return random.Random(zlib.crc32(f"{self.seed}:{self._episode}:{t}:{field}".encode())).gauss(0.0, self.sigma)

    def _wrap(self, obs: Observation) -> Observation:
        if self.sigma <= 0:
            return obs
        fields = dict(obs.fields)
        for f, v in fields.items():
            if f == "t" or not _num(v) or (self.fields is not None and f not in self.fields):
                continue
            fields[f] = round(v + self._noise(obs.t, f), 4)
        return obs.model_copy(update={"fields": fields})

    def reset(self, seed: int) -> Observation:
        self._episode = int(seed)
        return self._wrap(self._port.reset(seed))

    def observe(self) -> Observation:
        return self._wrap(self._port.observe())

    def act(self, action: Action) -> StepResult:
        res = self._port.act(action)
        return res.model_copy(update={"observation": self._wrap(res.observation)})


def residual_spread(theory: Theory, transitions: list[Transition]) -> dict[str, float]:
    """{numeric field: median |prediction - reading|} for reporting raw numerical error."""
    res: dict[str, list[float]] = {}
    for _, p, after in _replay(theory, transitions):
        for f, o in after.fields.items():
            if f != "t" and _num(o) and _num(p.get(f)):
                res.setdefault(f, []).append(abs(p[f] - o))
    return {f: round(statistics.median(v), 4) for f, v in res.items() if v}
