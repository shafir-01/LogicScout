"""Evidence-based detection of hidden change.

Every control step yields a surprise score: each mispredicted field counts with the confidence of the
rules that predicted it (a well-supported rule failing is strong evidence; a field no rule covers counts
as moderate evidence). Two detectors run on that stream:
  - a sliding window: the mean surprise over the last W steps versus the pre-change baseline;
  - a one-sided CUSUM on the same stream.
"suspected" when the window rate exceeds baseline + margin; "confirmed" when the CUSUM crosses its
threshold or the same rule (or uncovered field) fails repeatedly in the window while it rarely failed
before. The first `warmup` steps on a theory only calibrate the baseline. No timers, no outside signals: only prediction errors.
"""
from __future__ import annotations

from collections import Counter, deque
from typing import Literal

from logicscout.contracts import Mismatch, Theory

Status = Literal["ok", "suspected", "confirmed"]
UNCOVERED_WEIGHT = 0.5


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
    ) -> None:
        self.window, self.margin, self.slack = window, margin, slack
        self.threshold, self.repeats, self.alpha, self.warmup = threshold, repeats, alpha, warmup
        self._defaults = (margin, slack, threshold, warmup)
        self.flaky: set[str] = set()  # implicated before, and re-investigation left them as they were
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

    def calibrate(self, history: list[list[Mismatch]]) -> None:
        """Prime the baseline with the theory's known error profile on past experience, so chronic
        errors of an imperfect theory are not mistaken for change. Widens the detectors to its noise."""
        if not history:
            return
        scores = []
        for mism in history:
            s, keys = self.surprise(mism)
            scores.append(s)
            self.base_fail.update(keys)
        n = len(scores)
        mean = sum(scores) / n
        std = (sum((x - mean) ** 2 for x in scores) / n) ** 0.5
        self.base_steps += n
        self.baseline = mean
        self.slack = max(self.slack, 0.5 * std)
        self.margin = max(self.margin, std)
        self.threshold = max(self.threshold, 2.5 * std + 0.5)
        self.warmup = min(self.warmup, 3)

    def surprise(self, mismatches: list[Mismatch]) -> tuple[float, list[str]]:
        total, keys = 0.0, []
        for m in mismatches:
            ks = _key(m)
            ws = [self.confidence.get(k, UNCOVERED_WEIGHT) for k in ks]
            total += max(ws)
            keys.extend(ks)
        return total, sorted(set(keys))

    def rate(self) -> float:
        return sum(s for s, _ in self.recent) / len(self.recent) if self.recent else 0.0

    def observe(self, mismatches: list[Mismatch]) -> Status:
        s, keys = self.surprise(mismatches)
        self.steps += 1
        self.last_surprise = s
        self.recent.append((s, keys))
        if self.status == "confirmed":
            return self.status
        if self.steps <= self.warmup:  # calibrate: errors the theory already makes are not change
            self.base_steps += 1
            self.baseline += (s - self.baseline) / self.base_steps
            self.base_fail.update(keys)
            return self.status
        self.cusum = max(0.0, self.cusum + s - (self.baseline + self.slack))
        repeated = self._repeated()
        if self.cusum >= self.threshold or repeated:
            self.status = "confirmed"
            self.rules_implicated = repeated or self._top_keys()
        elif self.rate() > self.baseline + self.margin:
            self.status = "suspected"
        else:
            if self.status == "suspected" and self.cusum > 0:
                return self.status
            self.status = "ok"
            self.baseline += self.alpha * (s - self.baseline)
            self.base_steps += 1
            self.base_fail.update(keys)
        return self.status

    def _repeated(self) -> list[str]:
        counts = Counter(k for _, ks in self.recent for k in ks)
        out = []
        for k, n in counts.most_common():
            if k in self.flaky:
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
