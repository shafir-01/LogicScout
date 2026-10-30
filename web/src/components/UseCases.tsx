import type { ReactNode } from "react";
const CSS = `
.uc{margin:56px auto 0;max-width:980px;padding:0 16px}
.uc-list{list-style:none;margin:20px 0 0;padding:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px}
.uc-item{display:flex;flex-direction:column;gap:6px}
.uc-icon{width:28px;height:28px;color:var(--accent,#0071e3);fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.uc-item h3{margin:4px 0 0;font-size:15px;font-weight:600;color:var(--text,#1d1d1f)}
.uc-item p{margin:0;font-size:14px;line-height:1.45;color:var(--text-2,#6e6e73)}
.uc-note{margin:20px 0 0;font-size:12px;color:var(--text-3,#86868b);text-align:center}
@media (max-width:760px){.uc-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:420px){.uc-list{grid-template-columns:1fr}}
`;

const ICONS: Record<string, ReactNode> = {
  legacy: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <circle cx="9" cy="12.5" r="2.5" />
      <path d="M15 10.5h3M15 14.5h3M7 3v3M17 3v3" />
    </>
  ),
  api: (
    <>
      <path d="M8 7l-5 5 5 5M16 7l5 5-5 5" />
      <path d="M13.5 5l-3 14" />
    </>
  ),
  plant: (
    <>
      <path d="M3 20V10l5 3V10l5 3V5h4l1 15z" />
      <path d="M3 20h18" />
    </>
  ),
  remote: (
    <>
      <path d="M9 9l6 6M7.5 10.5l-3 3 6 6 3-3M16.5 13.5l3-3-6-6-3 3" />
      <path d="M17 3a4 4 0 0 1 4 4M17 6a1 1 0 0 1 1 1" />
    </>
  ),
};

const ITEMS: [keyof typeof ICONS, string, string][] = [
  ["legacy", "Legacy equipment", "Machines whose manuals are lost."],
  ["api", "Undocumented APIs", "Services that changed without notice."],
  ["plant", "Plants after maintenance", "Processes that behave differently than before."],
  ["remote", "Satellites and field devices", "Remote systems you can only probe."],
];

export default function UseCases() {
  return (
    <section className="uc" aria-labelledby="uc-title">
      <style>{CSS}</style>
      <h2 id="uc-title" className="section-title">Where this helps</h2>
      <ul className="uc-list">
        {ITEMS.map(([icon, title, text]) => (
          <li key={title} className="uc-item">
            <svg className="uc-icon" viewBox="0 0 24 24" aria-hidden="true">{ICONS[icon]}</svg>
            <h3>{title}</h3>
            <p>{text}</p>
          </li>
        ))}
      </ul>
      <p className="uc-note">These are application areas. The demo runs on simulated systems and one real HTTP service.</p>
    </section>
  );
}
