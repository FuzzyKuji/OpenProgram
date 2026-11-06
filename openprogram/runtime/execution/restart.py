"""Worker-restart continuation through durable canonical events and commands."""

from __future__ import annotations

import asyncio
import logging
from time import time

from .model import CommandStatus, ExecutionStatus

_log = logging.getLogger(__name__)
_REQUEST = "execution.restart.requested"
_SETTLED = "execution.restart.settled"


def window_seconds() -> int:
    """-1 preserves run intent indefinitely; zero is an explicit opt-out."""
    from openprogram.state.config import read_config

    settings = read_config().get("execution", {})
    if not isinstance(settings, dict):
        return 0
    value = settings.get("auto_resume_window_seconds", -1)
    return value if type(value) is int and value >= -1 else 0


def resume_deadline(interrupted_at: float, seconds: int) -> float | None:
    return None if seconds == -1 else interrupted_at + seconds


def record_intent(
    store, connection, execution, *, interrupted_at, seconds, pause_command_id=None, mode="checkpoint"
):
    """Called inside the transaction owning the interruption/pause intent."""
    store._append_event(
        connection,
        execution_id=execution.execution_id,
        execution_version=execution.status_version,
        kind=_REQUEST,
        payload=dict(
            interrupted_at=interrupted_at,
            resume_before=resume_deadline(interrupted_at, seconds),
            expected_version=execution.status_version,
            pause_command_id=pause_command_id,
            mode=mode,
        ),
        created_at=time(),
    )


def crash_checkpoint(service, connection, execution):
    """Only a current, opted-in checkpoint can survive abandoned ownership."""
    if not execution.capabilities.pause or not execution.checkpoint_head_id:
        return None
    checkpoint = service.checkpoints._get(connection, execution.checkpoint_head_id)
    if (
        checkpoint is None
        or checkpoint.execution_id != execution.execution_id
        or checkpoint.revision_id != execution.revision_id
    ):
        return None
    if (
        checkpoint.created_by_attempt_id != execution.current_attempt_id
        and execution.owner_lease.get("resume_checkpoint_id")
        != checkpoint.checkpoint_id
    ):
        return None
    seconds = checkpoint.state_refs.get("restart_window_seconds", 0)
    if type(seconds) is not int or seconds == 0 or seconds < -1:
        return None
    # A later committed action makes an older checkpoint unsafe to replay.
    if connection.execute(
        "SELECT 1 FROM effects WHERE execution_id = ? AND status = 'committed' AND updated_at > ? "
        "AND json_extract(metadata_json, '$.function_step') IS NULL "
        "AND COALESCE(json_extract(receipt_json, '$.function_suspended'), 0) != 1 LIMIT 1",
        (execution.execution_id, checkpoint.created_at),
    ).fetchone():
        return None
    attempt = service.attempts._require(connection, execution.current_attempt_id)
    return max(attempt.updated_at, execution.updated_at), seconds


def _service(runner, execution_id):
    if runner._execution_store.get_job_agent_input(execution_id) is not None:
        return runner._execution_control
    from . import default_control_service

    return default_control_service()


def prepare_shutdown(runner) -> None:
    """Request cooperative pause before the worker's bounded process teardown."""
    from openprogram.operations.self_update.control.maintenance import maintenance_blocks

    runner._restart_shutdown = True
    shutdown_event = getattr(runner, "_shutdown_event", None)
    if shutdown_event is not None:
        shutdown_event.set()
        runner._dispatch_wake.set()
    seconds = window_seconds()
    if seconds == 0 or maintenance_blocks("worker_restart"):
        return
    store = runner._execution_store
    for execution in store.list_nonterminal():
        if (
            execution.status is not ExecutionStatus.RUNNING
            or not execution.capabilities.pause
        ):
            continue
        command_id = f"worker-restart:pause:{execution.current_attempt_id}"
        # A normal safe point can advance the version before pause acceptance.
        # Retrying never transfers shutdown ownership to a replacement attempt.
        for retry in range(3):
            try:
                with store._transaction() as connection:
                    current = store._require_execution(
                        connection, execution.execution_id
                    )
                    if (
                        current.status is not ExecutionStatus.RUNNING
                        or current.current_attempt_id != execution.current_attempt_id
                    ):
                        break
                    if not any(
                        e.kind == _REQUEST
                        and e.payload.get("pause_command_id") == command_id
                        for e in store.list_events(execution.execution_id)
                    ):
                        record_intent(
                            store,
                            connection,
                            current,
                            interrupted_at=time(),
                            seconds=seconds,
                            pause_command_id=command_id,
                        )
                asyncio.run(
                    _service(runner, execution.execution_id).request_pause(
                        command_id=command_id,
                        execution_id=execution.execution_id,
                        expected_version=current.status_version,
                        actor={"surface": "worker-restart"},
                    )
                )
                break
            except Exception as exc:
                if getattr(exc, "code", None) == "stale_version" and retry < 2:
                    continue
                _log.exception(
                    "could not checkpoint execution %s during shutdown",
                    execution.execution_id,
                )
                break


_LIVE = frozenset({
    ExecutionStatus.QUEUED, ExecutionStatus.RUNNING,
    ExecutionStatus.PAUSING, ExecutionStatus.CANCELLING,
})


def _superseded(store, execution, interrupted_at) -> bool:
    """Whether another turn of the conversation began after ``interrupted_at``."""
    if not execution.session_id:
        return False
    from contextlib import closing
    with closing(store._connect()) as connection:
        return connection.execute(
            "SELECT 1 FROM executions WHERE session_id = ? AND execution_id != ? "
            "AND COALESCE(parent_execution_id, '') != ? AND created_at > ? LIMIT 1",
            (execution.session_id, execution.execution_id,
             execution.execution_id, interrupted_at),
        ).fetchone() is not None


def _settle(store, execution, event, outcome):
    with store._transaction() as connection:
        store._append_event(
            connection,
            execution_id=execution.execution_id,
            execution_version=execution.status_version,
            kind=_SETTLED,
            payload=dict(request_sequence=event.sequence, outcome=outcome),
            created_at=time(),
        )


def _fallback_after_contract_mismatch(store, execution, event, command):
    """A rejected immutable checkpoint can request a fresh chat, never tool replay."""
    payload = store.get_agent_turn_input(execution.execution_id)
    if (not payload or payload.get("kind") != "chat"
            or payload.get("request", {}).get("source") not in {"web", "tui", "acp"}):
        return False
    with store._transaction() as connection:
        if connection.execute(
            "SELECT 1 FROM execution_events WHERE execution_id = ? AND kind = ? "
            "AND json_extract(payload_json, '$.request_sequence') = ? LIMIT 1",
            (execution.execution_id, _SETTLED, event.sequence),
        ).fetchone():
            return True
        current = store._require_execution(connection, execution.execution_id)
        if (current.status is not ExecutionStatus.PAUSED or current.current_attempt_id
                or current.reason_code != "continuation_contract_mismatch"
                or current.status_version != command.result_version):
            return False
        store._append_event(connection, execution_id=current.execution_id,
            execution_version=current.status_version, kind=_REQUEST,
            payload=dict(event.payload, mode="new_turn", expected_version=current.status_version,
                         pause_command_id=None), created_at=time())
        store._append_event(connection, execution_id=current.execution_id,
            execution_version=current.status_version, kind=_SETTLED,
            payload=dict(request_sequence=event.sequence, outcome="checkpoint_incompatible"), created_at=time())
    return True


def reconcile(runner) -> None:
    """Resume the exact restart-owned pause, honoring any explicit deadline."""
    from openprogram.operations.self_update.control.maintenance import maintenance_blocks

    if getattr(runner, "_restart_shutdown", False) or maintenance_blocks(
        "worker_restart"
    ):
        return
    store = runner._execution_store
    from contextlib import closing
    with closing(store._connect()) as connection:
        # Include interrupted frames until their durable new-turn request settles.
        ids = [row[0] for row in connection.execute(
            "SELECT r.execution_id FROM execution_events r WHERE r.kind = ? "
            "AND NOT EXISTS (SELECT 1 FROM execution_events s WHERE s.execution_id = r.execution_id "
            "AND s.kind = ? AND json_extract(s.payload_json, '$.request_sequence') = r.sequence) "
            "GROUP BY r.execution_id ORDER BY MIN(r.sequence)",
            (_REQUEST, _SETTLED),
        )]
    for execution_id in ids:
        execution = store.get_execution(execution_id)
        if (
            execution is None or execution.current_attempt_id
        ):
            continue
        events = store.list_events(execution.execution_id)
        requests = [e for e in events if e.kind == _REQUEST]
        if not requests:
            continue
        event = requests[-1]
        if any(
            e.kind == _SETTLED and e.payload.get("request_sequence") == event.sequence
            for e in events
        ):
            continue
        data = event.payload
        if data.get("mode") == "new_turn":
            from .hooks import start_recovery_turn
            try:
                outcome = start_recovery_turn(store, execution, event)
                if outcome:
                    _settle(store, store.get_execution(execution.execution_id), event, outcome)
            except Exception:
                _log.exception("new-turn recovery failed for %s", execution.execution_id)
            continue
        if execution.status is not ExecutionStatus.PAUSED:
            continue
        command_id = (
            f"worker-restart:continue:{execution.execution_id}:{event.sequence}"
        )
        existing = store.get_command(command_id)
        if existing is not None:
            if (existing.status is CommandStatus.REJECTED
                    and existing.rejection_code == "continuation_contract_mismatch"
                    and _fallback_after_contract_mismatch(store, execution, event, existing)):
                continue
            if existing.status in {CommandStatus.APPLIED, CommandStatus.REJECTED}:
                _settle(store, execution, event, existing.status.value)
            continue
        pause_id = data["pause_command_id"]
        pause = store.get_command(pause_id) if pause_id else None
        expected = (
            pause.result_version
            if pause is not None and pause.status is CommandStatus.APPLIED
            else data["expected_version"]
            if pause_id is None
            else None
        )
        if expected != execution.status_version:
            _settle(store, execution, event, "execution_changed")
            continue
        if (
            time() < data["interrupted_at"]
            or (data["resume_before"] is not None and time() > data["resume_before"])
            or window_seconds() == 0
        ):
            _settle(store, execution, event, "expired")
            continue
        # The user has moved on: a later turn of this conversation started
        # after the interruption, so continuing this one now would act out
        # of turn. It stays paused for the user to continue by hand.
        if _superseded(store, execution, data["interrupted_at"]):
            _settle(store, execution, event, "superseded")
            continue
        service = _service(runner, execution.execution_id)
        if service.effects.list_unresolved(execution.execution_id):
            continue
        # A current user turn/wait in this conversation retains its ownership.
        # One stuck awaiting reconciliation is not current and blocks nothing.
        if any(
            e.execution_id != execution.execution_id
            and e.status in _LIVE
            for e in store.list_nonterminal(session_id=execution.session_id)
        ):
            continue
        try:
            kwargs = dict(
                command_id=command_id,
                execution_id=execution.execution_id,
                expected_version=execution.status_version,
                actor={"surface": "worker-restart"},
            )
            if store.get_job_agent_input(execution.execution_id) is not None:
                runner.queue_job_resume(**kwargs, step=False)
            else:
                asyncio.run(service.request_continue(**kwargs))
        except Exception:
            _log.exception("automatic restart failed for %s", execution.execution_id)
