import { useEffect, useState } from "react";
import { api } from "../api";
import { fmt } from "../ui";

type Obj = Record<string, unknown>;
const isObj = (x: unknown): x is Obj => !!x && typeof x === "object" && !Array.isArray(x);

function Value({ v }: { v: unknown }) {
  if (typeof v === "boolean") return <span className={`chip chip-${v ? "ok" : "bad"}`}>{v ? "yes" : "no"}</span>;
  if (Array.isArray(v) && v.every((x) => typeof x !== "object")) return <>{v.length ? v.map(fmt).join(", ") : "–"}</>;
  if (Array.isArray(v) && v.every(isObj)) return <ObjTable rows={v as Obj[]} />;
  if (isObj(v)) {
    return (
      <span className="kv">
        {Object.entries(v).map(([k, x]) => (
          <span key={k}><span className="dim">{k.replace(/_/g, " ")}</span> {typeof x === "boolean" ? <Value v={x} /> : fmt(x)}</span>
        ))}
      </span>
    );
  }
  return <>{fmt(v)}</>;
}

function ObjTable({ rows }: { rows: Obj[] }) {
  if (!rows.length) return <>–</>;
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  return (
    <table className="table compact">
      <thead><tr>{cols.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c} className="mono"><Value v={r[c]} /></td>)}</tr>)}</tbody>
    </table>
  );
}

const secs = (ms: unknown) => (typeof ms === "number" ? `${(ms / 1000).toFixed(1)} s` : "–");
const big = (n: unknown) => (typeof n !== "number" ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));
const LABELS: Record<string, string> = {
  providers: "Provider", models: "Models", model_calls: "Model calls", latency_ms: "Response time", tokens: "Tokens",
  error_rate: "Calls retried", tavily: "Public search",
};

function pretty(k: string, v: unknown): unknown {
  if (k === "latency_ms" && isObj(v)) return `median ${secs(v.p50)} · slowest 5% ${secs(v.p95)}`;
  if (k === "tokens" && isObj(v)) return `${big(v.prompt)} in · ${big(v.completion)} out`;
  if (k === "error_rate" && typeof v === "number") return `${Math.round(v * 100)}%`;
  if (typeof v === "number" && v >= 1e4) return big(v);
  return v;
}

export default function Infra() {
  const [data, setData] = useState<unknown>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.infra().then(setData).catch((e: Error) => setErr(e.message)); }, []);

  return (
    <main className="page">
      <h1 className="page-title">Under the hood</h1>
      <p className="page-sub">Live numbers from this server.</p>
      {err && <p className="error" role="alert">{err}</p>}
      {data == null && !err && <div className="skel skel-block" aria-busy="true" aria-label="Loading" />}
      {Array.isArray(data) && <div className="table-wrap"><ObjTable rows={data.filter(isObj)} /></div>}
      {isObj(data) && (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {Object.entries(data).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">{LABELS[k] ?? k.replace(/_/g, " ")}</th>
                  <td className="mono"><Value v={pretty(k, v)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
