"""The Investigator: turns ignorance into an executable Theory through active experiments.

The model proposes rival rules and candidate probes; everything that decides (validation, expected
information of a probe, support/refutation, acceptance of a revision) is computed in code.
"""
from __future__ import annotations

import asyncio
import random
import re
import zlib
from typing import Any

from logicscout import dsl
from logicscout.contracts import (
    Action, Hypothesis, Mismatch, Observation, Probe, ProbeOutcome, Rule, Theory, WorldManual, WorldPort,
)
from logicscout.logbook import Logbook
from logicscout.scout import induce, miner, prompts
from logicscout.theory import (
    Predictor, Transition, accuracy, compare, diff, persistence_accuracy, rule_stats, validate_theory,
)

MAX_PROBE_ACTIONS = 8
MAX_CYCLES = 40
# model-call caps per investigate() (credits are finite); past a cap the loop continues code-only
CALL_CAPS = {"hypothesize": 3, "design_probe": 3, "revise_theory": 2}
MAX_INDUCED_OPEN = 4  # open data-fitted questions at a time
SEARCHED_PROBES = 24  # code-generated candidate probes scored per design step
MOSTLY_RIGHT = 0.75  # a rival right this often, and better than the current theory, counts as supported
PROMPT_TRANSITIONS = 40
TARGET_ACCURACY = 0.97
REVISE_BELOW = 0.9
STALE_AFTER = 2  # probes in which a hypothesis stayed inconclusive before we stop chasing it
_KINDS = {"transition", "precondition", "constraint", "delay", "resource", "periodic", "other"}


def _strip_t(fields: dict) -> dict:
    return {k: v for k, v in fields.items() if k != "t"}


def _ordered(rules: list[Rule]) -> list[Rule]:
    """Rules for every step ('*') first, so action-specific rules refine them."""
    return sorted(rules, key=lambda r: r.action != "*")


def _short(v: Any) -> str:
    s = repr(v)
    return s if len(s) <= 40 else s[:37] + "..."


class Investigator:
    def __init__(self, llm, port: WorldPort, manual: WorldManual, log: Logbook,
                 priors: list[Hypothesis] | None = None) -> None:
        self.llm = llm
        self.port = port
        self.manual = manual
        self.log = log
        self.priors = list(priors or [])
        self.transitions: list[Transition] = []
        self.hypotheses: dict[str, Hypothesis] = {}
        self.probes_used = 0
        self.budget_left = 0
        self._actions = {a.name: a for a in manual.actions}
        self._hyp_n = 0
        self._rule_n = 0
        self._probe_n = 0
        self._groups: list[dict] = []  # {"question", "ids", "closed"}
        self._replaces: dict[str, str | None] = {}
        self._attempts: dict[str, int] = {}
        self._evidence: dict[str, list[int]] = {}
        self._adopted: set[str] = set()
        self._mem_init: dict = {}
        self._unknowns: list[str] = []
        self._seed_cache: dict[int, Observation] = {}
        self._priors_loaded = False
        self._calls: dict[str, int] = dict.fromkeys(CALL_CAPS, 0)
        self._rng = random.Random(zlib.crc32(manual.world_id.encode()))
        self._tried: set[tuple[str, str, str]] = set()
        self._fitted: set[str] = set()  # data-fitted rivals: judged by hit rate; model rivals must be exact

    # ------------------------------------------------------------------ main loop

    async def investigate(self, theory: Theory, budget: int, focus: list[Mismatch] | None = None,
                          caps: dict[str, int] | None = None) -> Theory:
        """`caps` lowers the per-purpose model-call caps for this pass (e.g. all 0 for a code-only refit)."""
        self.budget_left = max(0, int(budget))
        self._calls = dict.fromkeys(CALL_CAPS, 0)
        self._caps = {**CALL_CAPS, **(caps or {})}
        theory = theory.model_copy(deep=True)
        self._sync_rule_counter(theory)
        if not self._priors_loaded:
            self._load_priors(theory)
        if not self.transitions and self.budget_left > 0:
            await self._first_touch()
        cycles = idle = 0
        while self.budget_left > 0 and cycles < MAX_CYCLES:
            if (cycles >= 2 and self.budget_left <= 0.3 * budget and not self._open_groups()
                    and self._accuracy(theory) >= TARGET_ACCURACY):
                break
            cycles += 1
            if not self._induce(theory):
                self._mine(theory)
            if not any(g.get("model") for g in self._open_groups()):
                await self._hypothesize(theory, focus)
            groups = self._open_groups()
            probe = await self._design(theory, groups)
            if probe is None or not probe.actions:
                idle += 1
                if idle >= 3:
                    break
                continue
            used_before = self.probes_used
            outcome = await self._execute(theory, probe)
            if self.probes_used == used_before:
                idle += 1
                if idle >= 3:
                    break
            self._judge(probe, outcome)
            theory = await self._revise(theory, cycles)
            focus = None
        return theory

    # ------------------------------------------------------------------ helpers: ids, theories

    def _sync_rule_counter(self, theory: Theory) -> None:
        for r in theory.rules:
            m = re.fullmatch(r"R(\d+)", r.id)
            if m:
                self._rule_n = max(self._rule_n, int(m.group(1)))

    def _new_rule_id(self) -> str:
        self._rule_n += 1
        return f"R{self._rule_n}"

    def _can_call(self, purpose: str) -> bool:
        if self._calls.get(purpose, 0) >= getattr(self, "_caps", CALL_CAPS).get(purpose, 0):
            return False
        self._calls[purpose] = self._calls.get(purpose, 0) + 1
        return True

    def _new_hyp_id(self) -> str:
        self._hyp_n += 1
        while f"h{self._hyp_n}" in self.hypotheses:
            self._hyp_n += 1
        return f"h{self._hyp_n}"

    def _base(self, theory: Theory) -> Theory:
        t = theory.model_copy(deep=True)
        t.memory = {**self._mem_init, **t.memory}
        return t

    def _with(self, theory: Theory, hid: str) -> Theory:
        h = self.hypotheses[hid]
        t = self._base(theory)
        rep = self._replaces.get(hid)
        new = h.rule.model_copy(deep=True)
        new.status = "tentative"
        t.rules = _ordered([r for r in t.rules if r.id != rep and r.id != h.rule.id] + [new])
        return t

    def _accuracy(self, theory: Theory) -> float:
        if not self.transitions:
            return 0.0
        try:
            return accuracy(self._base(theory), self.transitions)
        except Exception:
            return 0.0

    def _open_groups(self) -> list[dict]:
        out = []
        for g in self._groups:
            if g["closed"]:
                continue
            live = [i for i in g["ids"] if self.hypotheses[i].status == "open"
                    and self._attempts.get(i, 0) < STALE_AFTER]
            if live:
                out.append(g)
            else:
                g["closed"] = True
        return out

    # ------------------------------------------------------------------ rules from model output

    def _rule_from(self, d: dict, source: str = "probe") -> Rule | None:
        try:
            effects = {str(k): str(v) for k, v in (d.get("effects") or {}).items()}
            memory = {str(k): str(v) for k, v in (d.get("memory") or {}).items()}
            kind = d.get("kind") if d.get("kind") in _KINDS else "transition"
            return Rule(
                id=self._new_rule_id(), statement=str(d.get("statement") or "unnamed rule")[:300], kind=kind,
                action=str(d.get("action") or "*"), when=str(d.get("when") or "True"),
                effects=effects, memory=memory, delay=max(0, int(d.get("delay") or 0)), source=source,
            )
        except Exception:
            return None

    def _rule_errors(self, rule: Rule, theory: Theory) -> list[str]:
        errs = dsl.validate(rule.when)
        for e in list(rule.effects.values()) + list(rule.memory.values()):
            errs += dsl.validate(e)
        if not rule.effects and not rule.memory:
            errs.append("rule has no effects")
        tmp = self._base(theory)
        tmp.rules = [r for r in tmp.rules if r.id != rule.id] + [rule]
        errs += validate_theory(tmp, self.manual)
        return list(dict.fromkeys(errs))

    def _register(self, rule: Rule, statement: str, source: str, replaces: str | None, question: str,
                  hid: str | None = None) -> Hypothesis:
        if not hid or hid in self.hypotheses:
            hid = self._new_hyp_id()
        h = Hypothesis(id=hid, statement=statement, rule=rule, source=source)
        self.hypotheses[h.id] = h
        self._replaces[h.id] = replaces
        self._attempts[h.id] = 0
        return h

    def _load_priors(self, theory: Theory) -> None:
        self._priors_loaded = True
        for p in self.priors:
            rule = p.rule.model_copy(deep=True)
            rule.id = self._new_rule_id()
            rule.status = "tentative"
            errs = self._rule_errors(rule, theory)
            if errs:
                self.log.append("note", {"text": f"Prior '{p.statement[:80]}' is not executable here: {errs[0]}"})
                continue
            h = self._register(rule, p.statement, p.source, None, "prior", hid=p.id)
            self._groups.append({"question": f"Does this {p.source} claim hold here?", "ids": [h.id], "closed": False})
            self.log.append("hypothesis.proposed", {"hypothesis": h.model_dump(), "question": "unverified prior"})

    # ------------------------------------------------------------------ experience replay

    def _replay(self, theory: Theory):
        """Yield (index, before, action, after, predicted, mismatches, predictor) continuing per episode."""
        pred: Predictor | None = None
        prev: Observation | None = None
        for i, (b, a, o) in enumerate(self.transitions):
            if pred is None or prev is None or b.t != prev.t or _strip_t(b.fields) != _strip_t(prev.fields):
                pred = Predictor(theory)
                pred.reset(b)
            p = pred.predict(b, a)
            yield i, b, a, o, p, compare(p, o.fields, pred.last_rules), pred
            pred.advance(o)
            prev = o

    def refit_recent(self, theory: Theory, window: int = 60) -> Theory:
        """No probes left: fit rules to the most recent experience only (the current regime) and keep each
        one that raises accuracy on it. Returns the theory unchanged when nothing helps."""
        recent = self.transitions[-window:]
        if len(recent) < 8:
            return theory
        new = self._base(theory)
        try:
            acc = accuracy(new, recent)
            cands = induce.induce(self.manual, recent)
        except Exception as e:
            self.log.append("error", {"message": f"refit failed: {e}"})
            return theory
        learned = []
        for c in sorted(cands, key=lambda c: c["unchanged"] - c["fits"][0]["hits"]):
            f, when = c["fits"][0], c.get("when", "True")
            rule = Rule(id=self._new_rule_id(), statement=f"After {'every step' if c['action'] == '*' else repr(c['action'])}"
                        f"{'' if when == 'True' else ' when ' + when}, {c['field']} becomes {f['expr']} (refit on recent control)",
                        kind="periodic" if "%" in f["expr"] else "transition", action=c["action"], when=when,
                        effects={c["field"]: f["expr"]}, status="supported")
            if self._rule_errors(rule, new):
                continue
            rep = {r.id for r in new.rules if r.action == rule.action and r.when == when
                   and c["field"] in r.effects and r.status in ("tentative", "supported")}
            cand = new.model_copy(deep=True)
            for r in cand.rules:
                if r.id in rep and set(r.effects) == {c["field"]}:
                    r.status = "retired"
            cand.rules = _ordered(cand.rules + [rule])
            a = accuracy(cand, recent)
            if a > acc + 1e-3:
                new, acc = cand, a
                learned.append(f"{rule.id}: {rule.statement}")
        if not learned:
            return theory
        new.version, new.parent = theory.version + 1, theory.version
        new.note = ("Refit on recent control experience: " + "; ".join(learned))[:600]
        self.log.append("theory.revised", {"theory": new.model_dump(), "diff": diff(theory, new),
                                           "accuracy": round(self._accuracy(new), 4),
                                           "baseline_accuracy": round(persistence_accuracy(self.transitions), 4)})
        return new

    def residuals(self, theory: Theory, last: int = 60) -> list[list[Mismatch]]:
        """Per-step mispredictions of `theory` on the most recent experience (empty list = all right)."""
        out: list[list[Mismatch]] = []
        try:
            for _, _, _, _, _, mism, _ in self._replay(self._base(theory)):
                out.append(mism)
        except Exception:
            return []
        return out[-last:]

    def _surprises(self, theory: Theory) -> tuple[list[str], list[str]]:
        surprises, calm = [], []
        try:
            for _, b, a, o, _, mism, _ in self._replay(self._base(theory)):
                line = prompts.surprise_line(b.t, _strip_t(b.fields), a.model_dump(), mism)
                (surprises if mism else calm).append(line)
        except Exception as e:  # a broken theory must not stop experiments
            self.log.append("error", {"message": f"replay failed: {e}"})
        surprises = surprises[-PROMPT_TRANSITIONS:]
        calm = calm[-max(0, min(10, PROMPT_TRANSITIONS - len(surprises))):] if len(surprises) < PROMPT_TRANSITIONS else []
        return surprises, calm

    # ------------------------------------------------------------------ world access

    async def _reset(self, seed: int) -> Observation:
        obs = await asyncio.to_thread(self.port.reset, seed)
        self._seed_cache.setdefault(seed, obs)
        return obs

    async def _observe(self) -> Observation:
        return await asyncio.to_thread(self.port.observe)

    def _seed_ok(self, seed: Any) -> int | None:
        if seed is None:
            return None
        lo, hi = self.manual.lab_seeds
        try:
            s = int(seed)
        except (TypeError, ValueError):
            return lo
        return s if lo <= s < hi else lo + (abs(s) % max(1, hi - lo))

    # ------------------------------------------------------------------ actions

    def _rep_arg(self, p, variant: int) -> Any:
        if p.type == "enum" or p.choices:
            ch = p.choices or [""]
            return ch[variant % len(ch)]
        if p.type == "bool":
            return variant % 2 == 0
        if p.type in ("int", "float"):
            lo = p.min if p.min is not None else 0
            hi = p.max if p.max is not None else (lo + 1)
            v = hi if variant % 2 == 0 else lo
            return int(v) if p.type == "int" else float(v)
        return ""

    def _random_arg(self, p) -> Any:
        if p.type == "enum" or p.choices:
            return self._rng.choice(p.choices or [""])
        if p.type == "bool":
            return self._rng.random() < 0.5
        if p.type in ("int", "float"):
            lo = p.min if p.min is not None else 0
            hi = p.max if p.max is not None else lo + 10
            return self._rng.randint(int(lo), int(hi)) if p.type == "int" else round(self._rng.uniform(lo, hi), 3)
        return ""

    def _clean_action(self, d: Any) -> Action | None:
        if not isinstance(d, dict):
            return None
        spec = self._actions.get(str(d.get("name")))
        if spec is None:
            return None
        raw = d.get("args") if isinstance(d.get("args"), dict) else {}
        args = {}
        for p in spec.params:
            v = raw.get(p.name)
            if v is None:
                args[p.name] = self._rep_arg(p, 0)
                continue
            if p.choices:
                args[p.name] = v if v in p.choices else p.choices[0]
            elif p.type in ("int", "float"):
                try:
                    x = float(v)
                except (TypeError, ValueError):
                    x = self._rep_arg(p, 0)
                if p.min is not None:
                    x = max(p.min, x)
                if p.max is not None:
                    x = min(p.max, x)
                args[p.name] = int(round(x)) if p.type == "int" else float(x)
            elif p.type == "bool":
                args[p.name] = bool(v)
            else:
                args[p.name] = str(v)
        return Action(name=spec.name, args=args)

    def _new_probe_id(self) -> str:
        self._probe_n += 1
        return f"p{self._probe_n}"

    # ------------------------------------------------------------------ 1. first touch

    async def _first_touch(self) -> None:
        actions = [Action(name=a.name, args={p.name: self._rep_arg(p, 0) for p in a.params}) for a in self.manual.actions]
        if self.budget_left >= 4 * len(actions):
            actions += [Action(name=a.name, args={p.name: self._rep_arg(p, 1) for p in a.params})
                        for a in self.manual.actions if a.params]
        probe = Probe(id=self._new_probe_id(), purpose="First touch: try every control once", hypotheses=[],
                      seed=self.manual.lab_seeds[0], actions=actions[: self.budget_left])
        self.log.append("probe.designed", {"probe": probe.model_dump(), "alternatives": []})
        outcome = await self._execute(None, probe)
        self.log.append("probe.outcome", {"outcome": outcome.model_dump()})

    # ------------------------------------------------------------------ 2. hypothesize

    async def _hypothesize(self, theory: Theory, focus: list[Mismatch] | None) -> None:
        if not self._can_call("hypothesize"):
            return
        surprises, calm = self._surprises(theory)
        tested = [prompts.rule_line(h.rule) + f" -> {h.status}" for h in self.hypotheses.values()][-20:]
        stats = induce.change_stats(self.manual, self.transitions)
        fits = self._fit_lines()
        user = prompts.hypothesize_user(self.manual, dsl.DSL_GUIDE, self._base(theory), surprises, calm,
                                        self.priors, focus, tested, stats, fits)
        try:
            out = await self.llm.json("hypothesize", prompts.SCIENTIST, user, prompts.HYPOTHESIZE_SCHEMA, tier="deep")
        except Exception as e:
            self.log.append("error", {"message": f"hypothesize failed: {e}; continuing with exploratory probes"})
            return
        mem = out.get("memory") if isinstance(out, dict) else None
        if isinstance(mem, dict):
            for k, v in mem.items():
                if k not in theory.memory and isinstance(v, (int, float, str, bool, list, type(None))):
                    self._mem_init.setdefault(str(k), v)
        unk = out.get("unknowns") if isinstance(out, dict) else None
        if isinstance(unk, list):
            self._unknowns = [str(u)[:200] for u in unk][:8]
        questions = out.get("questions") if isinstance(out, dict) else None
        existing = {r.id for r in theory.rules}
        for q in (questions or [])[:3]:
            if not isinstance(q, dict):
                continue
            text = str(q.get("question") or "unnamed question")[:300]
            ids = []
            for rd in (q.get("rivals") or [])[:3]:
                if not isinstance(rd, dict):
                    continue
                rule = self._rule_from(rd)
                if rule is None:
                    self.log.append("note", {"text": f"Dropped a malformed rival for '{text[:80]}'"})
                    continue
                errs = self._rule_errors(rule, theory)
                if errs:
                    self.log.append("note", {"text": f"Dropped non-executable rival {rule.id} ({rule.statement[:80]}): {errs[0]}"})
                    continue
                rep = rd.get("replaces")
                rep = rep if isinstance(rep, str) and rep in existing else None
                ids.append(self._register(rule, rule.statement, "probe", rep, text).id)
            if not ids:
                continue
            for i in ids:
                self.hypotheses[i].rivals = [j for j in ids if j != i]
                self.log.append("hypothesis.proposed", {"hypothesis": self.hypotheses[i].model_dump(), "question": text})
            self._groups.append({"question": text, "ids": ids, "closed": False, "model": True})

    # ------------------------------------------------------------------ 2b. data-fitted rivals

    def _fits(self) -> list[dict]:
        try:
            return induce.induce(self.manual, self.transitions)
        except Exception as e:
            self.log.append("error", {"message": f"rule fitting failed: {e}"})
            return []

    def _fit_lines(self) -> list[str]:
        out = []
        for c in self._fits()[:12]:
            f = c["fits"][0]
            out.append(f'{c["action"]}: {c["field"]} = {f["expr"]}  (fits {f["hits"]}/{f["n"]} steps; '
                       f'"unchanged" fits {c["unchanged"]})')
        return out

    def _theory_hits(self, theory: Theory) -> dict[tuple[str, str, str], int]:
        hits: dict[tuple[str, str, str], int] = {}
        try:
            for _, b, a, o, p, mism, _ in self._replay(self._base(theory)):
                bad = {m.field for m in mism}
                for f in o.fields:
                    if f == "t":
                        continue
                    ok = int(f not in bad)
                    keys = [(a.name, f, "True"), ("*", f, "True")]
                    keys += [(a.name, f, f"args.{k} == {v!r}") for k, v in a.args.items() if isinstance(v, str)]
                    for key in keys:
                        hits[key] = hits.get(key, 0) + ok
        except Exception:
            pass
        return hits

    def _induce(self, theory: Theory) -> int:
        """Offer simple rules fitted to all experience as rivals; probes must still support them.
        Returns how many questions were opened."""
        if len(self.transitions) < 6:
            return 0
        open_keys = {g["key"] for g in self._open_groups() if g.get("key")}
        room = MAX_INDUCED_OPEN - len(open_keys)
        if room <= 0:
            return 1
        have = self._theory_hits(theory)
        active = [r for r in self._base(theory).rules if r.status in ("tentative", "supported")]
        ranked = []
        for c in self._fits():
            key = (c["action"], c["field"], c.get("when", "True"))
            if key in open_keys:
                continue
            fits = [f for f in c["fits"] if (*key, f["expr"]) not in self._tried][:2]
            if not fits or fits[0]["hits"] <= have.get(key, 0) + 1:
                continue
            ranked.append((fits[0]["hits"] - have.get(key, 0), key, fits))
        ranked.sort(key=lambda x: -x[0])
        opened = 0
        for _, (action, field, when), fits in ranked[:room]:
            rep = next((r.id for r in active if r.action == action and r.when == when and set(r.effects) == {field}),
                       None)
            ids = []
            for f in fits:
                self._tried.add((action, field, f["expr"]))
                where = "every step" if action == "*" else f"'{action}'" + ("" if when == "True" else f" when {when}")
                rule = Rule(id=self._new_rule_id(), kind="periodic" if "%" in f["expr"] else "transition",
                            statement=f"After {where}, {field} becomes {f['expr']} (fits {f['hits']}/{f['n']} past steps)",
                            action=action, when=when, effects={field: f["expr"]})
                if self._rule_errors(rule, theory):
                    continue
                ids.append(self._register(rule, rule.statement, "probe", rep, "fit").id)
                self._fitted.add(ids[-1])
            if not ids:
                continue
            q = f"How does {field} change " + ("on every step?" if action == "*" else f"after '{action}'"
                                                 + ("" if when == "True" else f" when {when}") + "?")
            for i in ids:
                self.hypotheses[i].rivals = [j for j in ids if j != i]
                self.log.append("hypothesis.proposed", {"hypothesis": self.hypotheses[i].model_dump(),
                                                        "question": q + " (fitted to experience)"})
            self._groups.append({"question": q, "ids": ids, "closed": False, "key": (action, field, when)})
            opened += 1
        return opened

    def _mine(self, theory: Theory) -> None:
        """Second, independent rule source (lags, cooldowns, periodic guards) validated on held-out steps."""
        if len(self.transitions) < 6:
            return
        open_keys = {g["key"] for g in self._open_groups() if g.get("key")}
        room = MAX_INDUCED_OPEN - len(open_keys)
        if room <= 0:
            return
        try:
            mined = miner.mine(self.manual, self.transitions, self._base(theory), max_rules=8)
        except Exception as e:
            self.log.append("error", {"message": f"rule mining failed: {e}"})
            return
        active = [r for r in self._base(theory).rules if r.status in ("tentative", "supported")]
        for rule in mined:
            if room <= 0 or len(rule.effects) != 1:
                continue
            field = next(iter(rule.effects))
            key = (rule.action, field, rule.when)
            sig = (rule.action, field, rule.when + "|" + repr(sorted(rule.effects.items())) + repr(sorted(rule.memory.items())) + str(rule.delay))
            if key in open_keys or sig in self._tried:
                continue
            self._tried.add(sig)
            rule = rule.model_copy(update={"id": self._new_rule_id(), "status": "tentative"})
            if self._rule_errors(rule, theory):
                continue
            rep = next((r.id for r in active if r.action == rule.action and r.when == rule.when
                        and set(r.effects) == {field}), None)
            h = self._register(rule, rule.statement, "probe", rep, "mined")
            self._fitted.add(h.id)
            q = f"Does the mined rule for {field} hold?"
            self.log.append("hypothesis.proposed", {"hypothesis": h.model_dump(), "question": q + " (mined from experience)"})
            self._groups.append({"question": q, "ids": [h.id], "closed": False, "key": key})
            open_keys.add(key)
            room -= 1

    # ------------------------------------------------------------------ 3. design

    def _simulate(self, th: Theory, start: Observation, actions: list[Action]) -> list[dict]:
        out: list[dict] = []
        try:
            p = Predictor(th)
            p.reset(start)
            obs = start
            for a in actions:
                fields = _strip_t(p.predict(obs, a))
                nxt = Observation(t=obs.t + 1, fields=fields)
                p.advance(nxt)
                out.append(fields)
                obs = nxt
        except Exception:
            out += [dict(out[-1] if out else _strip_t(start.fields)) for _ in range(len(actions) - len(out))]
        return out

    def _score(self, theory: Theory, groups: list[dict], start: Observation, actions: list[Action]
               ) -> tuple[float, dict[str, list[dict]]]:
        preds: dict[str, list[dict]] = {}
        disagree = 0
        for g in groups:
            ids = [i for i in g["ids"] if self.hypotheses[i].status == "open"]
            sims = {i: self._simulate(self._with(theory, i), start, actions) for i in ids}
            preds.update(sims)
            runs = list(sims.values())
            if len(runs) == 1:
                runs.append(self._simulate(self._base(theory), start, actions))
            for step in range(len(actions)):
                bad: set[str] = set()
                for x in range(len(runs)):
                    for y in range(x + 1, len(runs)):
                        bad |= {m.field for m in compare(runs[x][step], runs[y][step])}
                disagree += len(bad)
        return disagree / max(1, len(actions)), preds

    def _random_actions(self, n: int) -> list[Action]:
        out = []
        for _ in range(n):
            spec = self._rng.choice(self.manual.actions)
            out.append(Action(name=spec.name, args={p.name: self._random_arg(p) for p in spec.params}))
        return out

    def _random_probe(self) -> dict:
        lo, hi = self.manual.lab_seeds
        seed = None
        if self._rng.random() < 0.35:
            cached = sorted(self._seed_cache)
            seed = self._rng.choice(cached) if cached and self._rng.random() < 0.5 else self._rng.randrange(lo, hi)
        n = min(self._rng.randint(3, 6), MAX_PROBE_ACTIONS)
        return {"purpose": "Exploratory probe: random controls to gather fresh experience", "seed": seed,
                "actions": self._random_actions(n)}

    def _variants(self) -> list[Action]:
        """Each control with every combination of its choice arguments (numbers at a typical value)."""
        out = []
        for spec in self.manual.actions:
            combos: list[dict] = [{}]
            for p in spec.params:
                vals = (p.choices or ([True, False] if p.type == "bool" else [self._rep_arg(p, 0)]))[:4]
                combos = [{**c, p.name: v} for c in combos for v in vals][:8]
            out += [Action(name=spec.name, args=c) for c in combos]
        return out

    @staticmethod
    def _sig(a: Action) -> str:
        enum = {k: v for k, v in a.args.items() if isinstance(v, (str, bool))}
        return a.name + (str(enum) if enum else "")

    def _inert(self) -> set[str]:
        """Control variants tried but never seen to change any field."""
        tried: dict[str, int] = {}
        active = set()
        for b, a, o in self.transitions:
            s = self._sig(a)
            tried[s] = tried.get(s, 0) + 1
            if compare(_strip_t(b.fields), _strip_t(o.fields)):
                active.add(s)
        return {s for s, n in tried.items() if s not in active and n < 6}

    def _novelty(self, acts: list[Action], inert: set[str]) -> float:
        seen = set()
        prev = None
        for b, a, o in self.transitions:
            seen.add((prev, self._sig(a)))
            prev = self._sig(a)
        pairs = {(x, y) for x, y in zip([None] + [self._sig(a) for a in acts], [self._sig(a) for a in acts])}
        new = len(pairs - seen)
        late_inert = any(self._sig(a) in inert for a in acts[1:])
        return 0.1 * new / max(1, len(acts)) + (0.3 if late_inert else 0.0)

    async def _searched_probe(self, theory: Theory, groups: list[dict]) -> dict | None:
        """Cheap code-side search: random short plans from the current state or a known seed,
        keeping the one whose predicted outcomes differ most between rivals."""
        current = await self._observe()
        seeds = sorted(self._seed_cache)
        best = None
        plans = []
        for spec in self.manual.actions:  # single-factor: repeat one control, everything else held
            for v in range(2 if spec.params else 1):
                act = Action(name=spec.name, args={p.name: self._rep_arg(p, v) for p in spec.params})
                plans.append((f"Single-factor: repeat {spec.name}{act.args or ''} and watch what changes",
                              None, [act] * 4))
        inert = self._inert()
        variants = self._variants()
        seen = {(self._sig(x[1]), self._sig(y[1])) for x, y in zip(self.transitions, self.transitions[1:])}
        pairs = [(a, b) for a in variants for b in variants if self._sig(b) in inert
                 and self._sig(a) != self._sig(b) and (self._sig(a), self._sig(b)) not in seen]
        for a, b in pairs[:40]:
            # controls may only act after another one prepared the state (e.g. warm-up): try ordered pairs
            k = self._rng.randint(1, 3)
            plans.append((f"Coverage: {self._sig(b)} after {k}x {self._sig(a)}", None, [a] * k + [b]))
        for _ in range(SEARCHED_PROBES):
            seed = self._rng.choice(seeds) if seeds and self._rng.random() < 0.3 else None
            plans.append(("Searched plan where the rival rules disagree most", seed,
                          self._random_actions(self._rng.randint(3, 6))))
        for purpose, seed, acts in plans:
            start = current if seed is None else self._seed_cache[seed]
            score, _ = self._score(theory, groups, start, acts) if groups else (0.0, {})
            score += self._novelty(acts, inert)
            if best is None or score > best[0] + 1e-9:
                best = (score, {"purpose": purpose, "seed": seed, "actions": acts})
        return best[1] if best and best[0] > 0 else None

    async def _design(self, theory: Theory, groups: list[dict]) -> Probe | None:
        cands: list[dict] = []
        if any(g.get("model") for g in groups) and self._can_call("design_probe"):
            current = await self._observe()
            qs = [{"question": g["question"], "rivals": [
                {"id": i, "rule": prompts.rule_line(self.hypotheses[i].rule)} for i in g["ids"]
                if self.hypotheses[i].status == "open"]} for g in groups if g.get("model")]
            user = prompts.design_user(self.manual, qs, {"t": current.t, **_strip_t(current.fields)},
                                       sorted(self._seed_cache), self.manual.lab_seeds)
            try:
                out = await self.llm.json("design_probe", prompts.DESIGNER, user, prompts.DESIGN_SCHEMA, tier="fast")
                for c in (out.get("probes") or [])[:3]:
                    if not isinstance(c, dict):
                        continue
                    acts = [a for a in (self._clean_action(x) for x in (c.get("actions") or [])) if a]
                    if acts:
                        cands.append({"purpose": str(c.get("purpose") or "distinguish rivals")[:300],
                                      "seed": self._seed_ok(c.get("seed")), "actions": acts[:MAX_PROBE_ACTIONS]})
            except Exception as e:
                self.log.append("error", {"message": f"design_probe failed: {e}; using code-generated probes"})
        cands.append(self._random_probe())
        best = await self._searched_probe(theory, groups)
        if best:
            cands.append(best)
        for c in cands:
            c["actions"] = c["actions"][: self.budget_left]
        cands = [c for c in cands if c["actions"]]
        if not cands:
            return None
        # seeded starts first (may reset the world; free), then the current state for "continue" probes
        starts: dict[int, Observation] = {}
        for c in cands:
            if c["seed"] is not None and c["seed"] not in starts:
                starts[c["seed"]] = self._seed_cache.get(c["seed"]) or await self._reset(c["seed"])
        current = await self._observe()
        inert = self._inert()
        hyps = sorted({i for g in groups for i in g["ids"] if self.hypotheses[i].status == "open"},
                      key=list(self.hypotheses).index)
        scored = []
        for c in cands:
            start = current if c["seed"] is None else starts[c["seed"]]
            score, preds = self._score(theory, groups, start, c["actions"]) if groups else (0.0, {})
            score += self._novelty(c["actions"], inert)
            scored.append((score, -len(c["actions"]), c, preds))
        best_i = max(range(len(scored)), key=lambda k: (scored[k][0], scored[k][1], -k))
        score, _, best, preds = scored[best_i]
        probe = Probe(id=self._new_probe_id(), purpose=best["purpose"], hypotheses=hyps, seed=best["seed"],
                      actions=best["actions"], predictions=preds, score=round(score, 4))
        alts = [{"purpose": c["purpose"], "score": round(s, 4)} for k, (s, _, c, _) in enumerate(scored) if k != best_i]
        self.log.append("probe.designed", {"probe": probe.model_dump(), "alternatives": alts})
        return probe

    # ------------------------------------------------------------------ 4. execute

    async def _execute(self, theory: Theory | None, probe: Probe) -> dict:
        obs = await self._reset(probe.seed) if probe.seed is not None else await self._observe()
        tracks: dict[str, Predictor] = {}
        if theory is not None:
            for hid in probe.hypotheses:
                try:
                    tracks[hid] = Predictor(self._with(theory, hid))
                    tracks[hid].reset(obs)
                except Exception:
                    pass
            try:
                tracks["_base"] = Predictor(self._base(theory))
                tracks["_base"].reset(obs)
            except Exception:
                pass
        rec = {"observations": [], "steps": []}
        for action in probe.actions:
            if self.budget_left <= 0:
                break
            preds: dict[str, dict] = {}
            rules: dict[str, tuple[list[str], dict[str, list[str]]]] = {}
            for hid, p in tracks.items():
                try:
                    preds[hid] = _strip_t(p.predict(obs, action))
                    rules[hid] = (list(p.fired), {k: list(v) for k, v in p.last_rules.items()})
                except Exception:
                    preds[hid] = _strip_t(obs.fields)
                    rules[hid] = ([], {})
            res = await asyncio.to_thread(self.port.act, action)
            self.probes_used += 1
            self.budget_left -= 1
            nxt = res.observation
            data: dict[str, Any] = {"probe_id": probe.id, "action": action.model_dump(), "observation": nxt.model_dump()}
            shown = {k: v for k, v in preds.items() if k != "_base"}
            if shown:
                data["predicted"] = shown
            if res.error:
                data["error"] = res.error
            ev = self.log.append("probe.step", data)
            rec["observations"].append(nxt)
            if not res.error:
                self.transitions.append((obs, action, nxt))
                rec["steps"].append({"seq": ev.seq, "t": nxt.t, "action": action, "before": obs, "after": nxt,
                                     "preds": preds, "rules": rules})
            for p in tracks.values():
                try:
                    p.advance(nxt)
                except Exception:
                    pass
            obs = nxt
            if res.done:
                break
        return rec if theory is not None else ProbeOutcome(probe_id=probe.id, observations=rec["observations"], outcomes={})

    # ------------------------------------------------------------------ 5. judge

    def _judge(self, probe: Probe, rec: dict) -> ProbeOutcome:
        outcomes: dict[str, str] = {}
        surprises: list[str] = []
        for st in rec["steps"]:
            base = st["preds"].get("_base")
            if base is not None:
                for m in compare(base, st["after"].fields):
                    surprises.append(f"t={st['t']} {m.field}: theory said {_short(m.predicted)}, saw {_short(m.observed)}")
        for hid in probe.hypotheses:
            h = self.hypotheses[hid]
            rid = h.rule.id
            fired_at, seqs, wrong = [], [], None
            right = misses = base_right = 0
            for st in rec["steps"]:
                fired, sources = st["rules"].get(hid, ([], {}))
                judged = [f for f, ids in sources.items() if ids and ids[-1] == rid and f in st["after"].fields]
                if rid in fired:
                    fired_at.append(st["t"])
                if not judged:
                    continue
                seqs.append(st["seq"])
                pred = st["preds"][hid]
                base = st["preds"].get("_base") or {}
                for f in judged:
                    seen = st["after"].fields[f]
                    base_right += int(not compare({f: base.get(f)}, {f: seen}))
                    if compare({f: pred.get(f)}, {f: seen}):
                        misses += 1
                        wrong = wrong or (f, pred.get(f), seen, st["t"])
                    else:
                        right += 1
            self._attempts[hid] = self._attempts.get(hid, 0) + 1
            if wrong and hid in self._fitted and right >= MOSTLY_RIGHT * (right + misses) and right > base_right:
                status = "supported"
                reason = f"right {right}/{right + misses} times (current theory {base_right}); not exact"
            elif wrong:
                f, p, o, t = wrong
                status, reason = "refuted", f"predicted {f}={_short(p)}, saw {f}={_short(o)} at t={t}"
            elif seqs:
                status, reason = "supported", f"fired {len(seqs)}x, every predicted effect matched"
            else:
                status = "inconclusive"
                reason = "condition never held" if not fired_at else "effect was overridden by another rule"
            outcomes[hid] = status
            if status == "inconclusive":
                continue
            h.status = status
            ev = self.log.append(f"hypothesis.{status}", {"id": hid, "probe_id": probe.id, "reason": reason})
            if status == "supported":
                self._evidence[hid] = self._evidence.get(hid, []) + seqs + [ev.seq]
        outcome = ProbeOutcome(probe_id=probe.id, observations=rec["observations"], outcomes=outcomes,
                               surprises=surprises[:20])
        self.log.append("probe.outcome", {"outcome": outcome.model_dump()})
        return outcome

    # ------------------------------------------------------------------ 6. revise

    async def _revise(self, theory: Theory, cycle: int) -> Theory:
        old = theory
        new = self._base(theory)
        learned: list[str] = []
        for g in self._groups:
            sup = [i for i in g["ids"] if self.hypotheses[i].status == "supported" and i not in self._adopted]
            if not sup:
                continue
            cur = self._accuracy(new)
            best = max(sup, key=lambda i: (self._accuracy(self._with(new, i)), -list(self.hypotheses).index(i)))
            cand = self._with(new, best)
            if self._accuracy(cand) + 1e-9 >= cur:
                self._adopted.update(sup)
                rep = self._replaces.get(best)
                for r in cand.rules:
                    if r.id == rep:
                        r.status = "retired"
                rule = next(r for r in cand.rules if r.id == self.hypotheses[best].rule.id)
                rule.status = "supported"
                rule.evidence = sorted(set(self._evidence.get(best, [])))
                new = cand
                learned.append(f"{rule.id}: {rule.statement}")
        for h in self.hypotheses.values():
            if h.status == "refuted":
                for r in new.rules:
                    if r.id == h.rule.id and r.status != "refuted":
                        r.status = "refuted"
                        learned.append(f"dropped {r.id} (refuted)")
        acc = self._accuracy(new)
        if acc < REVISE_BELOW and self.transitions:
            new, acc, msg = await self._model_revision(new, acc)
            if msg:
                learned.append(msg)
        try:
            stats = rule_stats(new, self.transitions)
        except Exception:
            stats = {}
        for r in new.rules:
            s = stats.get(r.id)
            if s and s["fired"]:
                r.confidence = round((s["correct"] + 1) / (s["fired"] + 2), 3)
        new.unknowns = self._unknowns or new.unknowns
        new.version = old.version + 1
        new.parent = old.version
        new.note = ("Learned: " + "; ".join(learned)) if learned else f"Cycle {cycle}: more experience, no rule changes."
        new.note = new.note[:600]
        try:
            base_acc = persistence_accuracy(self.transitions)
        except Exception:
            base_acc = 0.0
        self.log.append("theory.revised", {"theory": new.model_dump(), "diff": diff(old, new),
                                           "accuracy": round(acc, 4), "baseline_accuracy": round(base_acc, 4)})
        return new

    async def _model_revision(self, theory: Theory, acc: float) -> tuple[Theory, float, str]:
        if not self._can_call("revise_theory"):
            return theory, acc, ""
        residuals = []
        try:
            for _, b, a, o, _, mism, _ in self._replay(theory):
                if mism:
                    residuals.append(prompts.surprise_line(b.t, _strip_t(b.fields), a.model_dump(), mism))
        except Exception:
            pass
        user = prompts.revise_user(self.manual, dsl.DSL_GUIDE, theory, residuals[-25:], acc)
        try:
            out = await self.llm.json("revise_theory", prompts.SCIENTIST, user, prompts.REVISE_SCHEMA, tier="deep")
        except Exception as e:
            self.log.append("error", {"message": f"revise_theory failed: {e}"})
            return theory, acc, ""
        cand = theory.model_copy(deep=True)
        mem = out.get("memory") if isinstance(out, dict) else None
        if isinstance(mem, dict):
            cand.memory = {**cand.memory, **{str(k): v for k, v in mem.items() if k not in cand.memory}}
        by_id = {r.id: r for r in theory.rules}
        rules: list[Rule] = []
        for rd in (out.get("rules") or []) if isinstance(out, dict) else []:
            if not isinstance(rd, dict):
                continue
            rule = self._rule_from(rd)
            if rule is None:
                continue
            prev = by_id.get(str(rd.get("id")))
            if prev is not None:
                rule.id, rule.evidence, rule.source = prev.id, prev.evidence, prev.source
                rule.status = prev.status if prev.status in ("tentative", "supported") else "tentative"
            probe_t = cand.model_copy(deep=True)
            probe_t.rules = [r for r in rules if r.id != rule.id] + [rule]
            errs = self._rule_errors(rule, probe_t)
            if errs:
                self.log.append("note", {"text": f"Revision rule dropped ({rule.statement[:80]}): {errs[0]}"})
                continue
            rules.append(rule)
        if not rules:
            return theory, acc, ""
        if isinstance(mem, dict):
            for k, v in mem.items():
                self._mem_init.setdefault(str(k), v)
        # proposed corrections are not adopted blindly: each becomes a rival that a probe must support
        sig = lambda r: (r.action, r.when, r.effects, r.memory, r.delay)  # noqa: E731
        scored = []
        for rule in rules:
            prev = by_id.get(rule.id)
            if prev is not None and sig(prev) == sig(rule):
                continue
            rep = prev.id if prev is not None else None
            rule.id = self._new_rule_id()
            rule.status = "tentative"
            h = self._register(rule, rule.statement, "probe", rep, "revision")
            gain = self._accuracy(self._with(theory, h.id)) - acc
            scored.append((gain, h.id))
        keep = [hid for gain, hid in sorted(scored, key=lambda x: -x[0])[:6] if gain >= 0]
        for gain, hid in scored:
            if hid not in keep:
                del self.hypotheses[hid]
        for hid in keep:
            h = self.hypotheses[hid]
            q = "Does this correction from the revision hold?"
            self.log.append("hypothesis.proposed", {"hypothesis": h.model_dump(), "question": q})
            self._groups.append({"question": q, "ids": [hid], "closed": False, "model": True})
        note = str(out.get("note") or "").strip()[:160]
        return theory, acc, (f"model proposed {len(keep)} corrections to test" + (f" ({note})" if note else "")) if keep else ""
