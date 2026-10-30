// DEV ONLY. Synthetic events for UI development on the /dev route. Never used for real runs or recordings.
import type { LSEvent, Phase } from "../types";

let seq = 0;
let phase: Phase = "encounter";
const out: LSEvent[] = [];
const e = (kind: string, data: Record<string, unknown> = {}) => {
  if (kind === "phase") phase = data.phase as Phase;
  out.push({ seq: seq++, run_id: "dev-sample", ts: 0, kind, phase, data, digest: "" });
};

const manual = {
  world_id: "dev", title: "DEV sample network", domain: "sample", summary: "UI fixture",
  actions: [{ name: "route", params: [{ name: "link", type: "enum", choices: ["a", "b"] }] }, { name: "wait", params: [] }],
  observations: [{ name: "queue", type: "int" }, { name: "link_a", type: "int" }, { name: "link_b", type: "int" }, { name: "delivered", type: "int" }],
  objectives: [{ id: "o1", text: "Deliver 6 messages", success: "obs.delivered >= 6", horizon: 30 }],
  probe_budget: 24,
  layout: {
    kind: "graph",
    nodes: [{ id: "src", label: "source", x: 0, y: 1, field: "queue" }, { id: "a", label: "relay A", x: 1, y: 0, field: "link_a" },
      { id: "b", label: "relay B", x: 1, y: 2, field: "link_b" }, { id: "dst", label: "shore", x: 2, y: 1, field: "delivered" }],
    edges: [{ from: "src", to: "a" }, { from: "src", to: "b" }, { from: "a", to: "dst" }, { from: "b", to: "dst" }],
  },
};
const rule = (id: string, statement: string, status: string, confidence: number, source = "probe", citations: string[] = []) => ({
  id, statement, kind: "transition", action: "route", when: "args.link == 'a'", effects: { link_a: "obs.link_a + 1" },
  memory: {}, delay: 0, status, confidence, evidence: [12, 18], source, citations,
});
const obs = (t: number, q: number, a: number, b: number, d: number) => ({ t, fields: { queue: q, link_a: a, link_b: b, delivered: d }, events: [] });

e("phase", { phase: "encounter" });
e("run.started", { config: { world_id: "dev", use_briefing: true, use_transfer: false, seed: 7 }, manual });
e("phase", { phase: "briefing" });
e("briefing.query", { query: "store and forward relay" });
e("briefing.source", { url: "https://example.org/relay", title: "Sample source", published: "2024-01-01" });
e("briefing.claim", { hypothesis: { id: "b1", statement: "Each relay forwards one message per step", rule: rule("b1", "", "tentative", 0.4, "briefing", ["https://example.org/relay"]), rivals: [], status: "open", source: "briefing" } });
e("phase", { phase: "probing" });
e("hypothesis.proposed", { hypothesis: { id: "h1", statement: "Routing to A moves one message to relay A", rivals: ["h2"], status: "open", source: "probe" } });
e("hypothesis.proposed", { hypothesis: { id: "h2", statement: "Routing to A moves two messages to relay A", rivals: ["h1"], status: "open", source: "probe" } });
e("probe.designed", { probe: { id: "p1", purpose: "Does relay A take one message or two per step?", hypotheses: ["h1", "h2", "b1"], actions: [{ name: "route", args: { link: "a" } }, { name: "wait" }] } });
e("probe.step", { probe_id: "p1", action: { name: "route", args: { link: "a" } }, observation: obs(1, 9, 1, 0, 0) });
e("probe.step", { probe_id: "p1", action: { name: "wait", args: {} }, observation: obs(2, 9, 0, 0, 1) });
e("hypothesis.supported", { id: "h1", probe_id: "p1", reason: "predicted link_a=1, saw 1" });
e("hypothesis.refuted", { id: "h2", probe_id: "p1", reason: "predicted link_a=2, saw 1" });
e("probe.outcome", { outcome: { probe_id: "p1", observations: [], outcomes: { h1: "supported", h2: "refuted", b1: "inconclusive" }, surprises: ["delivered rose without a forward action"] } });
e("model.call", { purpose: "propose hypotheses", tier: "deep", model: "dev-model", provider: "dev", latency_ms: 2100, prompt_tokens: 1800, completion_tokens: 420, ok: true, escalated: false });
e("phase", { phase: "theory" });
e("theory.revised", { theory: { world_id: "dev", version: 1, rules: [rule("r1", "Routing to A moves one message to relay A", "supported", 0.9), rule("r2", "Relays deliver after one step", "tentative", 0.55, "briefing", ["https://example.org/relay"])], unknowns: ["What limits relay B?"], note: "first theory" }, diff: {}, accuracy: 0.62, baseline_accuracy: 0.41 });
e("theory.revised", { theory: { world_id: "dev", version: 2, rules: [rule("r1", "Routing to A moves one message to relay A", "supported", 0.94), rule("r2", "Relays deliver after one step", "supported", 0.8, "briefing", ["https://example.org/relay"]), rule("r3", "Relay B drops every third message", "refuted", 0.1)], unknowns: [], note: "delay confirmed" }, diff: {}, accuracy: 0.91, baseline_accuracy: 0.41 });
e("briefing.checked", { claims: [{ claim: "Each relay forwards one message per step", status: "confirmed", citations: ["https://example.org/relay"] }] });
e("playbook.compiled", { playbook: { id: "pb1", world_id: "dev", objective_id: "o1", theory_version: 2, origin: "synthesized", rules: [{ when: "obs.link_a == 0", do: { name: "route", args: { link: "'a'" } }, why: "keep A busy" }], fallback: { name: "wait", args: {} } }, simulated: { success: true, steps: 14 } });
e("phase", { phase: "control" });
for (let i = 0; i < 6; i++) e("control.step", { episode: 0, step: i, action: { name: "route", args: { link: "a" } }, predicted: {}, observation: obs(3 + i, 8 - i, 1, 0, i), mismatches: [] });
e("control.goal", { episode: 0, steps: 6 });
e("shift.applied", {});
e("control.step", { episode: 1, step: 0, action: { name: "route", args: { link: "a" } }, predicted: {}, observation: obs(10, 8, 0, 0, 0), mismatches: [{ field: "link_a", predicted: 1, observed: 0 }] });
e("phase", { phase: "drift" });
e("drift.suspected", { mismatches: [{ field: "link_a", predicted: 1, observed: 0 }], surprise: 3.2 });
e("drift.confirmed", { rules_implicated: ["r1"] });
e("phase", { phase: "reprobing" });
e("phase", { phase: "recovered" });
e("recovery.done", { steps_down: 4, probes_used: 5 });
e("phase", { phase: "referee" });
e("referee.report", { report: { run_id: "dev-sample", world_id: "dev", theory_version: 3, playbook_id: "pb2", cases: [{ case_id: "c1", success: true, steps: 12, cost: 0 }, { case_id: "c2", success: true, steps: 15, cost: 0 }, { case_id: "c3", success: false, steps: 30, cost: 0 }], success_rate: 0.67, prediction_accuracy: 0.88, baselines: { random: 0.1, greedy: 0.33 }, leakage_checks: { no_laws_in_prompts: true, held_out_seeds: true }, notes: [], digest: "0000" } });
e("phase", { phase: "done" });

export const SAMPLE_EVENTS: LSEvent[] = out;
