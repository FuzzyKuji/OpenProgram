"""Stored entrypoints follow the runtime modules to where they are now.

Execution inputs, revision manifests and projections written before the
runtime packages were grouped name ``openprogram.agent...``, and those written
before ``openprogram.runtime.agent`` was split by concept name its old
submodules; the owner's open renames them, and reopening leaves renamed rows
alone.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from openprogram.operations.worker.lock import WorkerLock
from openprogram.runtime.execution._schema import SCHEMA_VERSION
from openprogram.runtime.execution.model import CapabilitySet
from openprogram.runtime.execution.store import ExecutionStore, ExecutionStoreError

OLD = "openprogram.agent.production_driver:AgentProductionDriver"
# Before openprogram.runtime.agent was split by concept.
SPLIT_OLD = "openprogram.runtime.agent.production_driver:AgentProductionDriver"
NEW = "openprogram.runtime.conversation.production_driver:AgentProductionDriver"


def _old_store(path):
    executions = ExecutionStore(path)
    revision = executions.create_revision(manifest={"entrypoint": OLD, "turn_input_schema": 1})
    executions.create_execution(
        execution_id="exec", run_id="run", session_id="session",
        revision_id=revision.revision_id, capabilities=CapabilitySet(),
    )
    with closing(sqlite3.connect(path)) as connection:
        sequence = connection.execute(
            "SELECT max(sequence) FROM execution_events WHERE execution_id = 'exec'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO execution_inputs (execution_id, input_ref, input_hash, entrypoint, "
            "session_id, trusted_actor_json, config_snapshot_ref, created_at) "
            "VALUES ('exec', 'ref', 'hash', ?, 'session', '{}', 'config', 0)",
            (OLD,),
        )
        payload = {
            "input": {"entrypoint": OLD},
            "ui": {"label": OLD},
            "note": "prose naming openprogram.agent.production_driver stays",
        }
        connection.execute(
            "INSERT INTO execution_projection_current (projection_kind, execution_id, "
            "event_sequence, session_id, status, payload_json, updated_at) "
            "VALUES ('ui', 'exec', ?, 'session', 'pending', ?, 0)",
            (sequence, json.dumps(payload)),
        )
        connection.execute("PRAGMA user_version = 16")
        connection.commit()
    return revision


def test_opening_an_older_store_renames_its_entrypoints(tmp_path):
    path = tmp_path / "executions.db"
    revision = _old_store(path)

    executions = ExecutionStore(path)

    assert executions.get_execution_input("exec").entrypoint == NEW
    migrated = executions.get_revision(revision.revision_id)
    assert migrated.manifest == {"entrypoint": NEW, "turn_input_schema": 1}
    assert migrated.content_hash == revision.content_hash
    # The driver's current manifest reuses the renamed revision.
    reused = executions.create_revision(manifest={"entrypoint": NEW, "turn_input_schema": 1})
    assert reused.revision_id == revision.revision_id
    with closing(sqlite3.connect(path)) as connection:
        payload = json.loads(connection.execute(
            "SELECT payload_json FROM execution_projection_current WHERE execution_id = 'exec'"
        ).fetchone()[0])
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert payload["input"]["entrypoint"] == NEW
    assert payload["ui"]["label"] == NEW
    assert payload["note"] == "prose naming openprogram.agent.production_driver stays"
    assert version == SCHEMA_VERSION


def test_reopening_a_migrated_store_changes_nothing(tmp_path):
    path = tmp_path / "executions.db"
    _old_store(path)
    ExecutionStore(path)
    with closing(sqlite3.connect(path)) as connection:
        before = connection.execute("SELECT * FROM execution_projection_current").fetchall()

    ExecutionStore(path)

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT entrypoint FROM execution_inputs").fetchall() == [(NEW,)]
        assert connection.execute("SELECT * FROM execution_projection_current").fetchall() == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


# Only the profile's worker migrates its store. A store beside a
# ``worker.lock`` belongs to that profile's worker: another process opening
# it with newer code leaves the schema alone, and the worker's own open
# heals rows an older process wrote after the version moved on.


def _hold_worker_lock(directory):
    lock = WorkerLock()
    lock.path = directory / "worker.lock"
    assert lock.try_acquire()
    return lock


def _user_version(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


def test_a_process_without_the_worker_lock_does_not_migrate(tmp_path):
    path = tmp_path / "executions.db"
    _old_store(path)
    (tmp_path / "worker.lock").write_text("", encoding="utf-8")

    with pytest.raises(ExecutionStoreError) as raised:
        ExecutionStore(path)

    assert raised.value.code == "schema_migration_refused"
    assert f"from schema 16 to {SCHEMA_VERSION}" in str(raised.value)
    assert "openprogram worker restart" in str(raised.value)
    assert _user_version(path) == 16
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT entrypoint FROM execution_inputs").fetchall() == [(OLD,)]


def test_another_process_does_not_migrate_while_the_worker_holds_the_lock(tmp_path):
    path = tmp_path / "executions.db"
    _old_store(path)
    lock = _hold_worker_lock(tmp_path)
    try:
        result = subprocess.run(
            [sys.executable, "-c", (
                "import sys\n"
                "from openprogram.runtime.execution.store import ExecutionStore, ExecutionStoreError\n"
                "try:\n"
                "    ExecutionStore(sys.argv[1])\n"
                "except ExecutionStoreError as exc:\n"
                "    print(exc.code)\n"
            ), str(path)],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        lock.release()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "schema_migration_refused"
    assert "will not migrate" in result.stderr
    assert _user_version(path) == 16


def test_the_worker_migrates_and_heals_rows_written_late_by_an_older_process(tmp_path):
    path = tmp_path / "executions.db"
    revision = _old_store(path)
    lock = _hold_worker_lock(tmp_path)
    try:
        executions = ExecutionStore(path)
        assert _user_version(path) == SCHEMA_VERSION
        assert executions.get_execution_input("exec").entrypoint == NEW

        # An older worker still running keeps writing old names after the
        # upgrade; the version is already current.
        for execution_id in ("late", "late-split"):
            executions.create_execution(
                execution_id=execution_id, run_id=f"{execution_id}-run", session_id="session",
                revision_id=revision.revision_id, capabilities=CapabilitySet(),
            )
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "INSERT INTO execution_inputs (execution_id, input_ref, input_hash, entrypoint, "
                "session_id, trusted_actor_json, config_snapshot_ref, created_at) "
                "VALUES ('late', 'ref', 'hash', ?, 'session', '{}', 'config', 0)",
                (OLD,),
            )
            connection.execute(
                "INSERT INTO execution_inputs (execution_id, input_ref, input_hash, entrypoint, "
                "session_id, trusted_actor_json, config_snapshot_ref, created_at) "
                "VALUES ('late-split', 'ref', 'hash', ?, 'session', '{}', 'config', 0)",
                (SPLIT_OLD,),
            )
            connection.execute(
                "UPDATE revisions SET manifest_json = ? WHERE revision_id = ?",
                (json.dumps({"entrypoint": OLD, "turn_input_schema": 1}), revision.revision_id),
            )
            connection.commit()

        reopened = ExecutionStore(path)
    finally:
        lock.release()

    assert _user_version(path) == SCHEMA_VERSION
    assert reopened.get_execution_input("late").entrypoint == NEW
    assert reopened.get_execution_input("late-split").entrypoint == NEW
    assert reopened.get_revision(revision.revision_id).manifest["entrypoint"] == NEW


def test_a_store_written_before_the_agent_package_split_names_the_new_modules(tmp_path):
    path = tmp_path / "executions.db"
    executions = ExecutionStore(path)
    revision = executions.create_revision(manifest={"entrypoint": NEW, "turn_input_schema": 1})
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE revisions SET manifest_json = ? WHERE revision_id = ?",
            (json.dumps({"entrypoint": SPLIT_OLD, "turn_input_schema": 1}), revision.revision_id),
        )
        connection.execute("PRAGMA user_version = 17")
        connection.commit()

    reopened = ExecutionStore(path)

    assert reopened.get_revision(revision.revision_id).manifest["entrypoint"] == NEW
    assert _user_version(path) == SCHEMA_VERSION


def test_no_current_module_starts_with_a_renamed_path():
    """Renaming stays unambiguous: an old path never names a module that exists now.

    Otherwise the rename on every open would move a current, valid name.
    """
    from pathlib import Path

    from openprogram.runtime.execution._schema import (
        _RUNTIME_ENTRYPOINT_PREFIXES,
        _STALE_ENTRYPOINT,
        _rename_stored_modules,
    )

    root = Path(__file__).resolve().parents[3]
    modules = {
        ".".join(path.relative_to(root).with_suffix("").parts).removesuffix(".__init__")
        for path in (root / "openprogram").rglob("*.py")
        if "__pycache__" not in path.parts
    }
    for old, new in _RUNTIME_ENTRYPOINT_PREFIXES:
        clashes = sorted(m for m in modules if m == old or m.startswith(old + "."))
        assert clashes == [], (old, clashes)
        # Where the rename ends: a current module, or a former package
        # whose submodules are renamed one by one.
        final = _rename_stored_modules(old + ":name", _STALE_ENTRYPOINT, "").removesuffix(":name")
        renamed_further = any(other.startswith(final + ".") for other, _ in _RUNTIME_ENTRYPOINT_PREFIXES)
        assert final in modules or renamed_further, (old, final)


@pytest.mark.parametrize(("stored", "current"), [
    ("openprogram.agent.chat:ChatAgent", "openprogram.runtime.conversation.chat:ChatAgent"),
    ("openprogram.runtime.agent.agent:Agent", "openprogram.runtime.agent.loop.driver:Agent"),
    ("openprogram.runtime.agent.job.runner.service:run", "openprogram.runtime.jobs.runner.service:run"),
    ("openprogram.runtime.agentic_programming.continuation:step", "openprogram.runtime.agent.durable_steps:step"),
    ("openprogram.agentic_programming.agent:agent", "openprogram.runtime.agent.agent_function:agent"),
    ("openprogram.runtime.agent.loop.driver:LoopDriver", "openprogram.runtime.agent.loop.driver:LoopDriver"),
])
def test_a_stored_module_path_reaches_its_current_module(stored, current):
    from openprogram.runtime.execution._schema import _STALE_ENTRYPOINT, _rename_stored_modules

    assert _rename_stored_modules(stored, _STALE_ENTRYPOINT, "") == current


# The healing scan reads every projection row, so an owner runs it once per
# code revision on a store already at the current schema; a schema bump
# always runs it.


@pytest.fixture
def scans(monkeypatch):
    from openprogram.runtime.execution import _schema
    from openprogram.runtime.execution.store import ownership

    calls = []
    original = _schema._normalise_stored_rows

    def counted(connection):
        calls.append(1)
        original(connection)

    monkeypatch.setattr(_schema, "_normalise_stored_rows", counted)
    revision = {"value": "a" * 40}
    monkeypatch.setattr(ownership, "code_revision", lambda: revision["value"])
    return calls, revision


def test_a_second_owner_open_on_the_same_revision_does_not_scan(tmp_path, scans):
    calls, _ = scans
    path = tmp_path / "executions.db"
    ExecutionStore(path)  # a new store has nothing to heal
    assert calls == []

    ExecutionStore(path)
    assert len(calls) == 1
    ExecutionStore(path)
    ExecutionStore(path)
    assert len(calls) == 1


def test_a_changed_revision_scans_again(tmp_path, scans):
    calls, revision = scans
    path = tmp_path / "executions.db"
    ExecutionStore(path)
    ExecutionStore(path)
    assert len(calls) == 1

    revision["value"] = "b" * 40
    ExecutionStore(path)
    ExecutionStore(path)
    assert len(calls) == 2


def test_a_schema_bump_scans_whatever_revision_is_recorded(tmp_path, scans):
    calls, _ = scans
    path = tmp_path / "executions.db"
    ExecutionStore(path)
    ExecutionStore(path)
    assert len(calls) == 1
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
        connection.commit()

    ExecutionStore(path)

    assert len(calls) == 2
    assert _user_version(path) == SCHEMA_VERSION


def test_an_unknown_revision_scans_every_owner_open(tmp_path, scans, monkeypatch):
    from openprogram.runtime.execution.store import ownership

    calls, _ = scans
    monkeypatch.setattr(ownership, "code_revision", lambda: None)
    path = tmp_path / "executions.db"
    ExecutionStore(path)
    ExecutionStore(path)
    ExecutionStore(path)
    assert len(calls) == 2


def test_a_process_that_may_not_migrate_never_scans(tmp_path, scans):
    calls, _ = scans
    path = tmp_path / "executions.db"
    ExecutionStore(path)
    (tmp_path / "worker.lock").write_text("", encoding="utf-8")

    ExecutionStore(path)

    assert calls == []
