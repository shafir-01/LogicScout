import { useEffect, useRef, useState } from "react";
import { safetyCount, type RunView } from "../state";
import type { Rule } from "../types";
import { Chip, Meter, Sparkline, fmt, host, pct, statusTone } from "../ui";
import Timeline, { focusSeq } from "./Timeline";
import Debrief from "./Debrief";
import WhatIf from "./WhatIf";
import RuleViz from "./RuleViz";

const CODEY = /[=<>(){}[\]%`|&*]|\b(obs|args|mem)\.|_[a-z]/i;
const words = (s: string) => s.replace(/\b(obs|args|mem)\./g, "").replace(/_/g, " ");
/** A sentence for a rule; formulas are summarized as "what it affects". */
function plainRule(r: Rule): string {
  if (!CODEY.test(r.statement)) return r.statement;
  const fields = Object.keys(r.effects ?? {}).map(words);
  const act = r.action && r.action !== "*" ? `After “${words(r.action)}”` : "After every step";
  const cond = r.when && r.when !== "True" ? ", under some conditions," : "";
  return fields.length ? `${act}${cond} it changes ${fields.join(", ")}.` : words(r.statement);
}

function RuleRow({ r }: { r: Rule }) {
  const [open, setOpen] = useState(false);
  const status = r.status === "supported" && r.confidence < 0.7 ? "tentative" : r.status;
  const dsl = [
    `action: ${r.action ?? "*"}`,
    `when:   ${r.when ?? "True"}`,
    ...Object.entries(r.effects ?? {}).map(([k, e]) => `obs.${k} ← ${e}`),
    ...Object.entries(r.memory ?? {}).map(([k, e]) => `mem.${k} ← ${e}`),
    ...(r.delay ? [`delay:  ${r.delay}`] : []),
  ].join("\n");
  return (
    <li className={`rule rule-${r.status}`}>
      <RuleViz rule={r} />
      <div className="rule-top">
        <Chip tone={statusTone(status)}>{status}</Chip>
        <span className="rule-statement">{plainRule(r)}</span>
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
        <button className="link small" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide formula" : "Show formula"}</button>
      </div>
      {open && <>{plainRule(r) !== r.statement && <p className="small dim">{r.statement}</p>}<pre className="dsl mono">{dsl}</pre></>}
    </li>
  );
}

function TheoryTab({ v }: { v: RunView }) {
  const th = v.theory;
  const vs = [...v.versions].sort((a, b) => a.version - b.version);
  const order = { supported: 0, tentative: 1, refuted: 2, retired: 3 } as const;
  const [all, setAll] = useState(false);
  const seen = new Set<string>();
  const rules = [...(th?.rules ?? [])]
    .sort((a, b) => order[a.status] - order[b.status] || b.confidence - a.confidence)
    .filter((r) => {
      const key = `${r.action ?? ""}|${r.when ?? ""}|${JSON.stringify(r.effects ?? {})}|${r.statement.trim().toLowerCase()}`;
      const k2 = r.statement.trim().toLowerCase();
      if (seen.has(key) || seen.has(k2)) return false;
      seen.add(key); seen.add(k2);
      return true;
    });
  const shown = all ? rules : rules.slice(0, 8);
  return (
    <div className="tab-body">
      <div className="kpis">
        <div><span className="label">Rules version</span><strong className="mono">{th?.version ?? "–"}</strong></div>
        <div><span className="label" title="How often its rules correctly predict every reading one step ahead">Predicts the next step</span><strong className="mono">{pct(vs.at(-1)?.accuracy)}</strong></div>
        <div><span className="label" title="Score from assuming nothing ever changes">Guess nothing changes</span><strong className="mono dim">{pct(vs.at(-1)?.baseline)}</strong></div>
      </div>
      <Sparkline series={[
        { label: "its rules", tone: "accent", values: vs.map((x) => x.accuracy) },
        { label: "if nothing changes", tone: "muted", values: vs.map((x) => x.baseline) },
      ]} />
      <ul className="rules">{shown.map((r) => <RuleRow key={r.id} r={r} />)}</ul>
      {rules.length > 8 && <button className="link small" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${rules.length} rules`}</button>}
      {!rules.length && <p className="empty">No rules yet</p>}
      {th?.unknowns && th.unknowns.length > 0 && (
        <>
          <h3 className="label">Still unsure about</h3>
          <ul className="plain">{th.unknowns.map((u, i) => <li key={i} className="small">{u}</li>)}</ul>
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
        <div><span className="label">How it decides</span><strong>{pb.origin === "planner" ? "Looks ahead each step" : "Written checklist"}</strong></div>
        <div><span className="label">Based on rules version</span><strong className="mono">{pb.theory_version}</strong></div>
        <div>
          <span className="label" title="A practice run against its own rules, before touching the real system">Practice run</span>
          <strong className={`mono tone-${v.simulated?.success ? "ok" : v.simulated ? "bad" : "muted"}`}>
            {v.simulated ? `${v.simulated.success ? "✓" : "✗"} ${v.simulated.steps ?? ""}` : "–"}
          </strong>
        </div>
      </div>
      {pb.origin === "planner" && pb.rules.length === 0 ? (
        <p>No fixed checklist here. Each step it looks a few moves ahead using its learned rules and picks the best.</p>
      ) : (
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
          <code className="mono when dim">if nothing else applies</code>
          <span className="arrow" aria-hidden="true">→</span>
          <code className="mono do">{tpl(pb.fallback)}</code>
        </li>
      </ol>
      )}
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

const STRATEGY: Record<string, string> = { random: "Random moves", idle: "Doing nothing", greedy: "Simple greedy" };

function RefereeTab({ v }: { v: RunView }) {
  const r = v.referee;
  if (!r) return <div className="tab-body"><p className="empty">At the end, an independent referee tests it on situations it never saw.</p></div>;
  const persistence = r.baselines?.persistence_accuracy ?? v.versions.at(-1)?.baseline ?? r.baselines?.persistence;
  const maxSteps = Math.max(1, ...r.cases.map((c) => c.steps));
  return (
    <div className="tab-body">
      <div className="kpis">
        <div><span className="label">Success on unseen tests</span><strong className="mono big">{pct(r.success_rate)}</strong></div>
        <div><span className="label">Cases</span><strong className="mono">{r.cases.filter((c) => c.success).length}/{r.cases.length}</strong></div>
      </div>
      {(r.changed_accuracy != null || r.goal_field_accuracy != null) && (
        <div className="kpis">
          {r.changed_accuracy != null && (
            <div><span className="label">Predicts changes correctly</span><strong className="mono">{pct(r.changed_accuracy)}</strong>
              {r.changed_baseline != null && <span className="small dim">vs {pct(r.changed_baseline)} baseline</span>}
              {r.n_changed != null && <span className="small dim">{r.n_changed} changes{r.n_transitions != null ? ` in ${r.n_transitions} steps` : ""}</span>}
            </div>
          )}
          {r.goal_field_accuracy != null && <div><span className="label">Predicts the goal reading</span><strong className="mono">{pct(r.goal_field_accuracy)}</strong></div>}
        </div>
      )}
      {r.rollout_accuracy && Object.keys(r.rollout_accuracy).length > 0 && (
        <>
          <h3 className="label">Looking ahead</h3>
          <Bars rows={Object.entries(r.rollout_accuracy)
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([k, x]) => ({ label: `${k} ${Number(k) === 1 ? "step" : "steps"} ahead`, value: Number(x), tone: "accent" as const }))} />
        </>
      )}
      {safetyCount(v) != null && <p className="small dim">Safety limits kept: {safetyCount(v)} {safetyCount(v) === 1 ? "violation" : "violations"}</p>}
      <h3 className="label">Goal reached, compared with simple strategies</h3>
      <p className="small dim">Same unseen situations, same time limit, different ways of acting.</p>
      <Bars rows={[
        { label: "LogicScout", value: r.success_rate, tone: "accent" },
        ...Object.entries(r.baselines ?? {}).filter(([k]) => !k.endsWith("_accuracy"))
          .map(([k, x]) => ({ label: STRATEGY[k] ?? k.replace(/_/g, " "), value: x, tone: "muted" as const })),
      ]} />
      <h3 className="label">Prediction accuracy</h3>
      <Bars rows={[
        { label: "its rules", value: r.prediction_accuracy, tone: "accent" },
        ...(persistence != null && Number.isFinite(persistence) ? [{ label: "Guess nothing changes", value: persistence, tone: "muted" as const }] : []),
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
      <h3 className="label">Fairness checks</h3>
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

type TabProps = { v: RunView; runId?: string; base?: string };
export type TabRequest = { id: string; n: number } | null;

function ExperimentsTab({ v }: TabProps) {
  return <div className="tab-body"><Timeline v={v} /></div>;
}

function HiddenTab({ v, base }: TabProps) {
  if (!base) return <div className="tab-body"><p className="empty">Not available</p></div>;
  if (!v.finished) return <div className="tab-body"><p className="empty">Revealed when the run ends</p></div>;
  return <div className="tab-body"><Debrief base={base} rules={v.theory?.rules ?? []} driftRules={v.driftRules} recoveryDiff={v.recoveryDiff} /></div>;
}

const TABS: { id: string; label: string; hint: string; C: (p: TabProps) => JSX.Element | null }[] = [
  { id: "experiments", label: "Experiments", hint: "Every test it ran, what it expected, and what really happened.", C: ExperimentsTab },
  { id: "theory", label: "Rules", hint: "What it believes about how the system works, with how sure it is and the evidence.", C: TheoryTab },
  { id: "playbook", label: "Playbook", hint: "The step-by-step controller it wrote from its rules. It runs without any AI.", C: PlaybookTab },
  { id: "public", label: "Public vs observed", hint: "What public sources claimed, and whether its own experiments agreed.", C: PublicTab },
  { id: "referee", label: "Referee", hint: "An independent check on situations it never saw during learning.", C: RefereeTab },
  { id: "model", label: "Model calls", hint: "Each time it asked the AI model to think: why, how long, and how many words.", C: ModelTab },
  { id: "ask", label: "Ask", hint: "Try your own sequence of moves and compare its prediction with reality.", C: WhatIf },
  { id: "hidden", label: "Hidden laws", hint: "The real rules of the system, revealed after the run so you can compare.", C: HiddenTab },
];

export default function Tabs({ v, runId, base, request = null }: TabProps & { request?: TabRequest }) {
  const [tab, setTab] = useState(request?.id ?? "experiments");
  useEffect(() => { if (request) setTab(request.id); }, [request]);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    const on = () => setTab("experiments");
    window.addEventListener("ls-show-experiments", on);
    return () => window.removeEventListener("ls-show-experiments", on);
  }, []);
  const idx = Math.max(0, TABS.findIndex((t) => t.id === tab));
  const Active = TABS[idx].C;
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    const n = (idx + d + TABS.length) % TABS.length;
    setTab(TABS[n].id);
    refs.current[n]?.focus();
  };
  return (
    <section className="knowledge" aria-label="Details">
      <div className="tabs" role="tablist" aria-label="Details" onKeyDown={onKey}>
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
            title={t.hint}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === "referee" && v.referee && <span className="dot tone-ok" aria-hidden="true" />}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${TABS[idx].id}`} aria-labelledby={`tab-${TABS[idx].id}`} className="tabpanel">
        <p className="tab-hint">{TABS[idx].hint}</p>
        <Active v={v} runId={runId} base={base} />
      </div>
    </section>
  );
}
