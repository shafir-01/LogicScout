import { useEffect, useRef, useState } from "react";
import type { Hypothesis } from "../types";
import type { ProbeItem, RunView, TimelineItem } from "../state";
import { Chip, fmt, pct } from "../ui";

function short(s: string, n = 90) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function ProbeRow({ it, hyps }: { it: ProbeItem; hyps: Record<string, Hypothesis> }) {
  const ids = it.probe.hypotheses ?? [];
  const surprises = it.outcome?.surprises ?? [];
  const [all, setAll] = useState(false);
  const shown = all ? surprises : surprises.slice(0, 3);
  return (
    <>
      <div className="tl-head">
        <span className="tl-kind">Probe</span>
        <span className="mono dim small">{it.steps}/{it.probe.actions?.length ?? "?"} steps</span>
        {surprises.length > 0 && <Chip tone="warn" title={surprises.join("\n")}>! {surprises.length} surprise{surprises.length > 1 ? "s" : ""}</Chip>}
      </div>
      <p className="tl-purpose">{it.probe.purpose}</p>
      <ul className="hyps">
        {ids.map((id) => {
          const h = hyps[id];
          const hypOutcome = it.hypOutcomes[id]?.status ?? (it.outcome?.outcomes?.[id] === "inconclusive" ? "inconclusive" : it.outcome?.outcomes?.[id]);
          const reason = it.hypOutcomes[id]?.reason;
          const mark = hypOutcome === "supported" ? "✓" : hypOutcome === "refuted" ? "✗" : hypOutcome === "inconclusive" ? "?" : "·";
          const tone = hypOutcome === "supported" ? "ok" : hypOutcome === "refuted" ? "bad" : hypOutcome === "inconclusive" ? "warn" : "muted";
          return (
            <li key={id} className={`hyp hyp-${tone}`}>
              <span className={`mark tone-${tone}`} aria-label={hypOutcome ?? "pending"}>{mark}</span>
              <span className="hyp-text">{h ? short(h.statement) : <span className="mono">{id}</span>}</span>
              {reason && <span className="reason mono">{reason}</span>}
            </li>
          );
        })}
      </ul>
      {surprises.length > 0 && (
        <ul className="surprises">
          {shown.map((s, i) => <li key={i} className="mono small">! {s}</li>)}
          {surprises.length > 3 && (
            <li><button className="link small" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "fewer" : `+${surprises.length - 3} more`}</button></li>
          )}
        </ul>
      )}
    </>
  );
}

function Row({ it, hyps }: { it: TimelineItem; hyps: Record<string, Hypothesis> }) {
  switch (it.kind) {
    case "probe":
      return <ProbeRow it={it} hyps={hyps} />;
    case "episode":
      return (
        <div className="tl-head">
          <span className="tl-kind">Control</span>
          <span>Episode {it.episode + 1}</span>
          <span className="mono dim small">{it.steps} steps</span>
          {it.goal ? <Chip tone="ok">✓ goal reached</Chip> : <Chip>running</Chip>}
          {it.mismatches > 0 && <Chip tone="warn">{it.mismatches} off-prediction</Chip>}
        </div>
      );
    case "theory":
      return (
        <div className="tl-head">
          <span className="tl-kind">Theory</span>
          <span>v{it.version}</span>
          <span className="mono small">accuracy {pct(it.accuracy)} <span className="dim">vs {pct(it.baseline)} baseline</span></span>
          {it.note && <span className="dim small">{short(it.note, 120)}</span>}
        </div>
      );
    case "playbook":
      return (
        <div className="tl-head">
          <span className="tl-kind">Playbook</span>
          <span>{it.origin === "planner" ? "Planner" : "Compiled"}</span>
          {it.simulated && (
            <Chip tone={it.simulated.success ? "ok" : "bad"}>
              simulated {it.simulated.success ? "✓" : "✗"} {it.simulated.steps != null ? `${it.simulated.steps} steps` : ""}
            </Chip>
          )}
        </div>
      );
    case "rejected":
      return (
        <div className="tl-head">
          <span className="tl-kind">Playbook</span>
          <Chip tone="bad">rejected</Chip>
          <span className="dim small">{short(it.text, 140)}</span>
        </div>
      );
    case "shift":
      return (
        <div className="tl-head">
          <span className="tl-kind alarm">Hidden change</span>
          <span className="dim small">Rules changed silently</span>
        </div>
      );
    case "drift":
      return (
        <>
          <div className="tl-head">
            <span className="tl-kind alarm">Drift {it.level}</span>
            {it.surprise != null && <span className="mono small">surprise {fmt(it.surprise)}</span>}
            {it.rules?.map((r) => <Chip key={r} tone="bad">{r}</Chip>)}
          </div>
          {it.mismatches && it.mismatches.length > 0 && (
            <ul className="surprises">
              {it.mismatches.slice(0, 4).map((m, i) => (
                <li key={i} className="mono small">{m.field}: predicted {fmt(m.predicted)}, saw {fmt(m.observed)}</li>
              ))}
            </ul>
          )}
        </>
      );
    case "recovery":
      return (
        <div className="tl-head">
          <span className="tl-kind ok">Recovered</span>
          {it.stepsDown != null && <span className="mono small">{it.stepsDown} steps degraded</span>}
          {it.probesUsed != null && <span className="mono small">{it.probesUsed} probes</span>}
        </div>
      );
    case "referee":
      return (
        <div className="tl-head">
          <span className="tl-kind">Referee</span>
          <span className="mono">{pct(it.rate)} held-out success</span>
        </div>
      );
    case "note":
      return <div className={`tl-note ${it.error ? "error" : "dim"}`}>{it.text}</div>;
  }
}

export default function Timeline({ v }: { v: RunView }) {
  const ref = useRef<HTMLOListElement>(null);
  const follow = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [v.timeline.length, v.lastSeq]);

  return (
    <section className="experiments" aria-label="Experiments">
      <ol
        className="timeline"
        ref={ref}
        onScroll={(e) => {
          const el = e.currentTarget;
          follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {v.timeline.map((it) => (
          <li key={`${it.kind}-${it.seq}`} id={`ev-${it.seq}`} data-seq={it.seq} className={`tl tl-${it.kind}${it.kind === "drift" || it.kind === "shift" ? " tl-alarm" : ""}`}>
            <Row it={it} hyps={v.hypotheses} />
          </li>
        ))}
        {!v.timeline.length && <li className="empty">No experiments yet</li>}
      </ol>
    </section>
  );
}

export function focusSeq(seq: number) {
  window.dispatchEvent(new CustomEvent("ls-show-experiments"));
  window.setTimeout(() => scrollToSeq(seq), 60);
}

function scrollToSeq(seq: number) {
  const items = Array.from(document.querySelectorAll<HTMLElement>(".timeline > li[data-seq]"));
  let best: HTMLElement | null = null;
  for (const el of items) if (Number(el.dataset.seq) <= seq) best = el;
  if (!best) return;
  best.scrollIntoView({ block: "center", behavior: "smooth" });
  best.classList.remove("pulse");
  void best.offsetWidth;
  best.classList.add("pulse");
}
