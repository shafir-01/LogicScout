import type { RunView } from "../state";

const STEPS = ["Unknown", "Learning", "Understood", "In control", "Rules changed", "Recovered"] as const;

export function reached(v: RunView, i: number): boolean {
  switch (i) {
    case 0: return true;
    case 1: return v.probeSteps > 0 || v.phase === "probing";
    case 2: return v.versions.length > 0 || !!v.playbook;
    case 3: return v.controlSteps > 0;
    case 4: return v.shifted || v.drift === "confirmed" || v.driftRules.length > 0;
    case 5: return v.recovered;
  }
  return false;
}

/** True when a new playbook was compiled after the latest confirmed drift (re-investigation finished). */
export function backInControl(v: RunView): boolean {
  let drift = -1, pb = -1;
  for (const t of v.timeline) {
    if (t.kind === "drift" && t.level === "confirmed") drift = t.seq;
    if (t.kind === "playbook") pb = t.seq;
  }
  return drift >= 0 && pb > drift;
}

/** Index of the live step, or -1 once the run has ended. */
export function currentStep(v: RunView): number {
  if (v.finished) return -1;
  switch (v.phase) {
    case "encounter": case "briefing": return 0;
    case "probing": return 1;
    case "theory": return 2;
    case "control":
      if (v.drift === "confirmed" && !backInControl(v)) return 4;
      if (v.shifted && !v.recovered) return backInControl(v) ? 3 : 4;
      if (v.recovered) return 5;
      return 3;
    case "drift": case "reprobing": return v.shifted || v.drift === "confirmed" ? 4 : 3;
    case "recovered": return v.recovered ? 5 : 3;
    default: return -1;
  }
}

export default function PhaseRail({ v }: { v: RunView }) {
  const cur = currentStep(v);
  let last = 0;
  STEPS.forEach((_, i) => { if (reached(v, i)) last = i; });
  const focus = cur >= 0 ? cur : last;
  return (
    <ol className="progress" aria-label="Progress">
      {STEPS.map((label, i) => {
        const isCur = i === cur;
        const done = cur >= 0 ? i < cur && (i < 4 || reached(v, i)) : reached(v, i);
        const tone =
          (isCur && i === 4) || (v.failed && i === last) ? "bad"
          : (isCur && i === 5) || (cur < 0 && !v.failed && i === last && last === 5) ? "ok"
          : "";
        const cls = ["step", isCur ? "is-current" : "", done ? "is-done" : "", tone ? `is-${tone}` : "", i === focus ? "is-focus" : ""].join(" ");
        return (
          <li key={label} className={cls} aria-current={isCur ? "step" : undefined}>
            <span className="step-bar" aria-hidden="true" />
            <span className="step-label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
