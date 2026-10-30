"""Mechanism library for Forge: seed -> composed hidden laws, plain-words truth, reference DSL theory.

PRIVATE (worlds only). Laws are a flat dict (numbers/strings) plus `mechanisms` (list) and `names`
(dict of neutral public names per role). Every mechanism has a reference DSL encoding in
`reference_theory`, which reproduces the simulator exactly (proved in tests/test_world_forge.py).
"""
from __future__ import annotations

import random

from logicscout.contracts import JSON, Rule, Theory

MECHANISMS = ("delay", "cooldown", "window", "capacity", "resource", "ordering", "control", "threshold")
ACTION_WORDS = ["pulse", "vent", "route", "prime", "hold", "cycle", "shunt", "latch", "sweep", "draw",
                "tap", "align", "bleed", "kick", "settle", "trim", "press", "spin"]
FIELD_WORDS = ["flux", "charge", "output", "relay_ready", "bias", "gauge", "drift", "phase_mark",
               "tally", "store", "signal", "quiet", "beacon", "count", "trace", "yield_mark", "span"]
PADDING = ("uses", "idle", "last", "moves")
SINCE_CAP = 50
LEVELS = 4  # control action takes level 0..3


def generate_laws(seed: int, attempt: int = 0) -> JSON:
    """Deterministically compose 3-5 mechanisms with seed-chosen parameters and neutral names."""
    rng = random.Random(seed * 1_000_003 + 17 + 7919 * attempt)
    adders = ["ordering", "capacity", "control"]
    plain = ["delay", "cooldown", "window", "resource", "threshold"]
    n = rng.randint(3, 5)
    n_add = rng.randint(0, min(2, n - 1)) if n < 5 else rng.randint(1, 2)
    mechs = rng.sample(adders, n_add) + rng.sample(plain, n - n_add)
    mechs = [m for m in MECHANISMS if m in mechs]
    L: JSON = {"mechanisms": mechs, "gain": rng.randint(2, 4)}
    if "delay" in mechs:
        L["delay_steps"] = rng.randint(1, 3)
    if "cooldown" in mechs:
        L["cooldown_steps"] = rng.randint(1, 3)
    if "window" in mechs:
        p = rng.randint(4, 7)
        L["window_period"], L["window_open"] = p, rng.randint(2, p - 2)
    if "capacity" in mechs:
        L["cap"] = L["gain"] * rng.randint(2, 4) + rng.randint(0, L["gain"] - 1)
    if "resource" in mechs:
        cost = rng.randint(2, 4)
        L["res_cost"], L["res_regen"] = cost, rng.randint(1, cost - 1)
        L["res_max"] = cost * rng.randint(3, 5)
        L["gauge_step"] = rng.randint(2, 4)
    if "ordering" in mechs:
        L["order_within"] = rng.randint(2, 4)
    if "control" in mechs:
        L["control_mode"] = rng.choice(["inverted", "rate_limited"])
        L["bonus"] = rng.randint(1, 2)
    if "threshold" in mechs:
        L["heat_per_use"] = rng.randint(2, 4)
        L["heat_limit"] = L["heat_per_use"] + rng.randint(1, 4)
        L["lockout_steps"] = rng.randint(2, 4)

    roles = ["P", "hold"] + [r for m, r in (("ordering", "A"), ("capacity", "transfer"), ("control", "tune"))
                             if m in mechs]
    if len(roles) < 3:
        roles.append("decoy")
    words = rng.sample(ACTION_WORDS, len(roles))
    names: JSON = dict(zip(roles, words))
    names["order"] = rng.sample(roles, len(roles))  # public listing order of actions (by role)
    fkeys = ["out"] + [k for m, ks in (("capacity", ["buf"]), ("control", ["set"]), ("resource", ["gauge"]),
                                        ("threshold", ["heat", "ready"])) if m in mechs for k in ks]
    n_fields = max(5, min(8, len(fkeys) + rng.randint(1, 3)))
    fkeys += rng.sample(PADDING, min(len(PADDING), n_fields - len(fkeys)))
    fnames = rng.sample([w for w in FIELD_WORDS if w != "relay_ready"], len(fkeys))
    if "ready" in fkeys:
        fnames[fkeys.index("ready")] = "relay_ready"
    names["fields"] = dict(zip(fkeys, fnames))
    L["names"] = names
    return L


def action_list(L: JSON) -> list[str]:
    return [L["names"][r] for r in L["names"]["order"]]


# ---- plain words -----------------------------------------------------------------------


def describe(L: JSON) -> list[str]:
    N, F, m = L["names"], L["names"]["fields"], L["mechanisms"]
    tgt = F["buf"] if "capacity" in m else F["out"]
    gain = f"{L['gain']} + {L['bonus']} * {F['set']}" if "control" in m else str(L["gain"])
    out = [f"'{N['P']}' produces {gain} units into {tgt} when every gate below is open."]
    if "delay" in m:
        out.append(f"Delayed effect: the produced amount lands {L['delay_steps']} steps after '{N['P']}'.")
    if "cooldown" in m:
        out.append(f"Cooldown: after an effective '{N['P']}', it does nothing for {L['cooldown_steps']} steps.")
    if "window" in m:
        out.append(f"Availability window: '{N['P']}' only works when t % {L['window_period']} < {L['window_open']}.")
    if "capacity" in m:
        out.append(f"Capacity limit: {F['buf']} holds at most {L['cap']}; any excess is lost. "
                   f"'{N['transfer']}' moves all of {F['buf']} into {F['out']}.")
    if "resource" in m:
        out.append(f"Hidden reservoir (max {L['res_max']}, starts full): each effective '{N['P']}' costs "
                   f"{L['res_cost']}, needs at least that much, refills {L['res_regen']} per step; "
                   f"{F['gauge']} = reservoir // {L['gauge_step']}.")
    if "ordering" in m:
        out.append(f"Ordering precondition: '{N['P']}' only works if '{N['A']}' was used within the last "
                   f"{L['order_within']} steps.")
    if "control" in m:
        how = (f"sets {F['set']} = 3 - level (inverted)" if L["control_mode"] == "inverted"
               else f"moves {F['set']} one step toward level (rate-limited)")
        out.append(f"Control: '{N['tune']}' {how}.")
    if "threshold" in m:
        out.append(f"Threshold lockout: each effective '{N['P']}' adds {L['heat_per_use']} to {F['heat']} "
                   f"(which cools 1 per step); above {L['heat_limit']} production locks for "
                   f"{L['lockout_steps']} steps ({F['ready']} false).")
    if "decoy" in N:
        out.append(f"'{N['decoy']}' removes 1 from {F['out']}.")
    return out


# ---- reference DSL theory --------------------------------------------------------------


def reference_theory(L: JSON, world_id: str = "forge") -> Theory:
    """A Theory in the LogicScout DSL that reproduces the Forge simulator exactly."""
    m, N, F = L["mechanisms"], L["names"], L["names"]["fields"]
    o = {k: f"obs.{v}" for k, v in F.items()}
    gates = []
    if "window" in m:
        gates.append(f"t % {L['window_period']} < {L['window_open']}")
    if "cooldown" in m:
        gates.append("mem.cd == 0")
    if "threshold" in m:
        gates.append("mem.lock == 0")
    if "ordering" in m:
        gates.append(f"mem.since < {L['order_within']}")
    if "resource" in m:
        gates.append(f"mem.res >= {L['res_cost']}")
    E = " and ".join(gates) or "True"
    G = f"({L['gain']} + {L['bonus']} * {o['set']})" if "control" in m else str(L["gain"])
    d = L.get("delay_steps", 0) if "delay" in m else 0
    land = "mem.p1" if d else "0"
    cap = "capacity" in m
    tgt = "buf" if cap else "out"

    def tgt_expr(add: str) -> str:
        e = f"{o[tgt]} + {add}"
        return f"min({L['cap']}, {e})" if cap else e

    memory: JSON = {}
    rules: list[Rule] = []

    def rule(rid, statement, action="*", when="True", effects=None, mem=None, kind="transition"):
        rules.append(Rule(id=rid, statement=statement, kind=kind, action=action, when=when,
                          effects=effects or {}, memory=mem or {}, status="supported", confidence=1.0,
                          source="prior"))

    # base step (every action): landing, cooling, refill, counters
    base_eff: JSON = {}
    base_mem: JSON = {}
    if d:
        memory.update({f"p{i}": 0 for i in range(1, d + 1)})
        base_mem.update({f"p{i}": f"mem.p{i + 1}" for i in range(1, d)})
        base_mem[f"p{d}"] = "0"
        base_eff[tgt] = tgt_expr("mem.p1")
    if "cooldown" in m:
        memory["cd"] = 0
        base_mem["cd"] = "max(0, mem.cd - 1)"
    if "ordering" in m:
        memory["since"] = SINCE_CAP
        base_mem["since"] = f"min(mem.since + 1, {SINCE_CAP})"
    if "resource" in m:
        memory["res"] = L["res_max"]
        base_mem["res"] = f"min({L['res_max']}, mem.res + {L['res_regen']})"
        base_eff["gauge"] = f"min({L['res_max']}, mem.res + {L['res_regen']}) // {L['gauge_step']}"

    def heat_rules(h: int) -> tuple[JSON, JSON]:
        heat = f"(max(0, {o['heat']} - 1) + {h})"
        lock = f"({L['lockout_steps']} if (mem.lock == 0 and {heat} > {L['heat_limit']}) else max(0, mem.lock - 1))"
        return {"heat": heat, "ready": f"{lock} == 0"}, {"lock": lock}

    if "threshold" in m:
        memory["lock"] = 0
        e, mm = heat_rules(0)
        base_eff.update(e)
        base_mem.update(mm)
    for k in ("idle", "moves"):
        if k in F:
            base_eff[k] = "0" if k == "idle" else f"{o['moves']} + 1"
    rule("base", "Every step: pending output lands, hidden counters tick, reservoir refills, heat cools.",
         effects={F[k]: v for k, v in base_eff.items()}, mem=base_mem)

    # producer when every gate is open
    p_eff: JSON = {}
    p_mem: JSON = {}
    if d:
        p_mem[f"p{d}"] = G
    else:
        p_eff[tgt] = tgt_expr(G)
    if "cooldown" in m:
        p_mem["cd"] = str(L["cooldown_steps"])
    if "resource" in m:
        r = f"min({L['res_max']}, mem.res - {L['res_cost']} + {L['res_regen']})"
        p_mem["res"] = r
        p_eff["gauge"] = f"{r} // {L['gauge_step']}"
    if "threshold" in m:
        e, mm = heat_rules(L["heat_per_use"])
        p_eff.update(e)
        p_mem.update(mm)
    rule("produce", f"'{N['P']}' produces when all gates are open: {E}", action=N["P"], when=E,
         effects={F[k]: v for k, v in p_eff.items()}, mem=p_mem)

    if "uses" in F:
        rule("count_uses", f"'{N['P']}' is counted", action=N["P"], effects={F["uses"]: f"{o['uses']} + 1"})
    if "idle" in F:
        rule("idle", f"'{N['hold']}' extends the idle run", action=N["hold"], effects={F["idle"]: f"{o['idle']} + 1"})
    if "moves" in F:
        rule("moves_hold", f"'{N['hold']}' is not a move", action=N["hold"], effects={F["moves"]: o["moves"]})
    if "last" in F:
        for i, a in enumerate(action_list(L)):
            rule(f"last_{i}", f"{F['last']} records '{a}'", action=a, effects={F["last"]: str(i)})
    if "ordering" in m:
        rule("ordering", f"'{N['A']}' arms '{N['P']}'", action=N["A"], mem={"since": "0"}, kind="precondition")
    if cap:
        after = f"min({L['cap']}, mem.p1)" if d else "0"
        rule("transfer", f"'{N['transfer']}' empties the buffer into the output", action=N["transfer"],
             effects={F["out"]: f"{o['out']} + {o['buf']}", F["buf"]: after})
    if "control" in m:
        nxt = ("3 - args.level" if L["control_mode"] == "inverted"
               else f"{o['set']} + (1 if args.level > {o['set']} else (-1 if args.level < {o['set']} else 0))")
        rule("control", f"'{N['tune']}' changes the setting", action=N["tune"], effects={F["set"]: nxt})
    if "decoy" in N:
        rule("decoy", f"'{N['decoy']}' removes one unit", action=N["decoy"],
             effects={F["out"]: f"max(0, {o['out']} - 1)" + (f" + {land}" if d and not cap else "")})
    return Theory(world_id=world_id, version=1, memory=memory, rules=rules, note="reference theory")


# ---- hidden change ----------------------------------------------------------------------


SHIFT_LABELS = {
    "delay": "Produced output arrives after a different lag",
    "cooldown": "Producer needs a different rest between uses",
    "window": "Producer's working window narrows or widens",
    "capacity": "Buffer holds a different amount",
    "resource": "Hidden reserve refills at a different rate",
    "ordering": "Arming lasts a different number of steps",
    "control": "Level control changes how it responds",
    "threshold": "Overheat limit changes",
}


def mutate(L: JSON, rng: random.Random, kind: str | None = None) -> tuple[str, str]:
    """Change one mechanism parameter in place (`kind` if this system has it). Returns (kind, description)."""
    m = L["mechanisms"]
    pick = rng.choice(m)
    kind = kind if kind in m else pick
    if kind == "delay":
        L["delay_steps"] = L["delay_steps"] + 1 if L["delay_steps"] < 3 else 1
    elif kind == "cooldown":
        L["cooldown_steps"] = L["cooldown_steps"] + 1 if L["cooldown_steps"] < 3 else 1
    elif kind == "window":
        L["window_open"] = L["window_open"] - 1 if L["window_open"] > 1 else 2
    elif kind == "capacity":
        L["cap"] = L["cap"] - L["gain"] if L["cap"] >= 2 * L["gain"] else L["cap"] + 2 * L["gain"]
    elif kind == "resource":
        L["res_regen"] = L["res_regen"] - 1 if L["res_regen"] > 1 else L["res_regen"] + 1
    elif kind == "ordering":
        L["order_within"] = L["order_within"] - 1 if L["order_within"] > 1 else 3
    elif kind == "control":
        L["control_mode"] = "rate_limited" if L["control_mode"] == "inverted" else "inverted"
    else:
        L["heat_limit"] = L["heat_limit"] - 2 if L["heat_limit"] > 2 else L["heat_limit"] + 3
    return kind, SHIFT_LABELS[kind]
