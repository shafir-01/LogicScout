# Where does the model add value over code-side induction?

This page measures the investigation phase alone (no control) on relay, orbit, gate and two out-of-family forge systems (x101, x202), with the same probe budget (the world manual's budget of 50) in three modes.

| Mode | What runs |
|---|---|
| induction | code-side rule fitting and mining only, every model call refused (zero calls) |
| model | Nemotron hypotheses only, code-side fitting and mining switched off |
| both | the normal investigator |

Reproduce with `uv run python scripts/model_value.py` (see the script header for flags; `--dry` estimates calls first). Raw per-run JSON, including every final theory, is in `data/model_value/`, and `data/model_value/summary.json` aggregates it.

## Metrics

Referee accuracy is the fraction of (step, field) pairs predicted correctly on the referee's held-out standard cases, played with uniformly random actions. Changed accuracy is the same score restricted to pairs whose value actually changed, so a theory that predicts "nothing happens" scores zero there. Persistence is the "nothing changes" baseline.

Per-law scores come from 24 held-out episodes of 30 steps on unseen seeds (half random play, half a loose operator script so deeper laws get exercised). Referee code reads the hidden state before each step and tags the transitions that exercise a law, together with the fields that law moves. A law counts as captured on a transition when the final theory predicts all of those fields. The persistence column on each law shows how much a "nothing changes" guess would already score; a law where persistence is near 1.0 is not informative.

## Results

Status at publication. The induction cells are complete with 2 seeds each. The model and both cells are not measured. They were launched for relay, orbit and gate with one seed, but the model provider refused every one of the 28 requests with HTTP 402 (the account's inference budget is exhausted), so those runs never received a single model answer. Their raw files are kept apart in `data/model_value/provider_refused/` and are excluded from every number on this page, because a run in which every model call fails is a code-only run under another name. No forge cell with the model was attempted.

### Held-out referee accuracy (mean over seeds)

| World | induction acc | induction changed | model | both | persistence |
|---|---|---|---|---|---|
| relay | 0.876 | 0.638 | not measured | not measured | 0.785 |
| orbit | 0.899 | 0.164 | not measured | not measured | 0.883 |
| gate | 0.924 | 0.526 | not measured | not measured | 0.854 |
| forge x101 (out of family) | 0.956 | 0.866 | not run | not run | 0.713 |
| forge x202 (out of family) | 0.732 | 0.517 | not run | not run | 0.569 |

### Per-law capture, induction mode (seed 0 / seed 1; persistence in brackets)

Relay

| Law | n | induction | persistence |
|---|---|---|---|
| buoy contact window | 148 | 0.60 / 0.08 | 0.00 |
| buoy capacity per send | 11 | 0.00 / 0.00 | 0.00 |
| buoy recharge | 91 | 0.66 / 0.55 | 0.55 |
| satellite energy cost | 113 | 0.55 / 0.85 | 0.55 |
| satellite delivery latency | 51 | 0.00 / 0.00 | 0.00 |
| newest-first queue order | 131 | 0.44 / 0.39 | 0.63 |
| prioritize reorders queue | 46 | 0.37 / 0.30 | 0.00 |
| periodic arrivals | 240 | 0.87 / 0.72 | 0.17 |

Orbit

| Law | n | induction | persistence |
|---|---|---|---|
| lagged temperature | 720 | 0.43 / 0.41 | 0.39 |
| bus warm-up before payload | 36 | 0.00 / 0.00 | 0.00 |
| bus off clears payload | 17 | 0.00 / 0.00 | 0.00 |
| capture validity (band, calibration) | 43 | 0.65 / 0.65 | 0.65 |
| storage overwrite | 17 | 0.47 / 0.47 | 0.47 |
| downlink only in passes | 27 | 0.70 / 0.70 | 0.70 |

Gate

| Law | n | induction | persistence |
|---|---|---|---|
| token cost per request | 356 | 0.95 / 0.95 | 0.46 |
| token refill | 317 | 0.51 / 0.51 | 0.51 |
| empty bucket returns 429 | 24 | 0.00 / 0.00 | 0.00 |
| backing off clears strikes | 15 | 0.00 / 0.00 | 0.00 |
| commit within arm window | 4 | 0.00 / 0.00 | 0.00 |
| stale arm falls back to draft | 6 | 0.00 / 0.00 | 0.00 |
| arming evicts the oldest | 6 | 1.00 / 1.00 | 1.00 (uninformative) |

## What this shows so far

Code-side induction on its own already beats the persistence baseline on every world, but the margin lives almost entirely in template-shaped laws. On relay it recovers periodic arrivals and, on one of two seeds, the buoy contact window, and on gate it learns the per-request token cost. Those are counters, periods and fixed decrements, which is exactly what the fitting templates express.

The laws that need a precondition, an ordering or a lag are where induction scores zero or merely matches persistence. Orbit's lagged temperature sits at 0.41 to 0.43 against a persistence score of 0.39, the bus warm-up precondition and the bus-off reset are never predicted, and orbit's changed accuracy is only 0.15 to 0.18. On gate the whole request lifecycle (429 on an empty bucket, strike reset on back-off, commit inside the arm window, stale arms falling back to draft) is missed. Relay's satellite latency and buoy capacity are missed too. This is the region where a model that reads the manual and proposes structured hypotheses could add value, and it is also where the code-only investigator demonstrably leaves accuracy on the table.

The comparison that answers the question, the same laws scored in the model and both modes, could not be made in this snapshot because the provider refused every request. This page therefore supports only the narrower claim that induction alone fails on non-template laws; it does not show that the model fixes them, and it does not show that the model fails to. Rerunning `uv run python scripts/model_value.py --modes model,both --seeds 0,1` once inference credit is available fills the missing cells (about 48 calls for one seed across the three worlds). The two induction seeds also differ sharply on relay's buoy window (0.60 against 0.08), so single-seed cells in any mode should be read as indicative, not conclusive.

On the out-of-family forge systems, induction alone stays well above persistence on x101 (0.96 against 0.71) and gains less on x202 (0.73 against 0.57), which shows the out-of-family mechanisms do cost accuracy. Whether the model recovers any of that loss has not been measured here.

## Limits of this measurement

Each investigation starts with no briefing and no transferred priors, so the model mode sees only the manual and its own probes. Probe counts can run slightly over the nominal budget because a probe already in flight is allowed to finish. Gate's eviction law leaves the armed and draft counts unchanged at the step it fires, so its per-law score cannot separate a correct theory from a lazy one.
