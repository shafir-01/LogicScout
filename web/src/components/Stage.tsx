import type { EpisodeItem, ProbeItem, RunView, TimelineItem } from "../state";
import { pct } from "../ui";
import { backInControl } from "./PhaseRail";

type Tone = "" | "ok" | "bad" | "warn";

const lastOf = <K extends TimelineItem["kind"]>(v: RunView, kind: K) =>
  [...v.timeline].reverse().find((t) => t.kind === kind) as Extract<TimelineItem, { kind: K }> | undefined;

const trim = (s: string) => s.trim().replace(/[.\s]+$/, "");
const lower = (s: string) => (/^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);

function probeLine(p: ProbeItem, v: RunView, retest: boolean): string {
  if (p.outcome) {
    const ids = p.probe.hypotheses ?? [];
    const settled = ids.map((id) => ({ id, st: p.hypOutcomes[id]?.status ?? p.outcome?.outcomes?.[id] }));
    const yes = settled.find((x) => x.st === "supported" && v.hypotheses[x.id]);
    if (yes) return `Confirmed: ${lower(trim(v.hypotheses[yes.id].statement))}.`;
    const no = settled.find((x) => x.st === "refuted" && v.hypotheses[x.id]);
    if (no) return `Ruled out: ${lower(trim(v.hypotheses[no.id].statement))}.`;
  }
  const q = trim(p.probe.purpose || "");
  if (!q) return retest ? "Re-testing what changed." : "Running an experiment.";
  return `${retest ? "Re-testing" : "Testing"}: ${lower(q)}${q.endsWith("?") ? "" : "."}`;
}

function goalLine(ep: EpisodeItem | undefined, prefix: string): string {
  if (ep?.goal) return `${prefix} Goal reached in ${ep.steps} steps.`;
  if (ep) return `${prefix} Working toward the goal — step ${ep.steps}.`;
  return `${prefix} Taking control.`;
}

export function liveSentence(v: RunView): { text: string; tone: Tone } {
  const ep = lastOf(v, "episode");
  if (v.failed) {
    const err = lastOf(v, "note");
    return { text: err?.error ? `Stopped: ${trim(err.text)}.` : "The run stopped.", tone: "bad" };
  }
  if (v.finished) {
    const r = v.referee;
    if (r) return { text: `Done. ${pct(r.success_rate)} success on cases it never saw.`, tone: r.success_rate >= 0.5 ? "ok" : r.success_rate > 0 ? "warn" : "bad" };
    if (v.recovered) return { text: goalLine(ep, "Recovered."), tone: "ok" };
    return { text: "Done.", tone: "" };
  }
  switch (v.phase) {
    case "encounter":
      return { text: v.manual ? `Meeting ${v.manual.title} for the first time.` : "Connecting…", tone: "" };
    case "briefing":
      return { text: v.sources.length ? `Reading public sources — ${v.sources.length} found.` : "Searching public knowledge for clues.", tone: "" };
    case "probing": {
      const p = lastOf(v, "probe");
      return { text: p ? probeLine(p, v, false) : "Designing a first experiment.", tone: "" };
    }
    case "theory": {
      const last = [...v.timeline].reverse().find((t) => t.kind === "theory" || t.kind === "playbook" || t.kind === "rejected");
      if (last?.kind === "rejected") return { text: "First plan failed in simulation. Revising.", tone: "warn" };
      if (last?.kind === "playbook") return { text: last.simulated?.success ? `Plan ready. In simulation it reaches the goal in ${last.simulated.steps} steps.` : "Plan ready.", tone: "" };
      if (last?.kind === "theory") return { text: `Its rules now predict ${pct(last.accuracy)} of what happens.`, tone: "" };
      return { text: "Writing down the rules it found.", tone: "" };
    }
    case "drift":
      return { text: v.drift === "confirmed" ? "Prediction failed — something changed." : "A prediction missed. Checking whether something changed.", tone: v.drift === "confirmed" ? "bad" : "warn" };
    case "reprobing": {
      const p = lastOf(v, "probe");
      return { text: p ? probeLine(p, v, true) : "Prediction failed — something changed. Investigating.", tone: "bad" };
    }
    case "recovered":
      return { text: goalLine(ep, "Recovered."), tone: "ok" };
    case "referee":
      return { text: "Scoring on cases it never saw.", tone: "" };
    case "control":
      if (v.drift === "confirmed" && backInControl(v)) return { text: goalLine(ep, "Back in control with revised rules."), tone: "" };
      if (v.drift === "confirmed") return { text: "Prediction failed — something changed.", tone: "bad" };
      if (v.drift === "suspected") return { text: "A prediction missed. Checking whether something changed.", tone: "warn" };
      if (v.recovered) return { text: goalLine(ep, "Recovered."), tone: "ok" };
      if (v.shifted) return { text: "The rules just changed. It hasn't been told.", tone: "bad" };
      return { text: goalLine(ep, "In control."), tone: "" };
  }
  return { text: "Working…", tone: "" };
}

export function LiveSentence({ v }: { v: RunView }) {
  const { text, tone } = liveSentence(v);
  return (
    <p className={`live${tone ? ` tone-${tone}` : ""}`} aria-live="polite">
      <span key={text.replace(/\d+/g, "#")} className="live-text">{text}</span>
    </p>
  );
}

export function BigNumbers({ v }: { v: RunView }) {
  const latest = [...v.versions].sort((a, b) => a.version - b.version).at(-1);
  const eps = v.timeline.filter((t): t is EpisodeItem => t.kind === "episode");
  const goals = eps.filter((e) => e.goal).length;
  const probes = v.timeline.filter((t) => t.kind === "probe").length;
  const budget = v.config?.probe_budget ?? v.manual?.probe_budget;
  return (
    <dl className="numbers">
      <div>
        <dt>Prediction accuracy</dt>
        <dd className="n-val">{pct(latest?.accuracy)}</dd>
        <dd className="n-sub">{latest && Number.isFinite(latest.baseline) ? `baseline ${pct(latest.baseline)}` : " "}</dd>
      </div>
      <div>
        <dt>Goal</dt>
        <dd className="n-val">{eps.length ? <>{goals}<span className="n-of">/{eps.length}</span></> : "–"}</dd>
        <dd className="n-sub">{eps.length ? "episodes reached" : " "}</dd>
      </div>
      <div>
        <dt>Experiments</dt>
        <dd className="n-val">{probes}</dd>
        <dd className="n-sub">{budget && v.probeSteps <= budget ? `${v.probeSteps} of ${budget} steps` : `${v.probeSteps} steps`}</dd>
      </div>
    </dl>
  );
}
