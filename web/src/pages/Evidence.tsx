import { useEffect, useState } from "react";

type Row = { success: number | null; n: number; ci: [number, number] };
type Arms = Partial<Record<string, Row>>;
type Obj = Record<string, unknown>;
interface Evidence {
  bench?: { arms: Arms; in_family: Arms; out_of_family: Arms; order: string[]; full_runs: number };
  model_value?: Record<string, unknown>;
  drift?: unknown;
  forge_table?: string[][];
  anchors?: { count: number; latest: Obj[] };
}

const NAMES: Record<string, [string, string]> = {
  full: ["Full", "system"], no_model: ["No", "model"], model_only: ["Model", "only"],
  classical: ["Classical", ""], random: ["Random", ""], idle: ["Idle", ""],
};
const LONG: Record<string, string> = {
  full: "the full system", no_model: "rules found by code alone", model_only: "the model alone",
  classical: "a classical controller", random: "random actions", idle: "doing nothing",
};
const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const human = (k: string) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const isObj = (x: unknown): x is Obj => !!x && typeof x === "object" && !Array.isArray(x);

function sentence(arms: Arms): string | null {
  const full = arms.full;
  if (!full || full.success == null) return null;
  const parts: string[] = [`The full system reached the goal in ${pct(full.success)} of ${full.n} held-out cases.`];
  const nm = arms.no_model;
  if (nm?.success != null) {
    const near = Math.abs(nm.success - full.success) <= 0.1;
    parts.push(near
      ? `On these systems, rules found by code alone matched the full system (${pct(nm.success)}).`
      : nm.success < full.success ? `Rules found by code alone did worse (${pct(nm.success)}).` : `Rules found by code alone did better (${pct(nm.success)}).`);
  }
  const base = ["random", "idle"].map((k) => arms[k]?.success).filter((v): v is number => typeof v === "number");
  if (base.length) parts.push(`Random and idle play reached ${pct(Math.max(...base))} at best.`);
  return parts.join(" ");
}

function Chart({ arms, order, label }: { arms: Arms; order: string[]; label: string }) {
  const keys = order.filter((k) => arms[k]);
  if (!keys.length) return null;
  const W = 340, H = 190, top = 14, base = 128, slot = W / keys.length, bw = Math.min(30, slot - 14);
  const y = (v: number) => base - v * (base - top);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ width: "100%", maxWidth: 520, height: "auto", display: "block" }}>
      {[0, 0.5, 1].map((g) => (
        <g key={g}>
          <line x1="0" x2={W} y1={y(g)} y2={y(g)} stroke="var(--line)" strokeWidth="1" />
          <text x="0" y={y(g) - 3} fontSize="9" fill="var(--text-3)">{pct(g)}</text>
        </g>
      ))}
      {keys.map((k, i) => {
        const r = arms[k]!, cx = slot * i + slot / 2, v = r.success ?? 0;
        const [a, b] = NAMES[k] ?? [k, ""];
        return (
          <g key={k}>
            <rect x={cx - bw / 2} y={y(v)} width={bw} height={Math.max(1, base - y(v))} rx="4" fill={k === "full" ? "var(--accent-strong)" : "var(--text-3)"} opacity={k === "full" ? 1 : 0.55} />
            <line x1={cx} x2={cx} y1={y(r.ci[0])} y2={y(r.ci[1])} stroke="var(--text)" strokeWidth="1.5" />
            <line x1={cx - 5} x2={cx + 5} y1={y(r.ci[0])} y2={y(r.ci[0])} stroke="var(--text)" strokeWidth="1.5" />
            <line x1={cx - 5} x2={cx + 5} y1={y(r.ci[1])} y2={y(r.ci[1])} stroke="var(--text)" strokeWidth="1.5" />
            <text x={cx} y={base + 15} fontSize="10" textAnchor="middle" fill="var(--text)">{a}</text>
            <text x={cx} y={base + 27} fontSize="10" textAnchor="middle" fill="var(--text)">{b}</text>
            <text x={cx} y={base + 43} fontSize="9.5" textAnchor="middle" fill="var(--text-3)">n = {r.n}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Facts({ data }: { data: unknown }) {
  if (Array.isArray(data)) return <ul className="ev-list">{data.map((x, i) => <li key={i}>{isObj(x) ? <Facts data={x} /> : String(x)}</li>)}</ul>;
  if (!isObj(data)) return <p>{String(data)}</p>;
  return (
    <dl className="ev-facts">
      {Object.entries(data).map(([k, v]) => (
        <div key={k}>
          <dt className="dim">{human(k)}</dt>
          <dd>{isObj(v) || Array.isArray(v) ? <Facts data={v} /> : typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Section({ title, lead, children }: { title: string; lead?: string | null; children: React.ReactNode }) {
  return (
    <section className="ev-sec">
      <h2>{title}</h2>
      {lead && <p className="ev-lead">{lead}</p>}
      {children}
    </section>
  );
}

export default function Evidence() {
  const [d, setD] = useState<Evidence | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    fetch("/api/evidence").then((r) => (r.ok ? r.json() : Promise.reject())).then(setD).catch(() => setErr(true));
  }, []);
  const b = d?.bench;
  const inF = b && Object.keys(b.in_family).length ? b.in_family : null;
  const outF = b && Object.keys(b.out_of_family).length ? b.out_of_family : null;
  const empty = d && !Object.keys(d).length;
  return (
    <main className="page ev">
      <style>{`
        .ev { max-width: 720px; }
        .ev-sec { margin-top: 40px; padding-top: 24px; border-top: 1px solid var(--line); }
        .ev-sec h2 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 8px; }
        .ev-lead { color: var(--text-2); margin: 0 0 16px; }
        .ev-note { color: var(--text-3); font-size: 13px; margin-top: 10px; }
        .ev-facts > div { display: flex; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
        .ev-facts dt { min-width: 140px; } .ev-facts dd { margin: 0; flex: 1; min-width: 0; overflow-wrap: anywhere; }
        .ev-list { padding-left: 18px; margin: 0; }
        .ev-code { font: 12px var(--mono); overflow-wrap: anywhere; }
      `}</style>
      <h1 className="page-title">How well does it actually work?</h1>
      <p className="page-sub">Real numbers from held-out tests, with the uncertainty shown. Small samples stay small here.</p>
      {err && <p className="error" role="alert">Couldn’t load the evidence right now.</p>}
      {!d && !err && <div className="skel skel-block" aria-busy="true" aria-label="Loading" />}
      {empty && <p className="dim">No results have been published yet.</p>}

      {b && (
        <Section title="Reaching the goal on new cases" lead={sentence(b.arms)}>
          <Chart arms={b.arms} order={b.order} label="Share of held-out cases where each approach reached the goal, with 95% confidence ranges" />
          <p className="ev-note">Bars show the share of held-out cases that reached the goal; whiskers show the 95% range.
            Compared: {b.order.filter((k) => b.arms[k]).map((k) => LONG[k]).join(", ")}.</p>
        </Section>
      )}

      {(inF || outF) && (
        <Section title="Familiar systems and unfamiliar ones" lead={inF?.full && outF?.full
          ? `On familiar systems the full system reached the goal in ${pct(inF.full.success)} of ${inF.full.n} cases. On generated systems nobody had seen, ${pct(outF.full.success)} of ${outF.full.n}.`
          : "Results split by whether the system was one it was built around or a newly generated one."}>
          {inF && <><h3 className="small dim">Familiar</h3><Chart arms={inF} order={b!.order} label="Familiar systems" /></>}
          {outF && <><h3 className="small dim" style={{ marginTop: 16 }}>Unfamiliar</h3><Chart arms={outF} order={b!.order} label="Unfamiliar systems" /></>}
          {d?.forge_table && (
            <div className="table-wrap" style={{ marginTop: 16 }}>
              <table className="table compact">
                <thead><tr>{d.forge_table[0].map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
                <tbody>{d.forge_table.slice(1).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {d?.drift != null && (
        <Section title="When the rules change" lead="False alarms, how long it takes to notice a change, and whether it recovers.">
          <Facts data={d.drift} />
        </Section>
      )}

      {d?.model_value && (
        <Section title="What the model adds" lead="Measured by turning the model off.">
          <Facts data={d.model_value} />
        </Section>
      )}

      {d?.anchors && (
        <Section title="Verify a run" lead={`Each run’s record is chained with a fingerprint, so edits after the fact are detectable. ${d.anchors.count} anchored.`}>
          <ul className="ev-list">
            {d.anchors.latest.map((a, i) => (
              <li key={i} className="ev-code">{Object.entries(a).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ")}</li>
            ))}
          </ul>
          <p className="ev-note">Check any run yourself with <span className="ev-code">logicscout verify</span>.</p>
        </Section>
      )}
    </main>
  );
}
