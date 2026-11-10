"""The ``chat`` action's first phases: parse the command into a turn request.

``_ChatRequest`` carries what the client asked for between the phases of
:func:`~.turn.handle_chat`; later phases update ``text``, the tool flags and
the attachments in place as the message is expanded and persisted.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from .message_input import _with_recording


# The ``client_request_id`` of the ``chat`` command being handled. Every
# frame that answers the send before its ``chat_ack`` (and the ack itself)
# echoes it, so a client rejects only the pending send it belongs to.
_client_request_id: ContextVar[str | None] = ContextVar(
    "chat_client_request_id", default=None,
)


def client_request_id_of(cmd: dict) -> str | None:
    value = cmd.get("client_request_id")
    return value if isinstance(value, str) and 0 < len(value) <= 128 else None


def _with_client_request_id(data: dict) -> dict:
    request_id = _client_request_id.get()
    if request_id is not None:
        data["client_request_id"] = request_id
    return data


def _chat_error_data(session_id: str | None, code: str, content: str, *,
                     retry_query: str | None = None, **extra: Any) -> dict:
    """The ``chat_response`` error payload that ends a chat turn early.

    The client resolves its pending user bubble only from a frame that
    names the session and carries a message id, so every turn-ending
    error has both. The id is fresh: no reply row stands behind it.
    """
    data = {
        "type": "error",
        "session_id": session_id,
        "msg_id": uuid.uuid4().hex,
        "code": code,
        "content": content,
        "timestamp": time.time(),
        **extra,
    }
    if retry_query is not None:
        data["retry_query"] = retry_query
    return _with_client_request_id(data)


async def _send_chat_error(ws, session_id: str | None, code: str, content: str, *,
                           retry_query: str | None = None, **extra: Any) -> None:
    await ws.send_text(json.dumps({
        "type": "chat_response",
        "data": _chat_error_data(
            session_id, code, content, retry_query=retry_query, **extra,
        ),
    }, default=str))


@dataclass
class _ChatRequest:
    cmd: dict
    text: str
    session_id: str | None
    agent_id: str | None
    thinking_effort: str | None
    tools_flag: list | None
    web_search_flag: bool | None
    permission_mode: str | None
    sandbox_flag: Any
    surface_ref: dict | None
    service_tier: str | None
    response_format: Any
    attachments: list | None
    recording_meta: Any = None
    recording_images: list = field(default_factory=list)
    agent_invocation: dict | None = None
    requested_environment: str | None = None
    project_id: str | None = None
    # The attachments the user sent, before recording frames are appended.
    user_attachments: list | None = None
    # A ``/skill`` message's SKILL.md activation block, read by the model
    # only; the typed message stays the visible one.
    skill_name: str | None = None
    skill_activation: str | None = None


async def _parse_chat_command(ws, cmd: dict) -> _ChatRequest | None:
    """Read the composer's fields. ``None`` means the turn stops here."""
    text = cmd.get("text", "").strip()
    session_id = cmd.get("session_id")
    agent_id = cmd.get("agent_id") or None
    thinking_effort = cmd.get("thinking_effort") or None
    # The Agent's configuration decides the tool set; a turn only narrows
    # it to a /skill's allowed-tools (below) or overlays web search.
    tools_flag = None
    web_search_flag = bool(cmd.get("web_search"))
    from openprogram.runtime.permissions.modes import (
        normalize_permission as _normalize_permission,
    )
    _raw_perm = cmd.get("permission_mode")
    if _raw_perm is None or (
        isinstance(_raw_perm, str) and _raw_perm.strip().lower() in ("", "inherit")
    ):
        permission_mode = None
    else:
        # An illegal value is treated like no value: the turn inherits.
        permission_mode = _normalize_permission(_raw_perm)
    sandbox_flag = cmd.get("sandbox_enabled") if "sandbox_enabled" in cmd else None
    surface_ref = cmd.get("surface") if isinstance(cmd.get("surface"), dict) else None
    # Per-turn speed / priority tier from the composer's speed pill
    # ("priority" = Fast, "flex" = cheaper-slower). Rides the message
    # payload each turn (client remembers via localStorage like the
    # thinking pill) — no server-side persistence / DB column needed.
    service_tier = cmd.get("service_tier") or None
    response_format = None
    if cmd.get("response_format") is not None:
        from openprogram.models.providers.structured_output import (
            StructuredOutputError,
            normalize_response_format,
        )
        try:
            response_format = normalize_response_format(cmd["response_format"])
        except StructuredOutputError as exc:
            await _send_chat_error(
                ws, session_id, exc.code, "Structured output request is invalid",
                retry_query=text, issues=exc.issues,
            )
            return None
    raw_attachments = cmd.get("attachments") or None
    attachments = None
    if raw_attachments is not None and (not isinstance(raw_attachments, list) or len(raw_attachments) > 20):
        raise ValueError("Attachments must be a list of at most 20 files")
    if isinstance(raw_attachments, list) and raw_attachments:
        if any(not isinstance(a, dict) or not isinstance(a.get("data"), str)
               for a in raw_attachments):
            raise ValueError("Invalid attachment payload")
        attachments = raw_attachments
    recording_meta = None
    recording_images: list = []
    if cmd.get("recording") is not None:
        text, recording_meta, recording_images = await asyncio.to_thread(
            _with_recording, text, cmd.get("recording"))
    if not text and not attachments:
        return None
    if not text and attachments:
        text = "(see attachment)"
    return _ChatRequest(
        cmd=cmd,
        text=text,
        session_id=session_id,
        agent_id=agent_id,
        thinking_effort=thinking_effort,
        tools_flag=tools_flag,
        web_search_flag=web_search_flag,
        permission_mode=permission_mode,
        sandbox_flag=sandbox_flag,
        surface_ref=surface_ref,
        service_tier=service_tier,
        response_format=response_format,
        attachments=attachments,
        recording_meta=recording_meta,
        recording_images=recording_images,
    )


async def _prepare_agent_and_environment(ws, req: _ChatRequest) -> bool:
    """Validate the Agent invocation and the environment pick.

    Returns ``False`` after sending the error frame that stops the turn.
    """
    cmd = req.cmd
    from ..agent_invocation import AgentInvocationError, prepare_agent_invocation
    try:
        req.agent_invocation = prepare_agent_invocation(cmd)
    except AgentInvocationError as exc:
        await _send_chat_error(
            ws, req.session_id, exc.code, str(exc), retry_query=req.text,
        )
        return False
    # Environment pick for a brand-new conversation. Validated before any
    # state changes; an existing conversation ignores it (environments are
    # chosen once, at creation).
    requested_environment = (cmd.get("environment_id") or "").strip() or None
    req.requested_environment = requested_environment
    if requested_environment is not None:
        from openprogram.host.environments import get_environment
        if get_environment(requested_environment) is None:
            await _send_chat_error(
                ws, req.session_id, "unknown_environment",
                (f"Environment {requested_environment!r} no longer exists. "
                 "Pick another one in the composer."),
                retry_query=req.text,
            )
            return False
    if req.agent_invocation is not None:
        # A new Agent conversation starts from its configuration. Unrelated
        # composer defaults must not replace the Agent's effort or tools.
        req.thinking_effort = (
            req.agent_invocation["profile_snapshot"].get("thinking_effort") or None
        )
        req.tools_flag = None
        req.web_search_flag = None
    return True
