import { useEffect, useRef, useState, type ReactNode } from "react";
import type { EpisodeItem, ProbeItem, RunView, TimelineItem } from "../state";
import { pct } from "../ui";
import { backInControl } from "./PhaseRail";

type Tone = "" | "ok" | "bad" | "warn";

const lastOf = <K extends TimelineItem["kind"]>(v: RunView, kind: K) =>
  [...v.timeline].reverse().find((t) => t.kind === kind) as Extract<TimelineItem, { kind: K }> | undefined;

const trim = (s: string) => s.trim().replace(/\s+/g, " ").replace(/[.\s]+$/, "");
const lower = (s: string) => (/^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);
const cap = (s: string, n = 96) => {
  if (s.length <= n) return s;
  const cut = s.slice(0, n);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), n - 20)).replace(/[,;:\s]+$/, "")}…`;
};
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

const CODEY = /[=<>(){}[\]%`|&*]|'\w+'|\b(obs|args|mem)\.|_[a-z]|\b(rival|hypothes\w*|single-factor|probe|seed|dsl|predicate)\b/i;
/** Plain, human sentence safe to show on the main stage. */
const plain = (s: string | undefined) => !!s && s.length <= 140 && !CODEY.test(s);

function probeLine(p: ProbeItem, v: RunView, retest: boolean): string {
  if (p.outcome) {
    const ids = p.probe.hypotheses ?? [];
    const settled = ids.map((id) => ({ id, st: p.hypOutcomes[id]?.status ?? p.outcome?.outcomes?.[id] }));
    const yes = settled.find((x) => x.st === "supported");
    const no = settled.find((x) => x.st === "refuted");
    const say = (id: string) => { const t = v.hypotheses[id]?.statement; return plain(t) ? cap(lower(trim(t!))) : null; };
    if (yes) { const t = say(yes.id); return t ? `Confirmed: ${t}.` : retest ? "Found part of what changed." : "One more rule confirmed."; }
    if (no) { const t = say(no.id); return t ? `Ruled out: ${t}.` : "One idea ruled out."; }
    return retest ? "Still narrowing down what changed." : "Inconclusive. Designing a sharper test.";
  }
  const q = trim(p.probe.purpose || "");
  if (!plain(q)) {
    const n = v.timeline.filter((t) => t.kind === "probe").length;
    return retest ? "Re-testing what it thought it knew." : `Experiment ${n}: testing ${plural(Math.max(1, p.probe.hypotheses?.length ?? 1), "idea")}.`;
  }
  const body = cap(lower(q));
  return `${retest ? "Re-testing" : "Testing"}: ${body}${body.endsWith("?") || body.endsWith("…") ? "" : "."}`;
}

function goalLine(ep: EpisodeItem | undefined, prefix: string): string {
  if (ep?.goal) return `${prefix} Goal reached in ${plural(ep.steps, "step")}.`;
  if (ep) return `${prefix} Working toward the goal, step ${ep.steps}.`;
  return prefix === "In control." ? "Taking control." : prefix;
}

export function liveSentence(v: RunView, pendingShift = false): { text: string; tone: Tone } {
  const ep = lastOf(v, "episode");
  const changed = v.shifted && !v.recovered;
  if (v.failed) {
    const err = lastOf(v, "note");
    return { text: err?.error && plain(err.text) ? `Stopped: ${cap(lower(trim(err.text)), 80)}.` : "The run stopped unexpectedly.", tone: "bad" };
  }
  if (v.finished) {
    const r = v.referee;
    if (r) {
      const n = r.cases?.length ?? 0;
      const ok = r.cases?.filter((c) => c.success).length ?? 0;
      const text = n ? `Done. Reached the goal in ${ok} of ${n} situations it never saw.` : `Done. ${pct(r.success_rate)} success on situations it never saw.`;
      return { text, tone: r.success_rate >= 0.5 ? "ok" : "" };
    }
    if (v.recovered) return { text: "Done. It noticed the hidden change and recovered.", tone: "ok" };
    if (v.shifted) return { text: "Done. It did not fully recover from the change.", tone: "" };
    return { text: "Done.", tone: "" };
  }
  if (pendingShift && !changed) return { text: "Changing a hidden rule…", tone: "bad" };
  const lastPlan = [...v.timeline].reverse().find((t) => t.kind === "playbook" || t.kind === "rejected" || t.kind === "episode");
  const rejects = v.timeline.filter((t) => t.kind === "rejected").length;
  switch (v.phase) {
    case "encounter":
      return { text: v.manual ? "Meeting this system for the first time." : "Connecting…", tone: "" };
    case "briefing":
      if (v.config && !v.config.use_briefing) return { text: "Meeting this system for the first time.", tone: "" };
      return { text: v.sources.length ? `Reading what’s publicly known: ${plural(v.sources.length, "source")} so far.` : "Searching public knowledge for clues.", tone: "" };
    case "probing": {
      const p = lastOf(v, "probe");
      if (p) return { text: probeLine(p, v, false), tone: "" };
      const n = Object.keys(v.hypotheses).length;
      return { text: n ? `${plural(n, "guess", "guesses")} so far. Designing a first experiment.` : "Forming first guesses about how it works.", tone: "" };
    }
    case "theory": {
      const last = [...v.timeline].reverse().find((t) => t.kind === "theory" || t.kind === "playbook" || t.kind === "rejected");
      if (last?.kind === "rejected") return { text: `Its plan failed in simulation. Revising (try ${rejects + 1}).`, tone: "warn" };
      if (last?.kind === "playbook") return { text: last.simulated?.success && last.simulated.steps ? `Plan ready. In simulation it reaches the goal in ${plural(last.simulated.steps, "step")}.` : "Plan ready.", tone: "" };
      if (last?.kind === "theory") return { text: `Its rules now predict ${pct(last.accuracy)} of what happens next.`, tone: "" };
      return { text: "Writing down the rules it found.", tone: "" };
    }
    case "drift":
      if (!changed) return { text: "Its predictions are missing. Re-checking its rules.", tone: "warn" };
      return v.drift === "confirmed"
        ? { text: "A prediction failed. Something changed.", tone: "bad" }
        : { text: "A prediction missed. Checking whether something changed.", tone: "warn" };
    case "reprobing": {
      if (!changed) return { text: v.drift === "none" ? "Missed the goal. Refining its rules." : "Its predictions are missing. Re-checking its rules.", tone: "warn" };
      const p = lastOf(v, "probe");
      const drift = lastOf(v, "drift");
      const fresh = p && (!drift || p.seq > drift.seq);
      return { text: fresh ? probeLine(p, v, true) : "Something changed. Investigating what.", tone: "bad" };
    }
    case "recovered": {
      const rec = lastOf(v, "recovery");
      if (v.recovered) return { text: rec?.stepsDown ? `Recovered, ${plural(rec.stepsDown, "step")} after the change.` : "Recovered.", tone: "ok" };
      return { text: goalLine(ep, "Back in control with revised rules."), tone: "" };
    }
    case "referee":
      return { text: "Being tested on situations it has never seen.", tone: "" };
    case "control":
      if (lastPlan?.kind === "rejected") return { text: `Its plan failed in simulation. Revising (try ${rejects + 1}).`, tone: "warn" };
      if (changed) {
        const drift = lastOf(v, "drift");
        if (v.drift === "confirmed" && backInControl(v)) return { text: goalLine(ep, "Back in control with revised rules."), tone: "" };
        if (v.drift === "confirmed" && lastPlan && lastPlan.seq > (drift?.seq ?? 0)) return { text: goalLine(lastPlan.kind === "episode" ? ep : undefined, "Trying again with revised rules."), tone: "" };
        if (v.drift === "confirmed") return { text: "A prediction failed. Something changed.", tone: "bad" };
        if (v.drift === "suspected") return { text: "A prediction missed. Checking whether something changed.", tone: "warn" };
        return { text: "The rules just changed. It hasn’t been told.", tone: "bad" };
      }
      if (v.drift === "suspected") return { text: "A prediction missed. Double-checking.", tone: "warn" };
      if (v.recovered) return { text: goalLine(ep, "Recovered."), tone: "ok" };
      return { text: goalLine(ep, "In control."), tone: "" };
  }
  return { text: "Working…", tone: "" };
}

const shape = (t: string) => t.replace(/\d+/g, "#");

/** Holds each new sentence on screen for a moment so fast event bursts don't flicker. */
function useDwell(next: { text: string; tone: Tone }, urgent: boolean, ms = 1500) {
  const [shown, setShown] = useState(next);
  const since = useRef(Date.now());
  useEffect(() => {
    if (next.text === shown.text && next.tone === shown.tone) return;
    const show = () => { setShown(next); since.current = Date.now(); };
    if (urgent || shape(next.text) === shape(shown.text)) { setShown(next); return; }
    const wait = ms - (Date.now() - since.current);
    if (wait <= 0) { show(); return; }
    const t = window.setTimeout(show, wait);
    return () => clearTimeout(t);
  }, [next.text, next.tone, urgent]); // eslint-disable-line react-hooks/exhaustive-deps
  return shown;
}

export function LiveSentence({ v, pendingShift = false }: { v: RunView; pendingShift?: boolean }) {
  const { text, tone } = useDwell(liveSentence(v, pendingShift), v.finished || pendingShift);
  const loading = v.lastSeq < 0 && !v.config;
  return (
    <p className={`live${tone ? ` tone-${tone}` : ""}`} aria-live="polite">
      {loading
        ? <span className="skel skel-line" aria-label="Loading" />
        : <span key={shape(text)} className="live-text">{text}</span>}
    </p>
  );
}

function Tile({ label, value, sub, loading, title }: { label: string; value: ReactNode; sub: string; loading: boolean; title?: string }) {
  return (
    <div title={title}>
      <dt>{label}</dt>
      <dd className="n-val">{loading ? <span className="skel skel-num" /> : value}</dd>
      <dd className="n-sub">{loading ? " " : sub || " "}</dd>
    </div>
  );
}

export function BigNumbers({ v }: { v: RunView }) {
  const loading = v.lastSeq < 0 && !v.config;
  const latest = [...v.versions].sort((a, b) => a.version - b.version).at(-1);
  const eps = v.timeline.filter((t): t is EpisodeItem => t.kind === "episode");
  const goals = eps.filter((e) => e.goal).length;
  const probes = v.timeline.filter((t) => t.kind === "probe").length;
  const budget = v.config?.probe_budget ?? v.manual?.probe_budget;
  const r = v.referee;
  const cases = r?.cases ?? [];
  const hasBase = latest && Number.isFinite(latest.baseline);
  return (
    <dl className="numbers">
      <Tile
        label="Predicts correctly" loading={loading}
        value={pct(latest?.accuracy)}
        sub={hasBase ? `vs ${pct(latest.baseline)} if nothing changes` : latest ? "" : "after first experiments"}
        title={hasBase ? "Share of next-step values its rules predict correctly. Baseline assumes nothing changes." : undefined}
      />
      {r && cases.length ? (
        <Tile label="Unseen tests" loading={false}
          value={<>{cases.filter((c) => c.success).length}<span className="n-of">/{cases.length}</span></>}
          sub="passed" />
      ) : (
        <Tile label="Goal reached" loading={loading}
          value={eps.length ? <>{goals}<span className="n-of">/{eps.length}</span></> : "–"}
          sub={eps.length ? "attempts" : "once it takes control"} />
      )}
      <Tile label="Experiments" loading={loading}
        value={probes}
        sub={!budget ? plural(v.probeSteps, "step") : v.probeSteps <= budget ? `${v.probeSteps} of ${budget} steps used` : `${budget} steps + ${v.probeSteps - budget} re-testing`} />
    </dl>
  );
}
