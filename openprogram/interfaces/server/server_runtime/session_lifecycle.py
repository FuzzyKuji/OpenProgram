"""Server session lifecycle."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from .. import server as state

_log = logging.getLogger(__name__)


def _cleanup_session_resources(session_id: str, conv: dict):
    """Clean up all resources associated with a deleted conversation."""
    # Clean up follow-up queues and running tasks
    with state._follow_up_lock:
        state._follow_up_queues.pop(session_id, None)
    with state._running_tasks_lock:
        state._running_tasks.pop(session_id, None)
    # A Docker environment's per-session container goes with the session.
    try:
        from openprogram.host.backend.docker import remove_session_containers
        state.threading.Thread(target=remove_session_containers, args=(session_id,),
                               daemon=True).start()
    except Exception:
        # Docker backend is optional; leftover containers are reaped by Docker
        # cleanup.
        _log.debug(
            "container cleanup not started for session %s", session_id, exc_info=True)


def _stop_session_work(session_id: str, *, reason: str) -> list[str]:
    """Stop everything still working for a session that is going away.

    Cancels every unfinished root execution (its descendants follow the
    cancel), closes the session's open questions and approvals, releases
    the run slot and drops the queued inbox entries. Each step is
    best-effort: a deleted session must still be deleted when one of them
    fails. Returns the execution ids a cancel was requested for.
    """
    from openprogram.runtime.execution import default_store
    from openprogram.runtime.execution.waits import DurableWaitStore
    from openprogram.runtime.execution.run_control.cancellation import (
        _cancel_canonical_execution,
    )

    cancelled: list[str] = []
    try:
        store = default_store()
        executions = store.list_nonterminal(session_id=session_id)
    except Exception as exc:
        state._log(f"[stop_session_work] {session_id} list: {exc}")
        store, executions = None, []
    for execution in executions:
        if execution.parent_execution_id:
            continue
        try:
            _cancel_canonical_execution(execution, reason_code="cancel.session")
            cancelled.append(execution.execution_id)
        except Exception as exc:
            state._log(f"[stop_session_work] cancel {execution.execution_id}: {exc}")
        state._release_session_occupancy_for_execution(
            {"session_id": session_id, "execution_id": execution.execution_id},
        )
    if store is not None:
        # A cancel closes its own execution's waits; a wait whose execution
        # could not be cancelled must still stop prompting the user.
        try:
            waits = DurableWaitStore(store)
            for execution_id in {w.execution_id for w in waits.list_open(session_id=session_id)}:
                waits.cancel_execution(execution_id)
        except Exception as exc:
            state._log(f"[stop_session_work] waits {session_id}: {exc}")
    with state._running_tasks_lock:
        task = state._running_tasks.pop(session_id, None)
        state._unregister_active_runtime(session_id)
    if task is not None:
        state._emit_running_task_event(
            session_id,
            cleared_msg_id=task.get("msg_id"),
            cleared_execution_id=task.get("execution_id"),
        )
    try:
        from openprogram.runtime.conversation import inbox
        inbox.clear(session_id, reason=reason)
    except Exception as exc:
        state._log(f"[stop_session_work] inbox {session_id}: {exc}")
    return cancelled


def _get_or_create_session(session_id: str = None,
                                agent_id: str = None,
                                *,
                                channel: str = None,
                                account_id: str = None,
                                peer: str = None) -> dict:
    """Get or create a conversation with its own DAG session + Runtime.

    If ``agent_id`` is provided the new conversation is bound to that
    agent; otherwise it lands in the registry's default agent. Existing
    conversations keep whatever agent they were created under — we
    never rebind on lookup.

    The optional ``channel`` / ``account_id`` / ``peer`` triple binds the
    new conversation to a chat channel (e.g. ``wechat`` + ``baby``).
    Ignored on lookup of existing conversations — call
    ``set_conversation_channel`` to change them after creation.
    """
    if session_id is None:
        session_id = "local_" + uuid.uuid4().hex[:10]
    with state._sessions_lock:
        if session_id not in state._sessions:
            resolved_agent = agent_id or state._default_agent_id()
            # Hydrate the active branch from SessionDB so a webui
            # restart / fresh worker process sees the same messages
            # the dispatcher and channels worker have been writing.
            # Empty list for brand-new conversations.
            try:
                from openprogram.runtime.context.session_db import default_db
                _db = default_db()
                _hydrated = _db.get_branch(session_id) or []
                _sess = _db.get_session(session_id)
                _hydrated_head = _sess.get("head_id") if _sess else None
            except Exception:
                _hydrated = []
                _sess = None
                _hydrated_head = None
            resolved_agent = (
                agent_id
                or ((_sess or {}).get("agent_id") if isinstance(_sess, dict) else None)
                or resolved_agent
            )
            # New conversations start on the Agent's own model or the last
            # used one, unless a draft picker left a one-shot pin. Existing
            # rows keep their stored pin. Do not inherit the latest click
            # onto a rehydrated thread.
            from openprogram.runtime.conversation.session_model import new_session_chat_model
            _is_new = not isinstance(_sess, dict) or not _sess
            _inherit_prov = None
            _inherit_model = None
            if _is_new:
                _inherit_prov, _inherit_model = new_session_chat_model(resolved_agent)
                if state._user_pinned_provider and state._user_pinned_model:
                    _inherit_prov = state._user_pinned_provider
                    _inherit_model = state._user_pinned_model
                    state._user_pinned_provider = None
                    state._user_pinned_model = None
            state._log(
                f"[_get_or_create_session] creating {session_id!r} "
                f"inherit_prov={_inherit_prov!r} inherit_model={_inherit_model!r}"
            )
            state._sessions[session_id] = {
                "id": session_id,
                "runtime": None,          # created lazily on first message
                "agent_id": resolved_agent,  # so _resolve's agent-default tier fires
                "provider_name": ((_sess or {}).get("provider_name") if isinstance(_sess, dict) else None)
                                 or _inherit_prov,
                # Read the persisted per-conv override back (same pattern as
                # provider_name above); fall back to the global pinned value.
                # Without this a rebuilt session loses the user's model pick and
                # dispatch falls back to the agent/global default.
                "provider_override": ((_sess or {}).get("provider_override") if isinstance(_sess, dict) else None)
                                     or _inherit_prov,
                "model_override": ((_sess or {}).get("model_override") if isinstance(_sess, dict) else None)
                                  or _inherit_model,
                "messages": _hydrated,
                "head_id": _hydrated_head,
                "tools_override": ((_sess or {}).get("tools_override") if isinstance(_sess, dict) else None),
                "thinking_effort": ((_sess or {}).get("thinking_effort") if isinstance(_sess, dict) else None),
                "permission_mode": ((_sess or {}).get("permission_mode") if isinstance(_sess, dict) else None),
            }
            # session.start on the bus — plugin subscribers included.
            # emit_safe swallows failures: never break session creation.
            from openprogram.runtime.events import emit_safe
            emit_safe("session.start", "system", {
                "session_id": session_id,
                "agent_id": resolved_agent,
                "channel": channel,
            }, {"session": session_id})
            if _is_new and _inherit_prov and _inherit_model:
                try:
                    from openprogram.runtime.conversation.session_model import write_session_chat_model
                    write_session_chat_model(session_id, _inherit_prov, _inherit_model)
                except Exception:
                    # The session opens on the default model instead of the
                    # inherited one.
                    _log.warning(
                        "inherited chat model not written for session %s", session_id, exc_info=True)
        return state._sessions[session_id]


def _canonical_foreground_task(session_id: str) -> dict | None:
    from openprogram.runtime.execution import default_store
    from openprogram.runtime.execution.foreground import active_foreground_task

    return active_foreground_task(default_store(), session_id)


def _is_run_active(session_id: str) -> bool:
    """Is there an in-flight agent run for this conversation?

    Single source of truth for UI gating (Edit / Retry buttons go grey
    while a run is active). Driven off ``_running_tasks`` — the same
    dict we use for pause / stop, so we can't drift out of sync.
    """
    # A durable continuation no longer owns the initial transport thread.
    if state._canonical_foreground_task(session_id) is not None:
        return True
    with state._running_tasks_lock:
        task = state._running_tasks.get(session_id)
        # A chat handler reserves the session before it mutates the DAG and
        # before its runtime thread exists. Treat that short state as active;
        # otherwise a second handler would delete the reservation as a
        # "zombie" and both turns could pass the guard.
        stale_reservation = False
        stale_task = None
        if task and task.get("_reserved"):
            if state.time.time() - task.get("started_at", 0) > 300:
                stale_task = state._running_tasks.pop(session_id, None)
                stale_reservation = True
            else:
                return True
    if stale_reservation:
        state._emit_running_task_event(
            session_id,
            cleared_msg_id=(stale_task or {}).get("msg_id"),
            cleared_execution_id=(stale_task or {}).get("execution_id"),
        )
        return False
    if task is None:
        # Runtime registration precedes reservation handoff. If another
        # observer arrives in that interval, the runtime itself still blocks
        # a second turn even if stop/cleanup just removed the task entry.
        return state._has_active_runtime(session_id)
    # Zombie entry (no live runtime registered) → not actually running.
    # Drop it so subsequent calls don't keep blocking Edit/Retry/etc.
    if not state._has_active_runtime(session_id):
        with state._running_tasks_lock:
            current = state._running_tasks.get(session_id)
            if current is not task:
                # A concurrent observer may already have removed the stale
                # owner and admitted another turn. Never clear its reservation.
                return current is not None or state._has_active_runtime(session_id)
            if state._has_active_runtime(session_id):
                return True
            zombie = state._running_tasks.pop(session_id, None)
        state._emit_running_task_event(
            session_id,
            cleared_msg_id=(zombie or {}).get("msg_id"),
            cleared_execution_id=(zombie or {}).get("execution_id"),
        )
        return False
    return True


def _run_identity(session_id: str) -> dict | None:
    """The turn that makes a session active, as the ids its clear will name.

    A client that learns ``run_active`` from a load holds a running slot until
    a ``running_task_clear`` matches it; an anonymous slot matches nothing, so
    the load hands over the identity together with the flag. The execution's
    ``status_version`` rides along when the turn has one: a Stop is an exact
    command, so a client that reconnected mid-turn needs the version to cancel
    the turn it sees rather than only pretending to.
    """
    task = state._canonical_foreground_task(session_id)
    if task is None:
        with state._running_tasks_lock:
            current = state._running_tasks.get(session_id)
            task = dict(current) if current else None
    if not task:
        return None
    identity = {
        "msg_id": task.get("msg_id") or "",
        "execution_id": task.get("execution_id") or "",
    }
    version = task.get("status_version")
    if identity["execution_id"] and isinstance(version, int) and not isinstance(version, bool):
        identity["status_version"] = version
    return identity


def _try_reserve_run(session_id: str, msg_id: str) -> bool:
    from openprogram.state.store.session.session_lock import session_interprocess_lock
    try:
        with session_interprocess_lock(session_id, timeout=0.25):
            return state._try_reserve_run_locked(session_id, msg_id)
    except (TimeoutError, BlockingIOError):
        return False


def _try_reserve_run_locked(session_id: str, msg_id: str) -> bool:
    """Atomically reserve one session for a chat turn before DAG mutation."""
    try:
        from openprogram.state.store.session.migration import session_hold_active
        from openprogram.state.paths import get_state_dir
        if session_hold_active(Path(get_state_dir()) / "projects", session_id):
            return False
    except Exception:
        return False
    if state._is_run_active(session_id):
        return False
    now = state.time.time()
    with state._running_tasks_lock:
        if session_id in state._running_tasks:
            return False
        state._running_tasks[session_id] = {
            "msg_id": msg_id,
            "func_name": "_chat",
            "started_at": now,
            "last_event_at": now,
            "display_params": "",
            "loaded_func_ref": None,
            "stream_events": [],
            # Admission mints the canonical execution id. A provisional
            # reservation must not publish or derive one from msg_id.
            "execution_id": None,
            "_reserved": True,
        }
    return True


def _release_run_reservation(session_id: str, msg_id: str) -> None:
    """Release only the still-provisional reservation owned by ``msg_id``."""
    with state._running_tasks_lock:
        task = state._running_tasks.get(session_id)
        if task and task.get("_reserved") and task.get("msg_id") == msg_id:
            state._running_tasks.pop(session_id, None)


def _activate_run_reservation(session_id: str, msg_id: str, runtime) -> bool:
    """Atomically hand an owned reservation to its registered runtime."""
    with state._running_tasks_lock:
        task = state._running_tasks.get(session_id)
        if not (task and task.get("_reserved")
                and task.get("msg_id") == msg_id):
            return False
        # Publish the runtime handoff before clearing the provisional marker.
        # This closes the observer window in which _is_run_active could treat
        # an admitted turn as a zombie and allow a duplicate start.
        state._register_active_runtime(session_id, runtime)
        task.pop("_reserved", None)
        task["started_at"] = state.time.time()
        task["last_event_at"] = task["started_at"]
    return True


def _finish_owned_run(session_id: str, msg_id: str) -> bool:
    """Remove only the task/runtime pair still owned by ``msg_id``."""
    with state._running_tasks_lock:
        task = state._running_tasks.get(session_id)
        if not (task and task.get("msg_id") == msg_id):
            return False
        state._running_tasks.pop(session_id, None)
        # The active-runtime registration is the handoff counterpart to the
        # provisional reservation.  Retire it only after ownership was
        # matched (a late finisher must not clear a newer run), and under the
        # same lock: between the two, _is_run_active still answered True from
        # the runtime while _run_identity found no task, so a load in that
        # window handed clients an active run with no ids to clear it by.
        state._unregister_active_runtime(session_id)
    return True


def _release_session_occupancy_for_execution(execution: dict) -> bool:
    """Release the session slot as soon as cancel intent is accepted.

    Occupancy is the running-task entry AND the active runtime.
    Popping only ``_running_tasks`` is not enough: ``_is_run_active``
    still returns True via ``_has_active_runtime``. A newer reservation
    (different ``msg_id``) is left intact. Broadcasts
    ``running_task_clear`` so every client matches.
    """
    session_id = execution.get("session_id") if execution else None
    execution_id = (
        (execution.get("execution_id") or "").strip() if execution else ""
    )
    if not session_id or not execution_id:
        return False
    msg_id = None
    with state._running_tasks_lock:
        task = state._running_tasks.get(session_id)
        task_msg = task.get("msg_id") if task else None
        task_exec = task.get("execution_id") if task else None
    if task_msg:
        if task_exec == execution_id:
            msg_id = task_msg
        else:
            return False
    else:
        return False
    released = state._finish_owned_run(session_id, msg_id)
    if not released:
        # Task already gone; still drop a leftover foreground runtime so
        # ``_is_run_active`` cannot stay True via ``_has_active_runtime``.
        with state._running_tasks_lock:
            leftover = state._running_tasks.get(session_id)
            if leftover is None or leftover.get("msg_id") == msg_id:
                state._unregister_active_runtime(session_id)
                if leftover is not None:
                    state._running_tasks.pop(session_id, None)
                released = True
    if released:
        state._emit_running_task_event(
            session_id,
            cleared_execution_id=execution_id,
            cleared_msg_id=msg_id,
        )
    return released


class ServerRunSlot:
    """The server's run reservation as the runtime's run-slot port.

    A turn the runtime starts on its own (a reminder wake, an always-on
    check-in) reserves the same slot a typed message does, shows as the
    conversation's running task while it runs and frees the slot when it
    ends, so neither kind of turn can start on top of the other.
    """

    def reserve(self, session_id: str, owner: str) -> bool:
        return state._try_reserve_run(session_id, owner)

    def activate(self, session_id: str, owner: str, *, execution_id: str,
                 status_version: int, runner) -> bool:
        with state._running_tasks_lock:
            task = state._running_tasks.get(session_id)
            if task and task.get("msg_id") == owner:
                task["execution_id"] = execution_id
                task["status_version"] = status_version
        if not state._activate_run_reservation(session_id, owner, runner):
            return False
        state._emit_running_task_event(session_id)
        return True

    def finish(self, session_id: str, owner: str, *, execution_id: str) -> None:
        if state._finish_owned_run(session_id, owner):
            state._emit_running_task_event(
                session_id, cleared_msg_id=owner, cleared_execution_id=execution_id,
            )

    def release(self, session_id: str, owner: str) -> None:
        state._release_run_reservation(session_id, owner)
