"""The pointer's format and atomic write procedure."""
import os
import time

import pytest

from openprogram.operations.self_update.versions import pointer as pointers
from openprogram.operations.self_update.versions.layout import Layout

BASE = "py3.12-9f2c41aa77d04c11"
DOCUMENTED = f"""schema=1
generation=17
version=20261108T153012Z-3b08fd06e123
base={BASE}
last_good=20261101T101500Z-aa11bb22cc33
last_good_base={BASE}
previous_good=20261020T091100Z-77ee11aa22bb
previous_good_base={BASE}
probation=u_7f3a9c
probation_deadline=1794134010
writer=controller
"""


@pytest.fixture
def layout(tmp_path):
    return Layout(tmp_path)


def _seed(layout, **changes):
    fields = {"generation": 1, "version": "v1", "base": BASE, "writer": "test", **changes}
    return pointers.create(layout, pointers.Pointer(**fields))


def test_the_documented_format_round_trips():
    parsed = pointers.parse(DOCUMENTED)
    assert parsed.generation == 17 and parsed.probation_deadline == 1794134010
    assert pointers.render(parsed) == DOCUMENTED


def test_unknown_lines_are_kept():
    parsed = pointers.parse(DOCUMENTED + "future=1\n")
    assert pointers.render(parsed).endswith("future=1\n")


@pytest.mark.parametrize("text", [
    "", "schema=2\ngeneration=1\nversion=v\nbase=b\n", "schema=1\ngeneration=x\nversion=v\nbase=b\n",
    "schema=1\ngeneration=1\nversion=../v\nbase=b\n", "schema=1\ngeneration=1\nversion=v\n",
    "schema=1\nschema=1\ngeneration=1\nversion=v\nbase=b\n", "not a pointer\n",
    "schema=1\ngeneration=1\nversion=v\nbase=b\nnote=é\n",
])
def test_malformed_pointers_are_refused(text):
    with pytest.raises(pointers.PointerError):
        pointers.parse(text)


def test_compare_and_set_advances_and_keeps_the_previous(layout):
    _seed(layout)
    following = pointers.compare_and_set(layout, 1, writer="controller", version="v2")
    assert following.generation == 2
    assert pointers.read(layout).version == "v2"
    assert pointers.parse(layout.previous_pointer.read_text()).version == "v1"
    assert sorted(path.name for path in layout.root.iterdir()) == ["current", "current.prev"]


def test_a_stale_generation_changes_nothing(layout):
    _seed(layout)
    pointers.compare_and_set(layout, 1, writer="a", version="v2")
    with pytest.raises(pointers.PointerConflict):
        pointers.compare_and_set(layout, 1, writer="b", version="v3")
    assert pointers.read(layout).version == "v2"


def test_an_invalid_id_never_reaches_the_file(layout):
    _seed(layout)
    with pytest.raises(pointers.PointerError):
        pointers.compare_and_set(layout, 1, writer="a", version="../evil")
    assert pointers.read(layout).version == "v1"


def test_a_stale_lock_is_broken_and_a_fresh_one_is_not(layout, monkeypatch):
    _seed(layout)
    layout.lock.write_text("")
    old = time.time() - pointers.LOCK_BREAK_SECONDS - 1
    os.utime(layout.lock, (old, old))
    pointers.compare_and_set(layout, 1, writer="a", version="v2")
    assert not layout.lock.exists()
    layout.lock.write_text("")
    monkeypatch.setattr(pointers, "LOCK_WAIT_SECONDS", 0.05)
    original = pointers._acquire
    monkeypatch.setattr(pointers, "_acquire", lambda current: original(current, wait=0.05))
    with pytest.raises(pointers.PointerConflict):
        pointers.compare_and_set(layout, 2, writer="a", version="v3")


def test_commit_shifts_the_good_pairs(layout):
    _seed(layout, version="v3", last_good="v2", last_good_base=BASE, previous_good="v1",
          previous_good_base=BASE, probation="u1", probation_deadline=99)
    after = pointers.commit(layout, 1)
    assert (after.last_good, after.previous_good) == ("v3", "v2")
    assert after.probation == "" and after.probation_deadline is None


def test_a_good_pointer_falls_back_to_last_good_and_last_good_to_previous():
    candidate = pointers.Pointer(1, "v3", BASE, "v2", BASE, "v1", BASE)
    assert candidate.fallback() == ("v2", BASE)
    assert pointers.Pointer(1, "v2", BASE, "v2", BASE, "v1", BASE).fallback() == ("v1", BASE)
    assert pointers.Pointer(1, "v2", BASE, "v2", BASE).fallback() is None


def test_a_damaged_pointer_is_recovered_from_the_previous_one(layout):
    _seed(layout)
    pointers.compare_and_set(layout, 1, writer="a", version="v2")
    layout.pointer.write_text("garbage")
    assert pointers.read_or_recover(layout).version == "v1"


def test_rollback_moves_to_last_good(layout):
    _seed(layout, version="v2", last_good="v1", last_good_base=BASE, probation="u1", probation_deadline=9)
    assert pointers.rollback(layout, "v2", deadline=time.time() + 1) == "moved"
    after = pointers.read(layout)
    assert after.version == "v1" and after.probation == ""


def test_rollback_after_the_guard_already_moved_is_done(layout):
    _seed(layout, version="v1")
    assert pointers.rollback(layout, "v2", deadline=time.time() + 1) == "already"


def test_a_rollback_that_cannot_write_is_journaled(layout, monkeypatch):
    _seed(layout, version="v2", last_good="v1", last_good_base=BASE)
    def refuse(*_args, **_kwargs):
        raise pointers.PointerConflict("busy")
    monkeypatch.setattr(pointers, "compare_and_set", refuse)
    assert pointers.rollback(layout, "v2", deadline=0, sleep=lambda _: None) == "pending"
    assert layout.pending_rollback.read_text() == "version=v2\n"


def test_a_commit_leaves_no_probation_for_a_repair_to_bring_back(tmp_path):
    layout = Layout(tmp_path / "runtime")
    layout.root.mkdir()
    pointers.create(layout, pointers.Pointer(generation=1, version="old", base=BASE, last_good="old", last_good_base=BASE))
    pointers.activate(layout, 1, version="new", base=BASE, update_id="su_1", deadline=1)
    committed = pointers.commit(layout, 2)

    layout.pointer.write_text("not a pointer")
    repaired = pointers.read_or_recover(layout)

    assert repaired.version == "new" and repaired.probation == "" and repaired.probation_deadline is None
    assert repaired.last_good == committed.last_good == "new" and repaired.previous_good == "old"
