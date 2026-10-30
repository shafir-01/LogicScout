import { useRef, useState } from "react";
import type { RunView } from "../state";
import type { Rule } from "../types";
import { Chip, Meter, Sparkline, fmt, host, pct, statusTone } from "../ui";
import { focusSeq } from "./Timeline";
import WhatIf from "./WhatIf";

function RuleRow({ r }: { r: Rule }) {
  const [open, setOpen] = useState(false);
  const dsl = [
    `action: ${r.action ?? "*"}`,
    `when:   ${r.when ?? "True"}`,
    ...Object.entries(r.effects ?? {}).map(([k, e]) => `obs.${k} ← ${e}`),
    ...Object.entries(r.memory ?? {}).map(([k, e]) => `mem.${k} ← ${e}`),
    ...(r.delay ? [`delay:  ${r.delay}`] : []),
  ].join("\n");
  return (
    <li className={`rule rule-${r.status}`}>
      <div className="rule-top">
        <Chip tone={statusTone(r.status)}>{r.status}</Chip>
        <span className="rule-statement">{r.statement}</span>
      </div>
      <div className="rule-meta">
        <Meter value={r.confidence} tone={statusTone(r.status) === "muted" ? "accent" : statusTone(r.status)} label="confidence" />
        <span className="mono small">{pct(r.confidence)}</span>
        <Chip tone={r.source === "probe" ? "muted" : "accent"}>{r.source}</Chip>
        {r.evidence?.length > 0 && (
          <span className="evidence small">
            {r.evidence.length} evidence
            {r.evidence.slice(-3).map((s) => (
              <button key={s} className="link mono" onClick={() => focusSeq(s)} title="Show in experiments">#{s}</button>
            ))}
          </span>
        )}
        {r.citations?.map((u) => <a key={u} className="small" href={u} target="_blank" rel="noreferrer">{host(u)}</a>)}
        <button className="link small" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "hide rule" : "rule"}</button>
      </div>
      {open && <pre className="dsl mono">{dsl}</pre>}
    </li>
  );
}

function TheoryTab({ v }: { v: RunView }) {
  const th = v.theory;
  const vs = [...v.versions].sort((a, b) => a.version - b.version);
  const order = { supported: 0, tentative: 1, refuted: 2, retired: 3 } as const;
  const rules = [...(th?.rules ?? [])].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <div className="tab-body">
      <div className="kpis">
        <div><span className="label">Theory</span><strong className="mono">v{th?.version ?? "–"}</strong></div>
        <div><span className="label">Accuracy</span><strong className="mono">{pct(vs.at(-1)?.accuracy)}</strong></div>
        <div><span className="label">Baseline</span><strong className="mono dim">{pct(vs.at(-1)?.baseline)}</strong></div>
      </div>
      <Sparkline series={[
        { label: "theory", tone: "accent", values: vs.map((x) => x.accuracy) },
        { label: "nothing-changes baseline", tone: "muted", values: vs.map((x) => x.baseline) },
      ]} />
      <ul className="rules">{rules.map((r) => <RuleRow key={r.id} r={r} />)}</ul>
      {!rules.length && <p className="empty">No rules yet</p>}
      {th?.unknowns && th.unknowns.length > 0 && (
        <>
          <h3 className="label">Unknowns</h3>
          <ul className="plain">{th.unknowns.map((u, i) => <li key={i} className="small">? {u}</li>)}</ul>
        </>
      )}
    </div>
  );
}

function tpl(t: { name: string; args?: Record<string, string> }) {
  return `${t.name}(${Object.entries(t.args ?? {}).map(([k, e]) => `${k}=${e}`).join(", ")})`;
}

function PlaybookTab({ v }: { v: RunView }) {
  const pb = v.playbook;
  if (!pb) return <div className="tab-body"><p className="empty">No playbook yet</p></div>;
  return (
    <div className="tab-body">
      <div className="kpis">
        <div><span className="label">Origin</span><strong>{pb.origin}</strong></div>
        <div><span className="label">Theory</span><strong className="mono">v{pb.theory_version}</strong></div>
        <div>
          <span className="label">Simulated</span>
          <strong className={`mono tone-${v.simulated?.success ? "ok" : v.simulated ? "bad" : "muted"}`}>
            {v.simulated ? `${v.simulated.success ? "✓" : "✗"} ${v.simulated.steps ?? ""}` : "–"}
          </strong>
        </div>
      </div>
      <ol className="pb-rules">
        {pb.rules.map((r, i) => (
          <li key={i}>
            <code className="mono when">{r.when}</code>
            <span className="arrow" aria-hidden="true">→</span>
            <code className="mono do">{tpl(r.do)}</code>
            {r.why && <span className="dim small why">{r.why}</span>}
          </li>
        ))}
        <li>
          <code className="mono when dim">otherwise</code>
          <span className="arrow" aria-hidden="true">→</span>
          <code className="mono do">{tpl(pb.fallback)}</code>
        </li>
      </ol>
      <p className="dim small">Runs without the model.</p>
    </div>
  );
}

function PublicTab({ v }: { v: RunView }) {
  const claims = v.checked ?? v.claims.map((h) => ({ claim: h.statement, status: "untested" as const, citations: h.rule?.citations ?? [] }));
  const byUrl = new Map(v.sources.map((s) => [s.url, s]));
  if (!claims.length && !v.sources.length) {
    return <div className="tab-body"><p className="empty">{v.config && !v.config.use_briefing ? "Briefing off for this run" : "No public briefing yet"}</p></div>;
  }
  const counts = { confirmed: 0, contradicted: 0, untested: 0 };
  for (const c of claims) counts[c.status] = (counts[c.status] ?? 0) + 1;
  return (
    <div className="tab-body">
      <div className="kpis">
        <div><span className="label">Confirmed</span><strong className="mono tone-ok">{counts.confirmed}</strong></div>
        <div><span className="label">Contradicted</span><strong className="mono tone-bad">{counts.contradicted}</strong></div>
        <div><span className="label">Untested</span><strong className="mono dim">{counts.untested}</strong></div>
      </div>
      <ul className="claims">
        {claims.map((c, i) => (
          <li key={i} className="claim">
            <div className="rule-top"><Chip tone={statusTone(c.status)}>{c.status}</Chip><span>{c.claim}</span></div>
            <div className="cites">
              {c.citations.map((u) => {
                const s = byUrl.get(u);
                return (
                  <a key={u} className="cite" href={u} target="_blank" rel="noreferrer">
                    <span className="cite-title">{s?.title ?? host(u)}</span>
                    <span className="mono small dim">{host(u)}{s?.published ? ` · ${s.published}` : ""}</span>
                  </a>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
      {v.sources.length > 0 && (
        <>
          <h3 className="label">Sources</h3>
          <div className="cites">
            {v.sources.map((s) => (
              <a key={s.url} className="cite" href={s.url} target="_blank" rel="noreferrer">
                <span className="cite-title">{s.title ?? host(s.url)}</span>
                <span className="mono small dim">{host(s.url)}{s.published ? ` · ${s.published}` : ""}</span>
              </a>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Bars({ rows }: { rows: { label: string; value: number; tone: "ok" | "bad" | "accent" | "muted"; text?: string }[] }) {
  return (
    <ul className="bars">
      {rows.map((r) => (
        <li key={r.label}>
          <span className="bar-label small">{r.label}</span>
          <Meter value={r.value} tone={r.tone} label={r.label} />
          <span className="mono small">{r.text ?? pct(r.value)}</span>
        </li>
      ))}
    </ul>
  );
}

function RefereeTab({ v }: { v: RunView }) {
  const r = v.referee;
  if (!r) return <div className="tab-body"><p className="empty">The referee scores the run on held-out cases at the end.</p></div>;
  const persistence = v.versions.at(-1)?.baseline ?? r.baselines?.persistence;
  const maxSteps = Math.max(1, ...r.cases.map((c) => c.steps));
  return (
    <div className="tab-body">
      <div className="kpis">
        <div><span className="label">Held-out success</span><strong className="mono big">{pct(r.success_rate)}</strong></div>
        <div><span className="label">Cases</span><strong className="mono">{r.cases.filter((c) => c.success).length}/{r.cases.length}</strong></div>
      </div>
      <h3 className="label">vs baselines</h3>
      <Bars rows={[
        { label: "LogicScout", value: r.success_rate, tone: "accent" },
        ...Object.entries(r.baselines ?? {}).map(([k, x]) => ({ label: k.replace(/_/g, " "), value: x, tone: "muted" as const })),
      ]} />
      <h3 className="label">Prediction accuracy</h3>
      <Bars rows={[
        { label: "learned theory", value: r.prediction_accuracy, tone: "accent" },
        ...(persistence != null && Number.isFinite(persistence) ? [{ label: "nothing changes", value: persistence, tone: "muted" as const }] : []),
      ]} />
      <h3 className="label">Cases</h3>
      <ul className="bars">
        {r.cases.map((c) => (
          <li key={c.case_id} title={c.note}>
            <span className="bar-label mono small">{c.case_id}</span>
            <Meter value={c.steps / maxSteps} tone={c.success ? "ok" : "bad"} label={c.case_id} />
            <span className="mono small">{c.success ? "✓" : "✗"} {c.steps}</span>
          </li>
        ))}
      </ul>
      <h3 className="label">Leakage checks</h3>
      <ul className="checks">
        {Object.entries(r.leakage_checks ?? {}).map(([k, ok]) => (
          <li key={k}><span className={`mark tone-${ok ? "ok" : "bad"}`}>{ok ? "✓" : "✗"}</span><span className="small">{k.replace(/_/g, " ")}</span><Chip tone={ok ? "ok" : "bad"}>{ok ? "pass" : "fail"}</Chip></li>
        ))}
      </ul>
      {r.notes?.length > 0 && <ul className="plain">{r.notes.map((n, i) => <li key={i} className="small dim">{n}</li>)}</ul>}
      {r.digest && <p className="digest mono small" title="Referee report digest">digest {r.digest}</p>}
    </div>
  );
}

function ModelTab({ v }: { v: RunView }) {
  const calls = v.calls;
  const tot = calls.reduce(
    (a, c) => ({ ms: a.ms + (c.latency_ms ?? 0), pin: a.pin + (c.prompt_tokens ?? 0), pout: a.pout + (c.completion_tokens ?? 0), esc: a.esc + (c.escalated ? 1 : 0), fail: a.fail + (c.ok ? 0 : 1) }),
    { ms: 0, pin: 0, pout: 0, esc: 0, fail: 0 },
  );
  const models = Array.from(new Set(calls.map((c) => c.model)));
  return (
    <div className="tab-body">
      <div className="kpis">
        <div><span className="label">Calls</span><strong className="mono">{calls.length}</strong></div>
        <div><span className="label">Tokens</span><strong className="mono">{(tot.pin + tot.pout).toLocaleString()}</strong></div>
        <div><span className="label">Time</span><strong className="mono">{(tot.ms / 1000).toFixed(1)}s</strong></div>
        <div><span className="label">Escalated</span><strong className="mono">{tot.esc}</strong></div>
      </div>
      {models.length > 0 && <p className="mono small dim">{models.join(" · ")}</p>}
      <div className="table-wrap">
        <table className="table compact">
          <thead><tr><th>purpose</th><th>tier</th><th>model</th><th>ms</th><th>tokens</th><th></th></tr></thead>
          <tbody>
            {calls.map((c, i) => (
              <tr key={i} className={c.ok ? "" : "row-bad"} title={c.error ?? undefined}>
                <td className="small">{c.purpose}</td>
                <td><Chip tone={c.tier === "deep" ? "accent" : "muted"}>{c.tier}</Chip></td>
                <td className="mono small">{c.model}</td>
                <td className="mono small">{Math.round(c.latency_ms)}</td>
                <td className="mono small">{fmt((c.prompt_tokens ?? 0) + (c.completion_tokens ?? 0))}</td>
                <td className="small">{c.escalated ? <Chip tone="warn">escalated</Chip> : !c.ok ? <Chip tone="bad">error</Chip> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!calls.length && <p className="empty">No model calls yet</p>}
    </div>
  );
}

const TABS = [
  { id: "theory", label: "Theory", C: TheoryTab },
  { id: "playbook", label: "Playbook", C: PlaybookTab },
  { id: "public", label: "Public vs Observed", C: PublicTab },
  { id: "referee", label: "Referee", C: RefereeTab },
  { id: "model", label: "Model", C: ModelTab },
  { id: "ask", label: "Ask", C: WhatIf },
] as const;

export default function Tabs({ v, runId }: { v: RunView; runId?: string }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("theory");
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = TABS.findIndex((t) => t.id === tab);
  const Active = TABS[idx].C;
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    const n = (idx + d + TABS.length) % TABS.length;
    setTab(TABS[n].id);
    refs.current[n]?.focus();
  };
  return (
    <section className="panel knowledge" aria-label="Knowledge">
      <div className="tabs" role="tablist" onKeyDown={onKey}>
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => { refs.current[i] = el; }}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            className="tab"
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === "referee" && v.referee && <span className="dot tone-ok" aria-hidden="true" />}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        <Active v={v} runId={runId} />
      </div>
    </section>
  );
}
