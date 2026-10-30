import { useEffect, useRef, useState } from "react";
import { ApiError, api, type Replay } from "../api";
import type { RunConfig, WorldManual } from "../types";
import { go, humanGoal, shortTitle } from "../ui";
import HeroArt from "../components/HeroArt"; import UseCases from "../components/UseCases";

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

  const featured = replays.find((r) => r.name === "relay-recovery") ?? replays[0];
  const watchHref = `#/replay/${encodeURIComponent(featured?.name ?? "relay-recovery")}`;
  const toTry = () => document.getElementById("try")?.scrollIntoView({ behavior: "smooth", block: "start" });
  const loading = !worlds;

  return (
    <main className="home">
      <section className="hero" aria-label="What it is">
        <h1 className="headline">An AI that figures out how a machine works, by experimenting on it.</h1>
        <p className="hero-sub">
          LogicScout gets a system it has never seen, no manual, only its buttons and readings. It runs experiments,
          learns the hidden rules, takes control, and notices when the rules secretly change.
        </p>
        <div className="cta">
          <a className="btn btn-primary btn-xl" href={watchHref}>Watch it learn</a>
          <button className="link-more" onClick={toTry}>Try it live ↓</button>
        </div>
        <HeroArt />
        <p className="credits">Reasoning by NVIDIA Nemotron on Nebius · public knowledge via Tavily</p>
      </section>

      <section className="how" aria-labelledby="how-title">
        <h2 id="how-title" className="section-title">How it works</h2>
        <ol className="steps">
          {STEPS.map(([title, text], i) => (
            <li key={title}>
              <span className="step-n" aria-hidden="true">{i + 1}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </li>
          ))}
        </ol>
        <p className="quiet">Every result is checked by an independent referee on cases the AI never saw.</p>
      </section>

      <UseCases />
      <section className="try" id="try" aria-labelledby="try-title">
        <h2 id="try-title" className="section-title">Try it live</h2>
        <p className="try-sub">Pick a system. ‘Unknown system’ is generated just for you, so nobody has seen it before. A live run takes about three minutes.</p>

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
      </section>
      <p className="small dim" style={{ textAlign: "center", margin: "24px 0" }}><a href="#/evidence" className="dim">Evidence</a></p>
    </main>
  );
}

const STEPS: [string, string][] = [
  ["Experiments", "It guesses how the system might work and tests the guesses against it."],
  ["Learns the rules", "What survives becomes a set of rules it can use to predict what happens next."],
  ["Takes control", "It turns those rules into a controller that runs on its own, with no AI needed."],
  ["Adapts", "When the hidden rules change, its predictions fail. It notices, re-tests and recovers."],
];
