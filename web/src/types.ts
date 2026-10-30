export type JSONV = any;
export type Dict = Record<string, JSONV>;

export interface ParamSpec { name: string; type: string; choices?: string[] | null; min?: number | null; max?: number | null; description?: string }
export interface ActionSpec { name: string; params: ParamSpec[]; description?: string }
export interface FieldSpec { name: string; type: string; description?: string }
export interface Objective { id: string; text: string; success: string; horizon: number }
export interface WorldManual {
  world_id: string; title: string; domain: string; summary: string;
  actions: ActionSpec[]; observations: FieldSpec[]; objectives: Objective[];
  probe_budget: number; briefing_topics?: string[]; layout?: Dict;
}
export interface Action { name: string; args?: Dict }
export interface Observation { t: number; fields: Dict; events?: string[] }

export type RuleStatus = "tentative" | "supported" | "refuted" | "retired";
export type RuleSource = "probe" | "briefing" | "transfer" | "prior";
export interface Rule {
  id: string; statement: string; kind?: string; action?: string; when?: string;
  effects?: Record<string, string>; memory?: Record<string, string>; delay?: number;
  status: RuleStatus; confidence: number; evidence: number[]; source: RuleSource; citations: string[];
}
export interface Theory { world_id: string; version: number; parent?: number | null; memory?: Dict; rules: Rule[]; unknowns: string[]; note?: string }
export interface ActionTemplate { name: string; args?: Record<string, string> }
export interface PlaybookRule { when: string; do: ActionTemplate; why?: string }
export interface Playbook {
  id: string; world_id: string; objective_id: string; theory_version: number;
  origin: "synthesized" | "planner"; memory?: Dict; updates?: Record<string, string>;
  rules: PlaybookRule[]; fallback: ActionTemplate;
}
export interface Hypothesis { id: string; statement: string; rule?: Rule; rivals: string[]; status: "open" | "supported" | "refuted"; source: RuleSource }
export interface Probe { id: string; purpose: string; hypotheses: string[]; seed?: number | null; actions: Action[]; score?: number }
export interface ProbeOutcome { probe_id: string; observations: Observation[]; outcomes: Record<string, "supported" | "refuted" | "inconclusive">; surprises: string[] }
export interface Mismatch { field: string; predicted: JSONV; observed: JSONV; rule_ids?: string[] }

export type Phase = "encounter" | "briefing" | "probing" | "theory" | "control" | "drift" | "reprobing" | "recovered" | "referee" | "done" | "failed";

export interface RunConfig { world_id: string; objective_id?: string | null; seed?: number; use_briefing: boolean; use_transfer: boolean; probe_budget?: number | null; shift_after?: number | null }
export interface LSEvent { seq: number; run_id: string; ts: number; kind: string; phase: Phase; data: Dict; digest: string }
export interface ModelCall {
  purpose: string; tier: "fast" | "deep"; model: string; provider: string; latency_ms: number;
  prompt_tokens?: number | null; completion_tokens?: number | null; ok: boolean; escalated: boolean; error?: string | null;
}
export interface CaseResult { case_id: string; success: boolean; steps: number; cost: number; note?: string }
export interface RefereeReport {
  run_id: string; world_id: string; theory_version: number; playbook_id: string; cases: CaseResult[];
  success_rate: number; prediction_accuracy: number; baselines: Record<string, number>;
  leakage_checks: Record<string, boolean>; notes: string[]; digest: string;
}
export interface RunState {
  run_id: string; config: RunConfig; phase: Phase; live: boolean; theory?: Theory | null; playbook?: Playbook | null;
  hypotheses?: Hypothesis[]; metrics?: Dict; referee?: RefereeReport | null; started_at?: number; finished_at?: number | null;
}
