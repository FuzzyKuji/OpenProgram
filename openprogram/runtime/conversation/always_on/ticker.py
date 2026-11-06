"""Worker thread that wakes always-on conversations when their next wake is due.

A conversation takes part once it is used after its Agent's always-on was
turned on: it joins with its first wake one interval later, so a chat the
person just opened is never interrupted. Conversations older than that
stay quiet unless they are used again. Archiving a conversation stops its
wakes.
"""
from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger(__name__)

TICK_SECONDS = 30.0
# Conversations of one Agent looked at per tick.
SESSIONS_PER_AGENT = 500


def _enabled_at(spec, now: float) -> float:
    """When always-on was turned on for this Agent, recorded on first sight.

    The save that turned it on is the Agent's latest update, so a
    conversation started between that save and the next tick still joins.
    """
    from openprogram.runtime.conversation.always_on import store
    state = store.load_agent_state(spec.id)
    enabled_at = state.get("enabled_at")
    if not isinstance(enabled_at, (int, float)):
        saved_at = getattr(spec, "updated_at", None)
        enabled_at = min(now, saved_at) if isinstance(saved_at, (int, float)) and saved_at > 0 else now
        store.update_agent_state(spec.id, enabled_at=enabled_at)
        _adopt_home(spec.id, state, now)
    return float(enabled_at)


def _forget_disabled(spec) -> None:
    from openprogram.runtime.conversation.always_on import store
    if store.load_agent_state(spec.id).get("enabled_at") is not None:
        store.update_agent_state(spec.id, enabled_at=None)


def _adopt_home(agent_id: str, state: dict, now: float) -> None:
    """Older versions kept one home conversation per Agent: it keeps waking."""
    from openprogram.runtime.conversation.always_on import store
    from openprogram.runtime.conversation.always_on.runtime import _db
    sid = state.get("home_session_id")
    if not sid or not _db().get_session(sid) or store.load_state(sid):
        return
    store.update_state(sid, joined_at=now, **{
        key: state[key] for key in ("applied_goal", "last_check_in_at", "last_wake", "next_wake_at")
        if state.get(key) is not None})


def due_sessions(now: float) -> list[str]:
    """Conversations of always-on Agents whose next wake has passed."""
    from openprogram.runtime.agent_registry import manager
    from openprogram.runtime.conversation.always_on import store
    from openprogram.runtime.conversation.always_on.runtime import _db, owner_conversation, schedule_next
    due = []
    for spec in manager.list_all():
        config = spec.always_on or {}
        if not config.get("enabled"):
            _forget_disabled(spec)
            continue
        enabled_at = _enabled_at(spec, now)
        try:
            sessions = _db().list_sessions(agent_id=spec.id, limit=SESSIONS_PER_AGENT)
        except Exception:
            continue
        for session in sessions:
            if not owner_conversation(session):
                continue
            sid = str(session["id"])
            state = store.load_state(sid)
            if not state:
                if (session.get("updated_at") or 0) >= enabled_at:
                    schedule_next(sid, config, now, joined_at=now)
                continue
            next_wake = state.get("next_wake_at")
            if not isinstance(next_wake, (int, float)) or next_wake < enabled_at:
                # Turned on again after a pause: start counting from now.
                schedule_next(sid, config, now)
            elif next_wake <= now:
                due.append(sid)
    return due


def tick(now: float | None = None) -> list[dict]:
    from openprogram.runtime.conversation.always_on.runtime import wake
    results = []
    now = time.time() if now is None else now
    for session_id in due_sessions(now):
        try:
            results.append(wake(session_id, reason="schedule", now=now))
        except Exception as exc:  # noqa: BLE001 - one conversation never stops the others
            _log.warning("wake %s failed: %s: %s", session_id, type(exc).__name__, exc, exc_info=True)
    return results


def start_in_worker(interval: float = TICK_SECONDS) -> tuple[threading.Event, threading.Thread]:
    from openprogram.runtime.conversation.always_on import handoff
    try:
        # Chains an earlier worker left keep their hop counts and owed replies.
        handoff.restore()
    except Exception as exc:  # noqa: BLE001
        _log.warning("handoff chains not restored: %s: %s", type(exc).__name__, exc, exc_info=True)
    stop = threading.Event()

    def run():
        while not stop.wait(interval):
            try:
                tick()
            except Exception as exc:  # noqa: BLE001
                _log.warning("tick failed: %s: %s", type(exc).__name__, exc, exc_info=True)

    thread = threading.Thread(target=run, name="always-on-ticker", daemon=True)
    thread.start()
    return stop, thread
