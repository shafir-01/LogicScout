import pytest

from logicscout import config
from logicscout.sandbox import open_session
from logicscout.worlds import gate_service
from logicscout.worlds.base import load_all

WORLDS = ["relay", "rover", "orbit", "plant", "gate"]


@pytest.fixture(scope="module", autouse=True)
def gate_url():
    old = config.GATE_URL
    config.GATE_URL = gate_service.start_in_thread()
    yield
    config.GATE_URL = old


@pytest.mark.parametrize("world_id", WORLDS)
def test_shift_menu_kinds_apply(world_id):
    cls = load_all()[world_id]
    menu = cls.shift_menu()
    assert len(menu) >= 2 and all(m["id"] and m["label"] for m in menu)
    for m in menu:
        w = cls("standard")
        w.reset(cls.manual().lab_seeds[0])
        rec = w.shift(7, m["id"])
        assert rec.kind == m["id"]
        assert rec.after != rec.before or rec.after
    with pytest.raises(ValueError):
        cls("standard").shift(7, "no_such_change")


@pytest.mark.parametrize("world_id", WORLDS)
def test_default_shift_unchanged_and_sandbox_passes_kind(world_id):
    cls = load_all()[world_id]
    a, b = cls("standard"), cls("standard")
    assert a.shift(3).model_dump(exclude={"at_t"}) == b.shift(3, None).model_dump(exclude={"at_t"})
    s = open_session(world_id)
    kind = s.admin.world_class.shift_menu()[-1]["id"]
    assert s.admin.shift(1, kind).kind == kind
