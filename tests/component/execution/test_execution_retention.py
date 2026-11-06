"""A finished execution sheds its effects' replay payloads and unreferenced state."""
from __future__ import annotations

import pytest

from openprogram.runtime.execution import AttemptStore, ExecutionStore, RuntimeControlService
from openprogram.runtime.execution.driver import DriverRegistry
from openprogram.runtime.execution.effects import EffectClassification, EffectStore
from openprogram.runtime.execution.model import CapabilitySet, ExecutionStatus
from openprogram.runtime.execution import retention


def _execution(store: ExecutionStore, execution_id: str):
    revision = store.create_revision(
        revision_id=f"revision-{execution_id}",
        manifest={"entrypoint": "agent", "execution_id": execution_id},
    )
    execution = store.create_execution(
        execution_id=execution_id,
        run_id=f"run-{execution_id}",
        session_id=f"session-{execution_id}",
        revision_id=revision.revision_id,
        capabilities=CapabilitySet(
            pause=True, step=True,
            safe_point_kinds=("agent.provider.decision.after",),
            state_schema_version=1,
        ),
    )
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(
        execution.execution_id, expected_version=execution.status_version,
        owner_id="retention-owner", ttl_seconds=30,
    )
    active, running = attempts.activate(
        leased.attempt_id, generation=leased.generation,
        expected_execution_version=reserved.status_version,
    )
    return attempts, active, running


def _register(store, running, active, *, effect_id, kind, payload):
    return EffectStore(store).register(
        effect_id=effect_id, execution_id=running.execution_id,
        attempt_id=active.attempt_id, action_id=f"action-{effect_id}",
        classification=EffectClassification.NONREPEATABLE,
        idempotency_key=None,
        metadata={"kind": kind, "payload": payload},
    )


def _finish(store, attempts, active, running, target=ExecutionStatus.COMPLETED):
    control = RuntimeControlService(store, attempts, DriverRegistry())
    return control.finish_attempt(
        attempt_id=active.attempt_id, generation=active.generation,
        expected_execution_version=running.status_version,
        target=target, outcome=target.value,
    )


@pytest.fixture
def inline_compaction(monkeypatch):
    monkeypatch.setattr(retention, "defer", lambda _name, run: run())


def test_a_finished_execution_keeps_its_effects_identity_without_the_replay_payload(
    tmp_path, inline_compaction,
):
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    attempts, active, running = _execution(store, "exec-retention-1")
    _register(store, running, active, effect_id="effect-provider", kind="provider.before", payload={
        "context": {"messages": [{"role": "user", "content": "x" * 5000}]},
        "resolved_snapshot": {"model": {"id": "m"}, "system_prompt": "s"},
        "normalized_context_hash": "abc",
        "supports_idempotency_key": False,
    })
    _register(store, running, active, effect_id="effect-tool", kind="tool.before", payload={
        "tool_call_id": "call-1", "tool_name": "bash",
        "arguments": {"command": "echo " + "y" * 5000},
    })
    _register(store, running, active, effect_id="effect-open", kind="tool.before", payload={
        "tool_call_id": "call-2", "tool_name": "bash", "arguments": {"command": "rm x"},
    })
    effects = EffectStore(store)
    for effect_id in ("effect-provider", "effect-tool"):
        effects.resolve_not_started(effect_id, receipt={"ok": True})

    assert retention.compact_effects(store, running.execution_id) == 0, "a live execution is left alone"

    finished = _finish(store, attempts, active, running)
    assert finished.execution.status is ExecutionStatus.COMPLETED

    provider = EffectStore(store).get("effect-provider")
    assert provider.metadata["kind"] == "provider.before"
    assert provider.metadata["payload"] == {"normalized_context_hash": "abc", "supports_idempotency_key": False}
    tool = EffectStore(store).get("effect-tool")
    assert tool.metadata["payload"] == {"tool_call_id": "call-1", "tool_name": "bash"}
    # The call whose outcome is unknown keeps what it was asked to do.
    assert EffectStore(store).get("effect-open").metadata["payload"]["arguments"] == {"command": "rm x"}
    # Already compact: nothing left to rewrite.
    assert retention.compact_effects(store, running.execution_id) == 0


def test_the_sweep_catches_up_on_executions_that_finished_earlier(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "defer", lambda _name, _run: None)
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    done = []
    for index in range(3):
        attempts, active, running = _execution(store, f"exec-sweep-{index}")
        _register(store, running, active, effect_id=f"effect-{index}", kind="provider.before",
                  payload={"context": {"messages": []}, "normalized_context_hash": str(index)})
        EffectStore(store).resolve_not_started(f"effect-{index}", receipt={})
        _finish(store, attempts, active, running)
        done.append(running.execution_id)
    _attempts, live_active, live = _execution(store, "exec-sweep-live")
    _register(store, live, live_active, effect_id="effect-live", kind="provider.before",
              payload={"context": {"messages": []}})

    # Fresh terminal executions settle first; the sweep sees them once they are a minute old.
    assert retention.executions_to_compact(store) == []
    with store._transaction() as connection:
        connection.execute("UPDATE executions SET updated_at = updated_at - 600")
    assert retention.executions_to_compact(store) == done

    totals = retention.sweep(store, pause=0)
    assert totals == {"executions": 3, "effects": 3, "blobs": 0}
    assert retention.executions_to_compact(store) == []
    assert "context" in EffectStore(store).get("effect-live").metadata["payload"]
    for index in range(3):
        assert "context" not in EffectStore(store).get(f"effect-{index}").metadata["payload"]


def test_compaction_lets_go_of_state_blobs_nothing_references(tmp_path, inline_compaction):
    from openprogram.runtime.execution.state_blobs import ExecutionStateBlobStore

    store = ExecutionStore(tmp_path / "executions.sqlite3")
    attempts, active, running = _execution(store, "exec-blobs")
    blobs = ExecutionStateBlobStore(store)
    kept = blobs.put(execution_id=running.execution_id, attempt_id=active.attempt_id,
                     name="kept", payload=b"kept", media_type="application/octet-stream", schema_version=1)
    blobs.attach_ref(execution_id=running.execution_id, ref=kept.ref, name="checkpoint.kept",
                     reference_kind="checkpoint", reference_id="ckpt-1")
    loose = blobs.put(execution_id=running.execution_id, attempt_id=active.attempt_id,
                      name="loose", payload=b"loose", media_type="application/octet-stream", schema_version=1)

    _finish(store, attempts, active, running, target=ExecutionStatus.FAILED)

    assert blobs.get(kept.ref, execution_id=running.execution_id) is not None
    assert blobs.get(loose.ref, execution_id=running.execution_id) is None
    with store._transaction() as connection:
        rows = connection.execute("SELECT execution_id FROM execution_retention").fetchall()
    assert [row[0] for row in rows] == [running.execution_id]


def test_a_tool_effect_sheds_its_resolved_snapshot_too(tmp_path, inline_compaction):
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    attempts, active, running = _execution(store, "exec-retention-snapshot")
    _register(store, running, active, effect_id="effect-tool-snapshot", kind="tool.before", payload={
        "tool_call_id": "call-1", "tool_name": "bash", "arguments": {"command": "ls"},
        "resolved_snapshot": {"model": {"id": "m"}, "system_prompt": "s" * 4000, "tools": []},
        "turn": {"user_message_id": "u1"}, "next_tool_index": 0,
    })
    EffectStore(store).resolve_not_started("effect-tool-snapshot", receipt={"ok": True})
    _finish(store, attempts, active, running)

    payload = EffectStore(store).get("effect-tool-snapshot").metadata["payload"]
    assert "resolved_snapshot" not in payload and "arguments" not in payload
    assert payload["tool_call_id"] == "call-1" and payload["turn"] == {"user_message_id": "u1"}


def test_a_store_compacted_under_an_earlier_pass_is_revisited_once(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "defer", lambda _name, _run: None)
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    attempts, active, running = _execution(store, "exec-pass")
    _register(store, running, active, effect_id="effect-pass", kind="tool.before", payload={
        "tool_call_id": "call-1", "tool_name": "bash",
        "resolved_snapshot": {"model": {"id": "m"}, "system_prompt": "s", "tools": []},
    })
    EffectStore(store).resolve_not_started("effect-pass", receipt={})
    _finish(store, attempts, active, running)
    # The store was compacted when only `arguments` was shed: it lists the
    # execution as done and records no pass at all.
    with store._transaction() as connection:
        connection.execute("UPDATE executions SET updated_at = updated_at - 600")
        connection.execute(
            "INSERT INTO execution_retention (execution_id, compacted_at) VALUES (?, 1)",
            (running.execution_id,),
        )
    assert retention.executions_to_compact(store) == []

    assert retention.begin_pass(store) is True
    assert retention.executions_to_compact(store) == [running.execution_id]
    assert retention.begin_pass(store) is False, "the pass is recorded once"
    totals = retention.sweep(store, pause=0)
    assert totals["executions"] == 1 and totals["effects"] == 1
    assert "resolved_snapshot" not in EffectStore(store).get("effect-pass").metadata["payload"]
    assert retention.executions_to_compact(store) == []
    assert retention.sweep(store, pause=0)["executions"] == 0, "the next sweep has nothing to revisit"


def test_delivered_outbox_rows_go_after_a_week(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "defer", lambda _name, _run: None)
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    attempts, active, running = _execution(store, "exec-outbox")
    _finish(store, attempts, active, running)
    with store._transaction() as connection:
        total = connection.execute("SELECT COUNT(*) FROM execution_projection_outbox").fetchone()[0]
        assert total >= 8, "every canonical event fans out to the four projections"
        # Half the rows were delivered long ago, two just now, the rest are still pending.
        rows = [r[0] for r in connection.execute(
            "SELECT outbox_id FROM execution_projection_outbox ORDER BY event_sequence, projection_kind"
        ).fetchall()]
        old, fresh = rows[: total // 2], rows[total // 2: total // 2 + 2]
        for outbox_id in old:
            connection.execute(
                "UPDATE execution_projection_outbox SET state = 'delivered', delivered_at = ? WHERE outbox_id = ?",
                (1_000.0, outbox_id),
            )
        for outbox_id in fresh:
            connection.execute(
                "UPDATE execution_projection_outbox SET state = 'delivered', delivered_at = ? WHERE outbox_id = ?",
                (2_000_000.0, outbox_id),
            )

    deleted = retention.purge_delivered_outbox(store, now=2_000_000.0 + 3600, batch=3, pause=0)

    assert deleted == len(old)
    with store._transaction() as connection:
        left = connection.execute(
            "SELECT state, COUNT(*) FROM execution_projection_outbox GROUP BY state ORDER BY state"
        ).fetchall()
    assert [tuple(row) for row in left] == [("delivered", 2), ("pending", total - len(old) - 2)]


def test_the_file_switches_to_incremental_vacuum_once_and_then_shrinks_in_steps(tmp_path):
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    assert retention.reclaim_free_pages(store) == 0, "nothing to do before the switch"

    rebuilt = store.maintain_file()
    assert rebuilt is not None and rebuilt["after_bytes"] > 0
    assert store.maintain_file() is None, "the rebuild happens once"

    # Fill and empty a table: the pages stay in the file as free pages.
    with store._transaction() as connection:
        connection.execute("CREATE TABLE ballast (id INTEGER PRIMARY KEY, blob BLOB)")
        connection.executemany(
            "INSERT INTO ballast (blob) VALUES (?)", [(b"z" * 4000,) for _ in range(400)],
        )
    with store._transaction() as connection:
        connection.execute("DELETE FROM ballast")
    with store._transaction() as connection:
        free = connection.execute("PRAGMA freelist_count").fetchone()[0]
    assert free > 300

    first = retention.reclaim_free_pages(store, max_pages=100, step=40, pause=0)
    assert 100 <= first <= 120, "a sweep returns at most its budget, in steps"
    rest = retention.reclaim_free_pages(store, pause=0)
    with store._transaction() as connection:
        assert connection.execute("PRAGMA freelist_count").fetchone()[0] == 0
    assert first + rest == free
