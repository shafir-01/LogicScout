"""Evidence-based detection of hidden change.

Every control step yields a surprise score: each mispredicted field counts with the confidence of the
rules that predicted it (a well-supported rule failing is strong evidence; a field no rule covers counts
as moderate evidence). Three detectors run on prediction errors only (no timers, no outside signals):
  - fast: a sliding window rate and a one-sided CUSUM of the surprise stream against a reference level,
    plus "the same trusted rule failed repeatedly in the window while it rarely failed before";
  - slow: one Bernoulli CUSUM per rule (or uncovered field) on its failure rate. Each key's reference
    failure rate is learned on the first `reference` control steps and then frozen, so a change that
    arrives gradually cannot be absorbed into what counts as normal. A key that was already unreliable
    must fail clearly more often than before (an imperfect theory is not evidence of change).
"suspected" when the window rate exceeds the reference plus a margin; "confirmed" when any detector
fires. The reference level is fixed after the reference period: it is never pulled toward the stream
while a change may be under way. The slow detector needs `correct` keys (the mission passes them).
"""
from __future__ import annotations

import math
from collections import Counter, deque
from typing import Literal

from logicscout.contracts import Mismatch, Theory

Status = Literal["ok", "suspected", "confirmed"]
UNCOVERED_WEIGHT = 0.5
PROVEN = 2
REFERENCE_STEPS = 20  # control steps that fix each key's reference failure rate
KEY_THRESHOLD = 7.0  # log-likelihood ratio a key's failure-rate CUSUM must reach
KEY_MIN_FAILS = 3  # and at least this many failures since the reference was fixed


def _key(m: Mismatch) -> list[str]:
    return list(m.rule_ids) or [f"field:{m.field}"]


class DriftMonitor:
    def __init__(
        self,
        theory: Theory | None = None,
        window: int = 5,
        margin: float = 0.15,
        slack: float = 0.1,
        threshold: float = 1.5,
        repeats: int = 3,
        alpha: float = 0.1,
        warmup: int = 3,
        reference: int = REFERENCE_STEPS,
        key_threshold: float = KEY_THRESHOLD,
    ) -> None:
        self.window, self.margin, self.slack = window, margin, slack
        self.threshold, self.repeats, self.alpha, self.warmup = threshold, repeats, alpha, warmup
        self.reference, self.key_threshold = reference, key_threshold
        self._defaults = (margin, slack, threshold, warmup)
        self.flaky: set[str] = set()  # implicated before, and re-investigation left them as they were
        self.proven: Counter[str] = Counter()  # rule/field keys seen predicting correctly under control
        self.failed: Counter[str] = Counter()  # ...and failing, counted once a step leaves the window
        self.use_proven = False
        self.rules_implicated: list[str] = []
        self.reset(theory)

    def reset(self, theory: Theory | None = None) -> None:
        """Start afresh on a (new) theory: forget baseline and history. Keys implicated in the last alarm
        that survive unchanged into the new theory are known weaknesses, not evidence of change."""
        self.margin, self.slack, self.threshold, self.warmup = self._defaults
        ids = {r.id for r in (theory.rules if theory else [])}
        self.flaky |= {k for k in self.rules_implicated if k in ids or k.startswith("field:")}
        self.confidence = {r.id: _weight(r.confidence, r.status) for r in (theory.rules if theory else [])}
        for k in self.flaky:
            self.confidence[k] = 0.1
        self.recent: deque[tuple[float, list[str]]] = deque(maxlen=self.window)
        self.baseline = 0.0
        self.base_fail: Counter[str] = Counter()
        self.base_steps = 0
        self.cusum = 0.0
        self.steps = 0
        self.status: Status = "ok"
        self.rules_implicated: list[str] = []
        self.last_surprise = 0.0
        # slow detector: per-key reference counts (frozen after `reference` steps) and CUSUMs
        self.ref_tries: Counter[str] = Counter()
        self.ref_fails: Counter[str] = Counter()
        self.hist_rate: dict[str, float] = {}  # failure rates seen on past experience (calibration)
        self.ref_steps = 0
        self.key_cusum: dict[str, float] = {}
        self.key_fails: Counter[str] = Counter()

    def calibrate(self, history: list[list[Mismatch]]) -> None:
        """Prime the baseline with the theory's known error profile on past experience, so chronic
        errors of an imperfect theory are not mistaken for change. Widens the detectors to its noise."""
        if not history:
            return
        scores = []
        fails: Counter[str] = Counter()
        for mism in history:
            s, keys = self.surprise(mism)
            scores.append(s)
            self.base_fail.update(keys)
            fails.update(keys)
        n = len(scores)
        mean = sum(scores) / n
        std = (sum((x - mean) ** 2 for x in scores) / n) ** 0.5
        self.base_steps += n
        self.baseline = mean
        self.slack = max(self.slack, 0.5 * std)
        self.margin = max(self.margin, std)
        self.threshold = max(self.threshold, 2.5 * std + 0.5)
        self.warmup = min(self.warmup, 3)
        self.hist_rate = {k: c / n for k, c in fails.items()}

    def surprise(self, mismatches: list[Mismatch]) -> tuple[float, list[str]]:
        total, keys = 0.0, []
        for m in mismatches:
            ks = _key(m)
            ws = [self.confidence.get(k, UNCOVERED_WEIGHT) for k in ks]
            if self.use_proven:  # a rule that never worked in this regime failing is ignorance, not change
                ws = [w if self.trusted(k) else min(w, 0.1) for k, w in zip(ks, ws)]
            total += max(ws)
            keys.extend(ks)
        return total, sorted(set(keys))

    def trusted(self, key: str) -> bool:
        """A rule that has predicted right under control and rarely failed there. Fields no rule covers are
        never trusted: their failure means the theory never knew, not that the system changed."""
        if key.startswith("field:"):
            return False
        ok, bad = self.proven[key], self.failed[key]
        return ok >= PROVEN and bad <= 0.15 * (ok + bad)

    def rate(self) -> float:
        return sum(s for s, _ in self.recent) / len(self.recent) if self.recent else 0.0

    def observe(self, mismatches: list[Mismatch], correct: list[str] | None = None) -> Status:
        """`correct`: keys (rule ids, or field:<name> when no rule covered it) that predicted right this step.
        When given, only keys that have proven themselves before can raise a fast alarm, and the slow
        per-key detector runs."""
        if correct is not None:
            self.use_proven = True
        s, keys = self.surprise(mismatches)
        if correct:
            self.proven.update(set(correct))
        self.steps += 1
        self.last_surprise = s
        if len(self.recent) == self.recent.maxlen:
            self.failed.update(self.recent[0][1])
        self.recent.append((s, keys))
        slow = self._slow(keys, set(correct or ()) - set(keys)) if correct is not None else []
        if self.status == "confirmed":
            return self.status
        if self.steps <= self.warmup:  # calibrate: errors the theory already makes are not change
            self._learn_baseline(s, keys)
            return self.status
        self.cusum = max(0.0, self.cusum + s - (self.baseline + self.slack))
        repeated = self._repeated()
        if self.cusum >= self.threshold or repeated or slow:
            self.status = "confirmed"
            self.rules_implicated = repeated or slow or self._top_keys()
        elif self.rate() > self.baseline + self.margin:
            self.status = "suspected"
        else:
            if self.status == "suspected" and self.cusum > 0:
                return self.status
            self.status = "ok"
            if self.steps <= self.warmup + self.reference:  # reference period only: then the level is frozen
                self._learn_baseline(s, keys)
        return self.status

    def _learn_baseline(self, s: float, keys: list[str]) -> None:
        self.base_steps += 1
        self.baseline += (s - self.baseline) / self.base_steps
        self.base_fail.update(keys)

    # ---- slow detector: per-key failure-rate CUSUM against a frozen reference ------------------
    def _slow(self, failed: list[str], right: set[str]) -> list[str]:
        if self.ref_steps < self.reference:
            self.ref_steps += 1
            self.ref_tries.update(set(failed) | right)
            self.ref_fails.update(failed)
            return []
        out = []
        for k in set(failed) | right:
            if k in self.flaky:
                continue
            p0 = self._ref_rate(k)
            p1 = min(0.97, max(2 * p0, p0 + 0.3))
            if p1 <= p0:
                continue
            bad = k in failed
            llr = math.log(p1 / p0) if bad else math.log((1 - p1) / (1 - p0))
            c = max(0.0, self.key_cusum.get(k, 0.0) + llr)
            self.key_cusum[k] = c
            if bad:
                self.key_fails[k] += 1
            elif c == 0.0:
                self.key_fails[k] = 0
            if c >= self.key_threshold and self.key_fails[k] >= KEY_MIN_FAILS:
                out.append(k)
        return sorted(out, key=lambda k: -self.key_cusum[k])

    def _ref_rate(self, k: str) -> float:
        n, f = self.ref_tries[k], self.ref_fails[k]
        p = (f + 0.5) / (n + 1)  # unseen in the reference period: no confident expectation either way
        return min(0.9, max(p, self.hist_rate.get(k, 0.0), 0.02))

    def _repeated(self) -> list[str]:
        counts = Counter(k for _, ks in self.recent for k in ks)
        out = []
        for k, n in counts.most_common():
            if k in self.flaky or (self.use_proven and not self.trusted(k)):
                continue
            base_rate = self.base_fail[k] / self.base_steps if self.base_steps else 0.0
            if k.startswith("field:") or self.confidence.get(k, UNCOVERED_WEIGHT) < 0.6:
                # a field no trusted rule explains failing is ignorance, not change, unless it was reliably right
                if n >= max(self.repeats, self.window) and base_rate < 0.1:
                    out.append(k)
            elif n >= self.repeats and base_rate < 0.34:
                out.append(k)
        return out

    def _top_keys(self) -> list[str]:
        counts = Counter(k for _, ks in self.recent for k in ks)
        return [k for k, _ in counts.most_common(5)]


def _weight(confidence: float, status: str) -> float:
    w = min(max(confidence, 0.05), 1.0)
    if status == "supported":
        w = max(w, 0.7)
    elif status in ("refuted", "retired"):
        w = 0.1
    return w
