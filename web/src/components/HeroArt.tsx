const CSS = `
.ha{display:block;width:100%;max-width:360px;height:auto;margin:28px auto 8px;color:var(--text-2,#6e6e73)}
.ha-panel{fill:var(--surface-2,#f5f5f7);stroke:var(--line-2,#d2d2d7);stroke-width:1.5}
.ha-btn{fill:var(--surface,#fff);stroke:currentColor;stroke-width:1.5}
.ha-dial{fill:var(--surface,#fff);stroke:currentColor;stroke-width:1.5}
.ha-q{fill:currentColor;font:600 22px var(--sans,system-ui,sans-serif);text-anchor:middle}
.ha-lbl{fill:var(--text-3,#86868b);font:500 9px var(--sans,system-ui,sans-serif);text-anchor:middle;letter-spacing:.04em}
.ha-chip rect{fill:var(--accent-weak,rgba(0,113,227,.1));stroke:var(--accent,#0071e3);stroke-width:1}
.ha-chip text{fill:var(--accent-text,#0066cc);font:500 11px var(--sans,system-ui,sans-serif);text-anchor:middle}
.ha-ok circle{fill:var(--accent,#0071e3)}
.ha-ok path{fill:none;stroke:var(--on-accent,#fff);stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
.ha-cur path{fill:var(--text,#1d1d1f);stroke:var(--surface,#fff);stroke-width:1.2;stroke-linejoin:round}
.ha-q,.ha-chip,.ha-ok,.ha-cur,.ha-b1,.ha-b2,.ha-b3{animation:6s var(--ease,ease) infinite both}
.ha-cur{animation-name:ha-cur}
.ha-b1{animation-name:ha-b1}.ha-b2{animation-name:ha-b2}.ha-b3{animation-name:ha-b3}
.ha-q{animation-name:ha-q}
.ha-c1{animation-name:ha-c1}.ha-c2{animation-name:ha-c2}.ha-ok{animation-name:ha-ok}
@keyframes ha-cur{
0%{transform:translate(330px,190px);opacity:0}
6%{opacity:1}
15%,22%{transform:translate(66px,76px)}
30%,37%{transform:translate(114px,76px)}
45%,52%{transform:translate(162px,76px)}
60%{transform:translate(250px,190px);opacity:1}
64%,100%{transform:translate(250px,190px);opacity:0}}
@keyframes ha-b1{0%,17%,24%,100%{fill:var(--surface,#fff)}19%,22%{fill:var(--accent,#0071e3)}}
@keyframes ha-b2{0%,32%,39%,100%{fill:var(--surface,#fff)}34%,37%{fill:var(--accent,#0071e3)}}
@keyframes ha-b3{0%,47%,54%,100%{fill:var(--surface,#fff)}49%,52%{fill:var(--accent,#0071e3)}}
@keyframes ha-q{0%,52%{opacity:1}58%,92%{opacity:0}100%{opacity:1}}
@keyframes ha-c1{0%,56%{opacity:0;transform:translateY(6px)}62%,92%{opacity:1;transform:none}98%,100%{opacity:0}}
@keyframes ha-c2{0%,64%{opacity:0;transform:translateY(6px)}70%,92%{opacity:1;transform:none}98%,100%{opacity:0}}
@keyframes ha-ok{0%,74%{opacity:0;transform:scale(.6)}80%,92%{opacity:1;transform:none}98%,100%{opacity:0}}
.ha-ok{transform-origin:322px 160px;transform-box:view-box}
@media (prefers-reduced-motion:reduce){
.ha-q,.ha-chip,.ha-ok,.ha-cur,.ha-b1,.ha-b2,.ha-b3{animation:none}
.ha-q,.ha-cur{opacity:0}
}
`;

/** Hero illustration: a machine panel is probed, its unknown readings become learned rules. */
export default function HeroArt() {
  return (
    <>
      <style>{CSS}</style>
      <svg
        className="ha"
        viewBox="0 0 360 200"
        role="img"
        aria-label="Illustration: a machine panel with three buttons and two unknown readings. A cursor presses each button, the question marks turn into learned rules, 'works 2 of 6 steps' and 'max 2 at a time', and a check mark appears."
      >
        <rect className="ha-panel" x="20" y="16" width="320" height="112" rx="14" />
        <circle className="ha-btn ha-b1" cx="64" cy="72" r="15" />
        <circle className="ha-btn ha-b2" cx="112" cy="72" r="15" />
        <circle className="ha-btn ha-b3" cx="160" cy="72" r="15" />
        <text className="ha-lbl" x="112" y="110">BUTTONS</text>
        <rect className="ha-dial" x="206" y="44" width="54" height="56" rx="10" />
        <rect className="ha-dial" x="272" y="44" width="54" height="56" rx="10" />
        <text className="ha-q" x="233" y="80">?</text>
        <text className="ha-q" x="299" y="80">?</text>
        <text className="ha-lbl" x="266" y="116">READINGS</text>

        <g className="ha-chip ha-c1">
          <rect x="20" y="146" width="138" height="28" rx="14" />
          <text x="89" y="164">works 2 of 6 steps</text>
        </g>
        <g className="ha-chip ha-c2">
          <rect x="168" y="146" width="122" height="28" rx="14" />
          <text x="229" y="164">max 2 at a time</text>
        </g>
        <g className="ha-ok">
          <circle cx="322" cy="160" r="14" />
          <path d="M315 160.5l4.5 4.5 8-9" />
        </g>

        <g className="ha-cur" aria-hidden="true">
          <path d="M0 0v17l4.5-4.2 3.2 7 3-1.4-3.2-6.8h6.2z" />
        </g>
      </svg>
    </>
  );
}
