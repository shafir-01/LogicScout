import { useRef } from "react";
import type { Dict, WorldManual } from "../types";
import type { RunView } from "../state";
import { fmt } from "../ui";
import type { Action } from "../types";

const words = (s: string) => s.replace(/_/g, " ");
function actionText(a: Action): string {
  const args = Object.entries(a.args ?? {}).map(([k, v]) => `${words(k)} ${fmt(v)}`).join(", ");
  return args ? `${words(a.name)} · ${args}` : words(a.name);
}

type Node = { id: string; label: string; x?: number; y?: number; fields: string[] };
type Edge = { from: string; to: string; label?: string };

const clean = (f: unknown) => (typeof f === "string" ? f.replace(/^obs\./, "") : undefined);
const asList = (x: unknown): string[] => (Array.isArray(x) ? x : [x]).map(clean).filter((f): f is string => !!f);

function read(obs: Dict | null, field?: string): unknown {
  if (!obs || !field) return undefined;
  if (field in obs) return obs[field];
  return field.split(".").reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Dict)[k] : undefined), obs);
}

/** Running per-field maxima so numeric signals light nodes in proportion to what has been seen. */
function useScale(obs: Dict | null) {
  const max = useRef<Record<string, number>>({});
  for (const [k, v] of Object.entries(obs ?? {})) if (typeof v === "number") max.current[k] = Math.max(max.current[k] ?? 0, Math.abs(v));
  return (field: string, v: unknown): number => {
    if (typeof v === "boolean") return v ? 1 : 0;
    if (typeof v === "number") return Math.min(1, Math.abs(v) / Math.max(1, max.current[field] ?? 1));
    return v != null && v !== "" ? 0.5 : 0;
  };
}

function parseGraph(layout: Dict): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = (layout.nodes ?? []).map((n: Dict | string, i: number) =>
    typeof n === "string"
      ? { id: n, label: n, fields: [] }
      : { id: String(n.id ?? n.name ?? i), label: String(n.label ?? n.name ?? n.id ?? i), x: n.x, y: n.y, fields: asList(n.field ?? n.fields ?? []) });
  const edges: Edge[] = (layout.edges ?? []).map((e: Dict | string[]) =>
    Array.isArray(e) ? { from: e[0], to: e[1] } : { from: String(e.from ?? e.source), to: String(e.to ?? e.target), label: e.label });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const bind = layout.bind;
  if (bind && typeof bind === "object") {
    for (const [k, v] of Object.entries(bind as Dict)) {
      if (byId.has(k)) byId.get(k)!.fields.push(...asList(v));
      else if (typeof v === "string" && byId.has(v)) byId.get(v)!.fields.push(k);
    }
  }
  return { nodes, edges };
}

function layered(nodes: Node[], edges: Edge[]): Record<string, [number, number]> {
  const depth: Record<string, number> = Object.fromEntries(nodes.map((n) => [n.id, 0]));
  for (let i = 0; i < nodes.length; i++) {
    for (const e of edges) if (e.from in depth && e.to in depth) depth[e.to] = Math.max(depth[e.to], Math.min(nodes.length, depth[e.from] + 1));
  }
  const layers: Record<number, string[]> = {};
  for (const n of nodes) (layers[depth[n.id]] ??= []).push(n.id);
  const maxD = Math.max(0, ...Object.values(depth));
  const pos: Record<string, [number, number]> = {};
  for (const [d, ids] of Object.entries(layers)) {
    ids.forEach((id, j) => { pos[id] = [maxD ? Number(d) / maxD : 0.5, ids.length === 1 ? 0.5 : j / (ids.length - 1)]; });
  }
  return pos;
}

function Graph({ layout, obs }: { layout: Dict; obs: Dict | null }) {
  const scale = useScale(obs);
  const { nodes, edges } = parseGraph(layout);
  if (!nodes.length) return null;
  const maxFields = Math.min(3, Math.max(0, ...nodes.map((n) => n.fields.length)));
  const W = 400, padX = 64, padTop = 26, padBottom = 34 + maxFields * 12;
  const H = 130 + maxFields * 26;
  const hasXY = nodes.every((n) => typeof n.x === "number" && typeof n.y === "number");
  let unit: Record<string, [number, number]>;
  if (hasXY) {
    const xs = nodes.map((n) => n.x as number), ys = nodes.map((n) => n.y as number);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    unit = Object.fromEntries(nodes.map((n) => [n.id, [x1 > x0 ? (n.x! - x0) / (x1 - x0) : 0.5, y1 > y0 ? (n.y! - y0) / (y1 - y0) : 0.5]]));
  } else {
    unit = layered(nodes, edges);
  }
  const pos: Record<string, [number, number]> = {};
  for (const [id, [ux, uy]] of Object.entries(unit)) pos[id] = [padX + ux * (W - 2 * padX), padTop + uy * (H - padTop - padBottom)];
  const R = 14;

  return (
    <svg className="schematic" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="System schematic">
      <defs>
        <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L8,4 L0,8 z" className="edge-head" />
        </marker>
      </defs>
      {edges.map((e, i) => {
        const a = pos[e.from], b = pos[e.to];
        if (!a || !b) return null;
        const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
        return (
          <g key={i}>
            <line x1={a[0] + (dx / L) * R} y1={a[1] + (dy / L) * R} x2={b[0] - (dx / L) * (R + 3)} y2={b[1] - (dy / L) * (R + 3)} className="edge" markerEnd="url(#arrow)" />
            {e.label && <text x={(a[0] + b[0]) / 2} y={(a[1] + b[1]) / 2 - 5} className="edge-val">{e.label}</text>}
          </g>
        );
      })}
      {nodes.map((n) => {
        const [x, y] = pos[n.id];
        const vals = n.fields.map((f) => [f, read(obs, f)] as const);
        const lit = vals.length ? Math.max(...vals.map(([f, v]) => scale(f, v))) : 0;
        const alarm = vals.some(([f, v]) => v === true && /fault|trip|lock|alarm|error/i.test(f));
        return (
          <g key={n.id} className={`node${alarm ? " node-alarm" : ""}`}>
            <title>{[n.label, ...vals.map(([f, v]) => `${f}: ${fmt(v)}`)].join("\n")}</title>
            <circle cx={x} cy={y} r={R} className="node-ring" />
            <circle cx={x} cy={y} r={R} className="node-fill" style={{ opacity: obs && vals.length ? 0.1 + 0.4 * lit : 0 }} />
            <text x={x} y={y + R + 13} className="node-label">{n.label}</text>
            {vals.slice(0, 3).map(([f, v], i) => (
              <text key={f} x={x} y={y + R + 26 + i * 12} className="node-field">
                {f.replace(/_/g, " ")} <tspan className="node-v">{fmt(v)}</tspan>
              </text>
            ))}
          </g>
        );
      })}
    </svg>
  );
}

function Track({ layout, obs }: { layout: Dict; obs: Dict | null }) {
  const bind = (layout.bind ?? {}) as Dict;
  const len = Number(layout.length ?? layout.size ?? layout.max ?? 10);
  const min = Number(layout.min ?? 0);
  const pos = Number(read(obs, clean(bind.position ?? layout.field ?? "position")));
  const nextRaw = read(obs, clean(bind.next_site));
  const next = typeof nextRaw === "number" ? nextRaw : NaN;
  const locked = read(obs, clean(bind.locked)) === true;
  const terrain = read(obs, clean(bind.terrain));
  const sites = read(obs, clean(bind.sites));
  const W = 380, H = 78, pad = 16;
  const sx = (v: number) => pad + ((Math.max(min, Math.min(len, v)) - min) / (len - min || 1)) * (W - 2 * pad);
  const cells = typeof terrain === "string" && terrain.length >= len ? terrain : null;
  return (
    <svg className="schematic" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Position ${fmt(pos)} of ${len}`}>
      {cells && [...cells].slice(0, len).map((c, i) => (
        <rect key={i} x={sx(min + i)} y={30} width={(W - 2 * pad) / len} height={12} className={`cell cell-${c}`} />
      ))}
      <line x1={pad} x2={W - pad} y1={36} y2={36} className="track" />
      {Array.from({ length: Math.max(0, len - min) + 1 }, (_, i) => (
        <line key={i} x1={sx(min + i)} x2={sx(min + i)} y1={i % 4 ? 33 : 30} y2={i % 4 ? 39 : 42} className="track-tick" />
      ))}
      {Array.isArray(sites) && sites.map((s, i) => Number.isFinite(Number(s)) && (
        <line key={i} x1={sx(Number(s))} x2={sx(Number(s))} y1={22} y2={50} className="track-mark" />
      ))}
      {Number.isFinite(next) && next >= min && (
        <g>
          <line x1={sx(next)} x2={sx(next)} y1={22} y2={50} className="track-mark" />
          <text x={sx(next)} y={64} className="node-label">next site {next}</text>
        </g>
      )}
      {Number.isFinite(pos) && (
        <g className={`track-pos${locked ? " node-alarm" : ""}`}>
          <circle cx={sx(pos)} cy={36} r="7" />
          <text x={sx(pos)} y={18} className="node-v">{fmt(pos)}</text>
        </g>
      )}
      {typeof terrain === "string" && !cells && <text x={W - pad} y={76} className="node-field" textAnchor="end">terrain {terrain}</text>}
    </svg>
  );
}

function Schematic({ manual, obs }: { manual: WorldManual | null; obs: Dict | null }) {
  const layout = manual?.layout;
  if (!layout || !Object.keys(layout).length) return null;
  const kind = layout.kind ?? (layout.nodes ? "graph" : "track");
  if (kind === "graph") return <Graph layout={layout} obs={obs} />;
  if (kind === "track") return <Track layout={layout} obs={obs} />;
  return null;
}

export default function SystemPanel({ v }: { v: RunView }) {
  const fields = v.manual?.observations?.map((f) => f.name) ?? Object.keys(v.obs ?? {});
  const extra = Object.keys(v.obs ?? {}).filter((k) => !fields.includes(k));
  const all = [...fields, ...extra].filter((k) => k !== "t");
  return (
    <section className="system" aria-label="System">
      <Schematic manual={v.manual} obs={v.obs} />
      <p className="system-caption">
        {v.lastAction ? <><span>Last action</span> <strong className="system-act">{actionText(v.lastAction)}</strong></> : <span>{v.manual ? "Waiting for its first move" : " "}</span>}
        {v.obsT != null && <span className="system-t">step {v.obsT}</span>}
      </p>
      {all.length > 0 && (
        <dl className="signals">
          {all.map((k) => {
            const cur = v.obs?.[k];
            const prev = v.prevObs?.[k];
            const changed = v.prevObs != null && JSON.stringify(cur) !== JSON.stringify(prev);
            const delta = typeof cur === "number" && typeof prev === "number" ? cur - prev : null;
            return (
              <div key={k} className="signal">
                <dt>{k.replace(/_/g, " ")}</dt>
                <dd key={changed ? `c${v.obsTick}` : "s"} className={changed ? "flash" : ""}>
                  {fmt(cur)}
                  {changed && delta ? <span className={`delta ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? `+${fmt(delta)}` : fmt(delta)}</span> : null}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}
