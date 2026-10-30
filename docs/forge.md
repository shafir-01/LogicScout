# Forge: generated unknown systems

Forge builds a system nobody has seen before a run. A seed deterministically composes 3-5 mechanisms
from the mechanism library over neutral components, so there is no public documentation to look up
(`briefing_topics` is empty on purpose).

## Variants
- `standard` = seed 1; `g<seed>` = any seed (e.g. `g42`). `ForgeWorld.generate(seed)` is `ForgeWorld(f"g{seed}")`.
- `x<seed>` (e.g. `x42`) = an **out-of-family** system (see below). Title `Unknown system #x<seed>`.
- Title `Unknown system #<seed>`, domain `Generated`, lab seeds 0-1000, referee seeds 10001-10006 on the same system.

## What a seed decides
- 3-5 actions with neutral names (`pulse`, `vent`, `route`, ...): a producer, an idle control, plus the
  controls some mechanisms need (an arming control, a transfer control, a `level` control 0-3), or a
  harmless-looking decoy that removes one unit.
- 5-8 integer/bool readings with neutral names; one is the objective reading.
- Mechanisms and their parameters (`logicscout/worlds/mechanisms.py`):

| mechanism | law |
|---|---|
| delay | produced amount lands d steps later (d 1-3) |
| cooldown | producer does nothing for k steps after an effective use |
| window | producer works only when `t % p < w` |
| capacity | production fills a buffer capped at `cap` (excess lost); transfer moves it to the output |
| resource | hidden reservoir: each use costs c, refills r per step; a coarse gauge = reservoir // q |
| ordering | producer works only if the arming control was used within k steps |
| control | `level` control sets a gain bonus, either inverted (3 - level) or rate-limited (one step per use) |
| threshold | each use adds heat (cools 1/step); above x production locks for k steps |

- Objective: `Reach <reading> >= N within H steps`, where N = ceil(0.8 x best result of a beam search over
  the true laws) from the worst calibration start. Random play almost never reaches it.

## Learnability
`reference_theory(laws)` writes every mechanism as LogicScout DSL rules (integer arithmetic, `t % p`,
`mem` counters, a `mem` pipeline for delays). Tests show it predicts generated transitions with accuracy 1.0.

## Hidden change
`shift(seed)` changes one parameter of one composed mechanism (delay length, cooldown, window opening,
capacity, refill rate, arming span, control mode, heat limit). Shifts survive `reset`.

## Per-variant manual
`World.manual()` is a classmethod, but Forge's manual depends on the variant. A Forge instance sets
`self.manual` (and `self.instance_manual`), which shadows the classmethod, so `world.manual()` on an instance
returns the right manual. Class-level callers should use `ForgeWorld.manual_for(variant)` and
`ForgeWorld.referee_cases_for(variant)`.

## Out-of-family systems (`x<seed>`)
In-family systems are new combinations of the eight mechanisms above, and the rule miner searches exactly
those shapes. To measure transfer beyond that family, `x<seed>` takes an in-family base (3-5 mechanisms) and adds
2-4 mechanisms that are **not** in the generator family or in the miner's templates
(`OUT_OF_FAMILY` in `logicscout/worlds/mechanisms.py`):

| mechanism | law |
|---|---|
| noise | the objective reading (and one other numeric reading) shows the true value plus -1/0/+1 jitter; success is judged on the true value |
| saturation | each production yields `ceil(gain * s / (s + level reached))`: diminishing returns |
| modes | a hidden 3-mode cycle (normal, weak = half yield, strong = +b) advances every k effective producer uses; the mode and its counter are unobserved |
| drift | gradual wear: the producer's gain drops by 1 every n steps (floor 1), instead of an abrupt shift |

Everything is deterministic per (variant, reset seed, actions); the jitter is a pure function of
(system, reset seed, t, reading). Manuals contain no law parameters (tested). The objective is calibrated the
same way as in-family (beam search over the true laws, producer spam rejected).

**No exact reference theory is claimed for x-variants.** `best_reference_accuracy(variant)` reports the
prediction accuracy of the in-family reference theory (every in-family mechanism written exactly in the DSL):
1.0 on g-variants, below 1.0 on x-variants. It is the in-family ceiling, not an upper bound on what a
richer theory could reach. `reference_accuracies(variant)` also gives changed-only accuracy.

## In-family vs out-of-family
No-model evaluation (the `no_model` bench arm: every model call fails immediately, 0 calls), same probe budget
and settings, no hidden change, 10 in-family systems `g101-g110` vs 10 out-of-family systems `x101-x110`
(seeds not used in tuning), 6 held-out referee cases each. Prediction accuracy is over the referee's
random-policy transitions; changed-only scores only (step, reading) pairs whose value changed (persistence
scores 0 there). Oracle = beam search over the true simulator (width 48).

| | in-family (g101-g110) | out-of-family (x101-x110) |
|---|---|---|
| held-out goal success, scout (no model) | 13/60 cases (0.22) | 6/60 cases (0.10) |
| random policy | 2/60 (0.03) | 9/60 (0.15) |
| oracle (true laws) | 60/60 (1.00) | 60/60 (1.00) |
| prediction accuracy, learned theory | 0.92 | 0.72 |
| prediction accuracy, in-family reference (ceiling) | 1.00 | 0.78 |
| changed-only accuracy, learned theory | 0.88 | 0.57 |
| changed-only accuracy, in-family reference | 1.00 | 0.62 |
| persistence baseline | 0.68 | 0.51 |

Reading it honestly:
- Out of family, the learned theory loses 20 points of plain accuracy and 31 points of changed-only accuracy.
  Most of that loss is shared by the exact in-family reference theory, i.e. the hypothesis language cannot
  express noise, saturation, hidden modes or wear, and the scout does not invent them.
- Goal success halves (0.22 -> 0.10) and, out of family, is **below the random policy** (0.15). One system
  (x107) is easy for random play (5/6) while the scout fails it; one (x109) the scout solves 6/6.
- Even in family, the code-only scout reaches the goal in only 13/60 held-out cases against an oracle at 60/60:
  a good predictive theory (0.92) is not yet a good controller on these systems.
- 10 systems per arm and 6 cases each: differences of a few cases are within noise.
