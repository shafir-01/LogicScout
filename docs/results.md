# LogicScout results: relay world, objective `bulk8`

Date: 2026-10-30. Code: commit `ca208e5` plus uncommitted working-tree changes at run time (the scout, planner and
monitor were still being tuned; this page describes exactly the tree that was run, not a tagged release).
Reasoning models: `nvidia/Nemotron-3-Ultra-550b-a55b` (deep tier) and `nvidia/nemotron-3-super-120b-a12b` (fast tier)
on Nebius Token Factory. Protocol: [evaluation.md](evaluation.md), written before these runs. Raw per-seed JSON:
`data/bench/relay/<arm>/seed-<i>.json`. The tables below are copied from those files.

n is tiny (2 seeds, a few held-out cases). Rows are raw; nothing here is a statistic.

## Commands

```
uv run python -m logicscout.bench --world relay --objective bulk8 --seeds 2 \
  --arms full,random_probe,zero_shot,no_adaptation,reasoning_control \
  --max-cases 3 --max-steps 12 --out data/bench
```

Code-only row (no model at all; the model client raises on every call, so the mission runs on code-side rule
induction, the planner and the monitor alone). Script: a short driver that calls `run_mission` with that client
and scores with the same referee; seeds 0 and 1, `probe_budget=50`, `shift_after=10`, briefing off:

```
uv run python <driver>.py 0 ; uv run python <driver>.py 1     # writes data/bench/relay/code_only_no_model/seed-*.json
```

Not run: `prompt_only` (call budget), `passive`, `no_briefing`, `no_transfer`. Other worlds were not benchmarked here.
Total real model calls in the bench: 225.

## Per-seed rows

"Held-out success" is the referee's ground-truth success over all held-out cases (4 cases; random and idle baselines
scored 0.00 on every row). Per-step model arms (`zero_shot`, `reasoning_control`) were run on the first 3 referee
cases with a 12-step cap, so their number is a "subset" number and is not on the same footing as the others.

| arm | seed | held-out goal success | prediction acc / persistence (held-out) | probes | model calls | tokens | drift detected / recovered |
|---|---|---|---|---|---|---|---|
| full | 0 | 0.50 | 0.90 / 0.76 | 100 | 23 | 137,814 | yes (11 steps after shift) / yes (0.67 true success after shift) |
| full | 1 | 0.25 | 0.89 / 0.76 | 100 | 22 | 143,094 | not detected / no |
| random_probe | 0 | 0.00 | 0.76 / 0.76 | 50 | 4 | 12,476 | - |
| random_probe | 1 | 0.00 | 0.76 / 0.76 | 50 | 4 | 15,742 | - |
| no_adaptation | 0 | 0.00 | 0.88 / 0.76 | 62 | 14 | 60,751 | drift monitor disabled / no (0.00 after shift) |
| no_adaptation | 1 | 0.00 | 0.89 / 0.76 | 62 | 14 | 62,741 | drift monitor disabled / no (0.00 after shift) |
| zero_shot (subset, 12-step cap) | 0 | 0.00 | - | 0 | 36 | 43,952 | - |
| zero_shot (subset, 12-step cap) | 1 | 0.00 | - | 0 | 36 | 43,986 | - |
| reasoning_control (subset, 12-step cap) | 0 | 0.00 (compiled playbook on same cases: 0.00) | - | - | 36 | 116,832 | - |
| reasoning_control (subset, 12-step cap) | 1 | 0.00 (compiled playbook on same cases: 0.00) | - | - | 36 | 100,558 | - |
| code-only induction, no model | 0 | 0.50 | 0.91 / 0.76 | 50 (+ refits) | 0 | 0 | yes (4 steps after shift) / no |
| code-only induction, no model | 1 | 0.25 | 0.90 / 0.76 | 44 | 0 | 0 | yes (45 steps after shift) / yes |

Notes on the rows:
- `full` probe counts include the re-investigation after the change (50 + 50). In seed 1 the drift monitor never
  fired in the bench's own recovery measurement, so no recovery was attempted there.
- `reasoning_control` reuses the `full` arm's theory; its compiled playbook originated from the planner, not the
  model-written playbook, and scored 0.00 on the same capped subset.
- API failure rate was 0.04 for `full` seed 0 and 0.00 for every other row. All four leakage checks passed on every
  row that has them. No arm crashed.
- The code-only seeds (0, 1) are mission seeds from a separate driver and are not the bench's lab seeds (7, 8); the
  referee's held-out cases are the same. Its in-run episodes were 4 per run: seed 0 none reached the goal, seed 1 one did
  (the held-out success above is what the referee measured afterwards).
- `data/bench/relay/*/seed-*.json` may contain more fields than shown here (false-conclusion counts, latency, wall time).
  The held-out rule contradictions were 18 and 27 for `full`, 21 for each `no_adaptation` run, 0 for `random_probe`
  (which learned no rules).

## Findings

1. Prediction: the learned theory predicted held-out transitions better than "nothing changes" in every arm that
   built one (0.88 to 0.91 against 0.76). Random probing with the same 50-probe budget did not (0.76, identical to
   persistence). With this budget on this world, chosen experiments produced a useful theory and random ones did not.
2. Control: the full pipeline reached the goal on 2 of 4 held-out cases in one seed and 1 of 4 in the other. That is
   far from reliable, but random, idle, `random_probe`, `no_adaptation`, `zero_shot` and `reasoning_control` all scored 0.00
   in the same setting. The two per-step model arms were measured on a smaller, capped subset, so that comparison
   is weaker than the others.
3. The no-model row did as well as the model-driven `full` arm on goal success (0.50 and 0.25 against 0.50 and 0.25) and
   slightly better on held-out prediction accuracy (0.90 to 0.91 against 0.89 to 0.90). On this world, with this
   code, the model is not what produces the goal successes; the code-side rule fitting and planner are. LogicScout did
   NOT beat its own no-model variant here. We did not measure what the model adds on the other worlds.
4. Hidden change: with the drift monitor disabled (`no_adaptation`), held-out success was 0.00 and true success
   after the change was 0.00 in both seeds. With it on, one seed detected the change 11 steps after it was applied and
   recovered (0.67 true success after); the other seed's run did not detect it and did not recover. Detection is
   inconsistent: the no-model runs flagged the change after 4 and 45 steps, and only one of those two recovered.
5. Cost: a model call is cheap in count (22 to 23 for `full`) but not in tokens (about 140k), and the per-step model
   arms spent 36 calls and 44k to 117k tokens for zero goal successes on their subset.
