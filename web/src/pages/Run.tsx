import { useState } from "react";
import { api, runBase } from "../api";
import PhaseRail from "../components/PhaseRail";
import SystemPanel from "../components/SystemPanel";
import Tabs from "../components/Tabs";
import Timeline from "../components/Timeline";
import Debrief from "../components/Debrief";
import type { RunView } from "../state";
import { useRun, type Conn } from "../useRun";
import { pct } from "../ui";

export function RunLayout({
  v, banner, conn, base, runId, controls = true,
}: { v: RunView; banner?: string; conn?: Conn; base?: string; runId?: string; controls?: boolean }) {
  const [busy, setBusy] = useState<"shift" | "stop" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [debrief, setDebrief] = useState(false);
  const latest = v.versions.length ? [...v.versions].sort((a, b) => a.version - b.version).at(-1) : undefined;
  const budget = v.config?.probe_budget ?? v.manual?.probe_budget;
  const canShift = controls && !!runId && v.phase === "control" && !v.finished;
  const canStop = controls && !!runId && !v.finished;

  const act = async (kind: "shift" | "stop") => {
    if (!runId) return;
    setBusy(kind);
    setErr(null);
    try { await (kind === "shift" ? api.shift(runId) : api.stop(runId)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(null); }
  };

  return (
    <main className="run">
      {banner && <div className="banner" role="status">{banner}</div>}
      <header className="topbar">
        <div className="topbar-row">
          <div className="title">
            <strong>{v.manual?.title ?? v.config?.world_id ?? "…"}</strong>
            {v.manual?.objectives?.[0] && <span className="dim small">{(v.manual.objectives.find((o) => o.id === v.config?.objective_id) ?? v.manual.objectives[0]).text}</span>}
          </div>
          <dl className="counters">
            <div><dt>Probes</dt><dd className="mono">{v.probeSteps}{budget ? <span className="dim">/{budget}</span> : null}</dd></div>
            <div><dt>Theory</dt><dd className="mono">{pct(latest?.accuracy)} <span className="dim">vs {pct(latest?.baseline)}</span></dd></div>
            <div><dt>Model calls</dt><dd className="mono">{v.calls.length}</dd></div>
          </dl>
          <div className="actions">
            {conn && conn !== "open" && !v.finished && <span className="chip chip-warn" role="status">{conn === "retrying" ? "reconnecting" : conn}</span>}
            {controls && (
              <>
                <button className="btn danger" disabled={!canShift || busy !== null} onClick={() => act("shift")}
                  title={canShift ? "Silently change the hidden rules" : "Available during control"}>
                  {busy === "shift" ? "Changing…" : "Change the rules"}
                </button>
                <button className="btn" disabled={!canStop || busy !== null} onClick={() => act("stop")}>Stop</button>
              </>
            )}
            {v.finished && base && (
              <button className="btn" aria-pressed={debrief} onClick={() => setDebrief(!debrief)}>Debrief</button>
            )}
          </div>
        </div>
        <PhaseRail v={v} />
        {err && <p className="error" role="alert">{err}</p>}
      </header>
      {debrief && base && <Debrief base={base} rules={v.theory?.rules ?? []} />}
      <div className="columns">
        <SystemPanel v={v} />
        <Timeline v={v} />
        <Tabs v={v} />
      </div>
    </main>
  );
}

export default function Run({ kind, id }: { kind: "run" | "replay"; id: string }) {
  const base = runBase(kind, id);
  const { view, conn, loadError } = useRun(base);
  const replay = kind === "replay";
  return (
    <>
      {loadError && view.lastSeq < 0 && <p className="error page" role="alert">{loadError}</p>}
      <RunLayout v={view} conn={conn} base={base} runId={kind === "run" ? id : undefined}
        banner={replay ? "Recording" : undefined} controls={!replay} />
    </>
  );
}
