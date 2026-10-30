import type {
  Action, Dict, Hypothesis, LSEvent, ModelCall, Mismatch, Phase, Playbook, Probe, ProbeOutcome,
  RefereeReport, RunConfig, RunState, Theory, WorldManual,
} from "./types";

export interface ProbeItem {
  kind: "probe"; seq: number; probe: Probe; steps: number; outcome?: ProbeOutcome;
  hypOutcomes: Record<string, { status: "supported" | "refuted"; reason?: string }>;
}
export interface EpisodeItem {
  kind: "episode"; seq: number; episode: number; steps: number; mismatches: number; goal: boolean;
}
export type TimelineItem =
  | ProbeItem
  | EpisodeItem
  | { kind: "theory"; seq: number; version: number; accuracy: number; baseline: number; note?: string }
  | { kind: "playbook"; seq: number; id: string; origin: string; simulated?: Sim }
  | { kind: "rejected"; seq: number; text: string }
  | { kind: "shift"; seq: number }
  | { kind: "drift"; seq: number; level: "suspected" | "confirmed"; mismatches?: Mismatch[]; surprise?: number; rules?: string[] }
  | { kind: "recovery"; seq: number; stepsDown?: number; probesUsed?: number }
  | { kind: "referee"; seq: number; rate: number }
  | { kind: "trial"; seq: number; real?: boolean; predicted?: boolean; accepted?: boolean; steps?: number; mismatch?: number }
  | { kind: "note"; seq: number; text: string; error?: boolean };

export interface Sim { success?: boolean; steps?: number }
export interface Source { url: string; title?: string; published?: string | null }
export interface Claim { claim: string; status: "confirmed" | "contradicted" | "untested"; citations: string[] }

export interface RunView {
  lastSeq: number;
  phase: Phase;
  live: boolean | null;
  finished: boolean;
  failed: boolean;
  config: RunConfig | null;
  manual: WorldManual | null;
  hypotheses: Record<string, Hypothesis>;
  timeline: TimelineItem[];
  theory: Theory | null;
  versions: { version: number; accuracy: number; baseline: number }[];
  playbook: Playbook | null;
  simulated: Sim | null;
  obs: Dict | null;
  prevObs: Dict | null;
  obsT: number | null;
  obsTick: number;
  lastAction: Action | null;
  probeSteps: number;
  controlSteps: number;
  shifted: boolean;
  drift: "none" | "suspected" | "confirmed";
  recovered: boolean;
  driftRules: string[];
  recoveryDiff: Dict | null;
  queries: string[];
  sources: Source[];
  claims: Hypothesis[];
  checked: Claim[] | null;
  mechanisms: unknown[];
  referee: RefereeReport | null;
  calls: ModelCall[];
  metrics: Dict;
  safetyViolations: number;
}

export const initialView: RunView = {
  lastSeq: -1, phase: "encounter", live: null, finished: false, failed: false, config: null, manual: null,
  hypotheses: {}, timeline: [], theory: null, versions: [], playbook: null, simulated: null,
  obs: null, prevObs: null, obsT: null, obsTick: 0, lastAction: null, probeSteps: 0, controlSteps: 0,
  shifted: false, drift: "none", recovered: false, driftRules: [], recoveryDiff: null, queries: [], sources: [], claims: [], checked: null,
  mechanisms: [], referee: null, calls: [], metrics: {}, safetyViolations: 0,
};

export type ViewAction =
  | { type: "event"; ev: LSEvent }
  | { type: "events"; evs: LSEvent[] }
  | { type: "state"; state: RunState }
  | { type: "reset" };

function obsFields(o: unknown): { fields: Dict | null; t: number | null } {
  if (!o || typeof o !== "object") return { fields: null, t: null };
  const r = o as Dict;
  if (r.fields && typeof r.fields === "object") return { fields: r.fields as Dict, t: typeof r.t === "number" ? r.t : null };
  return { fields: r, t: null };
}

function withObs(s: RunView, observation: unknown, action: unknown): RunView {
  const { fields, t } = obsFields(observation);
  if (!fields) return s;
  return { ...s, prevObs: s.obs, obs: fields, obsT: t, obsTick: s.obsTick + 1, lastAction: (action as Action) ?? s.lastAction };
}

function updateProbe(s: RunView, probeId: string, f: (p: ProbeItem) => ProbeItem): RunView {
  let hit = false;
  const timeline = s.timeline.map((it) => {
    if (it.kind === "probe" && it.probe.id === probeId) { hit = true; return f(it); }
    return it;
  });
  return hit ? { ...s, timeline } : s;
}

const ENDED: Phase[] = ["done", "failed"];
const num = (x: unknown) => (typeof x === "number" ? x : NaN);

/** Safety-limit violations seen so far (events or server metrics), or null when the system has no limits and none were reported. */
export function safetyCount(v: RunView): number | null {
  const m = Number(v.metrics?.safety_violations);
  const n = Math.max(v.safetyViolations, Number.isFinite(m) ? m : 0);
  return v.manual?.safety?.length || n > 0 || Number.isFinite(m) ? n : null;
}

export function apply(s: RunView, ev: LSEvent): RunView {
  if (ev.seq <= s.lastSeq) return s;
  const d = ev.data ?? {};
  s = { ...s, lastSeq: ev.seq, phase: ev.phase ?? s.phase };
  const push = (it: TimelineItem): TimelineItem[] => [...s.timeline, it];
  switch (ev.kind) {
    case "phase": {
      const phase = d.phase as Phase;
      return {
        ...s, phase,
        finished: s.finished || ENDED.includes(phase),
        failed: s.failed || phase === "failed",
      };
    }
    case "run.started":
      return { ...s, config: (d.config as RunConfig) ?? s.config, manual: (d.manual as WorldManual) ?? s.manual };
    case "run.finished":
      return { ...s, finished: true };
    case "run.failed":
      return { ...s, finished: true, failed: true, timeline: push({ kind: "note", seq: ev.seq, text: String(d.message ?? d.error ?? "Run failed"), error: true }) };
    case "hypothesis.proposed": {
      const h = d.hypothesis as Hypothesis;
      if (!h?.id) return s;
      return { ...s, hypotheses: { ...s.hypotheses, [h.id]: h } };
    }
    case "hypothesis.supported":
    case "hypothesis.refuted": {
      const status = ev.kind === "hypothesis.supported" ? "supported" : "refuted";
      const id = String(d.id);
      const h = s.hypotheses[id];
      if (h) s = { ...s, hypotheses: { ...s.hypotheses, [id]: { ...h, status } } };
      if (d.probe_id) {
        s = updateProbe(s, String(d.probe_id), (p) => ({ ...p, hypOutcomes: { ...p.hypOutcomes, [id]: { status, reason: d.reason as string | undefined } } }));
      }
      return s;
    }
    case "probe.designed": {
      const probe = d.probe as Probe;
      if (!probe?.id) return s;
      return { ...s, timeline: push({ kind: "probe", seq: ev.seq, probe, steps: 0, hypOutcomes: {} }) };
    }
    case "probe.step":
      s = updateProbe(s, String(d.probe_id), (p) => ({ ...p, steps: p.steps + 1 }));
      return withObs({ ...s, probeSteps: s.probeSteps + 1 }, d.observation, d.action);
    case "probe.outcome": {
      const o = d.outcome as ProbeOutcome;
      if (!o?.probe_id) return s;
      return updateProbe(s, o.probe_id, (p) => ({ ...p, outcome: o }));
    }
    case "theory.revised": {
      const th = d.theory as Theory | undefined;
      const accuracy = num(d.accuracy);
      const baseline = num(d.baseline_accuracy);
      const version = th?.version ?? s.versions.length;
      return {
        ...s,
        theory: th ?? s.theory,
        recoveryDiff: s.drift === "confirmed" && d.diff && typeof d.diff === "object" ? (d.diff as Dict) : s.recoveryDiff,
        versions: [...s.versions.filter((v) => v.version !== version), { version, accuracy, baseline }],
        timeline: push({ kind: "theory", seq: ev.seq, version, accuracy, baseline, note: th?.note }),
      };
    }
    case "playbook.compiled": {
      const pb = d.playbook as Playbook | undefined;
      const sim = (d.simulated as Sim) ?? null;
      return { ...s, playbook: pb ?? s.playbook, simulated: sim, timeline: push({ kind: "playbook", seq: ev.seq, id: pb?.id ?? "", origin: pb?.origin ?? "", simulated: sim ?? undefined }) };
    }
    case "playbook.rejected": {
      const why = d.reason ?? (Array.isArray(d.errors) ? d.errors.join("; ") : d.errors);
      return { ...s, timeline: push({ kind: "rejected", seq: ev.seq, text: String(why ?? "rejected in simulation") }) };
    }
    case "control.step": {
      const ep = Number(d.episode ?? 0);
      const mm = Array.isArray(d.mismatches) ? d.mismatches.length : 0;
      const tl = [...s.timeline];
      let idx = -1;
      for (let i = tl.length - 1; i >= 0; i--) { const it = tl[i]; if (it.kind === "episode" && it.episode === ep) { idx = i; break; } }
      if (idx >= 0) {
        const it = tl[idx] as EpisodeItem;
        tl[idx] = { ...it, steps: Math.max(it.steps + 1, Number(d.step ?? 0) + 1), mismatches: it.mismatches + mm };
      } else {
        tl.push({ kind: "episode", seq: ev.seq, episode: ep, steps: 1, mismatches: mm, goal: false });
      }
      return withObs({ ...s, timeline: tl, controlSteps: s.controlSteps + 1 }, d.observation, d.action);
    }
    case "control.goal": {
      const ep = Number(d.episode ?? 0);
      const steps = Number(d.steps ?? 0);
      let hit = false;
      const tl = s.timeline.map((it) => {
        if (it.kind === "episode" && it.episode === ep) { hit = true; return { ...it, goal: true, steps: steps || it.steps }; }
        return it;
      });
      if (!hit) tl.push({ kind: "episode", seq: ev.seq, episode: ep, steps, mismatches: 0, goal: true });
      return { ...s, timeline: tl };
    }
    case "shift.applied":
      return { ...s, shifted: true, recovered: false, timeline: push({ kind: "shift", seq: ev.seq }) };
    case "drift.suspected":
      return {
        ...s, drift: s.drift === "confirmed" ? "confirmed" : "suspected",
        timeline: push({ kind: "drift", seq: ev.seq, level: "suspected", mismatches: d.mismatches as Mismatch[], surprise: d.surprise as number }),
      };
    case "drift.confirmed":
      return { ...s, drift: "confirmed", driftRules: (d.rules_implicated as string[]) ?? [], timeline: push({ kind: "drift", seq: ev.seq, level: "confirmed", rules: d.rules_implicated as string[] }) };
    case "recovery.done":
      return { ...s, recovered: true, drift: "none", timeline: push({ kind: "recovery", seq: ev.seq, stepsDown: d.steps_down as number, probesUsed: d.probes_used as number }) };
    case "briefing.query":
      return { ...s, queries: [...s.queries, String(d.query ?? "")] };
    case "briefing.source":
      return { ...s, sources: [...s.sources, { url: String(d.url ?? ""), title: d.title as string, published: d.published as string }] };
    case "briefing.claim": {
      const h = d.hypothesis as Hypothesis;
      if (!h) return s;
      return { ...s, claims: [...s.claims, h], hypotheses: h.id ? { ...s.hypotheses, [h.id]: h } : s.hypotheses };
    }
    case "briefing.checked":
      return { ...s, checked: (d.claims as Claim[]) ?? [] };
    case "transfer.loaded":
      return { ...s, mechanisms: (d.mechanisms as unknown[]) ?? [] };
    case "referee.report": {
      const r = d.report as RefereeReport | undefined;
      return { ...s, referee: r ?? s.referee, timeline: r ? push({ kind: "referee", seq: ev.seq, rate: r.success_rate }) : s.timeline };
    }
    case "playbook.trial":
      return { ...s, timeline: push({ kind: "trial", seq: ev.seq, real: d.real_success as boolean, predicted: d.predicted_success as boolean, accepted: d.accepted as boolean, steps: d.steps as number, mismatch: d.mismatch_rate as number }) };
    case "safety.violation":
      return { ...s, safetyViolations: s.safetyViolations + 1 };
    case "model.call":
      return { ...s, calls: [...s.calls, (d.call ?? d) as ModelCall] };
    case "note":
      return { ...s, timeline: push({ kind: "note", seq: ev.seq, text: String(d.text ?? "") }) };
    case "error":
      return { ...s, timeline: push({ kind: "note", seq: ev.seq, text: String(d.message ?? "error"), error: true }) };
    default:
      return s;
  }
}

export function reducer(s: RunView, a: ViewAction): RunView {
  switch (a.type) {
    case "reset":
      return initialView;
    case "event":
      return apply(s, a.ev);
    case "events":
      return a.evs.reduce(apply, s);
    case "state": {
      const st = a.state;
      const hyps = { ...s.hypotheses };
      for (const h of st.hypotheses ?? []) if (!hyps[h.id]) hyps[h.id] = h;
      return {
        ...s,
        live: st.live,
        config: s.config ?? st.config,
        phase: s.lastSeq < 0 ? st.phase : s.phase,
        finished: s.finished || st.finished_at != null || ENDED.includes(st.phase),
        theory: s.theory ?? st.theory ?? null,
        playbook: s.playbook ?? st.playbook ?? null,
        referee: s.referee ?? st.referee ?? null,
        hypotheses: hyps,
        metrics: st.metrics ?? s.metrics,
      };
    }
  }
}
