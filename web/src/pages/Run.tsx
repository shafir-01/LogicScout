import { useEffect, useRef, useState } from "react";
import { ApiError, api, runBase } from "../api";
import PhaseRail from "../components/PhaseRail";
import SystemPanel from "../components/SystemPanel";
import Tabs, { type TabRequest } from "../components/Tabs";
import { BigNumbers, LiveSentence } from "../components/Stage";
import type { RunView } from "../state";
import { useRun, type Conn } from "../useRun";
import { go, humanGoal, shortTitle } from "../ui";

function ShiftControl({ v, runId, ready, onApply, onError }: {
  v: RunView; runId: string; ready: boolean; onApply: (kind: string) => void; onError: (m: string) => void;
}) {
  const [menu, setMenu] = useState<{ id: string; label: string }[] | null>(null);
  const [pick, setPick] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!menu) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setMenu(null); btn.current?.focus(); } };
    const click = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setMenu(null); };
    window.addEventListener("keydown", key);
    window.addEventListener("mousedown", click);
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("mousedown", click); };
  }, [menu]);

  const toggle = () => {
    if (menu) { setMenu(null); return; }
    setPick("");
    api.shifts(v.config?.world_id ?? "").then((m) => {
      setMenu(m);
      requestAnimationFrame(() => wrap.current?.querySelector(".shift-menu")?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    }).catch((e: Error) => onError(e.message));
  };

  return (
    <div className="shift" ref={wrap} data-run={runId}>
      <button ref={btn} className="btn btn-change" disabled={!ready} onClick={toggle} aria-expanded={!!menu} aria-haspopup="true"
        aria-describedby={ready ? undefined : "shift-hint"}>
        Change the rules
      </button>
      {!ready && <p id="shift-hint" className="shift-hint">Available once it’s in control</p>}
      {menu && (
        <fieldset className="shift-menu" aria-label="Choose a hidden change">
          <legend>Change one hidden rule. It won’t be told.</legend>
          <div className="shift-options">
            {[{ id: "", label: "Surprise me" }, ...menu].map((m) => (
              <label key={m.id || "random"}>
                <input type="radio" name="shift-kind" checked={pick === m.id} onChange={() => setPick(m.id)} /> {m.label}
              </label>
            ))}
          </div>
          <button className="btn btn-danger" onClick={() => { onApply(pick); setMenu(null); }}>Change it</button>
        </fieldset>
      )}
    </div>
  );
}

export function RunLayout({
  v, banner, conn, base, runId, controls = true,
}: { v: RunView; banner?: string; conn?: Conn; base?: string; runId?: string; controls?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const [request, setRequest] = useState<TabRequest>(null);
  const [pending, setPending] = useState(false);
  const [queued, setQueued] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const detailsRef = useRef<HTMLDivElement>(null);
  const landed = (v.shifted && !v.recovered) || v.finished;
  useEffect(() => { if (landed) { setPending(false); setQueued(null); } }, [landed]);

  // A requested change is held until the run is in its control phase, then sent once.
  useEffect(() => {
    if (queued == null || !runId || v.phase !== "control") return;
    let alive = true;
    api.shift(runId, queued || null)
      .then(() => { if (alive) { setPending(true); setQueued(null); } })
      .catch((e: Error) => {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 409) { window.setTimeout(() => alive && setRetry((n) => n + 1), 1000); return; }
        setErr(e.message);
        setQueued(null);
      });
    return () => { alive = false; };
  }, [queued, v.phase, runId, retry]);

  const showShift = controls && !!runId && !v.finished && !!v.manual && !pending && queued == null && !(v.shifted && !v.recovered);
  const canStop = controls && !!runId && !v.finished;
  const objective = v.manual?.objectives?.find((o) => o.id === v.config?.objective_id) ?? v.manual?.objectives?.[0];

  const stop = async () => {
    if (!runId) return;
    setBusy(true);
    setErr(null);
    try { await api.stop(runId); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const open = (id?: string) => {
    setDetails(true);
    if (id) setRequest({ id, n: Date.now() });
    requestAnimationFrame(() => detailsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  return (
    <main className="run">
      <header className="run-head">
        <div className="run-title">
          <h1>{v.manual || v.config ? shortTitle(v.config?.world_id ?? v.manual?.world_id ?? "", v.manual?.title) : <span className="skel skel-title" aria-label="Loading" />}</h1>
          {objective ? <p>{humanGoal(objective.text)}</p> : !v.manual && <p><span className="skel skel-sub" /></p>}
        </div>
        <div className="run-meta">
          {banner && <span className="pill" role="status">{banner}</span>}
          {conn && conn !== "open" && !v.finished && <span className="pill pill-warn" role="status">{conn === "retrying" ? "Reconnecting" : "Connecting"}</span>}
          {canStop && <button className="link-quiet" disabled={busy} onClick={stop}>{busy ? "Stopping…" : "Stop"}</button>}
        </div>
      </header>

      <section className={`stage${v.shifted && !v.recovered && !v.finished ? " is-shifted" : ""}`} aria-label="Live run">
        <PhaseRail v={v} />
        <LiveSentence v={v} pendingShift={pending || queued != null} />
        <BigNumbers v={v} />
        <div className="stage-actions">
          {showShift && runId && (
            <ShiftControl v={v} runId={runId} ready={!!v.playbook} onApply={(k) => { setErr(null); setQueued(k); }} onError={setErr} />
          )}
          {v.finished && base && <button className="link-more" onClick={() => open("hidden")}>See what was hidden</button>}
          {v.finished && controls && <button className="btn" onClick={() => go("/")}>Try another system</button>}
        </div>
        {err && <p className="error" role="alert">{err}</p>}
      </section>

      <section className="visual" aria-label="System">
        <SystemPanel v={v} />
      </section>

      <div className="details" ref={detailsRef}>
        <button className="details-toggle" aria-expanded={details} aria-controls="details-body" onClick={() => (details ? setDetails(false) : open())}>
          Details <span className="chev" aria-hidden="true" />
        </button>
        {details && (
          <div id="details-body" className="details-body">
            <Tabs v={v} runId={runId} base={base} request={request} />
          </div>
        )}
      </div>
    </main>
  );
}

function Missing({ message, offline, what }: { message: string; offline: boolean; what: string }) {
  return (
    <main className="home missing">
      <h1 className="headline-s">{offline ? "Can’t reach LogicScout." : `This ${what} doesn’t exist.`}</h1>
      <p className="goal">{offline ? "Check your connection and try again." : /not found/i.test(message) ? "It may have expired, or the link is wrong." : message}</p>
      <div className="cta">
        {offline && <button className="btn btn-primary btn-xl" onClick={() => window.location.reload()}>Try again</button>}
        <button className={offline ? "link-quiet" : "btn btn-primary btn-xl"} onClick={() => go("/")}>Start a new run</button>
      </div>
    </main>
  );
}

export default function Run({ kind, id }: { kind: "run" | "replay"; id: string }) {
  const base = runBase(kind, id);
  const { view, conn, loadError } = useRun(base);
  const replay = kind === "replay";
  if (loadError && view.lastSeq < 0 && (loadError.status === 404 || (loadError.status === 0 && conn !== "open"))) {
    return <Missing message={loadError.message} offline={loadError.status === 0} what={replay ? "recording" : "run"} />;
  }
  return (
    <>
      {loadError && view.lastSeq < 0 && <p className="error page" role="alert">{loadError.message}</p>}
      <RunLayout v={view} conn={conn} base={base} runId={kind === "run" ? id : undefined}
        banner={replay ? "Recording of a real run" : undefined} controls={!replay} />
    </>
  );
}
