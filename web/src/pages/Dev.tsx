import { useEffect, useReducer, useState } from "react";
import { SAMPLE_EVENTS } from "../dev/sample-events";
import { initialView, reducer } from "../state";
import { RunLayout } from "./Run";

/** DEV ONLY: renders synthetic events. Not linked from navigation. `#/dev?at=N` freezes after N events. */
export default function Dev() {
  const at = Number(new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("at"));
  const frozen = Number.isFinite(at) && window.location.hash.includes("at=");
  const [v, dispatch] = useReducer(reducer, initialView, (s) => (frozen ? reducer(s, { type: "events", evs: SAMPLE_EVENTS.slice(0, at) }) : s));
  const [i, setI] = useState(0);
  useEffect(() => {
    if (frozen || i >= SAMPLE_EVENTS.length) return;
    const t = setTimeout(() => { dispatch({ type: "event", ev: SAMPLE_EVENTS[i] }); setI(i + 1); }, 120);
    return () => clearTimeout(t);
  }, [i, frozen]);
  return <RunLayout v={v} banner="DEV SAMPLE DATA — not a run" controls={false} />;
}
