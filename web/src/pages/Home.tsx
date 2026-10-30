import { useEffect, useRef, useState } from "react";
import { ApiError, api, type Replay } from "../api";
import type { RunConfig, WorldManual } from "../types";
import { go, humanGoal, shortTitle } from "../ui";

type Item = { id: string; title: string; goal?: string };
type Forge = { variant: string; manual: WorldManual };

async function forgeNew(): Promise<Forge | null> {
  try {
    const r = await fetch("/api/forge/new");
    if (!r.ok) return null;
    const j = await r.json();
    return j?.manual && j?.variant != null ? { variant: String(j.variant), manual: j.manual as WorldManual } : null;
  } catch { return null; }
}

function Picker({ items, value, onChange, onRegen }: { items: Item[]; value: string; onChange: (id: string) => void; onRegen?: () => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = Math.max(0, items.findIndex((w) => w.id === value));
  const onKey = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).getAttribute("role") !== "radio") return;
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (idx + d + items.length) % items.length;
    onChange(items[n].id);
    refs.current[n]?.focus();
  };
  return (
    <div className="picker" role="radiogroup" aria-label="System" onKeyDown={onKey}>
      {items.map((w, i) => {
        const on = i === idx;
        return (
          <div key={w.id} className="seg-wrap">
            <button
              ref={(el) => { refs.current[i] = el; }}
              role="radio"
              aria-checked={on}
              tabIndex={on ? 0 : -1}
              className="seg"
              onClick={() => onChange(w.id)}
            >
              {w.title}
            </button>
            {w.id === "forge" && on && onRegen && (
              <button className="seg-regen" onClick={onRegen} aria-label="Generate another unknown system" title="Generate another">↻</button>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function Home() {
  const [worlds, setWorlds] = useState<WorldManual[] | null>(null);
  const [replays, setReplays] = useState<Replay[]>([]);
  const [down, setDown] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState("");
  const [options, setOptions] = useState(false);
  const [briefing, setBriefing] = useState(true);
  const [search, setSearch] = useState(true);
  const [transfer, setTransfer] = useState(false);
  const [busy, setBusy] = useState(false);
  const [forge, setForge] = useState<Forge | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    forgeNew().then((f) => alive && f && setForge(f));
    api.worlds()
      .then((w) => { if (alive) { setWorlds(w); setDown(null); } })
      .catch((e: Error) => { if (alive) setDown(e.message); });
    api.replays().then((r) => alive && setReplays(r)).catch(() => undefined);
    api.health().then((h) => {
      if (!alive) return;
      const ok = h.tavily_configured !== false;
      setSearch(ok);
      setBriefing(ok);
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [attempt]);

  useEffect(() => {
    if (!down) return;
    const t = window.setTimeout(() => setAttempt((a) => a + 1), 5000);
    return () => clearTimeout(t);
  }, [down, attempt]);

  const items: Item[] = [
    ...(forge ? [{ id: "forge", title: shortTitle("forge", forge.manual.title), goal: humanGoal(forge.manual.objectives?.[0]?.text) }] : []),
    ...(worlds ?? []).filter((w) => w.world_id !== "forge").map((w) => ({ id: w.world_id, title: shortTitle(w.world_id, w.title), goal: humanGoal(w.objectives?.[0]?.text) })),
  ];
  const cur = items.some((x) => x.id === sel) ? sel : items[0]?.id ?? "";

  const start = async () => {
    if (!cur) return;
    setBusy(true);
    setErr(null);
    try {
      const cfg: RunConfig & { variant?: string } = { world_id: cur, use_briefing: briefing && search, use_transfer: transfer };
      if (cur === "forge" && forge) cfg.variant = forge.variant;
      const { run_id } = await api.startRun(cfg);
      go(`/run/${run_id}`);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      setErr(status >= 500 && status !== 503 ? "Couldn’t start. Try again." : (e as Error).message);
      setBusy(false);
    }
  };

  const replay = replays.find((r) => r.world_id === cur) ?? replays[0];
  const loading = !worlds;

  return (
    <main className="home">
      <h1 className="headline">It has never seen this system.<br /><span>Watch it learn the rules.</span></h1>

      {items.length > 0 && !loading
        ? <Picker items={items} value={cur} onChange={setSel} onRegen={() => forgeNew().then((f) => f && setForge(f))} />
        : <div className="picker-skeleton skel" aria-busy="true" aria-label="Loading systems" />}
      <p className="goal" aria-live="polite">{loading ? " " : items.find((x) => x.id === cur)?.goal}</p>

      <div className="cta">
        <button className="btn btn-primary btn-xl" onClick={start} disabled={busy || !cur || loading}>{busy ? "Starting…" : "Start"}</button>
        <button className="link-quiet" aria-expanded={options} aria-controls="options" onClick={() => setOptions(!options)}>
          Options <span className="chev" aria-hidden="true" />
        </button>
      </div>
      {options && (
        <div id="options" className="options">
          <label className={`switch${search ? "" : " is-off"}`}>
            <input type="checkbox" checked={briefing && search} disabled={!search} onChange={(e) => setBriefing(e.target.checked)} />
            <span>Look it up first<small>{search ? "Reads public sources before experimenting." : "Unavailable on this server."}</small></span>
          </label>
          <label className="switch">
            <input type="checkbox" checked={transfer} onChange={(e) => setTransfer(e.target.checked)} />
            <span>Reuse past lessons<small>Starts from rules learned on earlier systems.</small></span>
          </label>
        </div>
      )}
      {down && (
        <div className="notice" role="alert">
          <p>Can’t reach LogicScout. Retrying…</p>
          <button className="btn" onClick={() => setAttempt((a) => a + 1)}>Try again</button>
        </div>
      )}
      {err && <p className="error" role="alert">{err}</p>}

      {replay && (
        <a className="btn recording" href={`#/replay/${encodeURIComponent(replay.name)}`}>Watch a recording</a>
      )}
    </main>
  );
}
