"""The run tables keep SQL's guarantees without a database."""
from __future__ import annotations

import pytest

from openprogram.runtime.execution.store.run_tables import RowConflict, RunLogFiles, RunTables


def _tables(tmp_path):
    return RunTables(RunLogFiles(tmp_path / "runs"))


def _execution(execution_id, session_id="s1", status="queued", updated_at=1.0):
    return {
        "execution_id": execution_id, "run_id": "r1", "session_id": session_id, "revision_id": "rev",
        "status": status, "status_version": 1, "capabilities_json": "{}", "created_at": 1.0, "updated_at": updated_at,
    }


def _insert_all(handle, *ids):
    from openprogram.runtime.execution._schema import TABLES

    for execution_id in ids:
        row = _execution(execution_id)
        handle.insert("executions", {
            **{column: "x" for column in TABLES["executions"].required if column not in row},
            **{name: value for name, value in row.items() if name in TABLES["executions"].columns},
        })


def test_a_failed_transaction_leaves_nothing_behind(tmp_path):
    tables = _tables(tmp_path)
    with pytest.raises(ValueError):
        with tables.transaction() as handle:
            _insert_all(handle, "e1")
            raise ValueError("stop")
    assert tables.handle.count("executions") == 0
    assert list(tables.log.read("s1")) == []


def test_a_change_is_undone_with_its_lookups_and_unique_rules(tmp_path):
    tables = _tables(tmp_path)
    with tables.transaction() as handle:
        handle.insert("attempts", {
            "attempt_id": "a1", "execution_id": "e1", "generation": 1, "status": "leased",
            "owner_id": "o", "leased_at": 1.0, "updated_at": 1.0,
        })
    with pytest.raises(ValueError):
        with tables.transaction() as handle:
            handle.update("attempts", {"execution_id": "e2", "generation": 7}, attempt_id="a1")
            handle.delete("attempts", attempt_id="a1")
            raise ValueError("stop")
    assert tables.handle.rows("attempts", execution_id="e2") == []
    assert tables.handle.get("attempts", "a1")["generation"] == 1
    with tables.transaction() as handle, pytest.raises(RowConflict):
        handle.insert("attempts", {
            "attempt_id": "a2", "execution_id": "e1", "generation": 1, "status": "leased",
            "owner_id": "o", "leased_at": 1.0, "updated_at": 1.0,
        })


def test_rows_come_back_from_the_log_and_removed_rows_stay_gone(tmp_path):
    tables = _tables(tmp_path)
    with tables.transaction() as handle:
        _insert_all(handle, "e1", "e2")
    with tables.transaction() as handle:
        handle.update("executions", {"status": "running"}, execution_id="e1")
        handle.delete("executions", execution_id="e2")
    again = _tables(tmp_path)
    again.ensure_session("s1")
    assert [row["status"] for row in again.handle.rows("executions")] == ["running"]


def test_a_write_outside_a_transaction_is_refused_and_returned_rows_are_copies(tmp_path):
    tables = _tables(tmp_path)
    with pytest.raises(RuntimeError):
        tables.handle.delete("executions", execution_id="e1")
    with tables.transaction() as handle:
        _insert_all(handle, "e1")
    row = tables.handle.get("executions", "e1")
    row["status"] = "changed"
    assert tables.handle.get("executions", "e1")["status"] == "queued"


def test_order_limit_and_any_of(tmp_path):
    tables = _tables(tmp_path)
    with tables.transaction() as handle:
        _insert_all(handle, "e1", "e2", "e3")
        handle.update("executions", {"updated_at": lambda row: {"e1": 3.0, "e2": 1.0, "e3": 2.0}[row["execution_id"]]})
    found = tables.handle.rows("executions", execution_id=["e1", "e2"], order="-updated_at", limit=1)
    assert [row["execution_id"] for row in found] == ["e1"]


def test_job_tables_are_the_profiles_run_tables(tmp_path, monkeypatch):
    from openprogram.runtime.execution.store.store import ExecutionStore
    from openprogram.runtime.jobs.resource_governance.tables import _tables_beside
    from openprogram.state import paths

    run_state = tmp_path / "run-state"
    monkeypatch.setattr(paths, "get_run_state_path", lambda: run_state)

    assert _tables_beside(tmp_path / "usage.db") is ExecutionStore(run_state).tables
