"""The ``chat`` action's last phases: publish the running task, start the turn.

Every failure here unwinds what the earlier phases took in the same order
they always have: the surface bindings, the admission and the run
reservation (plus the running-task entry once it is published).
"""
from __future__ import annotations

import logging
import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Callable

from .context_usage import _record_canonical_context_stats

_log = logging.getLogger(__name__)

# Turn failures keep logging under the ``chat`` action's own module.
_TURN_LOGGER = f"{__package__}.turn"


@dataclass
class _AdmittedTurn:
    """An admitted turn: what launch and every unwinding path need."""
    session_id: str
    msg_id: str
    conv: dict
    adapter: Any
    admission: Any
    surface_context: Any
    release_surface_bindings: Callable[[Any], None]
    response_format: Any
    execution_id: Any


def _publish_running_task(_s, turn: _AdmittedTurn) -> None:
    # Mark the session running + push the sidebar list right now, before
    # the exec thread starts — so every connected tab shows the new
    # conversation row already flowing (convRunningFlow) the instant the
    # turn is dispatched, not a round-trip later when the exec thread's
    # own running_task broadcast lands. setdefault so the thread's later
    # _running_tasks[...] = {...} overwrite stays the single source of
    # the task entry (no double running_task with a different started_at).
    import time as _t
    session_id, msg_id = turn.session_id, turn.msg_id
    execution_id = turn.execution_id
    _admission = turn.admission
    try:
        with _s._running_tasks_lock:
            _running_task = _s._running_tasks.setdefault(session_id, {
                "msg_id": msg_id, "func_name": "_chat",
                "started_at": _t.time(), "last_event_at": _t.time(),
                "display_params": "", "loaded_func_ref": None,
                "stream_events": [],
                "execution_id": execution_id,
                "status_version": _admission.status_version,
            })
            # The reservation is created before the admission has an execution
            # id. Fill that exact id into the owned task rather than relying on
            # setdefault, which would leave a provisional value unable to
            # match the admitted execution.
            if _running_task.get("msg_id") == msg_id:
                _running_task["execution_id"] = execution_id
                _running_task["status_version"] = _admission.status_version
        _s._emit_running_task_event(session_id)
    except BaseException:
        with _s._running_tasks_lock:
            if (_s._running_tasks.get(session_id) or {}).get("msg_id") == msg_id:
                _s._running_tasks.pop(session_id, None)
        turn.adapter.fail_admission(_admission, reason_code="chat_handoff_failed")
        turn.release_surface_bindings(turn.surface_context)
        _s._release_run_reservation(session_id, msg_id)
        raise
    # The sidebar list reads every session row; build it off the event loop.
    # A one-row ``session_updated`` cannot replace it yet: peers drop rows
    # they do not know and do not re-sort on activity from that frame.
    from openprogram.interfaces.server.ws_actions.session import broadcast_sessions_list

    def _broadcast_list() -> None:
        try:
            broadcast_sessions_list()
        except Exception:
            # Runs off-loop; sidebars refetch the list on their next load.
            _log.debug("sessions list broadcast failed", exc_info=True)

    try:
        asyncio.get_running_loop().run_in_executor(None, _broadcast_list)
    except RuntimeError:
        _broadcast_list()


def _clear_running_task(_s, turn: _AdmittedTurn) -> None:
    _s._emit_running_task_event(
        turn.session_id,
        cleared_msg_id=turn.msg_id,
        cleared_execution_id=turn.execution_id,
    )


def _make_run_thread(_s, turn: _AdmittedTurn, **kwargs):
    try:
        return threading.Thread(**kwargs)
    except BaseException:
        turn.release_surface_bindings(turn.surface_context)
        turn.adapter.fail_admission(
            turn.admission, reason_code="agent_runner_error",
        )
        _s._release_run_reservation(turn.session_id, turn.msg_id)
        _clear_running_task(_s, turn)
        raise


def _canonical_runner(_s, turn: _AdmittedTurn):
    """The run thread's target: activate the admission and finish the run."""
    session_id, msg_id = turn.session_id, turn.msg_id
    _adapter, _admission = turn.adapter, turn.admission

    def _run_canonical(**_thread_options):
        def _publish_activation(active):
            with _s._running_tasks_lock:
                task = _s._running_tasks.get(session_id)
                if task and task.get("execution_id") == active.admission.execution_id:
                    task["status_version"] = active.status_version
            _s._emit_running_task_event(session_id)

        async def _activate():
            return await _adapter.activate(_admission, on_activated=_publish_activation)

        try:
            activated = asyncio.run(_activate())
            if activated is not None:
                _active, turn_result = activated
                # Stats are a derived projection; a transient failure here
                # must not change the already-committed turn's outcome.
                try:
                    _record_canonical_context_stats(
                        session_id, msg_id, turn.conv, turn_result,
                    )
                except Exception:
                    import logging
                    logging.getLogger(_TURN_LOGGER).exception(
                        "failed to record context stats for %s", session_id,
                    )
        finally:
            turn.release_surface_bindings(turn.surface_context)
            try:
                if _s._finish_owned_run(session_id, msg_id):
                    _s._emit_running_task_event(
                        session_id,
                        cleared_msg_id=msg_id,
                        cleared_execution_id=turn.execution_id,
                    )
            except Exception:
                # Worker exit path: an exception here would die unobserved.
                _log.warning(
                    "running task not cleared for session %s", session_id, exc_info=True)

    return _run_canonical


def _start_run_thread(_s, turn: _AdmittedTurn) -> None:
    session_id, msg_id = turn.session_id, turn.msg_id
    run_thread = _make_run_thread(
        _s, turn,
        target=_canonical_runner(_s, turn),
        args=(),
        kwargs={"response_format": turn.response_format},
        daemon=True,
    )

    if not _s._activate_run_reservation(session_id, msg_id, run_thread):
        turn.release_surface_bindings(turn.surface_context)
        turn.adapter.fail_admission(turn.admission, reason_code="agent_runner_error")
        _s._release_run_reservation(session_id, msg_id)
        _clear_running_task(_s, turn)
        raise RuntimeError("chat execution reservation was lost before startup")

    try:
        run_thread.start()
    except BaseException:
        turn.release_surface_bindings(turn.surface_context)
        turn.adapter.fail_admission(
            turn.admission, reason_code="agent_runner_error",
        )
        if _s._finish_owned_run(session_id, msg_id):
            _clear_running_task(_s, turn)
        _s._release_run_reservation(session_id, msg_id)
        raise
