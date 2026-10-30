import type { Rule } from "../types";

/* RuleViz: pattern-matches the learned rule DSL into tiny pictures a non-expert reads at a glance.
   Pure front-end; returns null when nothing recognisable is found (the raw rule stays below). */

export type Viz =
  | { kind: "window"; period: number; on: number[]; caption: string }
  | { kind: "cap"; cap: number; caption: string }
  | { kind: "cost"; amount: number; unit: string; field: string }
  | { kind: "delay"; steps: number }
  | { kind: "gate"; field: string; op: string; value: number };

const nice = (f: string) => f.replace(/_/g, " ");
const RESOURCE = /energy|cost|budget|fuel|battery|credit|money|power|cash|coins?|charge/i;

function windowFrom(off: number, p: number, op: string, k: number): number[] {
  const on: number[] = [];
  for (let t = 0; t < p; t++) {
    const m = (t + off) % p;
    const hit = op === "<" ? m < k : op === "<=" ? m <= k : op === ">" ? m > k : op === ">=" ? m >= k : op === "==" ? m === k : op === "!=" ? m !== k : false;
    if (hit) on.push(t);
  }
  return on;
}

export function parseRule(rule: Pick<Rule, "when" | "effects" | "delay">): Viz[] {
  const out: Viz[] = [];
  const seen = new Set<string>();
  const add = (key: string, v: Viz) => { if (!seen.has(key)) { seen.add(key); out.push(v); } };
  const effects = Object.entries(rule.effects ?? {});
  const all = [rule.when ?? "", ...effects.map(([, e]) => e)].join(" ; ");

  // (a) periodic windows: t % P < W, (t + 1) % P == k, ...
  // "(obs.x) if COND else (...)" means the change happens when COND is false: flip the window.
  const sources: [string, boolean][] = [[rule.when ?? "", false], ...effects.map(([f, e]): [string, boolean] => {
    const tern = e.trim().match(/^\((.*)\)\s+if\s+(.*)\s+else\s+\((.*)\)$/);
    return [e, !!tern && tern[1].trim() === `obs.${f}`];
  })];
  for (const [src, flip] of sources) for (const m of src.matchAll(/\(?\s*t\s*(?:\+\s*(\d+)\s*)?\)?\s*%\s*(\d+)\s*(<=|>=|==|!=|<|>)\s*(\d+)/g)) {
    const off = Number(m[1] ?? 0), p = Number(m[2]), op = m[3], k = Number(m[4]);
    if (!(p >= 2 && p <= 24)) continue;
    const raw = windowFrom(off, p, op, k);
    const on = flip ? Array.from({ length: p }, (_, i) => i).filter((i) => !raw.includes(i)) : raw;
    if (!on.length || on.length === p) continue;
    add(`w${p}:${on.join(",")}`, {
      kind: "window", period: p, on,
      caption: on.length === 1 ? `Once every ${p} steps` : `Works ${on.length} of every ${p} steps`,
    });
  }
  // (b) capacity: min(args.n, C)
  for (const m of all.matchAll(/min\(\s*args\.\w+\s*,\s*(\d+)\s*\)|min\(\s*(\d+)\s*,\s*args\.\w+\s*\)/g)) {
    const c = Number(m[1] ?? m[2]);
    if (c >= 1 && c <= 12) add(`c${c}`, { kind: "cap", cap: c, caption: `At most ${c} at a time` });
  }
  // (c) costs: obs.x - K * args.n | obs.x + -K | obs.x - K | obs.x + K (resource-like fields only for constants)
  for (const [field, e] of effects) {
    const per = e.match(new RegExp(`obs\\.${field}\\s*(?:-\\s*|\\+\\s*-\\s*)(\\d+(?:\\.\\d+)?)\\s*\\*\\s*args\\.(\\w+)`));
    if (per) { add(`k${field}`, { kind: "cost", amount: -Number(per[1]), unit: "per message", field }); continue; }
    if (!RESOURCE.test(field)) continue;
    const k = e.match(new RegExp(`obs\\.${field}\\s*(\\+\\s*-|-|\\+)\\s*(\\d+(?:\\.\\d+)?)`));
    if (k) add(`k${field}`, { kind: "cost", amount: (k[1].replace(/\s/g, "") === "+" ? 1 : -1) * Number(k[2]), unit: "per step", field });
  }
  // (d) delay
  if (rule.delay && rule.delay > 0) add("d", { kind: "delay", steps: rule.delay });
  // (e) thresholds in the condition: obs.x > V
  for (const m of (rule.when ?? "").matchAll(/obs\.(\w+)\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)/g)) {
    add(`g${m[1]}${m[2]}${m[3]}`, { kind: "gate", field: m[1], op: m[2], value: Number(m[3]) });
  }
  return out;
}

const OP: Record<string, string> = { ">": "above", ">=": "at least", "<": "below", "<=": "at most", "==": "exactly" };

function Item({ v }: { v: Viz }) {
  switch (v.kind) {
    case "window":
      return (
        <div className="rv-item" title={v.caption}>
          <div className="rv-cells" aria-hidden>
            {Array.from({ length: v.period }, (_, i) => <span key={i} className={v.on.includes(i) ? "rv-cell rv-on" : "rv-cell"} />)}
          </div>
          <span className="rv-cap">{v.caption}</span>
        </div>
      );
    case "cap":
      return (
        <div className="rv-item" title={v.caption}>
          <div className="rv-dots" aria-hidden>
            {Array.from({ length: v.cap + 2 }, (_, i) => <span key={i} className={i < v.cap ? "rv-dot rv-on" : "rv-dot"} />)}
          </div>
          <span className="rv-cap">{v.caption}</span>
        </div>
      );
    case "cost":
      return (
        <div className="rv-item">
          <span className={v.amount < 0 ? "rv-chip rv-neg" : "rv-chip rv-pos"}>
            {v.amount < 0 ? "−" : "+"}{Math.abs(v.amount)} {nice(v.field)} {v.unit}
          </span>
        </div>
      );
    case "delay":
      return (
        <div className="rv-item">
          <span className="rv-arrow" aria-hidden>●──▶</span>
          <span className="rv-cap">Takes effect after {v.steps} step{v.steps === 1 ? "" : "s"}</span>
        </div>
      );
    case "gate": {
      const pos = v.op.startsWith(">") ? 62 : v.op.startsWith("<") ? 38 : 50;
      return (
        <div className="rv-item">
          <span className={`rv-gauge rv-${v.op.startsWith(">") ? "hi" : v.op.startsWith("<") ? "lo" : "eq"}`} aria-hidden>
            <span className="rv-mark" style={{ left: `${pos}%` }} />
          </span>
          <span className="rv-cap">Only when {nice(v.field)} is {OP[v.op] ?? v.op} {v.value}</span>
        </div>
      );
    }
  }
}

const CSS = `
.rv{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin:2px 0 6px}
.rv-item{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--text-2,var(--text))}
.rv-cap{white-space:nowrap}
.rv-cells{display:inline-flex;gap:2px}
.rv-cell{width:10px;height:10px;border-radius:2px;background:var(--line);}
.rv-cell.rv-on{background:var(--accent)}
.rv-dots{display:inline-flex;gap:3px}
.rv-dot{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--line-2,var(--line));box-sizing:border-box}
.rv-dot.rv-on{background:var(--accent);border-color:var(--accent)}
.rv-chip{font-family:var(--mono);font-size:11px;padding:1px 7px;border-radius:999px}
.rv-neg{background:var(--bad-weak);color:var(--bad)}
.rv-pos{background:var(--ok-weak);color:var(--ok)}
.rv-arrow{font-family:var(--mono);color:var(--accent);letter-spacing:-1px}
.rv-gauge{position:relative;display:inline-block;width:44px;height:6px;border-radius:3px;background:var(--line);overflow:visible}
.rv-gauge.rv-hi{background:linear-gradient(90deg,var(--line) 62%,var(--accent-weak) 62%)}
.rv-gauge.rv-lo{background:linear-gradient(90deg,var(--accent-weak) 38%,var(--line) 38%)}
.rv-mark{position:absolute;top:-3px;width:2px;height:12px;margin-left:-1px;background:var(--accent);border-radius:1px}
`;

export default function RuleViz({ rule }: { rule: Rule }) {
  const viz = parseRule(rule);
  if (!viz.length) return null;
  return (
    <div className="rv" aria-label="Rule at a glance">
      <style>{CSS}</style>
      {viz.map((v, i) => <Item key={i} v={v} />)}
    </div>
  );
}
