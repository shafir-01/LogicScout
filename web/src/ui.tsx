import { useEffect, useState, type ReactNode } from "react";

export function useHashRoute(): string {
  const get = () => (window.location.hash.replace(/^#/, "") || "/").split("?")[0];
  const [route, setRoute] = useState(get);
  useEffect(() => {
    const on = () => { setRoute(get()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const go = (path: string) => { window.location.hash = path; };

export const pct = (x: number | null | undefined, digits = 0) =>
  x == null || Number.isNaN(x) ? "–" : `${(x * 100).toFixed(digits)}%`;

export function fmt(v: unknown): string {
  if (v == null) return "–";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(+v.toFixed(3));
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v); } catch { return String(v); }
}

export function fmtAction(a: { name: string; args?: Record<string, unknown> } | null | undefined): string {
  if (!a) return "–";
  const args = Object.entries(a.args ?? {}).map(([k, v]) => `${k}=${fmt(v)}`).join(", ");
  return `${a.name}(${args})`;
}

export type Tone = "ok" | "bad" | "warn" | "muted" | "accent";

export function Chip({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span className={`chip chip-${tone}`} title={title}>{children}</span>;
}

export const statusTone = (s: string): Tone =>
  s === "supported" || s === "confirmed" || s === "pass" ? "ok"
  : s === "refuted" || s === "contradicted" || s === "fail" ? "bad"
  : s === "tentative" || s === "open" || s === "inconclusive" ? "warn"
  : "muted";

export function Meter({ value, tone = "accent", label }: { value: number; tone?: Tone; label?: string }) {
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return (
    <span className="meter" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={v} aria-label={label}>
      <span className={`meter-fill tone-${tone}`} style={{ width: `${v * 100}%` }} />
    </span>
  );
}

export function Sparkline({ series, height = 44 }: { series: { values: number[]; tone: Tone; label: string }[]; height?: number }) {
  const n = Math.max(0, ...series.map((s) => s.values.length));
  if (n < 1) return <div className="empty">No versions yet</div>;
  const w = 240;
  const x = (i: number) => (n === 1 ? w / 2 : (i / (n - 1)) * (w - 8) + 4);
  const y = (v: number) => height - 4 - Math.max(0, Math.min(1, v)) * (height - 8);
  return (
    <figure className="spark">
      <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" role="img"
        aria-label={series.map((s) => `${s.label}: ${s.values.map((v) => pct(v)).join(", ")}`).join("; ")}>
        <line x1="0" x2={w} y1={y(1)} y2={y(1)} className="spark-grid" />
        <line x1="0" x2={w} y1={y(0.5)} y2={y(0.5)} className="spark-grid" />
        {series.map((s) => {
          const pts = s.values.map((v, i) => (Number.isFinite(v) ? `${x(i)},${y(v)}` : null)).filter(Boolean).join(" ");
          return (
            <g key={s.label} className={`tone-${s.tone}`}>
              <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
              {s.values.map((v, i) => Number.isFinite(v) && <circle key={i} cx={x(i)} cy={y(v)} r="2" fill="currentColor" />)}
            </g>
          );
        })}
      </svg>
      <figcaption>
        {series.map((s) => (
          <span key={s.label} className={`legend tone-${s.tone}`}><i />{s.label} {pct(s.values[s.values.length - 1])}</span>
        ))}
      </figcaption>
    </figure>
  );
}

export function host(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}
