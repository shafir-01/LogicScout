import type { RunView } from "../state";
import type { Rule } from "../types";

/** Calm four-beat summary of the run: started blank, ideas tested, rules learned, result. */

const CODEY = /[=<>(){}[\]%`|&*]|'\w+'|\b(obs|args|mem)\.|_[a-z]/i;
const plainRule = (r: Rule | undefined): string | null => {
  const s = r?.statement?.trim();
  if (!s || CODEY.test(s)) return null;
  const t = s.replace(/\.$/, "");
  return t.length > 90 ? `${t.slice(0, Math.max(t.lastIndexOf(" ", 88), 60))}…` : t;
};
const n = (x: number, one: string, many = `${one}s`) => `${x} ${x === 1 ? one : many}`;

interface Card { label: string; big: string | null; caption: string }

function cards(v: RunView): Card[] {
  const m = v.manual;
  const hyps = Object.values(v.hypotheses);
  const ruledOut = hyps.filter((h) => h.status === "refuted").length;

  const rules = (v.theory?.rules ?? []).filter((r) => r.status !== "refuted" && r.status !== "retired");
  const best = [...rules]
    .filter((r) => plainRule(r))
    .sort((a, b) => (b.status === "supported" ? 1 : 0) - (a.status === "supported" ? 1 : 0) || b.confidence - a.confidence)[0];

  const eps = v.timeline.filter((it) => it.kind === "episode");
  const goals = eps.filter((it) => it.kind === "episode" && it.goal).length;
  const r = v.referee;
  const randKey = r ? Object.keys(r.baselines ?? {}).find((k) => /random/i.test(k)) : undefined;
  const rand = r && randKey ? r.baselines[randKey] : undefined;
  const pc = (x: number) => `${Math.round(x * 100)}%`;

  let result: Card = { label: "Result", big: null, caption: "Waiting for it to take control" };
  if (r) {
    result = { label: "Result", big: pc(r.success_rate), caption: rand != null ? `Fresh tests passed, vs ${pc(rand)} for random` : "Fresh tests passed" };
  } else if (v.recovered) {
    result = { label: "Result", big: "Recovered", caption: "Re-learned the rules after the change" };
  } else if (v.drift !== "none") {
    result = { label: "Result", big: "Noticed the change", caption: "Its predictions stopped matching" };
  } else if (eps.length) {
    result = { label: "Result", big: `${goals} of ${eps.length}`, caption: "Goals reached" };
  }
  if (r && v.recovered) result.caption += " · recovered after the change";

  return [
    {
      label: "Started knowing nothing",
      big: m ? n(m.actions.length, "control") : null,
      caption: m ? `and ${n(m.observations.length, "reading")}, no rules given` : "Opening the system",
    },
    {
      label: "Ideas tested",
      big: hyps.length ? n(hyps.length, "idea") : null,
      caption: hyps.length ? `${ruledOut} ruled out by experiment` : "Waiting for first guesses",
    },
    {
      label: "Rules it learned",
      big: rules.length ? n(rules.length, "rule") : null,
      caption: rules.length ? (best ? `Most sure: ${plainRule(best)}` : "Kept after testing") : "Nothing confirmed yet",
    },
    result,
  ];
}

const CSS = `
.story-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 20px 0 8px; }
.story-card { background: var(--surface-2); border-radius: var(--r); padding: 14px 16px; min-height: 92px; display: flex; flex-direction: column; gap: 4px; }
.story-label { font-size: 12px; color: var(--text-3); letter-spacing: 0.01em; }
.story-big { font-size: 22px; font-weight: 600; line-height: 1.2; color: var(--text); letter-spacing: -0.01em; }
.story-big.is-empty { color: var(--text-3); font-weight: 400; }
.story-cap { font-size: 13px; line-height: 1.35; color: var(--text-2); overflow-wrap: anywhere; }
.story-fill { display: flex; flex-direction: column; gap: 4px; animation: story-in 480ms var(--ease) both; }
@keyframes story-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@media (max-width: 720px) { .story-strip { grid-template-columns: 1fr; } .story-card { min-height: 0; } }
@media (prefers-reduced-motion: reduce) { .story-fill { animation: none; } }
`;

export default function StoryStrip({ v }: { v: RunView }) {
  const cs = cards(v);
  return (
    <section className="story-strip" aria-label="Story so far">
      <style>{CSS}</style>
      {cs.map((c) => (
        <div className="story-card" key={c.label}>
          <span className="story-label">{c.label}</span>
          {c.big ? (
            <div className="story-fill" key="on">
              <span className="story-big">{c.big}</span>
              <span className="story-cap">{c.caption}</span>
            </div>
          ) : (
            <div key="off">
              <span className="story-big is-empty">—</span>
              <span className="story-cap" style={{ display: "block" }}>{c.caption}</span>
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
