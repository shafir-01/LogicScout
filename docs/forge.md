# Forge: generated unknown systems

Forge builds a system nobody has seen before a run. A seed deterministically composes 3-5 mechanisms
from the mechanism library over neutral components, so there is no public documentation to look up
(`briefing_topics` is empty on purpose).

## Variants
- `standard` = seed 1; `g<seed>` = any seed (e.g. `g42`). `ForgeWorld.generate(seed)` is `ForgeWorld(f"g{seed}")`.
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
