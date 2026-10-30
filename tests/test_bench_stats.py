import asyncio

import pytest

from logicscout.bench.__main__ import parse_variants
from logicscout.bench.baselines import ARMS, NO_CALL_ARMS, NullLLM, drift_metrics, estimate_calls
from logicscout.bench.stats import aggregate, wilson
from logicscout.contracts import Event, RunConfig


def test_wilson_known_values():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_aggregate_counts_cases_not_runs():
    rows = [{"world": "w", "arm": "a", "status": "ok", "n_cases": 4, "successes": 1, "model_calls": 10, "tokens": 100},
            {"world": "w", "arm": "a", "status": "ok", "n_cases": 4, "successes": 1, "model_calls": 10, "tokens": 100},
            {"world": "w", "arm": "a", "status": "crash"}]
    (a,) = aggregate(rows)
    assert (a["runs"], a["runs_ok"], a["n_cases"], a["successes"]) == (3, 2, 8, 2)
    assert a["tokens_per_success"] == 100


def test_arm_wiring_and_flags():
    for arm in ("full", "no_model", "model_only", "tabular", "random", "idle"):
        assert arm in ARMS
    assert NO_CALL_ARMS == {"no_model", "tabular", "random", "idle"}
    cfg = RunConfig(world_id="relay")
    assert cfg.use_model and cfg.use_induction
    assert parse_variants("g101-g103,g7") == ["g101", "g102", "g103", "g7"]
    from logicscout.referee.referee import world_class
    m = world_class("relay").manual()
    assert all(estimate_calls(a, m, 2, 10) == 0 for a in NO_CALL_ARMS)


def test_null_llm_always_fails():
    from logicscout.llm.nemotron import LLMError
    with pytest.raises(LLMError):
        asyncio.run(NullLLM().json("x", "s", "u"))


def test_drift_metrics_from_events():
    def ev(i, kind, data=None):
        return Event(seq=i, run_id="r", ts=0, kind=kind, phase="control", data=data or {})
    kinds = ["control.step"] * 3 + ["drift.confirmed", "control.step", "shift.applied"] + ["control.step"] * 4
    evs = [ev(i, k) for i, k in enumerate(kinds)] + [ev(20, "drift.confirmed"), ev(21, "recovery.done", {"steps_down": 9})]
    d = drift_metrics(evs)
    assert d["false_alarms_before_shift"] == 1 and d["shift_at_control_step"] == 4
    assert d["detection_delay_steps"] == 4 and d["recovered"] and d["recovery_steps"] == 9
