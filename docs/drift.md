# Drift detection, measured

LogicScout watches its own prediction errors during control and raises an alarm when the system it controls seems to have changed. This page reports how well that monitor works, measured offline with `scripts/drift_eval.py`. No model is called. Theories are learned by the code-only investigator, the controller is the theory planner, and the loop that feeds the monitor is the same one the mission runs. Raw numbers are in [drift.json](drift.json).

## How the measurement works

For each configuration the script learns one theory, then runs 160 control steps under four conditions. In a stationary run nothing changes, so every alarm is a false alarm. In an abrupt run one hidden change from the world's shift menu lands at step 50. In a gradual run the same kind of change is applied again every 20 steps, four times in all. A change is called harmless when every observation after it is identical to the unchanged run with the same seeds, which means the controller never exercises the changed law and an alarm would be wrong. After a confirmed alarm the monitor restarts on the same theory and counting continues, so false alarms are reported per 100 control steps. Detection delay is the number of control steps from the first change to the first confirmed alarm.

The configurations are relay with both objectives, plant, and six generated Forge systems (g1 to g6), one seed each. That gives 59 runs per monitor version. These counts are small, especially for abrupt changes (10 visible ones), so the rates below carry wide uncertainty. Run `uv run python scripts/drift_eval.py` without `--quick` for four seeds per configuration.

## Results

| Condition | Measure | Before | After |
|---|---|---|---|
| Stationary (9 runs, 1440 steps) | false alarms per 100 steps | 0.28 | 0.07 |
| Abrupt, visible (10 runs) | detected | 1 of 10 | 8 of 10 |
| Abrupt | median delay, steps | 3 | 6 |
| Abrupt | worst delay, steps | 3 | 79 |
| Abrupt | false alarms before the change | 5 | 0 |
| Gradual, visible (12 to 13 runs) | detected | 1 of 12 | 12 of 13 |
| Gradual | median delay, steps | 3 | 23 |
| Harmless (27 runs) | alarmed (lower is right) | 0 | 1 |

| World | Abrupt detected before | after | Gradual detected before | after |
|---|---|---|---|---|
| Forge g1 to g6 | 1 of 6 | 8 of 8 | 1 of 8 | 10 of 11 |
| Relay | 0 of 3 | 0 of 2 | 0 of 3 | 2 of 2 |
| Plant | 0 of 1 | none visible | 0 of 1 | none visible |

Run counts per world differ slightly between versions because a run is classed as visible or harmless by its observations, and the earlier monitor's restarts happen at different points.

## What the earlier monitor got wrong

The earlier monitor confirmed change only when a trusted rule failed several times inside a short window, or when the summed surprise crossed a CUSUM threshold. Both are fast and both are blind to the most common pattern in these runs. Learned theories are imperfect, so most rules that a change breaks were already failing now and then. Those rules are not trusted, their failures are down-weighted, and a rise from failing one step in five to failing most steps never crosses the threshold. The monitor also kept pulling its reference level toward the recent stream whenever it was not alarmed, so a change that arrived slowly could become part of what it treated as normal.

## What changed

The monitor now runs a slow detector beside the fast ones. For every rule, and every field no rule covers, it keeps a failure rate measured over the first 20 control steps on a theory, together with any failure rate the theory showed on past experience. After that period the reference is frozen. A Bernoulli CUSUM per key then tests whether the key now fails clearly more often than its reference (at least twice as often, or 30 points more), and it confirms change only after a log-likelihood ratio of 7 and at least three failures. The surprise level used by the fast detectors is also frozen after the reference period, so it can no longer drift toward a change in progress. The interface is unchanged, with `observe(mismatches, correct)` returning ok, suspected or confirmed, `rules_implicated` naming the keys that fired, and `reset` starting afresh on a new theory.

This separates model error from change in a simple, testable way. A rule that was always unreliable at a steady rate is model error and stays quiet. A rule whose failure rate rises after the reference period is evidence of change, whether it was trusted or not.

## Limits that remain

Detection is slower when the change only shows up in a regime the controller rarely visits. Three Forge runs were caught only 79 steps after the change. The cause of that shared late point has not been traced yet, and an alarm that late may partly be luck rather than evidence. Relay window changes under the priority objective were still missed, because the learned relay theory already fails often on the same fields and the change does not move those rates enough within 110 steps. One harmless run raised an alarm, which is a false alarm caused by the controller reaching a state the reference period never covered. Many shift-menu changes (27 of 59 runs) are invisible under the controller that was learned, which is correct behaviour but also means those laws are never checked.

The reference is learned from the first 20 control steps, so a change that lands inside that period becomes part of the reference. The mission restarts the monitor after every re-investigation, which opens that window again.

The mission still filters a float mismatch when the error is within the smallest gap between past readings. In these runs that filter hid no mismatch after a change, because the evaluated fields are integers or the gaps were small. It remains a weak estimate of sensor resolution and should be replaced by declared instrument resolution or a residual-based noise estimate.

## Reproduce

```
uv run python scripts/drift_eval.py --quick                     # current monitor, one seed per configuration
uv run python scripts/drift_eval.py --monitor path/to/other.py  # compare another monitor module
uv run python scripts/drift_eval.py --no-filter                 # feed every mismatch to the monitor
```
