import { useState } from "react";
import { whatif, type WhatIfResult } from "../api";
import type { RunView } from "../state";
import type { Action, ActionSpec, ParamSpec } from "../types";
import Export from "./Export";

const MAX = 12;

function defaultArg(p: ParamSpec): unknown {
  if (p.type === "enum") return p.choices?.[0] ?? "";
  if (p.type === "bool") return false;
  if (p.type === "int" || p.type === "float") return p.min ?? 0;
  return "";
}

function blank(spec: ActionSpec): Action {
  return { name: spec.name, args: Object.fromEntries(spec.params.map((p) => [p.name, defaultArg(p)])) } as Action;
}

function show(x: unknown): string {
  if (typeof x === "number") return Number.isInteger(x) ? String(x) : x.toFixed(2);
  return x === undefined ? "–" : JSON.stringify(x);
}

function ArgInput({ p, value, onChange }: { p: ParamSpec; value: unknown; onChange: (x: unknown) => void }) {
  if (p.type === "enum") {
    return <select value={String(value)} onChange={(e) => onChange(e.target.value)}>{(p.choices ?? []).map((c) => <option key={c}>{c}</option>)}</select>;
  }
  if (p.type === "bool") return <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />;
  if (p.type === "int" || p.type === "float") {
    return (
      <input type="number" className="num" value={String(value)} min={p.min ?? undefined} max={p.max ?? undefined}
        step={p.type === "int" ? 1 : "any"} onChange={(e) => onChange(Number(e.target.value))} />
    );
  }
  return <input value={String(value)} onChange={(e) => onChange(e.target.value)} />;
}

export default function WhatIf({ v, runId }: { v: RunView; runId?: string }) {
  const specs = v.manual?.actions ?? [];
  const [steps, setSteps] = useState<Action[]>([]);
  const [res, setRes] = useState<WhatIfResult | null>(null);
  const [busy, setBusy] = useState<"predict" | "test" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!runId) return <div className="tab-body"><p className="empty">Available during a live run.</p></div>;
  if (!v.theory) return <div className="tab-body"><p className="empty">No theory yet</p></div>;

  const edit = (i: number, a: Action | null) => {
    setSteps((s) => (a ? s.map((x, j) => (j === i ? a : x)) : s.filter((_, j) => j !== i)));
    setRes(null);
  };
  const run = async (test: boolean) => {
    setBusy(test ? "test" : "predict"); setErr(null);
    try { setRes(await whatif(runId, steps, test)); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };
  const fields = res ? Object.keys(res.predicted[0] ?? {}).filter((f) => f !== "t") : [];

  return (
    <div className="tab-body">
      {!steps.length && <p className="dim small">Add a few steps, then see what its rules predict, or test them on the real system.</p>}
      <ol className="whatif-steps">
        {steps.map((a, i) => {
          const spec = specs.find((s) => s.name === a.name);
          return (
            <li key={i}>
              <select value={a.name} onChange={(e) => { const s = specs.find((x) => x.name === e.target.value); if (s) edit(i, blank(s)); }}>
                {specs.map((s) => <option key={s.name}>{s.name}</option>)}
              </select>
              {spec?.params.map((p) => (
                <label key={p.name} className="small">{p.name}
                  <ArgInput p={p} value={a.args?.[p.name]} onChange={(x) => edit(i, { ...a, args: { ...a.args, [p.name]: x } } as Action)} />
                </label>
              ))}
              <button className="link small" onClick={() => edit(i, null)} aria-label="Remove step">✕</button>
            </li>
          );
        })}
      </ol>
      <div className="export-row">
        <button className="btn" disabled={!specs.length || steps.length >= MAX} onClick={() => { setSteps((s) => [...s, s.length ? { ...s[s.length - 1], args: { ...s[s.length - 1].args } } : blank(specs[0])]); setRes(null); }}>+ step</button>
        <button className="btn primary" disabled={busy !== null || !steps.length} onClick={() => run(false)}>{busy === "predict" ? "Predicting…" : "Predict"}</button>
        <button className="btn" disabled={busy !== null || !steps.length} onClick={() => run(true)}>{busy === "test" ? "Testing…" : "Test on the real system"}</button>
      </div>
      {err && <p className="small tone-bad">{err}</p>}
      {res && (
        <>
          {res.match_rate != null && <div className="kpis"><div><span className="label">Predictions that matched reality</span><strong className="mono big">{Math.round(res.match_rate * 100)}%</strong></div></div>}
          <p className="dim small">{res.observed ? "Predicted values. Where reality differed, the actual value is shown in red." : "Predicted values."}</p>
          <div className="table-wrap">
            <table className="table compact">
              <thead><tr><th>#</th><th>action</th>{fields.map((f) => <th key={f}>{f}</th>)}</tr></thead>
              <tbody>
                {res.predicted.map((p, i) => (
                  <tr key={i}>
                    <td className="mono small">{i + 1}</td>
                    <td className="mono small">{steps[i]?.name}</td>
                    {fields.map((f) => {
                      const ok = res.match?.[i]?.[f];
                      return (
                        <td key={f} className={`mono small${ok === false ? " tone-bad" : ""}`}>
                          {show(p[f])}
                          {res.observed && ok === false && <> (actual {show(res.observed[i]?.[f])})</>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <Export v={v} runId={runId} />
    </div>
  );
}
