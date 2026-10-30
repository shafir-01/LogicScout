"""Shared contracts. Every module talks to every other module through these types.

Public side (the scout may see):   WorldManual, Action, Observation, StepResult, WorldPort.
Private side (scout must never see): World internals, ShiftRecord, Case, referee truth.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

JSON = dict[str, Any]

# --------------------------------------------------------------------------------------
# World interface: public
# --------------------------------------------------------------------------------------


class ParamSpec(BaseModel):
    name: str
    type: Literal["int", "float", "str", "bool", "enum"]
    choices: list[str] | None = None
    min: float | None = None
    max: float | None = None
    description: str = ""


class ActionSpec(BaseModel):
    name: str
    params: list[ParamSpec] = Field(default_factory=list)
    description: str = ""  # what the control is called, never what it secretly does


class FieldSpec(BaseModel):
    name: str
    type: Literal["int", "float", "str", "bool", "list", "dict"]
    description: str = ""


class Objective(BaseModel):
    id: str
    text: str  # human goal, e.g. "Deliver 6 priority messages to shore"
    success: str  # DSL expression over obs.* that the scout can watch, e.g. "obs.delivered >= 6"
    horizon: int  # max control steps


class WorldManual(BaseModel):
    """Everything the scout is allowed to know before its first action. No laws."""

    world_id: str
    title: str
    domain: str
    summary: str  # one line, no rules
    actions: list[ActionSpec]
    observations: list[FieldSpec]
    objectives: list[Objective]
    probe_budget: int  # default number of probe steps
    lab_seeds: tuple[int, int] = (0, 1000)  # seeds the scout may reset to; referee uses others
    briefing_topics: list[str] = Field(default_factory=list)  # public-domain search topics
    layout: JSON = Field(default_factory=dict)  # visual hints for the UI only (nodes, edges, grid)
    safety: list[str] = Field(default_factory=list)  # operator limits: DSL over obs.* that must always hold (public, not laws)


class Action(BaseModel):
    name: str
    args: JSON = Field(default_factory=dict)


class Observation(BaseModel):
    t: int
    fields: JSON
    events: list[str] = Field(default_factory=list)


class StepResult(BaseModel):
    observation: Observation
    cost: float = 0.0
    done: bool = False
    error: str | None = None  # admissibility error the scout may see (bad arg, unknown action)


@runtime_checkable
class WorldPort(Protocol):
    """The ONLY handle the scout gets on a world. Implemented over HTTP (sandbox) or in-process."""

    def manual(self) -> WorldManual: ...
    def reset(self, seed: int) -> Observation: ...  # seed must be inside manual.lab_seeds
    def observe(self) -> Observation: ...
    def act(self, action: Action) -> StepResult: ...


# --------------------------------------------------------------------------------------
# World interface: private (sandbox + referee only)
# --------------------------------------------------------------------------------------


class ShiftRecord(BaseModel):
    """What a hidden change did. Never shown to the scout; shown in the debrief."""

    kind: str
    description: str
    before: JSON
    after: JSON
    at_t: int


class Case(BaseModel):
    """A held-out referee case. Never shown to the scout."""

    case_id: str
    seed: int
    variant: str = "standard"
    objective_id: str


# --------------------------------------------------------------------------------------
# Learned knowledge: theory (world model) and playbook (compiled controller)
# Expressions use the LogicScout DSL (logicscout/dsl.py): obs.*, args.*, mem.*, t,
# literals, arithmetic, comparisons, and/or/not, x if c else y, min/max/abs/round/len, `in`.
# --------------------------------------------------------------------------------------

RuleKind = Literal["transition", "precondition", "constraint", "delay", "resource", "periodic", "other"]
RuleStatus = Literal["tentative", "supported", "refuted", "retired"]
RuleSource = Literal["probe", "briefing", "transfer", "prior"]


class Rule(BaseModel):
    id: str
    statement: str  # plain words, shown in the UI
    kind: RuleKind = "transition"
    action: str = "*"  # action name it applies to; "*" = every step
    when: str = "True"  # DSL condition evaluated on (obs, args, mem, t) BEFORE the step
    effects: dict[str, str] = Field(default_factory=dict)  # obs field -> DSL expr for its next value
    memory: dict[str, str] = Field(default_factory=dict)  # mem var -> DSL expr for its next value
    delay: int = 0  # effects land this many steps later
    status: RuleStatus = "tentative"
    confidence: float = 0.5
    evidence: list[int] = Field(default_factory=list)  # logbook seq numbers
    source: RuleSource = "probe"
    citations: list[str] = Field(default_factory=list)  # URLs when source == "briefing"


class Theory(BaseModel):
    """The scout's executable model of a world. Prediction = copy obs, then apply matching rules."""

    world_id: str
    version: int = 0
    parent: int | None = None
    memory: JSON = Field(default_factory=dict)  # initial values of latent variables the scout posits
    rules: list[Rule] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    note: str = ""  # what changed in this version, plain words


class ActionTemplate(BaseModel):
    name: str
    args: dict[str, str] = Field(default_factory=dict)  # arg -> DSL expr


class PlaybookRule(BaseModel):
    when: str  # DSL condition on (obs, mem, t)
    do: ActionTemplate
    why: str = ""


class Playbook(BaseModel):
    """Compiled controller. Runs without the model: first matching rule fires."""

    id: str
    world_id: str
    objective_id: str
    theory_version: int
    origin: Literal["synthesized", "planner"] = "synthesized"
    memory: JSON = Field(default_factory=dict)
    updates: dict[str, str] = Field(default_factory=dict)  # mem var -> DSL expr, applied after each step
    rules: list[PlaybookRule]
    fallback: ActionTemplate


# --------------------------------------------------------------------------------------
# Investigation
# --------------------------------------------------------------------------------------


class Hypothesis(BaseModel):
    id: str
    statement: str
    rule: Rule  # formal candidate; predictions come from running it through the predictor, not from the model
    rivals: list[str] = Field(default_factory=list)  # ids of competing hypotheses
    status: Literal["open", "supported", "refuted"] = "open"
    source: RuleSource = "probe"


class Probe(BaseModel):
    id: str
    purpose: str  # plain words: what this experiment distinguishes
    hypotheses: list[str]
    seed: int | None = None  # reset to this lab seed first; None = continue from current state
    actions: list[Action]
    predictions: dict[str, list[JSON]] = Field(default_factory=dict)  # hyp id -> predicted fields per step
    score: float = 0.0  # expected information (disagreement between hypotheses) per unit cost


class ProbeOutcome(BaseModel):
    probe_id: str
    observations: list[Observation]
    outcomes: dict[str, Literal["supported", "refuted", "inconclusive"]]
    surprises: list[str] = Field(default_factory=list)


class Mismatch(BaseModel):
    field: str
    predicted: Any
    observed: Any
    rule_ids: list[str] = Field(default_factory=list)  # rules that produced the prediction


# --------------------------------------------------------------------------------------
# Runs, events, model calls, referee
# --------------------------------------------------------------------------------------

Phase = Literal[
    "encounter", "briefing", "probing", "theory", "control",
    "drift", "reprobing", "recovered", "referee", "done", "failed",
]


class RunConfig(BaseModel):
    world_id: str
    objective_id: str | None = None  # default: first objective
    seed: int = 7
    variant: str = "standard"  # "standard" (lab); forge also accepts "g<seed>" = a freshly generated system
    use_briefing: bool = True  # Tavily public-knowledge priors
    use_transfer: bool = False  # mechanisms learned in other worlds
    probe_budget: int | None = None  # default: manual.probe_budget
    use_model: bool = True  # False: every model call fails fast (code-only run, zero calls)
    use_induction: bool = True  # False: no code-side rule fitting/mining (model-only hypotheses)
    shift_after: int | None = None  # auto hidden change after N control steps; None = only by button


class Event(BaseModel):
    seq: int
    run_id: str
    ts: float
    kind: str  # see logicscout/logbook.py EVENT_KINDS
    phase: Phase
    data: JSON = Field(default_factory=dict)
    digest: str = ""  # sha256 of canonical(seq, run_id, kind, data, prev digest)


class ModelCall(BaseModel):
    purpose: str
    tier: Literal["fast", "deep"]
    model: str  # model id as returned by the provider
    provider: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    ok: bool
    escalated: bool = False
    error: str | None = None
    request_sha: str = ""


@runtime_checkable
class LLM(Protocol):
    """Implemented by logicscout.llm.Nemotron. Returns parsed JSON or raises LLMError."""

    async def json(
        self,
        purpose: str,
        system: str,
        user: str,
        schema: JSON | None = None,
        tier: Literal["fast", "deep"] = "fast",
    ) -> JSON: ...


class CaseResult(BaseModel):
    case_id: str
    success: bool
    steps: int
    cost: float
    note: str = ""


class RefereeReport(BaseModel):
    run_id: str
    world_id: str
    theory_version: int
    playbook_id: str
    cases: list[CaseResult]
    success_rate: float
    prediction_accuracy: float  # theory vs truth on held-out transitions
    baselines: dict[str, float] = Field(default_factory=dict)  # name -> success rate on the same cases
    leakage_checks: dict[str, bool] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    digest: str = ""
    # Metrics that cannot hide behind quiet steps (held-out random-policy + controller trajectories).
    changed_accuracy: float | None = None  # accuracy only on (step, field) pairs whose value changed
    changed_baseline: float | None = None  # "nothing changes" on those same pairs: 0.0 by construction
    rollout_accuracy: dict[int, float] = Field(default_factory=dict)  # k -> open-loop k-step accuracy
    goal_field_accuracy: float | None = None  # accuracy on the fields the objective is defined over
    n_transitions: int | None = None  # held-out transitions scored by the metrics above
    n_changed: int | None = None  # (step, field) pairs that changed among them


class RunState(BaseModel):
    run_id: str
    config: RunConfig
    phase: Phase
    live: bool  # False = replay of a recorded run
    theory: Theory | None = None
    playbook: Playbook | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    metrics: JSON = Field(default_factory=dict)
    referee: RefereeReport | None = None
    started_at: float = 0.0
    finished_at: float | None = None
