import { useEffect, useRef, useState } from "react";
import { api, type Replay } from "../api";
import type { RunConfig, WorldManual } from "../types";
import { go } from "../ui";

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
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState("");
  const [options, setOptions] = useState(false);
  const [briefing, setBriefing] = useState(true);
  const [transfer, setTransfer] = useState(false);
  const [busy, setBusy] = useState(false);
  const [forge, setForge] = useState<Forge | null>(null);

  useEffect(() => {
    forgeNew().then(setForge);
    api.worlds().then(setWorlds).catch((e: Error) => setErr(`Backend unavailable: ${e.message}`));
    api.replays().then(setReplays).catch(() => setReplays([]));
    api.health().then((h) => setBriefing(h.tavily_configured !== false)).catch(() => undefined);
  }, []);

  const items: Item[] = [
    ...(forge ? [{ id: "forge", title: forge.manual.title || "Unknown system", goal: forge.manual.objectives?.[0]?.text }] : []),
    ...(worlds ?? []).filter((w) => w.world_id !== "forge").map((w) => ({ id: w.world_id, title: w.title, goal: w.objectives?.[0]?.text })),
  ];
  const cur = items.some((x) => x.id === sel) ? sel : items[0]?.id ?? "";

  const start = async () => {
    if (!cur) return;
    setBusy(true);
    setErr(null);
    try {
      const cfg: RunConfig & { variant?: string } = { world_id: cur, use_briefing: briefing, use_transfer: transfer };
      if (cur === "forge" && forge) cfg.variant = forge.variant;
      const { run_id } = await api.startRun(cfg);
      go(`/run/${run_id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  const replay = replays.find((r) => r.world_id === cur) ?? replays[0];

  return (
    <main className="home">
      <h1 className="headline">It has never seen this system.<br /><span>Watch it learn the rules.</span></h1>

      {items.length > 0 && <Picker items={items} value={cur} onChange={setSel} onRegen={() => forgeNew().then((f) => f && setForge(f))} />}
      {!worlds && !err && <div className="picker-skeleton" aria-hidden="true" />}
      {items.length > 0 && <p className="goal" aria-live="polite">{items.find((x) => x.id === cur)?.goal}</p>}

      <div className="cta">
        <button className="btn btn-primary btn-xl" onClick={start} disabled={busy || !cur}>{busy ? "Starting…" : "Start"}</button>
        <button className="link-quiet" aria-expanded={options} aria-controls="options" onClick={() => setOptions(!options)}>
          Options <span className="chev" aria-hidden="true" />
        </button>
      </div>
      {options && (
        <div id="options" className="options">
          <label className="switch"><input type="checkbox" checked={briefing} onChange={(e) => setBriefing(e.target.checked)} /><span>Public briefing</span></label>
          <label className="switch"><input type="checkbox" checked={transfer} onChange={(e) => setTransfer(e.target.checked)} /><span>Transfer</span></label>
        </div>
      )}
      {err && <p className="error" role="alert">{err}</p>}

      {replay && (
        <a className="link-more recording" href={`#/replay/${encodeURIComponent(replay.name)}`}>Watch a recording</a>
      )}
    </main>
  );
}
