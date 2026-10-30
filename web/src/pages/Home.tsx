import { useEffect, useState } from "react";
import { api, type Replay } from "../api";
import type { WorldManual } from "../types";
import { go } from "../ui";

function WorldCard({ w, briefingDefault }: { w: WorldManual; briefingDefault: boolean }) {
  const [briefing, setBriefing] = useState(briefingDefault);
  useEffect(() => setBriefing(briefingDefault), [briefingDefault]);
  const [transfer, setTransfer] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const objective = w.objectives?.[0];

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { run_id } = await api.startRun({ world_id: w.world_id, use_briefing: briefing, use_transfer: transfer });
      go(`/run/${run_id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <article className="card world">
      <header>
        <h2>{w.title}</h2>
        <span className="dim mono">{w.domain}</span>
      </header>
      {objective && <p className="objective">{objective.text}</p>}
      <dl className="facts">
        <div><dt>Controls</dt><dd className="mono">{w.actions?.length ?? 0}</dd></div>
        <div><dt>Signals</dt><dd className="mono">{w.observations?.length ?? 0}</dd></div>
        <div><dt>Probe budget</dt><dd className="mono">{w.probe_budget}</dd></div>
      </dl>
      <div className="card-actions">
        <label className="toggle"><input type="checkbox" checked={briefing} onChange={(e) => setBriefing(e.target.checked)} /> Public briefing</label>
        <label className="toggle"><input type="checkbox" checked={transfer} onChange={(e) => setTransfer(e.target.checked)} /> Transfer</label>
        <button className="btn primary" onClick={start} disabled={busy}>{busy ? "Starting…" : "Start"}</button>
      </div>
      {err && <p className="error" role="alert">{err}</p>}
    </article>
  );
}

export default function Home() {
  const [worlds, setWorlds] = useState<WorldManual[] | null>(null);
  const [replays, setReplays] = useState<Replay[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [briefingOk, setBriefingOk] = useState(true);

  useEffect(() => {
    api.worlds().then(setWorlds).catch((e: Error) => setErr(e.message));
    api.replays().then(setReplays).catch(() => setReplays([]));
    api.health().then((h) => setBriefingOk(h.tavily_configured !== false)).catch(() => undefined);
  }, []);

  return (
    <main className="home">
      <section className="hero">
        <h1 className="wordmark">LogicScout</h1>
        <p className="pitch">It has never seen this system. It learns the rules, takes control, and adapts when they change.</p>
      </section>

      {err && <p className="error" role="alert">Backend unavailable: {err}</p>}
      {!worlds && !err && <p className="dim">Loading worlds…</p>}
      <section className="grid" aria-label="Worlds">
        {worlds?.map((w) => <WorldCard key={w.world_id} w={w} briefingDefault={briefingOk} />)}
      </section>

      {replays.length > 0 && (
        <section className="replays" aria-label="Recorded runs">
          <h3 className="label">Recorded runs</h3>
          <div className="replay-row">
            {replays.map((r) => (
              <a key={r.name} className="card replay" href={`#/replay/${encodeURIComponent(r.name)}`}>
                <span className="chip chip-muted">Recording</span>
                <strong>{r.title ?? r.world_id ?? r.name}</strong>
                <span className="dim mono small">{r.name}</span>
                {typeof r.success_rate === "number" && <span className="mono small">{Math.round(r.success_rate * 100)}% held-out success</span>}
              </a>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
