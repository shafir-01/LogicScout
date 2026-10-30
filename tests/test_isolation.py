"""Isolation: scout-side code never reaches worlds, referee or sandbox internals.

Port introspection note: LocalPort keeps the world only in closure cells of its bound functions.
Closures are deliberately accepted as out of scope (scout code is statically scanned and never
touches `__closure__`); the checks below cover every ordinary attribute path.
"""
from __future__ import annotations

import ast
from pathlib import Path

from logicscout.contracts import WorldPort
from logicscout.sandbox import open_session

import tests.test_sandbox  # noqa: F401  (registers toy_test)

ROOT = Path(__file__).resolve().parent.parent / "logicscout"
SCOUT_SIDE = ["scout", "llm", "briefing"]
FORBIDDEN = ("logicscout.worlds", "logicscout.referee", "logicscout.sandbox.session", "logicscout.sandbox.service")
SANDBOX_PUBLIC = {"open_session", "Session", "SandboxAdmin"}


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, set()
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, {a.name for a in node.names}


def test_scout_side_imports_are_clean():
    bad = []
    for pkg in SCOUT_SIDE:
        for f in (ROOT / pkg).rglob("*.py"):
            for mod, names in _imports(f):
                if mod.startswith(FORBIDDEN):
                    bad.append(f"{f.relative_to(ROOT)}: {mod}")
                elif mod == "logicscout" and names & {"worlds", "referee"}:
                    bad.append(f"{f.relative_to(ROOT)}: from logicscout import {names}")
                elif mod == "logicscout.sandbox" and names - SANDBOX_PUBLIC:
                    bad.append(f"{f.relative_to(ROOT)}: sandbox internals {names - SANDBOX_PUBLIC}")
    assert not bad, bad


def test_scout_side_has_no_law_access():
    bad = []
    for pkg in SCOUT_SIDE:
        for f in (ROOT / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr in {"laws", "referee_cases"}:
                    bad.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert not bad, bad


def test_port_exposes_no_path_to_laws():
    port = open_session("toy_test").port
    assert isinstance(port, WorldPort)
    assert not hasattr(port, "__dict__")
    assert set(type(port).__slots__) == {"manual", "reset", "observe", "act"}
    public = [n for n in dir(port) if not n.startswith("_")]
    assert set(public) == {"manual", "reset", "observe", "act"}
    seen: set[int] = set()

    def walk(obj, depth=0):
        if id(obj) in seen or depth > 3:
            return
        seen.add(id(obj))
        assert not hasattr(obj, "laws"), f"{type(obj)} exposes laws"
        for n in dir(obj):
            if n.startswith("_"):
                continue
            try:
                v = getattr(obj, n)
            except Exception:
                continue
            if isinstance(v, (str, int, float, bool, type(None))) or callable(v):
                continue
            walk(v, depth + 1)

    walk(port)
    # bound API values are plain functions: they have no `laws`, `world` or `admin` attribute
    for n in ("manual", "reset", "observe", "act"):
        fn = getattr(port, n)
        assert not any(hasattr(fn, a) for a in ("laws", "world", "admin", "_world"))
