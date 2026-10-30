import pytest

from logicscout.dsl import DSL_GUIDE, DSLError, evaluate, validate

ENV = {"obs": {"level": 10, "mode": "open", "items": [1, 2, 3]}, "args": {"rate": 3}, "mem": {"n": 2}, "t": 4}


@pytest.mark.parametrize("expr", [
    "__import__('os')", "obs.__class__", "obs.keys()", "(lambda x: x)(1)", "[x for x in obs.items]",
    "open('f')", "exec('1')", "x", "obs.level = 3", "{1: 2}", "min", "obs.items[0:2]", "max(*obs.items)",
    "f'{obs.level}'", "b'x'", "",
])
def test_rejects_unsafe(expr):
    assert validate(expr)
    with pytest.raises(DSLError):
        evaluate(expr, ENV)


@pytest.mark.parametrize("expr,want", [
    ("obs.level + args.rate * 2", 16),
    ("obs['level'] // 3", 3),
    ("-obs.level % 3", 2),
    ("2 ** 10", 1024),
    ("1 < obs.level <= 10", True),
    ("obs.mode == 'open' and mem.n > 1", True),
    ("not obs.mode in ['closed']", True),
    ("2 in obs.items", True),
    ("'a' if t > 3 else 'b'", "a"),
    ("clamp(obs.level + 50, 0, 20)", 20),
    ("min(obs.level, 4) + max(1, 2) + abs(-1) + len(obs.items)", 10),
    ("round(sqrt(2), 2)", 1.41),
    ("floor(2.7) + ceil(2.1)", 5),
    ("int('7') + float(1) + bool(1)", 9.0),
    ("obs.items[1]", 2),
    ("(1, 2)", (1, 2)),
])
def test_semantics(expr, want):
    assert validate(expr) == []
    assert evaluate(expr, ENV) == want


@pytest.mark.parametrize("expr", [
    "obs.missing", "obs.missing + 1", "obs.level / 0", "obs.level // 0", "mem.n.x", "obs.items[9]",
    "2 ** 1000", "'x' * 100000", "obs.missing > 3", "sqrt(-1)", "args.nope.deeper[0]",
])
def test_runtime_problems_are_none(expr):
    assert evaluate(expr, ENV) is None


def test_none_comparisons_and_bool():
    assert evaluate("obs.missing == None", ENV) is True
    assert evaluate("not obs.missing", ENV) is True
    assert evaluate("obs.missing or 5", ENV) == 5


def test_guide_compact():
    assert len(DSL_GUIDE.splitlines()) <= 40
    assert "delay" in DSL_GUIDE and '"*"' in DSL_GUIDE
