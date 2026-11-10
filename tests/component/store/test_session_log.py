"""The append-only session log: records, fold, damage."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openprogram.state.store.session import session_log
from openprogram.state.store.session.session_log import (
    SessionLog,
    decode_line,
    encode_record,
    fold_records,
    read_log_file,
)


def _node(node_id: str, seq: int, **extra) -> dict:
    return {"id": node_id, "seq": seq, "role": "user", "metadata": {}, **extra}


def test_a_line_round_trips_and_its_checksum_catches_a_changed_byte():
    line = encode_record(7, "node.put", {"payload": {"id": "n", "output": "中文"}})[:-1]
    assert decode_line(line)["data"]["payload"]["output"] == "中文"
    assert decode_line(line.replace("中".encode(), "文".encode())) is None


def test_the_fold_applies_puts_patches_deletes_and_meta(tmp_path: Path):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0))
    log.write_history(1, "user", "b", _node("b", 1, output="old"))
    log.patch_node("b", {"output": "new"}, {"status": "done"})
    log.write_history(2, "user", "c", _node("c", 2))
    log.delete_nodes(["c"])
    log.write_meta({"title": "t", "head_id": "b"})
    log.write_meta({"head_id": "a"})

    nodes = {n["id"]: n for n in SessionLog(tmp_path / "s").list_history()}
    assert set(nodes) == {"a", "b"}
    assert nodes["b"]["output"] == "new" and nodes["b"]["metadata"]["status"] == "done"
    assert SessionLog(tmp_path / "s").read_meta() == {"head_id": "a"}


def test_meta_writes_record_only_what_changed(tmp_path: Path):
    log = SessionLog(tmp_path / "s")
    log.write_meta({"title": "t", "branches": {"x": 1}})
    log.write_meta({"title": "t", "branches": {"x": 1}, "head_id": "n"})
    log.write_meta({"title": "t", "branches": {"x": 1}, "head_id": "n"})

    records = read_log_file(log.main_path)
    assert [r["data"]["set"] for r in records[1:]] == [{"head_id": "n"}]


def test_earlier_versions_stay_in_the_log(tmp_path: Path):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0, output="first"))
    log.patch_node("a", {"output": "second"})
    log.delete_nodes(["a"])

    text = log.main_path.read_text(encoding="utf-8")
    assert "first" in text and "second" in text
    assert log.list_history() == []


def test_a_line_cut_short_is_not_a_record_and_the_next_writer_removes_it(tmp_path: Path):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0))
    with open(log.main_path, "ab") as handle:
        handle.write(b'{"ts":9,"type":"node.put","data":{"payl')

    assert [n["id"] for n in SessionLog(tmp_path / "s").list_history()] == ["a"]

    session_log._prepared_files.clear()
    SessionLog(tmp_path / "s").write_history(1, "user", "b", _node("b", 1))
    assert [r["data"]["payload"]["id"] for r in read_log_file(log.main_path)] == ["a", "b"]


def test_reading_stops_at_a_damaged_line(tmp_path: Path):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0))
    with open(log.main_path, "ab") as handle:
        handle.write(b"garbage\n")
    log.write_history(1, "user", "b", _node("b", 1))

    assert [r["data"]["payload"]["id"] for r in read_log_file(log.main_path)] == ["a"]


def test_a_process_without_the_worker_lock_writes_its_own_file(tmp_path: Path):
    session_log.release_main_writer()
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "code", "child", _node("child", 0))

    assert not log.main_path.exists()
    assert len(list(log.agent_directory.glob("*.jsonl"))) == 1
    assert [n["id"] for n in SessionLog(tmp_path / "s").list_history()] == ["child"]


def test_records_from_two_processes_fold_in_time_order(tmp_path: Path):
    main = SessionLog(tmp_path / "s")
    main.write_history(0, "user", "a", _node("a", 0, output="main"))
    script = (
        "import sys;from openprogram.state.store.session.session_log import SessionLog;"
        "SessionLog(sys.argv[1]).patch_node('a',{'output':'child'})"
    )
    subprocess.run([sys.executable, "-c", script, str(tmp_path / "s")], check=True)

    assert main.stale()
    assert main.list_history()[0]["output"] == "child"
    assert len(list(main.agent_directory.glob("*.jsonl"))) == 1


def test_the_fold_reads_only_what_was_appended(tmp_path: Path, monkeypatch):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0, content="one"))
    assert [node["id"] for node in log.list_history()] == ["a"]
    offsets = []
    original = session_log.read_appended
    monkeypatch.setattr(session_log, "read_appended",
                        lambda path, start=0, **kw: (offsets.append(start), original(path, start, **kw))[1])
    log.write_history(1, "user", "b", _node("b", 1))
    assert [node["id"] for node in log.list_history()] == ["a", "b"]
    assert len(offsets) == 1 and offsets[0] > 0


def test_a_later_patch_leaves_an_earlier_read_alone(tmp_path: Path):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0, content="one"))
    before = log.list_history()
    log.patch_node("a", {"content": "two"})
    assert before[0]["content"] == "one"
    assert log.list_history()[0]["content"] == "two"


def test_a_line_that_sorts_early_folds_in_time_order(tmp_path: Path, monkeypatch):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0, content="old"))
    log.list_history()
    agents = log.agent_directory
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "other.jsonl").write_bytes(encode_record(1, "node.patch", {"id": "a", "set": {"content": "earliest"}}))
    # The record is older than the put already applied, so the put still wins.
    assert log.list_history()[0]["content"] == "old"


def test_a_replaced_file_is_read_again_from_the_start(tmp_path: Path):
    log = SessionLog(tmp_path / "s")
    log.write_history(0, "user", "a", _node("a", 0))
    log.list_history()
    log.main_path.write_bytes(encode_record(5, "node.put", {"payload": _node("z", 0)}))
    assert [node["id"] for node in log.list_history()] == ["z"]


def test_state_documents_live_in_the_log_with_their_history(tmp_path: Path):
    from openprogram.state.store.session.session_store.service import SessionStore

    store = SessionStore(tmp_path)
    store._open("s", create_if_missing=True)[0]._ensure_init()
    todos = store.state_file("s", "todos.json")
    assert not todos.exists()
    with pytest.raises(FileNotFoundError):
        todos.read_text()
    todos.write_text('{"v": 1}')
    todos.write_text('{"v": 2}')
    assert store.state_file("s", "todos.json").read_text() == '{"v": 2}'
    assert not (store._session_dir("s") / "todos.json").exists()
    session = store._session_dir("s")
    versions = [record["data"]["content"]
                for path in (session / "main.jsonl", *(session / "agents").glob("*.jsonl"))
                for record in read_log_file(path) if record["type"] == "file.put"]
    assert versions == ['{"v": 1}', '{"v": 2}']
    assert store.state_file("s", "todos.json").with_suffix(".lock").parent == store._session_dir("s")


def test_one_append_picks_its_file_once_when_the_writer_role_changes(tmp_path, monkeypatch):
    from itertools import cycle

    answers = cycle([True, False])
    monkeypatch.setattr(session_log, "is_main_writer", lambda: next(answers))
    log = session_log.SessionLog(tmp_path / "session")

    log.append_state_file("first.json", "1")
    log.append_state_file("second.json", "2")

    assert log.main_path.exists()
    assert list(log.agent_directory.glob("*.jsonl"))
