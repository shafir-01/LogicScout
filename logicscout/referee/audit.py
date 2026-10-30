"""Leakage audit. Each check returns (passed, notes). Missing inputs are reported as unverified (False)."""
from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from pathlib import Path

from logicscout.contracts import Case, Event, WorldManual
from logicscout.logbook import Logbook

ROOT = Path(__file__).resolve().parent.parent
SCOUT_DIRS = ("scout", "llm", "briefing")
FORBIDDEN_MODULES = ("logicscout.worlds", "logicscout.referee")
FORBIDDEN_ATTRS = {"laws", "truth", "referee_cases", "default_laws"}
SEEDED_KINDS = ("run.started", "probe.", "control.")


def _norm(s: str) -> str:
    """Lowercase, drop quotes/backslashes (JSON escaping), collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[\\\"']", " ", s)).strip().lower()


def public_names(manual: WorldManual) -> set[str]:
    names = {f.name for f in manual.observations} | {a.name for a in manual.actions}
    names |= {p.name for a in manual.actions for p in a.params}
    names |= {o.id for o in manual.objectives}
    return {n.lower() for n in names}


def _prompt_records(prompt_log: Path) -> list[tuple[str, str]]:
    """(prompt text, model response text) per logged call. Unparseable lines count as prompt text."""
    out = []
    for line in prompt_log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            out.append((_norm(line), ""))
            continue
        if not isinstance(rec, dict):
            out.append((_norm(json.dumps(rec)), ""))
            continue
        resp = str(rec.get("response_text", ""))
        rest = {k: v for k, v in rec.items() if k != "response_text"}
        out.append((_norm(json.dumps(rest, ensure_ascii=False).replace("\\n", " ")), _norm(resp)))
    return out


def _key_pattern(key: str) -> str:
    parts = [re.escape(p) for p in re.split(r"[_\s]+", key.lower()) if p]
    return r"[\s_]+".join(parts)


def no_law_text_in_prompts(
    prompt_log: Path | None, truths: Iterable[str], laws: Iterable[dict], manual: WorldManual
) -> tuple[bool, list[str]]:
    if prompt_log is None or not Path(prompt_log).exists():
        return False, ["no_law_text_in_prompts: unverified, no prompt log supplied"]
    records = _prompt_records(Path(prompt_log))
    public = public_names(manual)
    sentences = {_norm(s) for s in truths if len(s.strip()) >= 20}
    patterns: list[tuple[str, str]] = []
    for law in laws:
        for k, v in law.items():
            if k.lower() in public:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                patterns.append((f"law value written next to law name {k!r}",
                                 rf"\b{_key_pattern(k)}\s*[:=]\s*{re.escape(f'{v:g}')}(?![\d.])"))
            if "_" in k:
                patterns.append((f"hidden law key {k!r} appears", rf"\b{re.escape(k.lower())}\b"))
    patterns = sorted(set(patterns))
    notes: list[str] = []
    said = ""  # everything the model itself has written so far: echoing its own discoveries is not a leak
    for i, (text, resp) in enumerate(records, 1):
        for s in sentences:
            if s in text:
                notes.append(f"prompt line {i}: contains a hidden-law sentence verbatim")
        for what, pat in patterns:
            if re.search(pat, text):
                if re.search(pat, said):
                    continue
                notes.append(f"prompt line {i}: {what}")
        said += " " + resp
    if not records:
        notes.append("no_law_text_in_prompts: prompt log is empty (nothing was checked)")
        return False, notes
    return not notes, notes


def scout_imports_clean(root: Path = ROOT) -> tuple[bool, list[str]]:
    notes: list[str] = []
    files = [p for d in SCOUT_DIRS for p in sorted((root / d).rglob("*.py")) if (root / d).exists()]
    for path in files:
        rel = path.relative_to(root.parent).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            notes.append(f"{rel}: cannot parse ({e.msg})")
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    pkg = path.relative_to(root.parent).with_suffix("").parts[:-node.level]
                    base = ".".join([*pkg, base] if base else pkg)
                mods = [base] + [f"{base}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if any(node.value.startswith(m) for m in FORBIDDEN_MODULES):
                    notes.append(f"{rel}:{node.lineno}: string reference to {node.value!r}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRS:
                notes.append(f"{rel}:{node.lineno}: calls .{node.func.attr}()")
            elif (isinstance(node, ast.Attribute) and node.attr == "laws"
                  and not (isinstance(node.value, ast.Name) and node.value.id == "self")):
                notes.append(f"{rel}:{node.lineno}: reads .laws")
            bad = [m for m in mods if any(m == f or m.startswith(f + ".") for f in FORBIDDEN_MODULES)]
            if bad:
                notes.append(f"{rel}:{node.lineno}: imports {bad[0]}")
    return not notes, sorted(set(notes))


def _seeds_in(obj: object) -> Iterable[int]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "seed" and isinstance(v, int) and not isinstance(v, bool):
                yield v
            else:
                yield from _seeds_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _seeds_in(v)


def referee_cases_unseen(
    events: list[Event] | None, cases: list[Case], manual: WorldManual
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    lo, hi = manual.lab_seeds
    for i, c in enumerate(cases):
        if c.variant == "standard" and lo <= c.seed < hi:
            notes.append(f"case-{i}: standard-variant referee seed lies inside lab_seeds")
    if events is None:
        notes.append("referee_cases_unseen: unverified, no events supplied (only lab/referee disjointness checked)")
        return False, notes
    ref = {c.seed for c in cases}
    for ev in events:
        if ev.kind.startswith(SEEDED_KINDS) or ev.kind == "run.started":
            for s in _seeds_in(ev.data):
                if s in ref:
                    notes.append(f"event {ev.seq} ({ev.kind}) used a referee seed")
    return not notes, notes


def events_digest_ok(events: list[Event] | None) -> tuple[bool, list[str]]:
    if events is None:
        return False, ["events_digest_ok: unverified, no events supplied"]
    if not events:
        return False, ["events_digest_ok: event log is empty"]
    ok = Logbook.verify(events)
    return ok, [] if ok else ["events_digest_ok: logbook digest chain does not recompute (log was edited)"]
