"""Reality trial: a compiled controller must work on the real system before it is put in charge.

Simulating a controller inside the learned theory only shows that the controller and the theory agree;
it is not evidence about the real system (an optimizer can exploit an error in the theory). So before
deployment the controller runs for up to its horizon on a separate sandbox session, reset to a lab seed
other than the one it will operate on. The theory's simulated outcome is compared with what really
happened, and every one-step prediction is checked against the real observation.

Success is judged by the objective's own success expression on the real observations (what the scout can
see itself), never by privileged ground truth. Only the port (manual/reset/act) is used.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from logicscout.contracts import Mismatch, Objective, Observation, Theory, WorldManual
from logicscout.dsl import safe_evaluate
from logicscout.playbook import simulate
from logicscout.theory import Predictor, compare

MAX_MISMATCH = 0.5  # reject when more than half of the real steps contradict the theory's one-step prediction


def _goal(objective: Objective, obs: Observation) -> bool:
    try:
        return bool(safe_evaluate(objective.success, {"obs": obs.fields, "args": {}, "mem": {}, "t": obs.t}))
    except Exception:
        return False


async def reality_trial(
    policy_factory: Callable[[], Any],
    theory: Theory,
    port_factory: Callable[[], Any],
    manual: WorldManual,
    objective: Objective,
    seed: int,
    max_steps: int | None = None,
    threshold: float = MAX_MISMATCH,
    ignore: Callable[[Mismatch], bool] | None = None,
) -> dict[str, Any]:
    """Run a fresh controller on a fresh port and score the theory's forecast against reality.

    Returns {predicted_success, predicted_steps, real_success, mismatch_rate, steps, truncated, seed,
    accepted, reason, transitions}. `max_steps` caps real steps (the probe allowance); when the cap stops
    the run before the simulated goal step, the success comparison is inconclusive and only the
    mismatch rate decides. `ignore` drops mismatches that are within display resolution."""
    horizon = objective.horizon if max_steps is None else max(0, min(objective.horizon, max_steps))
    port = await asyncio.to_thread(port_factory)
    obs = await asyncio.to_thread(port.reset, seed)
    sim = simulate(policy_factory(), theory, obs, objective.success, objective.horizon)
    predicted, predicted_steps = bool(sim.get("success")), int(sim.get("steps") or 0)

    policy = policy_factory()
    predictor = Predictor(theory)
    predictor.reset(obs)
    transitions: list[tuple[Observation, Any, Observation]] = []
    wrong_steps = steps = 0
    real = _goal(objective, obs)
    while not real and steps < horizon:
        action = policy.next_action(obs)
        forecast = predictor.predict(obs, action)
        res = await asyncio.to_thread(port.act, action)
        new = res.observation
        mismatches = [m for m in compare(forecast, new.fields, predictor.last_rules) if not (ignore and ignore(m))]
        predictor.advance(new)
        policy.after_step(new)
        transitions.append((obs, action, new))
        steps += 1
        wrong_steps += bool(mismatches)
        obs = new
        real = _goal(objective, obs)
        if res.done:
            break

    rate = round(wrong_steps / steps, 4) if steps else 0.0
    truncated = not real and steps < objective.horizon and steps >= horizon
    comparable = not truncated or predicted_steps <= steps  # did reality get as many steps as the forecast needed?
    reasons = []
    if predicted and not real and comparable:
        reasons.append("the theory predicted success but the real system did not reach the goal")
    if rate > threshold:
        reasons.append(f"predictions were wrong on {rate:.0%} of real steps (limit {threshold:.0%})")
    return {
        "predicted_success": predicted, "predicted_steps": predicted_steps, "real_success": real,
        "mismatch_rate": rate, "steps": steps, "truncated": truncated, "seed": seed,
        "accepted": not reasons, "reason": "; ".join(reasons), "transitions": transitions,
    }
