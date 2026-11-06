"""Slash-command actions: manual compaction and the system sandbox toggle."""
from __future__ import annotations

import asyncio
import json
import uuid

from .session_agent import _db_agent_id


_compact_tasks: set[asyncio.Task] = set()


async def handle_compact(ws, cmd: dict):
    """Manual /compact entry point — user-initiated compaction.

    Frontend sends ``{action: "compact", session_id, keep_recent_tokens?}``.
    We delegate to ``dispatcher.trigger_compaction`` which walks the full
    ``engine.compact`` pipeline (LLM summary, DAG re-parent, event
    broadcast).

    Compaction rewrites the history a turn reads, so it holds the
    session's run slot: while a turn runs the request is refused with
    ``run_active``, and no turn starts until compaction ends. It runs as
    a background task so the requesting socket keeps serving its other
    actions during the summary call.
    """
    from openprogram.interfaces.server import server as _s
    from .turn_request import _send_chat_error

    session_id = cmd.get("session_id")
    if not session_id:
        await _send_chat_error(ws, None, "invalid_request", "compact: missing session_id")
        return

    from openprogram.runtime.context.session_db import default_db
    try:
        session_exists = await asyncio.to_thread(
            lambda: default_db().get_session(session_id) is not None,
        )
    except Exception:
        session_exists = False
    if not session_exists:
        await _send_chat_error(
            ws, session_id, "unknown_session", f"compact: unknown session {session_id}",
        )
        return

    agent_id = _db_agent_id(session_id)
    keep_recent_tokens = cmd.get("keep_recent_tokens")
    if keep_recent_tokens is not None:
        try:
            keep_recent_tokens = int(keep_recent_tokens)
        except (TypeError, ValueError):
            keep_recent_tokens = None

    reservation_id = "compact_" + uuid.uuid4().hex[:8]
    if not await asyncio.to_thread(_s._try_reserve_run, session_id, reservation_id):
        # The same frame a failed compaction sends, so the context panel
        # resets its compaction state; nothing touches a queued message.
        await ws.send_text(json.dumps({
            "type": "chat_response",
            "data": {
                "type": "compaction_failed",
                "session_id": session_id,
                "msg_id": "compact",
                "code": "run_active",
                "error": "A turn is running in this conversation; compact after it ends.",
                "user_initiated": True,
            },
        }))
        return

    task = asyncio.create_task(_run_compaction(
        _s, session_id, reservation_id, agent_id, keep_recent_tokens,
    ))
    _compact_tasks.add(task)
    task.add_done_callback(_compact_tasks.discard)


async def _run_compaction(_s, session_id: str, reservation_id: str,
                          agent_id: str, keep_recent_tokens) -> None:
    from openprogram.runtime.conversation.turn_runtime import trigger_compaction

    def _emit(envelope: dict) -> None:
        # Re-shape to the standard chat-response wire frame and
        # broadcast so every connected client sees compaction progress.
        if envelope.get("type") == "chat_response":
            _s._broadcast_chat_response(
                session_id, "compact", envelope.get("data") or {},
            )

    # Compaction is a blocking sync call (it runs an LLM under the hood
    # via its own event loop), so it runs on a worker thread.
    try:
        await asyncio.to_thread(
            trigger_compaction,
            session_id,
            agent_id=agent_id,
            on_event=_emit,
            keep_recent_tokens=keep_recent_tokens,
        )
        await asyncio.to_thread(_s.refresh_context_stats, session_id, "compact")
    except Exception as e:  # noqa: BLE001
        _s._broadcast_chat_response(session_id, "compact", {
            "type": "error",
            "content": f"compact failed: {type(e).__name__}: {e}",
        })
    finally:
        _s._release_run_reservation(session_id, reservation_id)


async def handle_sandbox(ws, cmd: dict):
    """Toggle the system sandbox on or off."""
    from openprogram.host.sandbox import is_enabled, set_mode, unavailable_reason
    current = is_enabled()
    reason = unavailable_reason()
    if not current and reason:
        await ws.send_text(json.dumps({
            "type": "chat_response",
            "data": {"type": "status",
                     "content": f"System sandbox not available ({reason})"},
        }))
        return
    # Persisted through the config, because the agent turn runs in a bare
    # thread that this asyncio task's context never reaches.
    set_mode(not current)
    state = "ON" if not current else "OFF"
    msg = f"Sandbox: {state}"
    if not current:
        msg += (" — bash writes confined to the working directory, "
                "credential paths unreadable, no network")
    await ws.send_text(json.dumps({
        "type": "chat_response",
        "data": {"type": "status", "content": msg},
    }))
