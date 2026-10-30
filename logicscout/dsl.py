"""LogicScout DSL: a small, safe expression language for rules and playbooks.

Parsed with `ast` and evaluated by walking a whitelist of node types. No eval/exec, no attribute
calls, no dunder access. Runtime problems (missing field, bad types, division by zero) yield None
instead of raising, so partial theories never crash the predictor. Invalid expressions raise DSLError.
"""
from __future__ import annotations

import ast
import math
import operator
from functools import lru_cache
from typing import Any

ROOTS = frozenset({"obs", "args", "mem", "t"})
MAX_EXPONENT = 64
MAX_SEQ = 10_000
MAX_LEN = 2_000


class DSLError(ValueError):
    pass


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


FUNCS: dict[str, Any] = {
    "min": min, "max": max, "abs": abs, "round": round, "len": len,
    "int": int, "float": float, "bool": bool,
    "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil, "clamp": _clamp,
}

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_CMPOPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_, ast.IsNot: operator.is_not,
}
_ALLOWED = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.BinOp, ast.UnaryOp, ast.USub, ast.UAdd, ast.Not,
    ast.Compare, ast.IfExp, ast.Call, ast.Constant, ast.Name, ast.Attribute, ast.Subscript,
    ast.List, ast.Tuple, ast.Load, *_BINOPS, *_CMPOPS,
)


def _check(tree: ast.AST) -> list[str]:
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            errors.append(f"disallowed syntax: {type(node).__name__}")
            continue
        if isinstance(node, ast.Constant) and not (
            node.value is None or isinstance(node.value, (bool, int, float, str))
        ):
            errors.append(f"disallowed literal: {node.value!r}")
        elif isinstance(node, ast.Name) and node.id not in ROOTS and node.id not in FUNCS:
            errors.append(f"unknown name: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            errors.append(f"disallowed attribute: {node.attr}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                errors.append("only plain function calls are allowed (no method calls)")
            elif node.func.id not in FUNCS:
                errors.append(f"unknown function: {node.func.id}")
            if node.keywords:
                errors.append("keyword arguments are not allowed")
            if any(isinstance(a, ast.Starred) for a in node.args):
                errors.append("star arguments are not allowed")
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            errors.append("slices are not allowed")
    # function names used as values (e.g. `min` alone) are not allowed
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FUNCS:
            if not _is_call_target(tree, node):
                errors.append(f"function used as a value: {node.id}")
    return list(dict.fromkeys(errors))


def _is_call_target(tree: ast.AST, name: ast.Name) -> bool:
    return any(isinstance(n, ast.Call) and n.func is name for n in ast.walk(tree))


@lru_cache(maxsize=4096)
def _parse(expr: str) -> tuple[ast.Expression | None, tuple[str, ...]]:
    if not isinstance(expr, str):
        return None, (f"expression must be a string, got {type(expr).__name__}",)
    if len(expr) > MAX_LEN:
        return None, (f"expression longer than {MAX_LEN} characters",)
    if not expr.strip():
        return None, ("empty expression",)
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        return None, (f"syntax error: {e.msg}",)
    errors = _check(tree)
    return (None if errors else tree), tuple(errors)


def validate(expr: str) -> list[str]:
    """Return a list of problems with `expr` (empty list = valid)."""
    return list(_parse(expr)[1])


def evaluate(expr: str, env: dict) -> Any:
    """Evaluate `expr` on env roots obs/args/mem (dicts) and t. Raises DSLError if invalid."""
    tree, errors = _parse(expr)
    if tree is None:
        raise DSLError("; ".join(errors))
    try:
        return _eval(tree.body, env)
    except (TypeError, ValueError, ArithmeticError, IndexError, KeyError, RecursionError):
        return None


def safe_evaluate(expr: str, env: dict) -> Any:
    """Like evaluate, but an invalid expression also yields None."""
    try:
        return evaluate(expr, env)
    except DSLError:
        return None


def _get(container: Any, key: Any) -> Any:
    if isinstance(container, dict):
        return container.get(key)
    if isinstance(container, (list, tuple, str)) and isinstance(key, int) and not isinstance(key, bool):
        return container[key] if -len(container) <= key < len(container) else None
    return None


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _binop(op: ast.operator, a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    if isinstance(op, ast.Pow):
        if not (_num(a) or isinstance(a, bool)) or not (_num(b) or isinstance(b, bool)):
            return None
        if abs(b) > MAX_EXPONENT or (abs(a) > 1e6 and b > 8):
            return None
        r = a ** b
        return None if isinstance(r, complex) else r
    if isinstance(op, ast.Mult) and (isinstance(a, (str, list, tuple)) or isinstance(b, (str, list, tuple))):
        seq, n = (a, b) if isinstance(a, (str, list, tuple)) else (b, a)
        if not isinstance(n, int) or len(seq) * max(n, 0) > MAX_SEQ:
            return None
    return _BINOPS[type(op)](a, b)


def _call(name: str, args: list[Any]) -> Any:
    if any(a is None for a in args) and name != "bool":
        return None
    if name in ("min", "max") and len(args) == 1 and not isinstance(args[0], (list, tuple)):
        return args[0]
    if name == "clamp" and len(args) != 3:
        return None
    return FUNCS[name](*args)


def _eval(node: ast.AST, env: dict) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.Attribute):
        return _get(_eval(node.value, env), node.attr)
    if isinstance(node, ast.Subscript):
        return _get(_eval(node.value, env), _eval(node.slice, env))
    if isinstance(node, ast.List):
        return [_eval(e, env) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, env) for e in node.elts)
    if isinstance(node, ast.BinOp):
        return _binop(node.op, _eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not v
        if v is None:
            return None
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        v = None
        for e in node.values:
            v = _eval(e, env)
            if (not v) if is_and else v:
                return v
        return v
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env)
            if not isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)) and (left is None or right is None):
                return None
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        return _call(node.func.id, [_eval(a, env) for a in node.args])
    raise DSLError(f"disallowed syntax: {type(node).__name__}")


DSL_GUIDE = """\
LogicScout DSL (Python-like expressions, nothing else)
Roots: obs.<field> (current observation), args.<name> (action arguments), mem.<var> (latent memory
the theory posits), t (current step). obs["field"] also works. A missing field evaluates to None.
Allowed: numbers, strings, True/False/None, lists; + - * / // % **; comparisons (chains ok), in,
not in; and/or/not; `a if cond else b`; functions min max abs round len int float bool sqrt floor
ceil clamp(x, lo, hi). No assignments, lambdas, comprehensions, imports or method calls.
Division by zero gives None.

A Rule = {action, when, effects, memory, delay}:
- action: the action name it applies to, or "*" for every step.
- when: condition evaluated on the state BEFORE the step (obs, args, mem, t).
- effects: {obs field: expr} giving the field's NEXT value, computed from the BEFORE state.
- memory: {mem var: expr} giving the latent variable's next value (also from the BEFORE state).
- delay: effects land d steps later instead of on the next observation (0 = next step).
Fields no rule mentions keep their value. Rules apply in list order; a later rule overrides an
earlier rule's effect on the same field.

Examples
1. Pumping raises the level by the rate, capped at 100:
   {"action": "pump", "when": "True", "effects": {"level": "min(obs.level + args.rate, 100)"}}
2. Everything leaks 2 units per step when the valve is open:
   {"action": "*", "when": "obs.valve == 'open'", "effects": {"level": "max(obs.level - 2, 0)"}}
3. The door opens 2 steps after the open command (values are computed when the action happens):
   {"action": "open", "when": "obs.door == 'closed'", "delay": 2, "effects": {"door": "'open'"}}
4. A hidden counter of presses; the door opens on the third press:
   {"action": "press", "when": "True", "memory": {"presses": "mem.presses + 1"},
    "effects": {"door": "'open' if mem.presses + 1 >= 3 else obs.door"}}
"""
