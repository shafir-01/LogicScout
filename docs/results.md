# LogicScout results: does the model add anything?

Date: 2026-10-30. Code: commit `446749f` plus working-tree changes at run time. Every number below is a count of
held-out referee cases (cases the scout never saw, scored on ground truth), with a 95% Wilson interval. Raw per-run
JSON: `data/bench/scale/<world>/<arm>/[<system>/]seed-<i>.json`; per-run table: `data/bench/scale/summary.md`.

## Arms (matched probe allowance)

| arm | what it is | model calls |
|---|---|---|
| `full` | model hypotheses + code-side rule fitting/mining + planner/playbook + drift monitor | yes |
| `no_model` | same mission, `use_model=False`: every model call fails at once, the mission runs on code-side rule fitting, the planner and the monitor | 0 |
| `model_only` | same mission, `use_induction=False`: no code-side rule fitting or mining; rules come only from the model | yes |
| `tabular` | classical system identification: coverage + random experience (2 x probe budget, the same total allowance a mission gets), a per-action / per-enum-argument table of mean change per field, then the same planner and referee | 0 |
| `random` | uniformly random actions on each held-out case | 0 |
| `idle` | the idle action on each held-out case | 0 |

Mission arms get the world's probe budget for the first investigation and at most the same again for
re-investigation after a hidden change; a hidden change is applied automatically after 40 control steps. Transfer
from other runs is off, so every system is met cold.

## Commands

```
uv run python -m logicscout.bench --world relay --objective bulk8 --seeds 8 --arms no_model,tabular,random,idle --out data/bench/scale
uv run python -m logicscout.bench --world forge --variants g101-g200 --seeds 1 --arms no_model,tabular,random,idle --out data/bench/scale
uv run python -m logicscout.bench --report-only --out data/bench/scale
```

(The runs were split across processes with `--variants g101-g120` etc. and `--first-index`; the outputs are identical.)
Forge systems `g101`..`g200` are 100 freshly generated systems, objective `reach`, 6 held-out cases each.

## Per-arm held-out goal success

| world | arm | runs (ok) | systems | held-out cases n | successes | rate | 95% Wilson CI | probes (mean) | pred acc / persistence | model calls | tokens | tokens per success |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| forge | idle | 100 (100) | 100 | 600 | 0 | 0.00 | [0.00, 0.01] | 0 | - / - | 0 | 0 | 0 |
| forge | no_model | 100 (100) | 100 | 600 | 123 | 0.20 | [0.17, 0.24] | 81 | 0.94 / 0.66 | 0 | 0 | 0 |
| forge | random | 100 (100) | 100 | 600 | 16 | 0.03 | [0.02, 0.04] | 0 | - / - | 0 | 0 | 0 |
| forge | tabular | 100 (100) | 100 | 600 | 0 | 0.00 | [0.00, 0.01] | 120 | 0.80 / 0.66 | 0 | 0 | 0 |
| relay | idle | 8 (8) | 1 | 32 | 0 | 0.00 | [0.00, 0.11] | 0 | - / - | 0 | 0 | 0 |
| relay | no_model | 8 (8) | 1 | 32 | 4 | 0.12 | [0.05, 0.28] | 98 | 0.88 / 0.76 | 0 | 0 | 0 |
| relay | random | 8 (8) | 1 | 32 | 0 | 0.00 | [0.00, 0.11] | 0 | - / - | 0 | 0 | 0 |
| relay | tabular | 8 (8) | 1 | 32 | 0 | 0.00 | [0.00, 0.11] | 100 | 0.80 / 0.76 | 0 | 0 | 0 |

## Hidden change (mission arm, change after 40 control steps)

A false alarm is a confirmed drift before any change was applied. Detection delay is control steps from the change
to the first confirmed drift. Recovery is a goal reached after re-investigation (`recovery.done`); recovery time is
control steps from the change to that point.

| world | arm | runs | change applied | false alarms before change (runs with any) | control steps before change | detected (95% CI) | detection delay, steps (median; all) | recovered (95% CI) | recovery time, steps (median) |
|---|---|---|---|---|---|---|---|---|---|
| forge | no_model | 100 | 100 | 28 (24) | 4000 | 19/100 [0.13, 0.28] | 31.0; [1, 2, 3, 5, 7, 10, 27, 27, 29, 31, 35, 40, 49, 55, 70, 91, 98, 106, 196] | 9/100 [0.05, 0.16] | 53.0 |
| relay | no_model | 8 | 8 | 5 (2) | 320 | 7/8 [0.53, 0.98] | 8.0; [2, 5, 5, 8, 9, 131, 162] | 2/8 [0.07, 0.59] | 22.0 |

## Missing: the model arms at scale

`full` and `model_only` were **not** measured at scale. The planned runs (`full` and `model_only` on Forge
`g101`..`g106` and relay seeds 0..2) were started and every model call was refused by the provider
(HTTP 402: inference budget exhausted). Those runs were stopped and their output discarded, because a run whose model
calls all fail is a `no_model` run under another name. No numbers in this page come from them.

The only model-arm data is the earlier small relay run (2 seeds, 4 held-out cases each, `data/bench/relay/`):
`full` reached the goal on 3 of 8 cases (0.38, 95% CI [0.14, 0.69]) with 22 to 23 model calls and about 140k tokens
per run (about 94k tokens per successful case); the no-model variant in that run also reached 3 of 8 (same CI) with
0 calls.

## What this shows / what it does not

- The code-only pipeline (`no_model`) does real work: on 100 generated Forge systems it reached the goal on
  123 of 600 held-out cases (0.20, [0.17, 0.24]) against 16 of 600 for random control and 0 for idle. On relay it
  reached 4 of 32 (0.12, [0.05, 0.28]) against 0 of 32 for random and idle. It is still far from reliable.
- The classical `tabular` baseline learned a model that beat "nothing changes" on prediction (0.80 vs 0.66 Forge,
  0.80 vs 0.76 relay) but reached the goal on 0 of 600 and 0 of 32 cases. With the same probe allowance and the same
  planner, a per-action mean-change table is not enough on these systems; the conditional and delayed rules the
  mission's rule fitting finds are what make planning work.
- Hidden changes: on Forge the monitor confirmed the change in 19 of 100 runs ([0.13, 0.28]), with a median delay of
  31 control steps and a long tail, recovered in 9 of 100 ([0.05, 0.16]), and raised a false alarm before any change in
  24 of 100 runs. On relay it confirmed 7 of 8 but recovered 2 of 8. Detection and recovery are weak; false alarms
  are common.
- Does the model add anything? **Not shown.** At scale we have no `full` or `model_only` numbers, so this page
  cannot say whether the model improves goal success. The only paired comparison (relay, 8 cases each) shows no
  difference: 3 of 8 with the model, 3 of 8 without, with intervals that cover almost everything. Every success
  measured at scale here was produced with zero model calls.
- Not measured: stochastic systems, systems outside Forge's mechanism families, long-horizon rollout accuracy,
  safety violations.
