import { useEffect, useReducer, useState } from "react";
import { SAMPLE_EVENTS } from "../dev/sample-events";
import { initialView, reducer } from "../state";
import { RunLayout } from "./Run";

/** DEV ONLY: renders synthetic events. Not linked from navigation. */
export default function Dev() {
  const [v, dispatch] = useReducer(reducer, initialView);
  const [i, setI] = useState(0);
  useEffect(() => {
    if (i >= SAMPLE_EVENTS.length) return;
    const t = setTimeout(() => { dispatch({ type: "event", ev: SAMPLE_EVENTS[i] }); setI(i + 1); }, 120);
    return () => clearTimeout(t);
  }, [i]);
  return <RunLayout v={v} banner="DEV SAMPLE DATA — not a run" controls={false} />;
}
