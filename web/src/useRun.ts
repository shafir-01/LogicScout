import { useEffect, useReducer, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { initialView, reducer } from "./state";
import type { LSEvent } from "./types";

const KINDS = [
  "run.started", "run.finished", "run.failed", "phase",
  "briefing.query", "briefing.source", "briefing.claim", "briefing.checked",
  "hypothesis.proposed", "hypothesis.supported", "hypothesis.refuted",
  "probe.designed", "probe.step", "probe.outcome",
  "theory.revised", "playbook.compiled", "playbook.rejected",
  "control.step", "control.goal", "shift.applied",
  "drift.suspected", "drift.confirmed", "recovery.done",
  "transfer.loaded", "transfer.saved", "playbook.trial", "safety.violation", "referee.report", "model.call", "note", "error",
];

export type Conn = "connecting" | "open" | "retrying" | "closed";

/** Folds a run's event stream into view state. `base` is the REST prefix (/api/runs/{id} or /api/replays/{name}). */
export function useRun(base: string | null) {
  const [view, dispatch] = useReducer(reducer, initialView);
  const [conn, setConn] = useState<Conn>("connecting");
  const [loadError, setLoadError] = useState<{ message: string; status: number } | null>(null);
  const finishedRef = useRef(false);
  finishedRef.current = view.finished;

  useEffect(() => {
    if (!base) return;
    dispatch({ type: "reset" });
    setLoadError(null);
    let cancelled = false;
    let es: EventSource | null = null;
    let timer: number | undefined;
    let lastId = -1;
    let retries = 0;
    let buf: LSEvent[] = [];
    let raf = 0;
    let tmo = 0;

    // Batch bursts (history replay) into one render; rAF pauses in hidden tabs, so a timer backs it up.
    const flush = () => {
      cancelAnimationFrame(raf);
      clearTimeout(tmo);
      raf = 0;
      if (buf.length) { dispatch({ type: "events", evs: buf }); buf = []; }
    };
    const onData = (raw: string) => {
      let ev: LSEvent;
      try { ev = JSON.parse(raw); } catch { return; }
      if (typeof ev?.seq !== "number" || ev.seq <= lastId) return;
      lastId = ev.seq;
      buf.push(ev);
      if (ev.kind === "run.finished" || ev.kind === "run.failed" || (ev.kind === "phase" && (ev.data?.phase === "done" || ev.data?.phase === "failed"))) {
        finishedRef.current = true;
      }
      if (!raf) { raf = requestAnimationFrame(flush); tmo = window.setTimeout(flush, 120); }
    };

    const connect = () => {
      if (cancelled) return;
      setConn(retries ? "retrying" : "connecting");
      const url = `${base}/events${lastId >= 0 ? `?last_event_id=${lastId}` : ""}`;
      es = new EventSource(url);
      es.onopen = () => { retries = 0; setConn("open"); };
      es.onmessage = (m) => onData(m.data);
      for (const k of KINDS) es.addEventListener(k, (m) => onData((m as MessageEvent).data));
      es.addEventListener("end", () => { es?.close(); setConn("closed"); });
      es.onerror = (e) => {
        // The logbook has an event kind named "error"; those arrive here as data, not as a transport failure.
        if (typeof (e as MessageEvent).data === "string") return;
        if (!es) return;
        if (finishedRef.current) { es.close(); setConn("closed"); return; }
        if (es.readyState === EventSource.CLOSED) {
          retries += 1;
          setConn("retrying");
          timer = window.setTimeout(connect, Math.min(8000, 500 * 2 ** Math.min(retries, 4)));
        } else {
          setConn("retrying");
        }
      };
    };

    api.run(base)
      .then((st) => { if (!cancelled) dispatch({ type: "state", state: st }); })
      .catch((e: Error) => {
        if (cancelled) return;
        const status = e instanceof ApiError ? e.status : 0;
        setLoadError({ message: e.message, status });
        if (status === 404 && lastId < 0) {
          // Unknown run: stop retrying the stream.
          cancelled = true;
          es?.close();
          if (timer) clearTimeout(timer);
          setConn("closed");
        }
      });
    connect();

    return () => {
      cancelled = true;
      es?.close();
      if (timer) clearTimeout(timer);
      cancelAnimationFrame(raf);
      clearTimeout(tmo);
    };
  }, [base]);

  return { view, conn, loadError, dispatch };
}
