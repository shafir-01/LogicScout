import { useEffect, useState } from "react";
import type { RunView } from "../state";

// Reads the run's own event log (independently of the main view) to recover per-step surprise counts.
interface Rule { id: string; statement?: string }
interface Trace {
  steps: { seq: number; mm: number }[];
  shift: number | null;
  noticed: number | null;
  recovered: number | null;
  removed: string[];
  added: string[];
  names: Record<string, string>;
}
const EMPTY: Trace = { steps: [], shift: null, noticed: null, recovered: null, removed: [], added: [], names: {} };
const KINDS = ["control.step", "shift.applied", "drift.confirmed", "recovery.done", "theory.revised", "run.finished"];

function plain(s?: string): string {
  return (s ?? "").replace(/\s*\(fits [^)]*\)\s*$/, "").trim();
}

function useTrace(base: string): Trace {
  const [t, setT] = useState<Trace>(EMPTY);
  useEffect(() => {
    const acc: Trace = { ...EMPTY, steps: [], names: {} };
    let raf = 0;
    let last = -1;
    const es = new EventSource(`${base}/events`);
    const onData = (raw: string) => {
      let ev: { seq: number; kind: string; data?: Record<string, unknown> };
      try { ev = JSON.parse(raw); } catch { return; }
      if (typeof ev?.seq !== "number" || ev.seq <= last) return;
      last = ev.seq;
      const d = ev.data ?? {};
      switch (ev.kind) {
        case "control.step":
          acc.steps.push({ seq: ev.seq, mm: Array.isArray(d.mismatches) ? d.mismatches.length : 0 });
          break;
        case "shift.applied":
          if (acc.shift == null) acc.shift = ev.seq;
          break;
        case "drift.confirmed":
          if (acc.shift != null && acc.noticed == null) acc.noticed = ev.seq;
          break;
        case "recovery.done":
          if (acc.shift != null && acc.recovered == null) acc.recovered = ev.seq;
          break;
        case "theory.revised": {
          const rules = ((d.theory as { rules?: Rule[] } | undefined)?.rules) ?? [];
          for (const r of rules) if (r.statement && !acc.names[r.id]) acc.names[r.id] = plain(r.statement);
          const diff = d.diff as { added?: string[]; removed?: string[]; changed?: string[] } | undefined;
          if (acc.shift != null && diff && (acc.recovered == null || ev.seq <= acc.recovered)) {
            acc.added = [...acc.added, ...(diff.added ?? []), ...(diff.changed ?? [])];
            acc.removed = [...acc.removed, ...(diff.removed ?? [])];
          }
          break;
        }
        case "run.finished":
          es.close();
          break;
      }
      if (!raf) raf = requestAnimationFrame(() => { raf = 0; setT({ ...acc, steps: [...acc.steps] }); });
    };
    es.onmessage = (m) => onData(m.data);
    for (const k of KINDS) es.addEventListener(k, (m) => onData((m as MessageEvent).data));
    es.addEventListener("end", () => es.close());
    return () => { es.close(); cancelAnimationFrame(raf); };
  }, [base]);
  return t;
}

export default function ChangeCard({ v, base, onHidden }: { v: RunView; base: string; onHidden?: () => void }) {
  const t = useTrace(base);
  if (t.shift == null || t.steps.length < 2) return null;

  const idx = (seq: number | null) => (seq == null ? -1 : t.steps.findIndex((s) => s.seq > seq));
  const iShift = idx(t.shift);
  if (iShift < 0) return null;
  const iNoticed = t.noticed != null ? (idx(t.noticed) < 0 ? t.steps.length : idx(t.noticed)) : -1;
  const iRec = t.recovered != null ? (idx(t.recovered) < 0 ? t.steps.length : idx(t.recovered)) : -1;

  const W = 320, H = 64, PAD = 4, TOP = 14;
  const n = t.steps.length;
  const max = Math.max(1, ...t.steps.map((s) => s.mm));
  const x = (i: number) => PAD + (i / Math.max(1, n - 1)) * (W - PAD * 2);
  const y = (m: number) => H - PAD - (m / max) * (H - PAD - TOP);
  const pts = t.steps.map((s, i) => `${x(i).toFixed(1)},${y(s.mm).toFixed(1)}`).join(" ");
  const marks = [
    { i: iShift, label: "Rules changed here", cls: "cc-m-shift" },
    { i: iNoticed, label: "Noticed", cls: "cc-m-notice" },
    { i: iRec, label: "Recovered", cls: "cc-m-rec" },
  ].filter((m) => m.i >= 0);

  const noticedAfter = iNoticed >= 0 ? iNoticed - iShift : null;
  const recAfter = iRec >= 0 && iNoticed >= 0 ? iRec - iNoticed : null;
  const steps = (k: number) => `${k} step${k === 1 ? "" : "s"}`;
  let sentence: string;
  if (noticedAfter == null) sentence = v.finished ? "It never confirmed the change before the run ended." : "The rules changed. It hasn’t noticed yet.";
  else if (noticedAfter <= 0) sentence = "It noticed right away.";
  else sentence = `It noticed ${steps(noticedAfter)} after the change`;
  if (noticedAfter != null) {
    const head = noticedAfter <= 0 ? "It noticed right away" : sentence;
    sentence = recAfter != null ? `${head} and recovered ${steps(recAfter)} later.`
      : v.finished ? `${head}, but the run ended before it fully recovered.` : `${head}; still relearning.`;
  }

  const unique = (a: string[]) => [...new Set(a)];
  const removed = unique(t.removed).filter((r) => !t.added.includes(r));
  const added = unique(t.added);
  const before = removed.map((id) => t.names[id]).find(Boolean);
  const after = added.map((id) => t.names[id]).find(Boolean);
  const more = Math.max(0, added.length - 1);

  return (
    <section className="cc" aria-label="What happened when the rules changed">
      <style>{CSS}</style>
      <h3 className="cc-h">When the rules changed</h3>
      <svg className="cc-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label={`Prediction surprises per step, ${n} steps. ${sentence}`}>
        {iNoticed >= 0 && <rect className="cc-band" x={x(iShift)} y={TOP - 2} width={Math.max(0, x(Math.min(iNoticed, n - 1)) - x(iShift))} height={H - TOP} />}
        <polyline className="cc-line" points={pts} vectorEffect="non-scaling-stroke" />
        {marks.map((m) => {
          const mx = x(Math.min(m.i, n - 1));
          return <line key={m.cls} className={`cc-m ${m.cls}`} x1={mx} x2={mx} y1={TOP - 2} y2={H} vectorEffect="non-scaling-stroke" />;
        })}
      </svg>
      <div className="cc-legend" aria-hidden="true">
        {marks.map((m) => <span key={m.cls} className={`cc-key ${m.cls}`}>{m.label}</span>)}
        <span className="cc-key-dim">line = prediction surprises per step</span>
      </div>
      <p className="cc-sentence">{sentence}</p>
      {(before || after) && (
        <div className="cc-diff">
          <div className="cc-dh">What it changed in its rules</div>
          {before && <div className="cc-row"><span className="cc-tag cc-tag-old">Dropped</span><span className="cc-rule">{before}</span></div>}
          {after && <div className="cc-row"><span className="cc-tag cc-tag-new">Added</span><span className="cc-rule">{after}{more > 0 ? ` (+${more} more)` : ""}</span></div>}
        </div>
      )}
      {onHidden && <button className="cc-link" onClick={onHidden}>See what was really hidden</button>}
    </section>
  );
}

const CSS = `
.cc { margin-top: 16px; padding: 14px 16px; border: 1px solid var(--line); border-radius: var(--r); background: var(--surface); }
.cc-h { margin: 0 0 8px; font-size: 0.95rem; font-weight: 600; color: var(--text); }
.cc-spark { display: block; width: 100%; height: 64px; }
.cc-line { fill: none; stroke: var(--text-2); stroke-width: 1.5; stroke-linejoin: round; }
.cc-band { fill: var(--warn-weak); opacity: 0.6; }
.cc-m { stroke-width: 2; }
.cc-m-shift { stroke: var(--bad); }
.cc-m-notice { stroke: var(--warn); stroke-dasharray: 3 2; }
.cc-m-rec { stroke: var(--ok); }
.cc-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 6px; font-size: 0.78rem; color: var(--text-2); }
.cc-key::before { content: ""; display: inline-block; width: 3px; height: 10px; margin-right: 5px; vertical-align: -1px; border-radius: 1px; }
.cc-key.cc-m-shift::before { background: var(--bad); }
.cc-key.cc-m-notice::before { background: var(--warn); }
.cc-key.cc-m-rec::before { background: var(--ok); }
.cc-key-dim { color: var(--text-3); }
.cc-sentence { margin: 10px 0 0; color: var(--text); }
.cc-diff { margin-top: 10px; font-size: 0.85rem; }
.cc-dh { color: var(--text-3); font-size: 0.78rem; margin-bottom: 4px; }
.cc-row { display: flex; gap: 8px; align-items: baseline; margin-top: 2px; min-width: 0; }
.cc-tag { flex: none; font-size: 0.72rem; padding: 1px 6px; border-radius: var(--r-s); }
.cc-tag-old { background: var(--bad-weak); color: var(--bad); }
.cc-tag-new { background: var(--ok-weak); color: var(--ok); }
.cc-rule { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.cc-link { margin-top: 10px; padding: 0; border: 0; background: none; color: var(--accent-text); font: inherit; font-size: 0.85rem; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
`;
