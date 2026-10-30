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
  shift: (id: string, kind?: string | null) =>
    req<unknown>(`/api/runs/${encodeURIComponent(id)}/shift`, { method: "POST", body: JSON.stringify(kind ? { kind } : {}) }),
  shifts: (worldId: string) => req<{ id: string; label: string }[]>(`/api/worlds/${encodeURIComponent(worldId)}/shifts`),
  stop: (id: string) => req<unknown>(`/api/runs/${encodeURIComponent(id)}/stop`, { method: "POST" }),
  debrief: (base: string) =>
    base.startsWith("/api/replays/")
      ? req<{ debrief?: unknown }>(base).then((x) => { if (!x.debrief) throw new Error("No debrief recorded"); return x.debrief; })
      : req<unknown>(`${base}/debrief`),
};

export function runBase(kind: "run" | "replay", id: string): string {
  return kind === "run" ? `/api/runs/${encodeURIComponent(id)}` : `/api/replays/${encodeURIComponent(id)}`;
}

export interface WhatIfResult {
  seed: number; start: Record<string, unknown>; predicted: Record<string, unknown>[]; theory_version: number;
  observed?: Record<string, unknown>[]; match?: Record<string, boolean>[]; match_rate?: number;
}

export function whatif(id: string, actions: { name: string; args?: Record<string, unknown> }[], test: boolean): Promise<WhatIfResult> {
  return req<WhatIfResult>(`/api/runs/${encodeURIComponent(id)}/whatif`, { method: "POST", body: JSON.stringify({ actions, test }) });
}

export function exportUrl(id: string, file: "manual.md" | "controller.py"): string {
  return `/api/runs/${encodeURIComponent(id)}/export/${file}`;
}
