"""Storage layer for the todo planning board.

Session-scoped: todos live in ``<session-repo>/todos.json``, the same
placement pattern as ``inbox.json`` (agent/inbox.py). Each entry:

    id          short incrementing string ("1", "2", …)
    subject     required title
    description optional details
    status      pending | in_progress | completed
    owner       optional free-text claimant
    blocked_by  list of todo ids this entry waits on
    scope       absent for the conversation's own agent, ``agent:<id>``
                for a todo a sub-agent created (its own plan)
    created_at / updated_at  unix timestamps

Beside the board, ``plans`` records where each plan appeared: one entry
per (turn, plan), holding the plan as that turn last left it. The chat
draws each entry under the reply of its ``anchor_id`` turn. A file
without ``plans`` (version 1) reads as a board with no placed plans.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Optional
import logging

_log = logging.getLogger(__name__)

STATUSES = ("pending", "in_progress", "completed")

# Placed plans kept per session; the oldest drop off past this.
MAX_PLANS = 200

# ponytail: one global lock; per-session locks if todo traffic ever matters
_lock = threading.Lock()


def current_session_id() -> Optional[str]:
    try:
        from openprogram.runtime.execution.run_control.binding import (
            _current_session_id,
        )
        return _current_session_id.get(None)
    except Exception:
        return None


def todos_path(session_id: str):
    """Path to the session's todos.json, or None when the session repo
    doesn't exist."""
    from openprogram.runtime.context.session_db import default_db
    sessions = default_db()
    if not sessions._session_dir(session_id).exists():  # noqa: SLF001 — same as inbox.py
        return None
    return sessions.state_file(session_id, "todos.json")


def _read(session_id: str) -> dict[str, Any]:
    path = todos_path(session_id)
    if path is None or not path.exists():
        return {}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return blob if isinstance(blob, dict) else {}


def load(session_id: str) -> list[dict[str, Any]]:
    todos = _read(session_id).get("todos")
    return todos if isinstance(todos, list) else []


def load_plans(session_id: str) -> list[dict[str, Any]]:
    plans = _read(session_id).get("plans")
    if not isinstance(plans, list):
        return []
    return [p for p in plans if isinstance(p, dict) and p.get("anchor_id") and isinstance(p.get("todos"), list)]


def save(session_id: str, todos: list[dict[str, Any]], plans: Optional[list[dict[str, Any]]] = None) -> None:
    """Write the board; ``plans`` omitted keeps the placed plans on file."""
    path = todos_path(session_id)
    if path is None:
        raise ValueError(f"session {session_id!r} not found")
    if plans is None:
        plans = load_plans(session_id)
    payload = {"version": 2, "todos": todos, "plans": plans}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def next_id(todos: list[dict[str, Any]]) -> str:
    highest = 0
    for t in todos:
        try:
            highest = max(highest, int(t.get("id", 0)))
        except (TypeError, ValueError):
            continue
    return str(highest + 1)


def current_anchor() -> Optional[str]:
    """The assistant reply of the turn in flight: the message a plan the
    turn changes is drawn under. None outside a turn."""
    try:
        from openprogram.state.store import _current_turn_id
        raw = _current_turn_id.get() or ""
    except Exception:
        return None
    # A tool run in a function subprocess carries ``<reply>|node:<id>``.
    raw = raw.split("|node:", 1)[0]
    if raw.startswith("pred:"):
        raw = raw[len("pred:"):]
    return raw if raw and raw != "ROOT" else None


def current_scope() -> str:
    """Whose plan a new todo joins: "" for the conversation's own agent,
    ``agent:<id>`` for a sub-agent, so a worker's todos form its own plan."""
    try:
        from openprogram.runtime.agent.turn_request import get_turn_request
        req = get_turn_request()
    except Exception:
        return ""
    if req is None or getattr(req, "source", None) != "agent_spawn":
        return ""
    return f"agent:{getattr(req, 'agent_id', '') or 'agent'}"


def plan_of(todos: list[dict[str, Any]], todo_id: str) -> list[dict[str, Any]]:
    """The plan ``todo_id`` belongs to: its scope's todos in creation order,
    where a todo created once every earlier one was completed starts a new
    plan (the board only grows)."""
    entry = next((t for t in todos if t.get("id") == todo_id), None)
    if entry is None:
        return []
    scope = entry.get("scope") or ""
    ordered = sorted(
        (t for t in todos if (t.get("scope") or "") == scope),
        key=lambda t: (float(t.get("created_at") or 0), _id_order(t)),
    )
    plans: list[list[dict[str, Any]]] = []
    for todo in ordered:
        current = plans[-1] if plans else None
        finished = bool(current) and all(
            item.get("status") == "completed"
            and float(item.get("updated_at") or 0) <= float(todo.get("created_at") or 0)
            for item in current
        )
        if current is None or finished:
            plans.append([todo])
        else:
            current.append(todo)
    return next((plan for plan in plans if any(t.get("id") == todo_id for t in plan)), [])


def _id_order(todo: dict[str, Any]) -> int:
    try:
        return int(todo.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def place_plan(session_id: str, todos: list[dict[str, Any]], todo_id: str) -> list[dict[str, Any]]:
    """Record the plan ``todo_id`` belongs to under the turn that changed it.

    One entry per (turn, plan): a later change in the same turn replaces
    the entry, a change in a later turn adds one, so earlier turns keep the
    plan as they left it. A sub-agent ticking off its parent's todo updates
    the parent's latest entry instead, since that plan is not the
    sub-agent's own. Returns the plans to save."""
    plans = load_plans(session_id)
    plan = plan_of(todos, todo_id)
    anchor = current_anchor()
    if not plan or anchor is None:
        return plans
    plan_id = str(plan[0].get("id"))
    scope = plan[0].get("scope") or ""
    snapshot = [
        {"id": str(t.get("id")), "subject": t.get("subject") or "", "status": t.get("status") or "pending"}
        for t in plan
    ]
    now = time.time()
    if current_scope() != scope:
        owner = next((p for p in reversed(plans) if p.get("plan_id") == plan_id and (p.get("scope") or "") == scope), None)
        if owner is not None:
            owner["todos"], owner["updated_at"] = snapshot, now
            return plans
    for existing in plans:
        if existing.get("anchor_id") == anchor and existing.get("plan_id") == plan_id:
            existing["todos"], existing["updated_at"] = snapshot, now
            return plans
    plans.append({
        "anchor_id": anchor, "plan_id": plan_id, "scope": scope,
        "created_at": now, "updated_at": now, "todos": snapshot,
    })
    return plans[-MAX_PLANS:]


def publish(session_id: str, todos: list[dict[str, Any]], plans: Optional[list[dict[str, Any]]] = None) -> None:
    """Push the saved board and its placed plans to every connected UI tab
    (best-effort — the server may not be running, e.g. pure-CLI use or
    tests). The chat draws each plan under its turn from these frames;
    ``load_session`` hydrates them."""
    try:
        from openprogram.runtime import interface_link
        interface_link.broadcast(
            {"type": "todos_update", "data": {
                "session_id": session_id, "todos": todos,
                "plans": plans if plans is not None else load_plans(session_id),
            }},
        )
    except Exception:
        # No interface may be running (CLI, tests); load_session hydrates the board later.
        _log.debug("todos broadcast failed session=%s", session_id, exc_info=True)


def notify_goal(session_id: str) -> None:
    """Refresh derived Goal progress after saving and releasing the todo lock."""
    from openprogram.programs.tools.planning.goal import chat
    try:
        chat.refresh_todos(session_id)
    except Exception:
        # The todo is already durable; terminal accounting reconciles progress.
        import logging
        logging.getLogger(__name__).exception("Goal todo progress refresh deferred")


def lock() -> threading.Lock:
    return _lock
