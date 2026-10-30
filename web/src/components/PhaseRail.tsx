import type { RunView } from "../state";

const STAGES = [
  { key: "unknown", label: "Unknown", phases: ["encounter", "briefing"] },
  { key: "probing", label: "Probing", phases: ["probing"] },
  { key: "theory", label: "Theory", phases: ["theory"] },
  { key: "control", label: "Control", phases: ["control"] },
  { key: "change", label: "Hidden change", phases: ["drift", "reprobing"] },
  { key: "recovered", label: "Recovered", phases: ["recovered"] },
  { key: "referee", label: "Referee", phases: ["referee", "done"] },
] as const;

function currentIndex(v: RunView): number {
  if (v.phase === "control" && v.drift !== "none") return 4;
  if (v.phase === "control" && v.recovered) return 5;
  const i = STAGES.findIndex((s) => (s.phases as readonly string[]).includes(v.phase));
  if (i >= 0) return i;
  if (v.phase === "failed") {
    let last = 0;
    STAGES.forEach((_, j) => { if (reached(v, j)) last = j; });
    return last;
  }
  return 0;
}

function reached(v: RunView, i: number): boolean {
  switch (STAGES[i].key) {
    case "unknown": return true;
    case "probing": return v.probeSteps > 0;
    case "theory": return v.versions.length > 0;
    case "control": return v.controlSteps > 0;
    case "change": return v.shifted || v.drift !== "none";
    case "recovered": return v.recovered;
    case "referee": return !!v.referee;
  }
  return false;
}

export default function PhaseRail({ v }: { v: RunView }) {
  const cur = currentIndex(v);
  const alarm = v.drift !== "none" || v.phase === "drift" || v.phase === "reprobing";
  return (
    <ol className="rail" aria-label="Run phase">
      {STAGES.map((s, i) => {
        const isCur = i === cur;
        const done = i < cur;
        const skipped = done && s.key === "change" && !reached(v, i);
        const cls = [
          "rail-step",
          isCur ? "is-current" : "",
          done && !skipped ? "is-done" : "",
          skipped ? "is-skipped" : "",
          s.key === "change" && (alarm || (isCur && v.shifted)) ? "is-alarm" : "",
          isCur && v.failed ? "is-alarm" : "",
        ].join(" ");
        return (
          <li key={s.key} className={cls} aria-current={isCur ? "step" : undefined}>
            <span className="rail-dot" aria-hidden="true" />
            <span className="rail-label">
              {s.label}
              {s.key === "change" && v.drift !== "none" && <em> · {v.drift}</em>}
              {isCur && v.failed && <em> · failed</em>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
