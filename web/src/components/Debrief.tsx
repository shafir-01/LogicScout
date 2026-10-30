import { useEffect, useState } from "react";
import { api } from "../api";
import type { Rule } from "../types";
import { Chip, fmt, statusTone } from "../ui";

type Shift = { kind?: string; label?: string; description?: string; before?: Record<string, unknown>; after?: Record<string, unknown>; at_t?: number; control_step?: number };

const words = (s: string) => s.replace(/_/g, " ");
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const stripFits = (s: string) => s.replace(/\s*\((fits [^)]*|mined from experience)\)\s*$/i, "");
const STATUS: Record<string, string> = { supported: "confirmed", tentative: "likely", refuted: "ruled out", retired: "replaced" };

function laws(d: Record<string, unknown>): string[] {
  for (const k of ["truth", "laws", "hidden_laws", "truth_before", "rules"]) {
    const x = d[k];
    if (Array.isArray(x)) return x.map((s) => (typeof s === "string" ? s : fmt(s)));
    if (x && typeof x === "object") return Object.entries(x).map(([a, b]) => `${words(a)} = ${fmt(b)}`);
  }
  return [];
}

/** "buoy signal each step", "delivered after send by buoy". */
function ruleLabel(r: Rule): string {
  const fields = Object.keys(r.effects ?? {}).map(words);
  const what = fields.length ? fields.join(" and ") : "its readings";
  if (!r.action || r.action === "*") return `${what} each step`;
  const via = (r.when ?? "").match(/args\.via\s*==\s*'(\w+)'/);
  return `${what} after ${words(r.action)}${via ? ` by ${words(via[1])}` : ""}`;
}

const looksLikeFormula = (s: string) => /obs\.|args\.|%|==|becomes \(|\bmax\(|\bmin\(/.test(s);

function ruleText(r: Rule): string {
  const s = stripFits(r.statement);
  return looksLikeFormula(s) ? `How ${ruleLabel(r)} works` : s;
}

const STOP = new Set(["the", "and", "gets", "get", "more", "less", "after", "every", "step", "steps", "becomes", "when", "obs", "args",
  "max", "min", "else", "that", "with", "from", "this", "each", "are", "its", "per", "goes", "than", "into", "slower", "faster"]);

function tokens(s: string): string[] {
  return s.toLowerCase().split(/[^a-z]+/).filter((w) => w.length >= 3 && !STOP.has(w));
}

const related = (a: string[], b: string[]) => a.some((x) => b.some((y) => x === y || (x.length >= 3 && y.length >= 3 && (x.startsWith(y) || y.startsWith(x)))));

function ruleTokens(r: Rule): string[] {
  return [...Object.keys(r.effects ?? {}).flatMap(tokens), ...tokens(r.action ?? ""), ...tokens((r.when ?? "").replace(/args\.via\s*==\s*/g, "")), ...tokens(stripFits(r.statement))];
}

/** "Delay went from 2 steps to 4" style line from before/after values. */
function changeLine(s: Shift): string | null {
  if (!s.before || !s.after) return null;
  const parts = Object.keys(s.after).map((k) => {
    const name = /latency|delay/i.test(k) ? "delay" : words(k);
    const unit = /latency|delay/i.test(k) && typeof s.after?.[k] === "number" ? " steps" : "";
    return `${name} went from ${fmt(s.before?.[k])} to ${fmt(s.after?.[k])}${unit}`;
  });
  return parts.length ? cap(parts.join(", ")) : null;
}

function ChangeStory({ s, live, rules, driftRules, recovered, detectedAfter, missedFields, recoveryDiff }: {
  s: Shift; live: boolean; rules: Rule[]; driftRules: string[]; recovered?: boolean; detectedAfter?: number | null;
  missedFields?: string[]; recoveryDiff: Record<string, unknown> | null;
}) {
  const at = s.at_t ?? s.control_step;
  const change = [s.label ?? (s.description ? cap(words(s.description)) : "One hidden rule changed"), changeLine(s), at != null ? `at step ${at}` : null]
    .filter(Boolean).join(". ").replace(/\. (at step)/, ", $1") + ".";

  // Readings and rules it ended up blaming.
  const blamedFields = new Set<string>();
  const blamedRules: Rule[] = [];
  let unknown = 0;
  for (const id of driftRules) {
    if (id.startsWith("field:")) { blamedFields.add(words(id.slice(6))); continue; }
    const r = rules.find((x) => x.id === id);
    if (r) { blamedRules.push(r); Object.keys(r.effects ?? {}).forEach((f) => blamedFields.add(words(f))); } else unknown += 1;
  }
  const blamed = [...blamedFields];

  const changeTok = [...Object.keys({ ...s.before, ...s.after }).flatMap(tokens), ...tokens(s.label ?? "")];
  const blameTok = [...blamed.flatMap(tokens), ...blamedRules.flatMap(ruleTokens)];
  const isRelated = blameTok.length > 0 && related(changeTok, blameTok);

  const fields = (missedFields ?? []).map(words);
  const noticed = !driftRules.length
    ? "It never confirmed that anything had changed."
    : detectedAfter != null
      ? `Noticed ${detectedAfter} ${detectedAfter === 1 ? "step" : "steps"} after the change${fields.length ? `, when ${fields.join(" and ")} stopped matching its predictions` : ", when its predictions started missing"}.`
      : `Its predictions started missing${fields.length ? ` on ${fields.join(" and ")}` : ""}, so it stopped trusting some rules.`;

  let concluded: string | null = null;
  if (driftRules.length) {
    const about = blamed.length ? `its rules about ${blamed.join(", ")}` : "rules it later replaced";
    if (isRelated) concluded = `It blamed ${about}, which this change does affect.${recovered ? " Then it reached the goal again." : ""}`;
    else if (blamed.length || unknown) concluded = `${recovered ? "It recovered control, but" : "It adjusted, but"} blamed rules unrelated to this change (${about}).`;
  }

  return (
    <div className="you-changed">
      <p><strong>{live ? "You changed" : "The change in this recording"}</strong> {change}</p>
      <p className="small"><strong>What it noticed</strong> {noticed}</p>
      {concluded && <p className="small"><strong>What it concluded</strong> {concluded}</p>}
      {recoveryDiff && (
        <details className="small">
          <summary>Show what it rewrote</summary>
          <div className="mono small dim">{fmt(recoveryDiff)}</div>
        </details>
      )}
    </div>
  );
}

function LearnedRule({ r }: { r: Rule }) {
  const [open, setOpen] = useState(false);
  const formula = stripFits(r.statement);
  const text = ruleText(r);
  return (
    <li>
      <Chip tone={statusTone(r.status)}>{STATUS[r.status] ?? r.status}</Chip> {text}
      {text !== formula && (
        <>
          {" "}<button className="link small" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide formula" : "Show formula"}</button>
          {open && <div className="mono small dim">{formula}</div>}
        </>
      )}
    </li>
  );
}

export default function Debrief({ base, rules, driftRules = [], recoveryDiff = null, live, recovered, detectedAfter = null, missedFields }:
  {
    base: string; rules: Rule[]; driftRules?: string[]; recoveryDiff?: Record<string, unknown> | null;
    /** Live run owner (says "You changed"). Defaults to false for replays. */
    live?: boolean; recovered?: boolean; detectedAfter?: number | null; missedFields?: string[];
  }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.debrief(base).then((x) => setData(x as Record<string, unknown>)).catch((e: Error) => setErr(e.message));
  }, [base]);

  if (err) return <p className="error" role="alert">{err}</p>;
  if (!data) return <p className="dim">Loading debrief…</p>;
  const isLive = live ?? !base.startsWith("/api/replays/");
  const truth = laws(data);
  const truthAfter = Array.isArray(data.truth_after) ? (data.truth_after as string[]) : [];
  const shifts = (Array.isArray(data.shifts) ? data.shifts : Array.isArray(data.shift_records) ? data.shift_records : []) as Shift[];
  const learned = rules.filter((r) => r.status !== "retired");

  // Closest learned rule for each hidden law, by shared reading names. Naive on purpose; shown as a hint, not a verdict.
  const lawRows = truth.map((t) => {
    const lt = tokens(t);
    let best: Rule | null = null;
    let score = 0;
    for (const r of learned) {
      const ft = Object.keys(r.effects ?? {}).flatMap(tokens);
      const sc = ft.filter((x) => lt.includes(x)).length + (r.action && r.action !== "*" && lt.includes(r.action) ? 1 : 0);
      if (sc > score) { score = sc; best = r; }
    }
    return { law: t, rule: best };
  });

  return (
    <section className="debrief" aria-label="Debrief">
      {shifts.map((s, i) => (
        <ChangeStory key={i} s={s} live={isLive} rules={rules} driftRules={driftRules} recovered={recovered}
          detectedAfter={detectedAfter} missedFields={missedFields} recoveryDiff={i === shifts.length - 1 ? recoveryDiff : null} />
      ))}
      <div className="debrief-cols">
        <div>
          <h3 className="label">Hidden laws</h3>
          <ul className="plain laws">
            {lawRows.map(({ law, rule }, i) => (
              <li key={i}>
                {law}
                <div className="small dim">
                  {rule ? <>Closest learned rule <span>{ruleText(rule)}</span></> : "Nothing it learned is about this"}
                </div>
              </li>
            ))}
          </ul>
          {truthAfter.length > 0 && (
            <>
              <h3 className="label">After the hidden change</h3>
              <ul className="plain laws">{truthAfter.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </>
          )}
        </div>
        <div>
          <h3 className="label">What it learned</h3>
          <ul className="plain laws">
            {learned.map((r) => <LearnedRule key={r.id} r={r} />)}
          </ul>
          {!learned.length && <p className="dim small">No rules learned yet.</p>}
        </div>
      </div>
    </section>
  );
}
