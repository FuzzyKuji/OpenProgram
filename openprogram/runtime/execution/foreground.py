"""Read-only foreground controls derived from durable Agent executions."""
from __future__ import annotations

from .model import ExecutionRecord, ExecutionStatus, TERMINAL_EXECUTION_STATUSES

# A turn paused at one of these waits is still the conversation's turn: the
# user answers its question or approval and the same execution continues.
# Any other pause (an explicit Pause) hands the conversation back.
WAITING_PAUSE_REASONS = frozenset({"wait_open", "system_access_required"})

#: Sources that are chat channels.
CHANNEL_SOURCES = frozenset({"telegram", "discord", "slack", "wechat"})
# A chat app's turn is a foreground turn like a typed one. When it pauses at a
# question or approval its receiving thread ends and frees the run slot, so
# only this record keeps another turn from starting on top of it.
FOREGROUND_SOURCES = frozenset({"web", "tui", "acp"}) | CHANNEL_SOURCES


def foreground_task_snapshot(store, execution: ExecutionRecord) -> dict | None:
    """Return controls for an active interactive turn, never a background Job."""
    if execution.status in TERMINAL_EXECUTION_STATUSES:
        return None
    if (execution.status is ExecutionStatus.PAUSED
            and execution.reason_code not in WAITING_PAUSE_REASONS):
        return None
    if (execution.status is ExecutionStatus.RECONCILIATION_REQUIRED
            and execution.current_attempt_id is None):
        return None
    payload = store.get_agent_turn_input(execution.execution_id)
    if payload is None:
        return None
    request = payload.get("request", {}) if payload.get("kind") == "chat" else payload
    if request.get("source") not in FOREGROUND_SOURCES:
        return None
    if request.get("interaction") not in {None, "interactive"}:
        return None
    source = store.get_execution_input(execution.execution_id)
    if source is None or not source.user_message_id:
        return None
    return {
        "session_id": execution.session_id,
        "msg_id": source.user_message_id,
        "execution_id": execution.execution_id,
        "status_version": execution.status_version,
        "status": execution.status.value,
        "reason_code": execution.reason_code,
        "func_name": "agent" if payload.get("kind") == "chat" else payload.get("tool_name", "function"),
        "started_at": execution.created_at,
    }


def active_foreground_task(store, session_id: str) -> dict | None:
    """Prefer the newest admitted foreground turn when branches share a session."""
    for execution in reversed(store.list_nonterminal(session_id=session_id)):
        task = foreground_task_snapshot(store, execution)
        if task is not None:
            return task
    return None
