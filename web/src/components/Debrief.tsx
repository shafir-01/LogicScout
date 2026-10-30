import { useEffect, useState } from "react";
import { api } from "../api";
import type { Rule } from "../types";
import { Chip, fmt, statusTone } from "../ui";

type Shift = { kind?: string; description?: string; before?: Record<string, unknown>; after?: Record<string, unknown>; at_t?: number };

function laws(d: Record<string, unknown>): string[] {
  for (const k of ["truth", "laws", "hidden_laws", "truth_before", "rules"]) {
    const x = d[k];
    if (Array.isArray(x)) return x.map((s) => (typeof s === "string" ? s : fmt(s)));
    if (x && typeof x === "object") return Object.entries(x).map(([a, b]) => `${a} = ${fmt(b)}`);
  }
  return [];
}

export default function Debrief({ base, rules }: { base: string; rules: Rule[] }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.debrief(base).then((x) => setData(x as Record<string, unknown>)).catch((e: Error) => setErr(e.message));
  }, [base]);

  if (err) return <p className="error" role="alert">{err}</p>;
  if (!data) return <p className="dim">Loading debrief…</p>;
  const truth = laws(data);
  const truthAfter = Array.isArray(data.truth_after) ? (data.truth_after as string[]) : [];
  const shifts = (Array.isArray(data.shifts) ? data.shifts : Array.isArray(data.shift_records) ? data.shift_records : []) as Shift[];
  const learned = rules.filter((r) => r.status !== "retired");

  return (
    <section className="debrief" aria-label="Debrief">
      <div className="debrief-cols">
        <div>
          <h3 className="label">Hidden laws</h3>
          <ul className="plain laws">{truth.map((t, i) => <li key={i}>{t}</li>)}</ul>
          {truthAfter.length > 0 && (
            <>
              <h3 className="label">After the hidden change</h3>
              <ul className="plain laws">{truthAfter.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </>
          )}
          {shifts.length > 0 && (
            <>
              <h3 className="label">Hidden changes</h3>
              <ul className="plain">
                {shifts.map((s, i) => (
                  <li key={i}>
                    <Chip tone="bad">{s.kind ?? "change"}</Chip> {s.description}
                    {s.at_t != null && <span className="mono small dim"> t={s.at_t}</span>}
                    {s.before && s.after && (
                      <div className="mono small dim">{fmt(s.before)} → {fmt(s.after)}</div>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div>
          <h3 className="label">Learned rules</h3>
          <ul className="plain laws">
            {learned.map((r) => (
              <li key={r.id}><Chip tone={statusTone(r.status)}>{r.status}</Chip> {r.statement}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
