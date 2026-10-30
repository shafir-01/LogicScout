import type { RunConfig, RunState, WorldManual } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ? String(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : msg; } catch { /* plain */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export interface Replay { name: string; world_id?: string; title?: string; run_id?: string; [k: string]: unknown }

export const api = {
  worlds: () => req<WorldManual[] | { worlds: WorldManual[] }>("/api/worlds").then((x) => (Array.isArray(x) ? x : x.worlds ?? [])),
  replays: () => req<Replay[] | { replays: Replay[] }>("/api/replays").then((x) => (Array.isArray(x) ? x : x.replays ?? [])),
  health: () => req<{ ok: boolean; tavily_configured?: boolean; model_configured?: boolean }>("/api/health"),
  infra: () => req<unknown>("/api/infra"),
  startRun: (cfg: RunConfig) => req<{ run_id: string }>("/api/runs", { method: "POST", body: JSON.stringify(cfg) }),
  run: (base: string) => req<RunState | { state: RunState }>(base).then((x) => ("state" in x && x.state ? x.state : (x as RunState))),
  shift: (id: string) => req<unknown>(`/api/runs/${encodeURIComponent(id)}/shift`, { method: "POST" }),
  stop: (id: string) => req<unknown>(`/api/runs/${encodeURIComponent(id)}/stop`, { method: "POST" }),
  debrief: (base: string) =>
    base.startsWith("/api/replays/")
      ? req<{ debrief?: unknown }>(base).then((x) => { if (!x.debrief) throw new Error("No debrief recorded"); return x.debrief; })
      : req<unknown>(`${base}/debrief`),
};

export function runBase(kind: "run" | "replay", id: string): string {
  return kind === "run" ? `/api/runs/${encodeURIComponent(id)}` : `/api/replays/${encodeURIComponent(id)}`;
}
