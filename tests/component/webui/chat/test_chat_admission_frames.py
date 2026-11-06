"""What a ``chat`` or ``compact`` request sends back before a turn runs.

Turn-ending errors name the session and carry a message id so the client
can resolve the sent bubble; a ``/skill`` refusal is a local reply, never a
model turn; a committed message reaches the other tabs; ``/compact`` holds
the run slot without holding up the requesting socket.
"""
from __future__ import annotations

import asyncio
import json
import types

import pytest


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def _clear_slot(session_id: str) -> None:
    from openprogram.interfaces.server import server as _s
    with _s._running_tasks_lock:
        _s._running_tasks.pop(session_id, None)


def test_invalid_response_format_error_names_session_and_message():
    from openprogram.interfaces.server.ws_actions.chat import handle_chat

    ws = _FakeWS()
    asyncio.run(handle_chat(ws, {
        "text": "hi", "session_id": "s-format",
        "response_format": {"type": "json_schema", "schema": "not a schema"},
    }))

    data = ws.sent[0]["data"]
    assert data["type"] == "error"
    assert data["session_id"] == "s-format"
    assert data["msg_id"]
    assert data["retry_query"] == "hi"


def test_local_error_frames_carry_a_message_id():
    from openprogram.interfaces.server.ws_actions.chat.turn_local_command import (
        _send_local_error,
    )

    ws = _FakeWS()
    asyncio.run(_send_local_error(ws, "s1", "function_call_failed", "boom"))

    data = ws.sent[0]["data"]
    assert (data["session_id"], data["code"], data["content"]) == (
        "s1", "function_call_failed", "boom")
    assert data["msg_id"]


@pytest.fixture
def chat_env(monkeypatch):
    """A handle_chat with the session and workspace phases stubbed."""
    from openprogram.interfaces.server import server as _s
    import openprogram.runtime.conversation.workspace_alignment as alignment

    appended: list[dict] = []
    monkeypatch.setattr(_s, "_get_or_create_session", lambda sid, **kw: {"id": sid})
    monkeypatch.setattr(alignment, "get_workspace_alignment", lambda sid: {})
    monkeypatch.setattr(
        _s, "_append_msg", lambda conv, msg, **kw: appended.append(msg),
    )
    return appended


@pytest.mark.parametrize("found, code", [
    (None, "skill_not_installed"),
    ("ambiguous", "skill_ambiguous"),
])
def test_unusable_skill_is_a_local_reply_not_a_model_turn(
    monkeypatch, chat_env, found, code,
):
    from openprogram.interfaces.server import server as _s
    from openprogram.interfaces.server.ws_actions.chat import handle_chat
    import openprogram.extensions.skills.loader as loader

    def _resolve(name):
        if found == "ambiguous":
            raise loader.AmbiguousSkillError(name, ["a/x", "b/x"])
        return None

    monkeypatch.setattr(loader, "get_skill", lambda name: None)
    monkeypatch.setattr(loader, "resolve", _resolve)
    session_id = f"skill-{code}"
    _clear_slot(session_id)

    ws = _FakeWS()
    asyncio.run(handle_chat(ws, {"text": "/skill x do it", "session_id": session_id}))

    assert chat_env == []
    assert [f["data"]["type"] for f in ws.sent] == ["local_command"]
    reply = ws.sent[0]["data"]
    assert reply["code"] == code
    assert reply["session_id"] == session_id
    with _s._running_tasks_lock:
        assert session_id not in _s._running_tasks


def test_skill_body_reaches_the_model_only():
    from openprogram.interfaces.server.ws_actions.chat.turn_request import _ChatRequest
    from openprogram.interfaces.server.ws_actions.chat.turn_skill import _skill_model_text

    req = _ChatRequest(
        cmd={}, text="/skill review check src/a.py", session_id="s1",
        agent_id=None, thinking_effort=None, tools_flag=None,
        web_search_flag=None, permission_mode=None, sandbox_flag=None,
        surface_ref=None, service_tier=None, response_format=None,
        attachments=None,
    )
    assert _skill_model_text(req) is None

    req.skill_name = "review"
    req.skill_activation = "Activating skill: **review**\n\nBODY\n\n---\n\n"
    assert _skill_model_text(req) == req.skill_activation + "check src/a.py"
    assert req.text == "/skill review check src/a.py"

    req.text = "/skill review"
    assert _skill_model_text(req).endswith("Please apply the review skill.")


def test_committed_message_is_broadcast_to_other_tabs_only(monkeypatch):
    from openprogram.interfaces.server import server as _s
    from openprogram.interfaces.server.ws_actions.chat.turn import _broadcast_user_message

    sent: list[tuple[dict, object]] = []
    monkeypatch.setattr(
        _s, "_broadcast",
        lambda msg, *, exclude=None: sent.append((json.loads(msg), exclude)),
    )
    sender = object()
    turn = types.SimpleNamespace(session_id="s1", msg_id="m1")

    _broadcast_user_message(_s, sender, turn, {
        "content": "hello", "source": "web", "timestamp": 2.0, "predecessor": "r0",
    })

    frame, excluded = sent[0]
    assert excluded is sender
    assert frame == {"type": "chat_response", "data": {
        "type": "user_message", "session_id": "s1", "msg_id": "m1",
        "content": "hello", "source": "web", "timestamp": 2.0, "predecessor": "r0",
    }}


@pytest.fixture
def compact_env(monkeypatch):
    from openprogram.interfaces.server import server as _s
    import openprogram.runtime.context.session_db as session_db
    import openprogram.runtime.conversation.turn_runtime as turn_runtime
    from openprogram.interfaces.server.ws_actions.chat import commands

    calls: list[str] = []
    monkeypatch.setattr(
        session_db, "default_db",
        lambda: types.SimpleNamespace(get_session=lambda sid: {"id": sid}),
    )
    monkeypatch.setattr(commands, "_db_agent_id", lambda sid: "main")
    monkeypatch.setattr(_s, "refresh_context_stats", lambda *a: None)
    monkeypatch.setattr(
        turn_runtime, "trigger_compaction",
        lambda sid, **kw: calls.append(sid),
    )
    return calls


def test_compact_is_refused_while_a_turn_runs(compact_env):
    from openprogram.interfaces.server import server as _s
    from openprogram.interfaces.server.ws_actions.chat.commands import handle_compact

    session_id = "compact-busy"
    _clear_slot(session_id)
    assert _s._try_reserve_run(session_id, "turn")
    try:
        ws = _FakeWS()
        asyncio.run(handle_compact(ws, {"session_id": session_id}))
    finally:
        _s._release_run_reservation(session_id, "turn")

    assert compact_env == []
    data = ws.sent[0]["data"]
    assert (data["type"], data["code"], data["session_id"]) == (
        "compaction_failed", "run_active", session_id)


def test_compact_holds_the_slot_and_runs_in_the_background(compact_env):
    from openprogram.interfaces.server import server as _s
    from openprogram.interfaces.server.ws_actions.chat import commands

    session_id = "compact-idle"
    _clear_slot(session_id)
    observed: dict = {}

    async def _main():
        ws = _FakeWS()
        await commands.handle_compact(ws, {"session_id": session_id})
        # The handler returned with compaction still pending: the slot is held.
        observed["active"] = _s._is_run_active(session_id)
        await asyncio.gather(*commands._compact_tasks)
        observed["sent"] = ws.sent

    asyncio.run(_main())

    assert observed["active"] is True
    assert observed["sent"] == []
    assert compact_env == [session_id]
    with _s._running_tasks_lock:
        assert session_id not in _s._running_tasks


def test_pre_ack_error_echoes_the_client_request_id(monkeypatch, chat_env):
    from openprogram.interfaces.server import server as _s
    from openprogram.interfaces.server.ws_actions.chat import handle_chat
    from openprogram.interfaces.server.ws_actions.chat.turn_request import _client_request_id

    monkeypatch.setattr(_s, "_try_reserve_run", lambda sid, mid: False)
    ws = _FakeWS()
    asyncio.run(handle_chat(ws, {
        "text": "hi", "session_id": "s-echo", "client_request_id": "req-7",
    }))

    data = ws.sent[0]["data"]
    assert (data["code"], data["client_request_id"]) == ("run_active", "req-7")
    assert _client_request_id.get() is None

    ws = _FakeWS()
    asyncio.run(handle_chat(ws, {"text": "hi", "session_id": "s-echo"}))
    assert "client_request_id" not in ws.sent[0]["data"]
