import { useEffect, useRef, useState } from "react";
import type { Action, Dict, Hypothesis, Mismatch, Objective, Rule } from "../types";
import type { EpisodeItem, ProbeItem, RunView, TimelineItem } from "../state";
import { Chip, fmt, pct } from "../ui";

function short(s: string, n = 90) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

const words = (s: string) => s.replace(/_/g, " ");
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;

/** "send 3 by buoy", "wait", "prioritize". */
function moveText(a?: Action | null): string {
  if (!a) return "";
  const parts = [words(a.name)];
  for (const [k, v] of Object.entries(a.args ?? {})) {
    const val = typeof v === "string" ? v.replace(/^'|'$/g, "") : fmt(v);
    if (k === "via") parts.push(`by ${words(val)}`);
    else if (k === "n" || typeof v === "number") parts.push(val);
    else parts.push(`${words(k)} ${words(val)}`);
  }
  return parts.join(" ");
}

function purposeText(p: string | undefined, first?: Action): string {
  const s = (p ?? "").trim();
  if (/^first touch/i.test(s)) return "Pressing every button once to see what happens.";
  if (/rival rules disagree|disagree most/i.test(s)) return "Picked moves where its competing guesses predict different results.";
  if (/^single-factor/i.test(s)) return first ? `Repeating one move (${moveText(first)}) to isolate its effect.` : "Repeating one move to isolate its effect.";
  if (/^exploratory/i.test(s)) return "Random moves to collect fresh examples.";
  return s.replace(/:\s*/g, ". ");
}

/** Rewrites judge strings like "predicted delivered=4, saw delivered=3 at t=5". */
function reasonText(r: string): string {
  let m = r.match(/^predicted (\w+)=(\S+), saw \w+=(\S+) at t=(\d+)$/);
  if (m) return `Expected ${m[2]} ${words(m[1])}, got ${m[3]} (step ${m[4]})`;
  m = r.match(/^fired (\d+)x, every predicted effect matched$/);
  if (m) return m[1] === "1" ? "Matched the one time it applied" : `Matched all ${m[1]} times it applied`;
  return r;
}

/** "t=5 queue: theory said 9, saw 7" -> "Step 5 queue was 7, it expected 9". */
function surpriseText(s: string): string {
  const m = s.match(/^t=(\d+) (\w+): theory said (\S+), saw (\S+)$/);
  return m ? `Step ${m[1]} ${words(m[2])} was ${m[4]}, it expected ${m[3]}` : s.replace(/:\s*/g, " ");
}

const MARK_TITLE: Record<string, string> = { "✓": "Held up", "✗": "Ruled out", "?": "Test could not tell", "·": "Waiting for result" };

function ProbeRow({ it, n, hyps }: { it: ProbeItem; n: number; hyps: Record<string, Hypothesis> }) {
  const ids = it.probe.hypotheses ?? [];
  const surprises = it.outcome?.surprises ?? [];
  const [all, setAll] = useState(false);
  const shown = all ? surprises : surprises.slice(0, 3);
  const total = it.probe.actions?.length;
  return (
    <>
      <div className="tl-head">
        <span className="tl-kind">Experiment {n}</span>
        <span className="mono dim small">{total != null && it.steps < total ? `${it.steps} of ${total} moves` : plural(total ?? it.steps, "move")}</span>
        {surprises.length > 0 && <Chip tone="warn" title="Readings it did not predict">{plural(surprises.length, "surprise")}</Chip>}
      </div>
      <p className="tl-purpose">{purposeText(it.probe.purpose, it.probe.actions?.[0])}</p>
      <ul className="hyps">
        {ids.map((id) => {
          const h = hyps[id];
          const hypOutcome = it.hypOutcomes[id]?.status ?? (it.outcome?.outcomes?.[id] === "inconclusive" ? "inconclusive" : it.outcome?.outcomes?.[id]);
          const reason = it.hypOutcomes[id]?.reason;
          const mark = hypOutcome === "supported" ? "✓" : hypOutcome === "refuted" ? "✗" : hypOutcome === "inconclusive" ? "?" : "·";
          const tone = hypOutcome === "supported" ? "ok" : hypOutcome === "refuted" ? "bad" : hypOutcome === "inconclusive" ? "warn" : "muted";
          return (
            <li key={id} className={`hyp hyp-${tone}`}>
              <span className={`mark tone-${tone}`} title={MARK_TITLE[mark]} aria-label={MARK_TITLE[mark]}>{mark}</span>
              <span className="hyp-text">{h ? short(h.statement) : "A guess it no longer tracks"}</span>
              {reason && <span className="reason small">{reasonText(reason)}</span>}
            </li>
          );
        })}
      </ul>
      {surprises.length > 0 && (
        <ul className="surprises">
          {shown.map((s, i) => <li key={i} className="small">{surpriseText(s)}</li>)}
          {surprises.length > 3 && (
            <li><button className="link small" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "fewer" : `+${surprises.length - 3} more`}</button></li>
          )}
        </ul>
      )}
    </>
  );
}

/* ---- control attempts ---------------------------------------------------------- */

function objectiveOf(v: RunView): Objective | undefined {
  const objs = v.manual?.objectives ?? [];
  return objs.find((o) => o.id === v.config?.objective_id) ?? objs[0];
}

type Clause = { field: string; op: string; target: number };
function clauses(success?: string): Clause[] {
  const out: Clause[] = [];
  const re = /obs\.(\w+)\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)/g;
  for (let m; (m = re.exec(success ?? "")); ) out.push({ field: m[1], op: m[2], target: Number(m[3]) });
  return out;
}

function met(c: Clause, x: number): boolean {
  switch (c.op) {
    case ">=": return x >= c.target;
    case "<=": return x <= c.target;
    case ">": return x > c.target;
    case "<": return x < c.target;
    default: return x === c.target;
  }
}

/** Why an attempt missed, from the goal readings at its last step. "7 of 8 delivered", "13 delivered, but 12 lost, limit 2". */
function goalReason(obj: Objective | undefined, obs: Dict | undefined): string | null {
  if (!obj || !obs) return null;
  const cs = clauses(obj.success).filter((c) => typeof obs[c.field] === "number");
  if (!cs.length) return null;
  const bad: string[] = [];
  const good: string[] = [];
  for (const c of cs) {
    const x = obs[c.field] as number;
    const f = words(c.field);
    if (met(c, x)) { if (c.op === ">=" || c.op === ">") good.push(`${x} ${f}`); continue; }
    if (c.op === ">=") bad.push(`${x} of ${c.target} ${f}`);
    else if (c.op === ">") bad.push(`${x} ${f}, needed more than ${c.target}`);
    else if (c.op === "<=") bad.push(`${x} ${f}, limit ${c.target}`);
    else if (c.op === "<") bad.push(`${x} ${f}, needed under ${c.target}`);
    else bad.push(`${f} ${x}, needed ${c.target}`);
  }
  if (!bad.length) return null;
  return good.length ? `${good.join(", ")}, but ${bad.join(", ")}` : bad.join(", ");
}

/**
 * Readings at the last step of each attempt. The reducer keeps only the latest observation,
 * so we remember it per attempt while it is the newest one. Prefer `last` on the item if the reducer provides it.
 */
const lastObs = new Map<string, { t: number; obs: Dict }>();
const runKey = (v: RunView) => `${v.config?.world_id ?? ""}|${v.config?.seed ?? ""}`;

function rememberAttempt(v: RunView) {
  if (v.phase !== "control" || !v.obs || v.obsT == null) return;
  let last: EpisodeItem | undefined;
  for (let i = v.timeline.length - 1; i >= 0; i--) { const it = v.timeline[i]; if (it.kind === "episode") { last = it; break; } }
  if (!last) return;
  // control.step observations carry t == step; reject probe observations that may share the batch.
  if (v.obsT > last.steps || v.obsT < last.steps - 1) return;
  const k = `${runKey(v)}|${last.seq}`;
  const prev = lastObs.get(k);
  if (!prev || prev.t <= v.obsT) lastObs.set(k, { t: v.obsT, obs: v.obs });
}

function EpisodeRow({ it, v }: { it: EpisodeItem; v: RunView }) {
  const obj = objectiveOf(v);
  const lastEp = !v.timeline.some((x) => x.kind === "episode" && x.episode > it.episode);
  const finished = it.goal || !lastEp || v.finished || v.phase !== "control";
  const extra = it as EpisodeItem & { last?: Dict; obs?: Dict };
  const cached = lastObs.get(`${runKey(v)}|${it.seq}`);
  const obs = extra.last ?? extra.obs ?? cached?.obs;
  const horizon = obj?.horizon;
  const steps = cached && !it.goal ? cached.t : horizon != null ? Math.min(it.steps, horizon) : it.steps;
  const stopped = !it.goal && finished && horizon != null && steps < horizon;
  const reason = !it.goal && finished ? goalReason(obj, obs) : null;
  return (
    <div className="tl-head">
      <span className="tl-kind">Control</span>
      <span>Attempt {it.episode + 1}</span>
      {it.goal ? (
        <Chip tone="ok">goal reached in {plural(it.steps, "step")}</Chip>
      ) : !finished ? (
        <><span className="mono dim small">{plural(it.steps, "step")} so far</span><Chip>running</Chip></>
      ) : stopped ? (
        <><span className="mono dim small">{plural(steps, "step")}</span><Chip tone="warn" title="Its predictions kept missing, so it paused to run new experiments.">stopped to relearn</Chip></>
      ) : (
        <><span className="mono dim small">{plural(steps, "step")}</span><Chip tone="bad" title="Ran out of steps before reaching the goal.">goal missed</Chip></>
      )}
      {reason && <span className="small">{reason}</span>}
      {it.mismatches > 0 && <Chip tone="warn" title="Steps where a reading came out different from what its rules predicted">{plural(it.mismatches, "missed prediction")}</Chip>}
    </div>
  );
}

/* ---- drift ---------------------------------------------------------------------- */

const stripFits = (s: string) => s.replace(/\s*\((fits [^)]*|mined from experience)\)\s*$/i, "");

/** A short plain label for a rule: "buoy signal each step", "delivered after send by buoy". */
function ruleLabel(r: Rule): string {
  const fields = Object.keys(r.effects ?? {}).map(words);
  const what = fields.length ? fields.join(" and ") : "its readings";
  if (!r.action || r.action === "*") return `${what} each step`;
  const via = (r.when ?? "").match(/args\.via\s*==\s*'(\w+)'/);
  return `${what} after ${words(r.action)}${via ? ` by ${words(via[1])}` : ""}`;
}

/** Plain label for an implicated id: "field:x" is a reading, "R12" a rule. */
function implicated(id: string, rules: Rule[], fieldOf: Record<string, string>): { text: string; title: string } {
  if (id.startsWith("field:")) {
    const f = words(id.slice(6));
    return { text: f, title: `Its rules about ${f}` };
  }
  const r = rules.find((x) => x.id === id);
  if (r) return { text: short(ruleLabel(r), 50), title: `${stripFits(r.statement)} (${id})` };
  if (fieldOf[id]) return { text: words(fieldOf[id]), title: `A rule about ${words(fieldOf[id])} it later replaced (${id})` };
  return { text: "a rule it later replaced", title: id };
}

function mismatchText(m: Mismatch): string {
  return `${cap(words(m.field))} was ${fmt(m.observed)}, it expected ${fmt(m.predicted)}`;
}

function DriftRow({ it, v, fieldOf }: { it: Extract<TimelineItem, { kind: "drift" }>; v: RunView; fieldOf: Record<string, string> }) {
  const rules = v.theory?.rules ?? [];
  if (it.level === "confirmed") {
    const seen = new Set<string>();
    const chips = (it.rules ?? []).map((id) => implicated(id, rules, fieldOf)).filter((c) => !seen.has(c.text) && !!seen.add(c.text));
    return (
      <>
        <div className="tl-head">
          <span className="tl-kind alarm">Rules have changed</span>
          <span className="dim small">Misses kept happening, so it stopped trusting some rules.</span>
        </div>
        {chips.length > 0 && (
          <div className="tl-head">
            <span className="small">Suspects its rules about</span>
            {chips.map((c) => <Chip key={c.text} tone="bad" title={c.title}>{c.text}</Chip>)}
          </div>
        )}
      </>
    );
  }
  const mm = it.mismatches ?? [];
  return (
    <>
      <div className="tl-head">
        <span className="tl-kind alarm">Prediction missed</span>
        {mm.length > 0 && (
          <span className="small" title={it.surprise != null ? `How far off its predictions were. 0 is perfect, 1 is completely wrong. This time ${fmt(it.surprise)}.` : undefined}>
            {mm.length === 1 ? "1 reading came out different from what it predicted" : `${mm.length} readings came out different from what it predicted`}
          </span>
        )}
      </div>
      {mm.length > 0 && (
        <ul className="surprises">
          {mm.slice(0, 4).map((m, i) => <li key={i} className="small">{mismatchText(m)}</li>)}
        </ul>
      )}
    </>
  );
}

/* ---- other rows ----------------------------------------------------------------- */

function theoryNote(note?: string): { text?: string; title?: string } {
  if (!note) return {};
  const m = note.match(/^Cycle \d+:\s*(.*)$/);
  if (m) return { text: cap(m[1]) };
  // "Learned R112 ..." is the model's own changelog with ids and formulas; keep it out of sight.
  return { title: note };
}

function noteText(t: string): string {
  if (/^falling back to planner/i.test(t)) return "Gave up on a fixed plan. It will plan each step instead.";
  if (/^episode missed the goal/i.test(t)) return "Missed the goal, so it is refitting its rules on what just happened.";
  return t;
}

function Row({ it, v, n, fieldOf, firstRejected }: { it: TimelineItem; v: RunView; n: number; fieldOf: Record<string, string>; firstRejected: boolean }) {
  switch (it.kind) {
    case "probe":
      return <ProbeRow it={it} n={n} hyps={v.hypotheses} />;
    case "episode":
      return <EpisodeRow it={it} v={v} />;
    case "theory": {
      const nt = theoryNote(it.note);
      return (
        <div className="tl-head" title={nt.title}>
          <span className="tl-kind">Rules updated</span>
          <span>version {it.version}</span>
          <span className="mono small">predicts {pct(it.accuracy)} of next steps <span className="dim">vs {pct(it.baseline)} if nothing changes</span></span>
          {nt.text && <span className="dim small">{short(nt.text, 120)}</span>}
        </div>
      );
    }
    case "playbook":
      return (
        <div className="tl-head">
          <span className="tl-kind">Plan</span>
          <span>{it.origin === "planner" ? "Switched to planning each step ahead" : "Wrote a control plan"}</span>
          {it.simulated && (
            <Chip tone={it.simulated.success ? "ok" : "bad"} title="Before touching the real system, it rehearses each plan against its rules.">
              {it.simulated.success
                ? `practice run reached goal${it.simulated.steps != null ? ` in ${plural(it.simulated.steps, "step")}` : ""}`
                : "practice run missed the goal"}
            </Chip>
          )}
        </div>
      );
    case "rejected":
      return (
        <>
          <div className="tl-head" title={it.text}>
            <span className="tl-kind">Plan</span>
            <Chip tone="bad">Plan failed a practice run</Chip>
            <span className="dim small">Its own rules say this plan would not reach the goal</span>
          </div>
          {firstRejected && <p className="dim small">Before touching the real system, it rehearses each plan against its rules.</p>}
        </>
      );
    case "shift":
      return (
        <div className="tl-head">
          <span className="tl-kind alarm">Hidden change</span>
          <span className="dim small">A hidden rule was changed without telling it</span>
        </div>
      );
    case "drift":
      return <DriftRow it={it} v={v} fieldOf={fieldOf} />;
    case "recovery":
      return (
        <div className="tl-head">
          <span className="tl-kind ok">Recovered</span>
          {it.stepsDown != null && <span className="mono small">{plural(it.stepsDown, "step")} to recover</span>}
          {it.probesUsed != null && <span className="mono small">{plural(it.probesUsed, "test move")}</span>}
        </div>
      );
    case "trial":
      return (
        <div className="tl-head">
          <span className="tl-kind">Plan</span>
          <span>Tried the plan on a fresh copy</span>
          <Chip tone={it.real ? "ok" : "bad"}>{it.real ? "worked" : "failed"}</Chip>
          {it.accepted === false && <span className="dim small">plan rejected</span>}
          {it.steps != null && <span className="mono dim small">{plural(it.steps, "step")}</span>}
        </div>
      );
    case "referee":
      return (
        <div className="tl-head">
          <span className="tl-kind">Referee</span>
          <span className="mono">Reached the goal on {pct(it.rate)} of unseen tests</span>
        </div>
      );
    case "note":
      return <div className={`tl-note ${it.error ? "error" : "dim"}`}>{noteText(it.text)}</div>;
  }
}

export default function Timeline({ v }: { v: RunView }) {
  const ref = useRef<HTMLOListElement>(null);
  const follow = useRef(true);
  rememberAttempt(v);
  useEffect(() => {
    const el = ref.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [v.timeline.length, v.lastSeq]);

  // Rule ids that have since been replaced can still be named by the reading they predicted.
  const fieldOf: Record<string, string> = {};
  for (const it of v.timeline) if (it.kind === "drift") for (const m of it.mismatches ?? []) for (const id of m.rule_ids ?? []) fieldOf[id] ??= m.field;
  let probeN = 0;
  let rejectedSeen = false;

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
        {v.timeline.map((it) => {
          const n = it.kind === "probe" ? ++probeN : 0;
          const firstRejected = it.kind === "rejected" && !rejectedSeen;
          if (it.kind === "rejected") rejectedSeen = true;
          return (
            <li key={`${it.kind}-${it.seq}`} id={`ev-${it.seq}`} data-seq={it.seq} className={`tl tl-${it.kind}${it.kind === "drift" || it.kind === "shift" ? " tl-alarm" : ""}`}>
              <Row it={it} v={v} n={n} fieldOf={fieldOf} firstRejected={firstRejected} />
            </li>
          );
        })}
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
