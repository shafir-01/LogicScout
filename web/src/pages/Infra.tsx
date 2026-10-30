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

export default function Infra() {
  const [data, setData] = useState<unknown>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.infra().then(setData).catch((e: Error) => setErr(e.message)); }, []);

  return (
    <main className="page">
      <h1 className="page-title">Infrastructure</h1>
      {err && <p className="error" role="alert">{err}</p>}
      {data == null && !err && <p className="dim">Loading…</p>}
      {Array.isArray(data) && <div className="table-wrap"><ObjTable rows={data.filter(isObj)} /></div>}
      {isObj(data) && (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {Object.entries(data).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">{k.replace(/_/g, " ")}</th>
                  <td className="mono"><Value v={v} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
