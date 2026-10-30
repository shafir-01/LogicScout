"""Independent referee: scores a theory + playbook on held-out cases against ground truth.

Privileged: imports worlds directly. Nothing the scout runs may import this module.
"""
from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

from logicscout.contracts import (
    Action,
    ActionSpec,
    Case,
    CaseResult,
    Event,
    Objective,
    Observation,
    Playbook,
    RefereeReport,
    Theory,
    WorldManual,
)
from logicscout.logbook import canonical
from logicscout.referee import audit
from logicscout.worlds.base import REGISTRY, World, load_all

N_TRANSITIONS = 30
IDLE_NAMES = ("wait", "idle", "noop", "hold", "coast", "pass")
PolicyFactory = Callable[[World, WorldManual, Objective], Any]  # returns an object with next_action/after_step


def world_class(world_id: str) -> type[World]:
    if world_id not in REGISTRY:
        load_all()
    if world_id not in REGISTRY:
        raise KeyError(f"unknown world {world_id!r}")
    return REGISTRY[world_id]


def objective_of(manual: WorldManual, objective_id: str) -> Objective:
    for o in manual.objectives:
        if o.id == objective_id:
            return o
    raise KeyError(f"unknown objective {objective_id!r} for {manual.world_id}")


def manual_of(cls: type[World], variant: str = "standard", world: World | None = None) -> WorldManual:
    """Generated worlds have a manual per variant (instance_manual / manual_for)."""
    m = getattr(world, "instance_manual", None) if world is not None else None
    if m is None and variant != "standard" and hasattr(cls, "manual_for"):
        m = cls.manual_for(variant)
    return m or cls.manual()


def cases_for(cls: type[World], objective_id: str, variant: str = "standard") -> list[Case]:
    """Held-out cases for this objective, renamed to opaque ids (case-0, case-1, ...)."""
    raw = cls.referee_cases_for(variant) if hasattr(cls, "referee_cases_for") else cls.referee_cases()
    cases = [c for c in raw if c.objective_id == objective_id]
    return [c.model_copy(update={"case_id": f"case-{i}"}) for i, c in enumerate(cases)]


# ---- policies ----------------------------------------------------------------------------

def random_action(spec_list: list[ActionSpec], rng: random.Random) -> Action:
    spec = rng.choice(spec_list)
    args: dict[str, Any] = {}
    for p in spec.params:
        if p.type == "enum" or p.choices:
            args[p.name] = rng.choice(p.choices or [""])
        elif p.type == "bool":
            args[p.name] = rng.random() < 0.5
        elif p.type == "int":
            args[p.name] = rng.randint(int(p.min if p.min is not None else 0), int(p.max if p.max is not None else 10))
        elif p.type == "float":
            args[p.name] = rng.uniform(p.min if p.min is not None else 0.0, p.max if p.max is not None else 1.0)
        else:
            args[p.name] = ""
    return Action(name=spec.name, args=args)


class RandomPolicy:
    def __init__(self, manual: WorldManual, seed: int) -> None:
        self.actions, self.rng = manual.actions, random.Random(seed)

    def next_action(self, obs: Observation) -> Action:
        return random_action(self.actions, self.rng)

    def after_step(self, obs: Observation) -> None:
        pass


class IdlePolicy:
    """Wait/no-op every step; falls back to the playbook fallback if the world has no idle action."""

    def __init__(self, manual: WorldManual, playbook: Playbook | None) -> None:
        spec = next((a for a in manual.actions if a.name in IDLE_NAMES and not a.params), None)
        self.runner = None
        self.action = Action(name=spec.name) if spec else None
        if self.action is None and playbook is not None:
            from logicscout.playbook import PlaybookRunner

            self.runner = PlaybookRunner(playbook.model_copy(update={"rules": []}))
        if self.action is None and self.runner is None:
            self.action = Action(name=manual.actions[0].name)

    def next_action(self, obs: Observation) -> Action:
        return self.runner.next_action(obs) if self.runner else self.action

    def after_step(self, obs: Observation) -> None:
        if self.runner:
            self.runner.after_step(obs)


def controller(theory: Theory, playbook: Playbook) -> PolicyFactory:
    def make(world: World, manual: WorldManual, objective: Objective) -> Any:
        if playbook.origin == "planner":
            from logicscout.planner import PlannerPolicy

            return PlannerPolicy(theory, manual, objective, depth=4, beam=16)
        from logicscout.playbook import PlaybookRunner

        return PlaybookRunner(playbook)

    return make


# ---- case runner ---------------------------------------------------------------------------

def run_case(cls: type[World], case: Case, objective_id: str, make_policy: PolicyFactory,
             horizon: int | None = None) -> CaseResult:
    """Fresh world of the case variant, reset(seed), run the policy to the horizon. Success is ground truth."""
    world = cls(variant=case.variant)
    manual = manual_of(cls, case.variant, world)
    objective = objective_of(manual, objective_id)
    obs = world.reset(case.seed)
    steps, cost, errors = 0, 0.0, 0
    try:
        policy = make_policy(world, manual, objective)
        limit = objective.horizon if horizon is None else min(horizon, objective.horizon)
        while steps < limit and not world.success(objective_id):
            action = policy.next_action(obs)
            res = world.act(action)
            steps += 1
            cost += res.cost
            errors += res.error is not None
            obs = res.observation
            policy.after_step(obs)
            if res.done:
                break
    except Exception as e:  # a crashing controller is a failed case, not a crashed referee
        return CaseResult(case_id=case.case_id, success=False, steps=steps, cost=cost,
                          note=f"controller error: {type(e).__name__}: {e}")
    ok = world.success(objective_id)
    note = f"{errors} inadmissible actions" if errors else ""
    return CaseResult(case_id=case.case_id, success=ok, steps=steps, cost=round(cost, 6), note=note)


def success_rate(results: list[CaseResult]) -> float:
    return round(sum(r.success for r in results) / len(results), 4) if results else 0.0


def collect_transitions(cls: type[World], case: Case, n: int = N_TRANSITIONS) -> list[tuple[Observation, Action, Observation]]:
    world = cls(variant=case.variant)
    manual = manual_of(cls, case.variant, world)
    rng = random.Random(case.seed * 7919 + 1)
    obs = world.reset(case.seed)
    out = []
    for _ in range(n):
        a = random_action(manual.actions, rng)
        res = world.act(a)
        out.append((obs, a, res.observation))
        obs = res.observation
        if res.done:
            break
    return out


def rule_contradictions(theory: Theory, transitions: list[tuple[Observation, Action, Observation]]) -> dict[str, int]:
    """Rule id -> number of held-out predictions it got wrong (as the final word on a field)."""
    from logicscout.theory import rule_stats

    return {rid: s["fired"] - s["correct"] for rid, s in rule_stats(theory, transitions).items()
            if s["fired"] > s["correct"]}


def report_digest(report: RefereeReport) -> str:
    return hashlib.sha256(canonical(report.model_dump(exclude={"digest"})).encode()).hexdigest()


# ---- main entry point -------------------------------------------------------------------------

def evaluate(
    world_id: str,
    theory: Theory,
    playbook: Playbook,
    objective_id: str,
    run_id: str,
    prompt_log: Path | None = None,
    events: list[Event] | list[dict] | None = None,
    variant: str = "standard",
    *,
    world_cls: type[World] | None = None,
    make_policy: PolicyFactory | None = None,
) -> RefereeReport:
    from logicscout.theory import accuracy, persistence_accuracy

    cls = world_cls or world_class(world_id)
    manual = manual_of(cls, variant)
    cases = cases_for(cls, objective_id, variant)
    notes: list[str] = []
    if not cases:
        notes.append(f"world declares no referee cases for objective {objective_id!r}")

    policy = make_policy or controller(theory, playbook)
    results = [run_case(cls, c, objective_id, policy) for c in cases]
    rand = [run_case(cls, c, objective_id, lambda w, m, o, s=c.seed: RandomPolicy(m, s)) for c in cases]
    idle = [run_case(cls, c, objective_id, lambda w, m, o: IdlePolicy(m, playbook)) for c in cases]

    acc, pers, n_tr, contradicted = 0.0, 0.0, 0, {}
    for c in cases:
        tr = collect_transitions(cls, c)
        if not tr:
            continue
        try:
            acc += accuracy(theory, tr) * len(tr)
        except Exception as e:
            notes.append(f"{c.case_id}: theory could not be evaluated ({type(e).__name__}: {e}); scored 0")
        pers += persistence_accuracy(tr) * len(tr)
        n_tr += len(tr)
        if c.variant == variant:
            try:
                for rid, k in rule_contradictions(theory, tr).items():
                    contradicted[rid] = contradicted.get(rid, 0) + k
            except Exception as e:
                notes.append(f"{c.case_id}: rule attribution failed ({type(e).__name__})")
    acc, pers = (round(acc / n_tr, 4), round(pers / n_tr, 4)) if n_tr else (0.0, 0.0)
    if contradicted:
        notes.append("rules contradicted on held-out standard cases: "
                     + ", ".join(f"{r} x{k}" for r, k in sorted(contradicted.items())))

    ev = [e if isinstance(e, Event) else Event.model_validate(e) for e in events] if events is not None else None
    law_variants = list(dict.fromkeys([variant] + (cls.variants() if variant == "standard" else [])))
    laws = [cls.default_laws(v) for v in law_variants]
    truths = [s for law in laws for s in cls.truth(law)]
    checks: dict[str, bool] = {}
    for name, (ok, n) in {
        "no_law_text_in_prompts": audit.no_law_text_in_prompts(prompt_log, truths, laws, manual),
        "scout_imports_clean": audit.scout_imports_clean(),
        "referee_cases_unseen": audit.referee_cases_unseen(ev, cases, manual),
        "events_digest_ok": audit.events_digest_ok(ev),
    }.items():
        checks[name] = ok
        notes.extend(n[:20] + ([f"{name}: {len(n) - 20} more"] if len(n) > 20 else []))

    notes.append(f"{len(cases)} held-out cases; prediction accuracy over {n_tr} random-policy transitions")
    notes.append("digest = sha256 of this report: proves integrity (not edited), not correctness")
    report = RefereeReport(
        run_id=run_id, world_id=world_id, theory_version=theory.version, playbook_id=playbook.id,
        cases=results, success_rate=success_rate(results), prediction_accuracy=acc,
        baselines={"random": success_rate(rand), "idle": success_rate(idle), "persistence_accuracy": pers},
        leakage_checks=checks, notes=notes,
    )
    report.digest = report_digest(report)
    return report
