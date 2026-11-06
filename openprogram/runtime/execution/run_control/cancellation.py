"""Cancellation requests: exact execution cancel, session cancel, child admission and the canonical control service."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

from .. import hooks
from .tokens import (
    _cancel_flags_lock,
    _current_tokens,
    current_token,
)
from .errors import (
    ExecutionNotCancellable,
    ExecutionNotFound,
    ExecutionSpawnRefused,
)
from .records import (
    _ACTIVE_STATUSES,
    _CANCEL_INTENT_STATUSES,
    _TERMINAL_STATUSES,
    _caller_descendants,
    _cas_write_status,
    _execution_dto,
    _finalize_projections,
    _find_execution,
    _find_job,
    _get_node,
    _job_descendants,
    _job_execution_view,
    _node_status,
    _persist_job_cancel_intent,
)
from .owners import (
    _ensure_grace_watch,
    _execution_cancel_lock,
    _has_live_owner,
    _request_cancel_signals,
    retire_execution_owner,
)
import logging

_log = logging.getLogger(__name__)


_after_intent_hook: Callable[[str], None] | None = None

_cancel_reason: ContextVar[str] = ContextVar(
    "_cancel_reason", default="cancel.user",
)


def set_after_intent_hook(hook: Callable[[str], None] | None) -> None:
    """Test seam: run after durable cancelling is written, before signaling."""
    global _after_intent_hook
    _after_intent_hook = hook


def mark_cancelled(session_id: str, *, execution_id: str) -> None:
    """Cancel one exact execution through the canonical control path.

    ``session_id`` remains in the internal call signature so callers can
    retain their session context, but it is never used to infer a foreground
    token or to cancel another execution. A missing execution id is a caller
    error; session-scoped cancellation belongs to the canonical session
    control command and is not implemented by this helper.
    """
    if not execution_id:
        raise ValueError("execution_id is required for exact cancellation")
    with _cancel_flags_lock:
        token = _current_tokens.get((session_id, execution_id))
    try:
        result = cancel_execution(execution_id)
    except ExecutionNotCancellable:
        return
    except ExecutionNotFound:
        # The execution may be registered before its durable record is
        # visible. Signal only the exact registered execution token; never
        # infer or touch a session foreground token.
        if token is not None:
            token.cancel()
        return
    except Exception:
        if token is not None:
            token.cancel()
        return
    status = (
        result.get("status") if isinstance(result, dict)
        else getattr(result, "status", None)
    )
    if token is not None and status not in _TERMINAL_STATUSES:
        token.cancel()


def admit_child_execution(session_id: str, parent_execution_id: str, *, store=None) -> None:
    """Refuse spawn when any ancestor is cancelling or cancelled."""
    from openprogram.runtime.context.session_db import default_db

    store = default_db() if store is None else store
    current: str | None = parent_execution_id
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        node = _get_node(store, session_id, current)
        if node is not None:
            if _node_status(node) in _CANCEL_INTENT_STATUSES:
                raise ExecutionSpawnRefused("cancel.parent")
            current = node.caller or None
            continue
        job = _find_job(current)
        if job is None:
            break
        if _node_status(_job_execution_view(job)) in _CANCEL_INTENT_STATUSES:
            raise ExecutionSpawnRefused("cancel.parent")
        current = getattr(job, "parent_job_id", None)


@contextmanager
def child_execution_admission(
    session_id: str,
    parent_execution_id: str,
    *,
    store=None,
):
    """Hold admission through the child's durable entry write."""
    with _execution_cancel_lock:
        admit_child_execution(session_id, parent_execution_id, store=store)
        yield


def resolve_foreground_execution(session_id: str) -> str | None:
    """Best-effort current execution id for a compatibility session stop."""
    token = current_token(session_id, execution_id=None)
    if token is not None and token.execution_id:
        return token.execution_id
    with _cancel_flags_lock:
        ids = [
            key[1] for key in _current_tokens
            if key[0] == session_id and key[1]
        ]
    if len(ids) == 1:
        return ids[0]
    from openprogram.runtime.context.session_db import default_db

    store = default_db()
    try:
        nodes = store.get_nodes(session_id)
    except Exception:
        return None
    active = [
        node for node in nodes
        if _node_status(node) in {"queued", "running", "cancelling"}
    ]
    if not active:
        return None
    roots = [node for node in active if not node.caller]
    return (roots[-1] if roots else active[-1]).id


def cancel_session_executions(session_id: str) -> list[dict[str, Any]]:
    """Cancel every non-terminal root execution in a session."""
    from openprogram.runtime.context.session_db import default_db

    store = default_db()
    try:
        nodes = store.get_nodes(session_id)
    except Exception:
        return []
    roots = [
        node for node in nodes
        if not node.caller
        and _node_status(node) in {"queued", "running", "cancelling"}
    ]
    if not roots:
        foreground = resolve_foreground_execution(session_id)
        if foreground:
            roots = [
                node for node in nodes if node.id == foreground
            ]
    token = _cancel_reason.set("cancel.session")
    results: list[dict[str, Any]] = []
    try:
        for node in roots:
            try:
                results.append(cancel_execution(node.id))
            except (ExecutionNotFound, ExecutionNotCancellable):
                continue
    finally:
        _cancel_reason.reset(token)
    return results


def cancel_execution(execution_id: str):
    """Cancel exactly one execution and its active ``caller`` descendants."""
    canonical = _canonical_execution(execution_id)
    if canonical is not None:
        return _cancel_canonical_execution(canonical)
    # A JobStore row is only a read projection after the Job cutover.  Never
    # interpret it as an executable legacy record when its canonical identity
    # is absent; callers receive the same stable not-found result as any
    # unavailable execution.
    if _find_job(execution_id) is not None:
        raise ExecutionNotFound(execution_id)
    from openprogram.runtime.context.session_db import default_db

    store = default_db()
    root_reason = _cancel_reason.get()
    with _execution_cancel_lock:
        found = _find_execution(store, execution_id)
        if found is None:
            raise ExecutionNotFound(execution_id)

        session_id, root = found
        root_status = _node_status(root)
        if root_status in {"completed", "failed", "interrupted", "error"}:
            raise ExecutionNotCancellable(
                execution_id, _execution_dto(session_id, root),
            )
        if root_status in _CANCEL_INTENT_STATUSES:
            return _execution_dto(session_id, root)

        dag_descendants = _caller_descendants(store, session_id, execution_id)
        known_ids = {execution_id, *(node.id for node in dag_descendants)}
        descendants = [
            (session_id, node) for node in dag_descendants
        ]
        descendants.extend(
            (target_session_id, node)
            for target_session_id, node in _job_descendants(execution_id)
            if node.id not in known_ids
        )
        requested_at = time.time()
        targets = [(session_id, root, root_reason), *[
            (target_session_id, node, "cancel.parent")
            for target_session_id, node in descendants
        ]]
        scope_has_live_owner = any(
            _has_live_owner(target_session_id, node.id)
            for target_session_id, node, _reason in targets
        )
        for target_session_id, node, reason_code in targets:
            dag = _get_node(store, target_session_id, node.id)
            live = dag if dag is not None else node
            status = _node_status(live)
            if status in {"completed", "failed", "interrupted", "error"}:
                if node.id == execution_id:
                    raise ExecutionNotCancellable(
                        execution_id, _execution_dto(session_id, live),
                    )
                continue
            if status in _CANCEL_INTENT_STATUSES:
                continue
            if status not in _ACTIVE_STATUSES:
                continue
            has_live = _has_live_owner(target_session_id, node.id)
            final_status = (
                "cancelling"
                if has_live or (node.id == execution_id and scope_has_live_owner)
                else "cancelled"
            )
            patch = {
                "status": final_status,
                "reason_code": reason_code,
                "cancellation_requested_at": requested_at,
            }
            if final_status == "cancelled":
                patch["finished_at"] = time.time()
            wrote = False
            if dag is not None:
                wrote = _cas_write_status(
                    store,
                    target_session_id,
                    node.id,
                    from_statuses=_ACTIVE_STATUSES,
                    metadata=patch,
                )
            else:
                wrote = _persist_job_cancel_intent(
                    target_session_id,
                    node.id,
                    reason_code=reason_code,
                    requested_at=requested_at,
                    terminal=final_status == "cancelled",
                )
            if not wrote:
                if node.id == execution_id:
                    live = _get_node(store, session_id, execution_id) or live
                    live_status = _node_status(live) if live is not None else None
                    if live_status in {
                        "completed", "failed", "interrupted", "error",
                    }:
                        raise ExecutionNotCancellable(
                            execution_id,
                            _execution_dto(session_id, live),
                        )
                    if live is not None and live_status in _CANCEL_INTENT_STATUSES:
                        return _execution_dto(session_id, live)
                continue
            if final_status == "cancelled":
                retire_execution_owner(node.id)
                _finalize_projections(
                    store, target_session_id, node.id, live,
                )

        hook = _after_intent_hook
        if hook is not None:
            hook(execution_id)

        to_signal = []
        to_grace = []
        for target_session_id, node, _reason in targets:
            live = _get_node(store, target_session_id, node.id)
            if live is None:
                job = _find_job(node.id)
                live = _job_execution_view(job) if job is not None else node
            status = _node_status(live)
            if status in _CANCEL_INTENT_STATUSES or _has_live_owner(
                target_session_id, node.id,
            ):
                to_signal.append((target_session_id, node.id))
            if status == "cancelling" or _has_live_owner(
                target_session_id, node.id,
            ):
                to_grace.append(node.id)

        refreshed = _get_node(store, session_id, execution_id)
        if refreshed is None:
            job = _find_job(execution_id)
            if job is not None:
                refreshed = _job_execution_view(job)
        if refreshed is None:
            raise ExecutionNotFound(execution_id)
        result = _execution_dto(session_id, refreshed)

    for target_session_id, node_id in to_signal:
        _request_cancel_signals(target_session_id, node_id)
    for node_id in to_grace:
        _ensure_grace_watch(node_id)
    return result


def _canonical_execution(execution_id: str):
    """Return the canonical record when this id belongs to the new runtime."""
    from openprogram.runtime.execution import default_store

    return default_store().get_execution(execution_id)


def _run_control_awaitable(awaitable):
    """Bridge canonical async control from both sync and event-loop callers."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: list[Any] = []
    failure: list[BaseException] = []

    def run() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # noqa: BLE001
            failure.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0]


def _cancel_canonical_execution(execution, *, reason_code: str | None = None):
    """Submit one canonical cancel command for every canonical public surface."""
    from openprogram.runtime.execution.model import TERMINAL_EXECUTION_STATUSES
    from openprogram.runtime.execution.control import ProjectionRecoveryRequired

    if execution.status in TERMINAL_EXECUTION_STATUSES:
        if execution.status.value == "cancelled":
            current = execution
            try:
                command = _canonical_control_service(
                    execution.execution_id,
                ).executions.get_command(
                    f"execution-cancel:{execution.execution_id}",
                )
            except Exception:
                command = None
            if (
                command is not None
                and command.rejection_code == ProjectionRecoveryRequired.code
            ):
                result = current.to_dict()
                result["issue_code"] = ProjectionRecoveryRequired.code
                result["recovery_required"] = True
                return result
            return current.to_dict()
        raise ExecutionNotCancellable(execution.execution_id, execution.to_dict())
    reason_code = reason_code or _cancel_reason.get() or "cancel.user"
    try:
        from openprogram.runtime.execution import default_store

        descendants = [
            item for item in default_store().list_nonterminal()
            if item.parent_execution_id == execution.execution_id
        ]
    except Exception:
        descendants = []
    for child in descendants:
        _cancel_canonical_execution(child, reason_code="cancel.parent")
    service = _canonical_control_service(execution.execution_id)
    try:
        dispatch = None
        # Retry the existing durable command against its exact current owner;
        # submitting its id again with a newer version would be a collision.
        if (
            execution.status.value == "cancelling"
            and execution.current_attempt_id
            and isinstance(execution.owner_lease.get("generation"), int)
        ):
            dispatch = _run_control_awaitable(service.deliver_pending_cancel(
                execution_id=execution.execution_id,
                attempt_id=execution.current_attempt_id,
                generation=execution.owner_lease["generation"],
            ))
        if dispatch is None:
            dispatch = _run_control_awaitable(service.request_cancel(
                command_id=f"execution-cancel:{execution.execution_id}",
                execution_id=execution.execution_id,
                expected_version=execution.status_version,
                actor={"source": "run_control"},
                reason_code=reason_code,
            ))
    except Exception as exc:
        from openprogram.runtime.execution.store import ExecutionConflict

        current = _canonical_execution(execution.execution_id)
        if isinstance(exc, ProjectionRecoveryRequired):
            result = (current or execution).to_dict()
            result["issue_code"] = ProjectionRecoveryRequired.code
            result["recovery_required"] = True
            return result
        if current is not None and current.status.value == "cancelled":
            return current.to_dict()
        if current is not None and current.status.value == "cancelling":
            result = current.to_dict()
            result["issue_code"] = "cancel_delivery_unconfirmed"
            return result
        if isinstance(exc, ExecutionConflict) and current is not None:
            raise ExecutionNotCancellable(
                execution.execution_id, current.to_dict(),
            ) from exc
        raise
    result = dispatch.execution.to_dict()
    if dispatch.issue_code:
        result["issue_code"] = dispatch.issue_code
    if dispatch.command.rejection_code == ProjectionRecoveryRequired.code:
        result["issue_code"] = ProjectionRecoveryRequired.code
        result["recovery_required"] = True
    return result


def _canonical_control_service(execution_id: str):
    """Use the JobRunner's live registry when this is a public Job."""
    from openprogram.runtime.execution import default_control_service

    try:
        from openprogram.runtime.execution import default_store

        runner = hooks.job_runner(default_store())
        if runner is not None:
            canonical = runner._execution_store.get_execution(execution_id)
            input_record = runner._execution_store.get_execution_input(execution_id)
            if (
                canonical is not None
                and input_record is not None
                and input_record.input_ref.startswith("job-input-v1:")
            ):
                return runner._execution_control
    except Exception:
        # Fall back to the default control service.
        _log.debug("job runner control lookup failed for %s", execution_id, exc_info=True)
    return default_control_service()
