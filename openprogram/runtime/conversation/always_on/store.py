"""Runtime state and reports of always-on conversations.

A conversation whose Agent is always-on keeps its own wake state and
reports next to its messages: ``<session dir>/always_on.json`` and
``always_on_reports.jsonl``, written atomically under a per-conversation
lock. The Agent keeps only one fact of its own, when always-on was turned
on (``<agent dir>/always_on/state.json``), which decides the conversations
that take part. Handoff chains, which span conversations, live in one file
for the worker (``<state dir>/always_on/handoffs.json``). None touches ``agent.json``, so wakes never bump the
configuration revision or conflict with an open editor draft.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

MAX_REPORTS = 200
TITLE_MAX = 200
BODY_MAX = 8000
LINKS_MAX = 10

_locks: dict[str, threading.RLock] = {}
_locks_master = threading.Lock()


def lock(key: str) -> threading.RLock:
    with _locks_master:
        return _locks.setdefault(key, threading.RLock())


def directory(session_id: str) -> Path | None:
    """The conversation's directory; None when the conversation is gone."""
    from openprogram.runtime.context.session_db import default_db
    folder = default_db()._session_dir(session_id)  # noqa: SLF001 — beside todos.json
    return folder if folder.exists() else None


def _agent_state_path(agent_id: str) -> Path:
    from openprogram.runtime.agent_registry.manager import agent_dir
    return agent_dir(agent_id) / "always_on" / "state.json"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _state_path(session_id: str) -> Path | None:
    folder = directory(session_id)
    return folder / "always_on.json" if folder else None


def _reports_path(session_id: str) -> Path | None:
    folder = directory(session_id)
    return folder / "always_on_reports.jsonl" if folder else None


def load_state(session_id: str) -> dict[str, Any]:
    return _read_json(_state_path(session_id))


def update_state(session_id: str, **changes: Any) -> dict[str, Any]:
    with lock(session_id):
        path = _state_path(session_id)
        if path is None:
            raise ValueError(f"conversation {session_id!r} not found")
        state = load_state(session_id)
        state.update(changes)
        _write_json(path, state)
        return state


def _handoffs_path() -> Path:
    from openprogram.state.paths import get_state_dir
    return get_state_dir() / "always_on" / "handoffs.json"


def load_handoffs() -> dict[str, Any]:
    """The handoff chains' turns, by user message id (see ``handoff.py``)."""
    return _read_json(_handoffs_path())


def save_handoffs(chains: dict[str, Any]) -> None:
    with lock("handoffs"):
        _write_json(_handoffs_path(), chains)


def load_agent_state(agent_id: str) -> dict[str, Any]:
    return _read_json(_agent_state_path(agent_id))


def update_agent_state(agent_id: str, **changes: Any) -> dict[str, Any]:
    with lock("agent:" + agent_id):
        state = load_agent_state(agent_id)
        state.update(changes)
        _write_json(_agent_state_path(agent_id), state)
        return state


def load_reports(session_id: str, limit: int = MAX_REPORTS) -> list[dict[str, Any]]:
    """Newest first."""
    path = _reports_path(session_id)
    if path is None:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _clean_links(links: Any) -> list[str]:
    if not isinstance(links, list):
        return []
    return [str(link).strip()[:2000] for link in links if str(link).strip()][:LINKS_MAX]


def add_report(session_id: str, *, title: str, body: str, links: Any = None,
               deliveries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        raise ValueError("A report needs a title")
    report = {
        "id": uuid.uuid4().hex,
        "at": time.time(),
        "title": title[:TITLE_MAX],
        "body": str(body or "").strip()[:BODY_MAX],
        "links": _clean_links(links),
        "session_id": session_id,
    }
    if deliveries:
        report["deliveries"] = deliveries
    with lock(session_id):
        _write_reports(session_id, [*reversed(load_reports(session_id, MAX_REPORTS - 1)), report])
    return report


def update_report(session_id: str, report_id: str, **changes: Any) -> dict[str, Any] | None:
    """Merge ``changes`` into one stored report; None when it was trimmed away."""
    with lock(session_id):
        rows = list(reversed(load_reports(session_id, MAX_REPORTS)))
        for row in rows:
            if row.get("id") == report_id:
                row.update(changes)
                _write_reports(session_id, rows)
                return row
    return None


def _write_reports(session_id: str, rows: list[dict[str, Any]]) -> None:
    """Oldest first, one JSON object per line."""
    path = _reports_path(session_id)
    if path is None:
        raise ValueError(f"conversation {session_id!r} not found")
    descriptor, temporary = tempfile.mkstemp(prefix="reports.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
