"""Wake an always-on conversation: start its standing Goal or a read-only check-in.

Always-on is part of an Agent's configuration; the conversations that use
the Agent are what wake. Each keeps its own Goal, check-ins and reports.

Design: docs/reference/design/runtime/always-on-agents.md
"""
from __future__ import annotations

import logging
import time
from typing import Any

from openprogram.runtime.conversation.always_on import schedule, store

_log = logging.getLogger(__name__)

# Sessions a person talks in: web chats (stored with an empty source), the
# home conversations older versions created, and channel conversations.
# Sub-agent and imported conversations never wake.
OWNER_SOURCES = {None, "", "web", "always_on"}
# Turns themselves are ordinary owner chat turns (source "web"), so Goal
# continuation, verification and approval cards treat them like any chat
# the owner started.
TURN_SOURCE = "web"

# Goals the runtime may replace. ``goal.chat.create`` refuses any other status.
GOAL_ENDED = {"achieved", "cancelled", "cleared", "impossible"}

CHECK_IN_TOOLS = (
    "read", "grep", "glob", "list", "web_search", "web_fetch",
    "read_conversation", "memory_search", "memory_get",
    "todo_list", "open_work", "get_goal", "always_on_report",
)
ACT_TOOLS = ("create_goal", "todo_create", "todo_update", "handoff")


class WakeRefused(ValueError):
    """The conversation cannot be woken (unknown, or its Agent is not always-on)."""


def _agent(agent_id: str):
    from openprogram.runtime.agent_registry import manager
    return manager.get(agent_id)


def _db():
    from openprogram.runtime.context.session_db import default_db
    return default_db()


def _broadcast(frame: dict[str, Any]) -> None:
    try:
        from openprogram.runtime import interface_link
        interface_link.broadcast(frame)
    except Exception:
        # Live UI refresh only; clients re-read always-on state on reconnect.
        _log.debug("always-on frame broadcast failed: %s", frame.get("type"), exc_info=True)


def _mark_unread(session_id: str) -> None:
    """A report shows as the sidebar's unread dot at once, not only when its turn ends."""
    try:
        from openprogram.runtime.conversation.turn_runtime.turn_writer import mark_session_unread
        mark_session_unread(_db(), session_id)
    except Exception as exc:  # noqa: BLE001 - the report is saved either way
        _log.warning("unread mark for %s failed: %s: %s", session_id, type(exc).__name__, exc)


def owner_conversation(session: dict | None) -> bool:
    """A conversation a person talks in, still in the sidebar."""
    return bool(session) and not session.get("archived") and (
        session.get("source") in OWNER_SOURCES or bool(session.get("channel")))


def _session_and_agent(session_id: str):
    try:
        session = _db().get_session(session_id)
    except Exception:
        session = None
    if not owner_conversation(session):
        return session, None
    return session, _agent(str(session.get("agent_id") or "main"))


def agent_for_session(session_id: str) -> str | None:
    """The always-on Agent this conversation uses, if any."""
    _session, spec = _session_and_agent(session_id)
    return spec.id if spec is not None and (spec.always_on or {}).get("enabled") else None


def _goal(session_id: str) -> dict | None:
    import openprogram.programs.tools.planning.goal as goals
    return goals.load_goal(session_id)


def _turn_running(session_id: str) -> bool:
    from openprogram.runtime.conversation.run_control import is_turn_running
    return is_turn_running(session_id)


def _start_turn(session_id: str, agent_id: str, text: str, tools: list[str]) -> str:
    """One owner chat turn in the conversation, under its own permissions.

    A check-in tells the owner only through ``always_on_report``, which
    marks the conversation unread itself; one that finds nothing ends
    without the unread dot.
    """
    from openprogram.runtime.conversation.owner_turn import start_owner_turn
    return start_owner_turn(session_id, agent_id, text, tools=tools, name="always-on",
                            reason_code="always_on_activation_failed", quiet_finish=True)


def check_in_prompt(config: dict, last_check_in: float | None, now: float) -> str:
    if last_check_in:
        minutes = max(1, int((now - last_check_in) // 60))
        since = f"Your previous check-in was {minutes} minutes ago."
    else:
        since = "This is your first check-in."
    goal = config.get("goal") or ""
    lines = [
        "Always-on check-in. " + since,
        f"Standing goal: {goal}" if goal else "You have no standing goal; watch for what matters to the user.",
        "Review your memory, your open work and this conversation for open threads, then look for "
        "anything new that matters, using only the read-only tools you have now.",
        "If you found something the user should see, call always_on_report once with a short "
        "title, the essentials and any links. If nothing is worth reporting, say so in one line "
        "and do not report.",
    ]
    if config.get("autonomy") == "act":
        lines.append(
            "If a finding needs real work, you may create a Goal for it with create_goal and plan it "
            "with the todo tools; it runs next under your normal permissions. When another of the "
            "user's conversations owns that kind of work, hand it over with handoff instead. "
            "Report what you started."
        )
    else:
        lines.append("Do not start work yourself; propose it in a report instead.")
    return "\n".join(lines)


def wake(session_id: str, reason: str = "manual", now: float | None = None) -> dict[str, Any]:
    """Run one wake decision for a conversation. Records the outcome and the next wake."""
    session, spec = _session_and_agent(session_id)
    if session is None:
        raise WakeRefused(f"Unknown conversation {session_id!r}")
    if spec is None:
        raise WakeRefused("This conversation does not wake")
    config = dict(spec.always_on or {})
    now = time.time() if now is None else now
    if not config.get("enabled"):
        if reason == "manual":
            raise WakeRefused("Always-on is off for this conversation's Agent")
        return _record(session_id, spec.id, config, now, reason, "disabled")
    if reason != "manual" and schedule.is_quiet(now, config):
        # Saved before quiet hours were set, or the clock moved: skip to
        # the end of the quiet stretch. Wake now always runs.
        return _record(session_id, spec.id, config, now, reason, "quiet",
                       next_at=schedule.next_allowed(now, config))
    with store.lock(session_id):
        state = store.load_state(session_id)
        if _turn_running(session_id):
            return _record(session_id, spec.id, config, now, reason, "busy")
        goal = _goal(session_id)
        standing = (config.get("goal") or "").strip()
        applied = (state.get("applied_goal") or {}).get("text")
        unfinished = goal is not None and goal.get("status") not in GOAL_ENDED
        if standing and standing != applied and not unfinished:
            from openprogram.programs.tools.planning.goal import chat
            created = chat.create(session_id, standing, origin="always_on")
            store.update_state(session_id, applied_goal={"text": standing, "goal_id": created.get("goal_id")})
            chat.start_from_controls(session_id, source=TURN_SOURCE)
            return _record(session_id, spec.id, config, now, reason, "goal_started")
        if unfinished:
            status_text = str(goal.get("status") or "")
            outcome = "goal_paused" if status_text.startswith("paused") or goal.get("stop_requested") else "goal_in_progress"
            return _record(session_id, spec.id, config, now, reason, outcome)
        if not config.get("research", True):
            return _record(session_id, spec.id, config, now, reason, "idle")
        tools = list(CHECK_IN_TOOLS) + (list(ACT_TOOLS) if config.get("autonomy") == "act" else [])
        from openprogram.runtime.conversation.run_control.run_slot import RunSlotBusy
        try:
            _start_turn(session_id, spec.id, check_in_prompt(config, state.get("last_check_in_at"), now), tools)
        except RunSlotBusy:
            # A turn took the conversation after the check above; the next
            # wake tries again.
            return _record(session_id, spec.id, config, now, reason, "busy")
        store.update_state(session_id, last_check_in_at=now)
        return _record(session_id, spec.id, config, now, reason, "check_in")


def next_wake_after(config: dict, now: float) -> float:
    """One interval from ``now``, moved past quiet hours and days without wakes."""
    minutes = int(config.get("wake_minutes") or 60)
    return schedule.next_allowed(now + minutes * 60, config)


def schedule_next(session_id: str, config: dict, now: float, *, next_at: float | None = None,
                  **changes: Any) -> dict[str, Any]:
    if not config.get("enabled"):
        next_at = None
    elif next_at is None:
        next_at = next_wake_after(config, now)
    return store.update_state(session_id, next_wake_at=next_at, **changes)


def join(session_id: str, now: float | None = None) -> dict[str, Any] | None:
    """Start waking a conversation that was just switched to an always-on Agent.

    Picking the Agent counts as using the conversation, so it joins at once
    and its first wake comes one interval later.
    """
    _session, spec = _session_and_agent(session_id)
    config = (spec.always_on or {}) if spec is not None else {}
    if not config.get("enabled"):
        return None
    now = time.time() if now is None else now
    state = schedule_next(session_id, config, now, joined_at=now)
    _broadcast({"type": "always_on_update", "data": {"session_id": session_id, "agent_id": spec.id}})
    return state


def _record(session_id: str, agent_id: str, config: dict, now: float, reason: str,
            outcome: str, next_at: float | None = None) -> dict[str, Any]:
    state = schedule_next(session_id, config, now, next_at=next_at,
                          last_wake={"at": now, "reason": reason, "outcome": outcome})
    _broadcast({"type": "always_on_update", "data": {"session_id": session_id, "agent_id": agent_id}})
    return {"session_id": session_id, "agent_id": agent_id, "outcome": outcome,
            "next_wake_at": state.get("next_wake_at")}


def status(session_id: str, *, report_limit: int = 20) -> dict[str, Any]:
    """The conversation's always-on state, as its Activity panel shows it."""
    session, spec = _session_and_agent(session_id)
    if session is None:
        raise WakeRefused(f"Unknown conversation {session_id!r}")
    config = dict(spec.always_on or {}) if spec is not None else {}
    enabled = bool(config.get("enabled"))
    state = store.load_state(session_id)
    goal = _goal(session_id) if enabled else None
    next_wake = state.get("next_wake_at") if enabled else None
    if isinstance(next_wake, (int, float)):
        # A wake saved before quiet hours were set is skipped to their end.
        next_wake = schedule.next_allowed(next_wake, config)
    return {
        "session_id": session_id,
        "agent_id": spec.id if spec is not None else None,
        "agent_name": (spec.name or spec.id) if spec is not None else None,
        "enabled": enabled,
        "config": {key: config.get(key) for key in (
            "goal", "wake_minutes", "research", "autonomy", "quiet_hours", "wake_days")} if enabled else None,
        "running": enabled and _turn_running(session_id),
        "goal": {"text": goal.get("text"), "status": goal.get("status")} if goal else None,
        "last_wake": state.get("last_wake"),
        "next_wake_at": next_wake,
        "quiet_now": enabled and schedule.is_quiet(time.time(), config),
        "reports": store.load_reports(session_id, report_limit),
    }


def report(session_id: str, title: str, body: str, links: Any = None) -> dict[str, Any]:
    """Record a report in the conversation, tell every client, and send it to
    the Agent's chosen channel conversations in the background."""
    from openprogram.runtime.conversation.always_on import delivery

    agent_id = agent_for_session(session_id)
    if agent_id is None:
        raise ValueError("always_on_report works only in a conversation whose Agent is always-on")
    spec = _agent(agent_id)
    name = spec.name or spec.id
    targets = list((spec.always_on or {}).get("channels") or [])
    row = store.add_report(session_id, title=title, body=body, links=links,
                           deliveries=delivery.pending(targets))
    _broadcast({"type": "always_on_report", "data": {
        "agent_id": agent_id, "agent_name": name, "session_id": session_id, "report": row,
    }})
    _mark_unread(session_id)
    delivery.deliver(session_id, name, row, on_done=lambda _row: _broadcast({
        "type": "always_on_update", "data": {"session_id": session_id, "agent_id": agent_id},
    }))
    return row
