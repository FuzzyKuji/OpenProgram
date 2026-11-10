"""The ``chat`` action: admission, reservation and turn execution.

:func:`handle_chat` runs the turn as a sequence of phases. Parsing lives in
``turn_request``, the ``/skill`` expansion in ``turn_skill``, local builtin
commands in ``turn_local_command`` and the running-task hand-off and run
thread in ``turn_launch``; this module keeps the session, reservation,
run-config and admission phases.
"""
from __future__ import annotations

import logging
import asyncio
import json
import time
import uuid

from .session_agent import _db_agent_id
from .context_usage import _record_context_usage
from .attachments import _persist_attachments_async
from .attachments import _attachments_for_dispatch
from .message_input import _title_from_text
from .message_input import _pasted_text_elements
from .turn_request import _ChatRequest
from .turn_request import _send_chat_error
from .turn_request import _client_request_id
from .turn_request import _with_client_request_id
from .turn_request import client_request_id_of
from .turn_request import _parse_chat_command
from .turn_request import _prepare_agent_and_environment
from .turn_skill import _expand_skill_command
from .turn_skill import _is_skill_command
from .turn_skill import _skill_model_text
from .turn_local_command import _run_local_command
from .turn_launch import _AdmittedTurn
from .turn_launch import _publish_running_task
from .turn_launch import _start_run_thread

_log = logging.getLogger(__name__)


async def handle_chat(ws, cmd: dict):
    token = _client_request_id.set(client_request_id_of(cmd))
    try:
        await _handle_chat(ws, cmd)
    finally:
        _client_request_id.reset(token)


async def _handle_chat(ws, cmd: dict):
    from openprogram.interfaces.server import server as _s
    req = await _parse_chat_command(ws, cmd)
    if req is None:
        return
    if not await _prepare_agent_and_environment(ws, req):
        return
    # Session open, run config, admission and the user-message commit read
    # and write the session repo and the execution store. They run off the
    # event loop so one send never stalls every other socket.
    conv = await asyncio.to_thread(_open_session, _s, req)
    if not _is_skill_command(req.text) and not await _run_local_command(ws, req):
        return
    if not await _check_workspace_alignment(ws, req):
        return
    msg_id = await _reserve_run(ws, _s, req)
    if msg_id is None:
        return
    if not await _admit_skill_command(ws, _s, req, msg_id):
        return
    run_cfg, effective_permission = await asyncio.to_thread(
        _save_run_config, _s, req, conv, msg_id,
    )
    await _persist_turn_attachments(_s, req, msg_id)
    turn, user_msg = await asyncio.to_thread(
        _admit_and_commit, _s, ws, req, conv, msg_id, run_cfg, effective_permission,
    )
    _broadcast_user_message(_s, ws, turn, user_msg)
    await _send_chat_ack(ws, req, turn, effective_permission)
    _publish_running_task(_s, turn)
    _start_run_thread(_s, turn)


def _admit_and_commit(_s, ws, req: _ChatRequest, conv: dict, msg_id: str,
                      run_cfg, effective_permission):
    """Admit the turn and commit its user message; ``(turn, user_msg)``."""
    _backfill_title(req)
    parsed, local_authority, surface_context, release_surface = (
        _capture_turn_inputs(_s, ws, req, msg_id)
    )
    user_msg = _build_user_msg(req, msg_id, parsed, local_authority)
    turn = _admit_turn(
        _s, req, conv, msg_id, run_cfg, effective_permission,
        parsed, local_authority, surface_context, release_surface,
    )
    _commit_user_message(_s, req, turn, user_msg)
    return turn, user_msg


def _broadcast_user_message(_s, ws, turn: _AdmittedTurn, user_msg: dict) -> None:
    """Show the committed message in every other tab on this session.

    The sender already holds the bubble and learns its id from
    ``chat_ack``, so it is left out.
    """
    try:
        _s._broadcast(json.dumps({
            "type": "chat_response",
            "data": {
                "type": "user_message",
                "session_id": turn.session_id,
                "msg_id": turn.msg_id,
                "content": user_msg.get("content") or "",
                "source": user_msg.get("source"),
                "timestamp": user_msg.get("timestamp"),
                "predecessor": user_msg.get("predecessor"),
            },
        }, default=str), exclude=ws)
    except Exception:
        # Peers catch up on their next load; the turn itself is committed.
        _log.debug(
            "user_message not broadcast for session %s", turn.session_id, exc_info=True)


def _open_session(_s, req: _ChatRequest) -> dict:
    cmd = req.cmd
    new_channel = (cmd.get("channel") or "").strip().lower() or None
    new_account_id = (cmd.get("account_id") or "").strip() or None
    new_peer = (cmd.get("peer") or "").strip() or None
    conv = _s._get_or_create_session(
        req.session_id,
        agent_id=req.agent_id,
        channel=new_channel,
        account_id=new_account_id,
        peer=new_peer,
    )
    session_id = req.session_id = conv["id"]

    # Project binding MUST happen before the first DB write below (the
    # title backfill / run-config / _append_msg all update_session with
    # create_if_missing=True, which would materialise the session repo
    # at the home root). create_session is the only path that can place
    # the repo inside the project (<project>/.openprogram/sessions/<id>/),
    # so when the composer sent the picker's project_id with the first
    # message, create the session with it right here. A draft whose
    # settings were already stored (a model pick) has a repo but is not
    # created yet, so the check is ``is_created``. Existing sessions
    # are untouched — mid-chat project switches go through
    # set_session_project and never move the repo.
    project_id = req.project_id = (cmd.get("project_id") or "").strip() or None
    if project_id:
        try:
            from openprogram.runtime.context.session_db import default_db as _proj_db
            _pdb = _proj_db()
            if not _pdb.is_created(session_id):
                _pdb.create_session(
                    session_id,
                    req.agent_id or _s._default_agent_id(),
                    project_id=project_id,
                )
        except Exception:
            # The turn proceeds; the first save creates the row without the
            # project.
            _log.warning(
                "project session row not created for %s", session_id, exc_info=True)
    return conv


async def _check_workspace_alignment(ws, req: _ChatRequest) -> bool:
    # A conversation-only checkout deliberately leaves files untouched.
    # The next mutating turn must adopt that workspace explicitly; otherwise
    # the model would edit one branch while reading another branch's history.
    session_id = req.session_id
    from openprogram.runtime.conversation.workspace_alignment import (
        adopt_current_workspace,
        get_workspace_alignment,
    )
    alignment = await asyncio.to_thread(get_workspace_alignment, session_id)
    if alignment.get("status") == "mismatch":
        if req.cmd.get("workspace_decision") == "keep_current_files":
            alignment = await asyncio.to_thread(adopt_current_workspace, session_id)
        if alignment.get("status") == "mismatch":
            await _send_chat_error(
                ws, session_id, "workspace_alignment_required",
                ("Conversation and workspace are not aligned. "
                 "Choose Keep current files or Restore branch code first."),
                retry_query=req.text,
                workspace_alignment=alignment, display="chat",
            )
            return False
    return True


async def _reserve_run(ws, _s, req: _ChatRequest) -> str | None:
    """Reserve the session's run slot; the turn's message id, or ``None``."""
    # Run-active guard — the last unguarded HEAD-moving entry point
    # (fn-form dispatch, retry/edit, checkout, merge, rewind all check
    # _is_run_active already). Without it, two clients racing on one
    # session dispatch two turns that _append_msg + advance the same
    # HEAD concurrently and interleave the conversation chain. The
    # frontend routes to either its queue or the explicit ``steer`` action
    # when it knows a run is active; this covers the race window it cannot
    # see. A concurrent ordinary ``chat`` remains a queue fallback, never an
    # implicit steer, so the user's selected running-message mode stays exact.
    session_id = req.session_id
    msg_id = uuid.uuid4().hex
    from openprogram.programs.tools.planning.goal.chat import note_user_waiting
    if not await asyncio.to_thread(_s._try_reserve_run, session_id, msg_id):
        # The client re-queues this message; an automatic Goal turn yields to it.
        note_user_waiting(session_id, True)
        await _send_chat_error(
            ws, session_id, "run_active", _s.RUN_ACTIVE_ERROR,
            retry_query=req.text, display="chat",
        )
        return None
    return msg_id


async def _admit_skill_command(ws, _s, req: _ChatRequest, msg_id: str) -> bool:
    """Expand a ``/skill`` message inside the turn's reservation.

    An unknown, ambiguous or blocked skill ends the turn with a local
    reply; it never becomes a model turn about the failure.
    """
    try:
        refusal = await asyncio.to_thread(_expand_skill_command, req)
    except BaseException:
        _s._release_run_reservation(req.session_id, msg_id)
        raise
    if refusal is None:
        return True
    _s._release_run_reservation(req.session_id, msg_id)
    code, content = refusal
    await ws.send_text(json.dumps({
        "type": "chat_response",
        "data": _with_client_request_id({
            "type": "local_command",
            "session_id": req.session_id,
            "command": "skill",
            "code": code,
            "error": True,
            "content": content,
        }),
    }))
    return False


def _save_run_config(_s, req: _ChatRequest, conv: dict, msg_id: str):
    """Persist the session and its run settings; ``(run_cfg, permission)``."""
    session_id = req.session_id
    try:
        from openprogram.runtime.conversation.session_config import (
            permission_from_config,
            project_defaults,
            save_session_run_config,
        )
        # This is an accepted message, not an unsent composer draft. Persist
        # its session before saving settings so a first-turn Bypass selection
        # (and other run settings) survives refresh without a project binding.
        from openprogram.runtime.context.session_db import default_db
        session_db = default_db()
        if not session_db.is_created(session_id):
            session_db.create_session(session_id, req.agent_id or _s._default_agent_id(),
                                      project_id=req.project_id)
            _bind_draft_channel(_s, req)
        from openprogram.host.environments import assign_new_session_environment
        conv["environment_id"] = assign_new_session_environment(
            session_db, session_id, req.requested_environment)
        if req.agent_invocation is not None:
            from ..agent_invocation import persist_agent_invocation
            persist_agent_invocation(session_id, req.agent_invocation, conv)
        run_cfg = save_session_run_config(
            session_id,
            agent_id=_db_agent_id(session_id),
            tools=req.tools_flag,
            # web_search stored as INTENT (not expanded into a list) so
            # the session always follows the live tool set.
            web_search=req.web_search_flag,
            thinking_effort=req.thinking_effort,
            permission_mode=req.permission_mode,
            # 草稿会话（尚无 session_id）在首条消息落地额外工作目录的唯一通道
            # （additional-working-directories.md §3.3）。None = 不动既有配置。
            additional_working_dirs=req.cmd.get("additional_working_dirs"),
            sandbox_enabled=req.sandbox_flag,
        )
    except BaseException:
        _s._release_run_reservation(session_id, msg_id)
        raise
    effective_permission = permission_from_config(
        run_cfg, default=project_defaults(session_id).get("permission_mode"))
    conv["tools_override"] = run_cfg.tools_override
    conv["web_search"] = run_cfg.web_search
    conv["thinking_effort"] = run_cfg.thinking_effort
    conv["permission_mode"] = run_cfg.permission_mode
    conv["sandbox_enabled"] = (
        run_cfg.sandbox_enabled if run_cfg.sandbox_enabled is not None
        else req.sandbox_flag
    )
    return run_cfg, effective_permission


def _bind_draft_channel(_s, req: _ChatRequest) -> None:
    """A draft's channel pick arrives with its first message; bind the
    conversation the moment its row exists, the same as picking it on a
    saved chat."""
    channel = (req.cmd.get("channel") or "").strip()
    if not channel:
        return
    from .conversation_channel import bind_conversation_channel
    try:
        result = bind_conversation_channel(
            _s, req.session_id, channel,
            req.cmd.get("account_id"), req.cmd.get("peer"),
        )
    except Exception:
        # The turn runs; the chat stays unbound and the chip shows it.
        _log.warning("draft channel not bound for %s", req.session_id, exc_info=True)
        return
    if not result.ok:
        _log.warning("draft channel not bound for %s: %s",
                     req.session_id, result.error)


async def _persist_turn_attachments(_s, req: _ChatRequest, msg_id: str) -> None:
    # Persist EVERY attachment to the session workdir so the agent's file
    # tools can read them and the chat can render them back, and embed the
    # saved ABSOLUTE PATH into the message text (every file is referenced
    # by path, never inlined). Images additionally continue to the
    # dispatcher as ImageContent blocks; documents are NOT passed as
    # content blocks (providers have no document-block support here).
    attachments = req.attachments
    if attachments:
        try:
            # Attachment decoding, hashing, and filesystem access are all
            # synchronous.  Keep the operation one sequential unit so the
            # durable admission/ACK order is unchanged, but do not block the
            # WebSocket event loop while a browser upload is being copied.
            req.text = await _persist_attachments_async(
                req.session_id, attachments, req.text,
            )
        except BaseException:
            _s._release_run_reservation(req.session_id, msg_id)
            raise
        attachments = _attachments_for_dispatch(attachments)
    req.user_attachments = attachments
    if req.recording_images:
        attachments = (attachments or []) + req.recording_images
    req.attachments = attachments


def _backfill_title(req: _ChatRequest) -> None:
    # Stage 1 (immediate, zero-latency sidebar placeholder): truncate the
    # user's first line into a title the instant the message is sent, so the
    # sidebar never shows an empty row while stage 2 (the background LLM
    # title in finalize→_maybe_auto_title) is still running. We mark
    # ``_auto_titled`` — the SAME flag _maybe_auto_title uses — so its own
    # stage-1 backfill is a no-op and its race guard (which compares the
    # live title against the truncation it expects) keeps the LLM title.
    # We do NOT set _user_titled: this is an automatic title, not a manual
    # rename, so the LLM stage and turn-1/6/16/40 re-titling stay live.
    try:
        from openprogram.runtime.context.session_db import default_db as _chat_ddb
        _chat_sess = _chat_ddb().get_session(req.session_id) or {}
    except Exception:
        _chat_sess = {}
    _chat_extra = _chat_sess.get("extra_meta") or {}
    if not _chat_extra.get("_auto_titled") and not _chat_extra.get("_user_titled"):
        _truncated = _title_from_text(req.text)
        try:
            _chat_ddb().update_session(req.session_id, title=_truncated,
                                       _auto_titled=True)
        except Exception:
            # Auto-title is cosmetic; the background rename retries it.
            _log.debug(
                "auto title not written for session %s", req.session_id, exc_info=True)


def _capture_turn_inputs(_s, ws, req: _ChatRequest, msg_id: str):
    """Parse the text, take the local authority and bind the surface.

    Returns ``(parsed, local_authority, surface_context, release_bindings)``.
    """
    session_id = req.session_id
    try:
        parsed = _s._parse_chat_input(req.text)
    except BaseException:
        _s._release_run_reservation(session_id, msg_id)
        raise

    try:
        from openprogram.runtime.permissions.authority import local_owner_authority
        _local_authority = local_owner_authority()
    except BaseException:
        _s._release_run_reservation(session_id, msg_id)
        raise

    # The renderer's surface reference is only a hint. Resolve it against
    # this authenticated websocket and capture a server-owned binding before
    # durable admission; client-supplied capability fields are never stored.
    from openprogram.runtime.conversation.surface_context import (
        capture as _capture_surface,
        release_bindings as _release_surface_bindings,
    )
    try:
        surface_context = _capture_surface(req.surface_ref, ws, session_id=session_id)
    except BaseException:
        _s._release_run_reservation(session_id, msg_id)
        raise
    return parsed, _local_authority, surface_context, _release_surface_bindings


def _build_user_msg(req: _ChatRequest, msg_id: str, parsed: dict,
                    _local_authority: dict) -> dict:
    text = req.text
    user_msg = {
        "role": "user",
        "id": msg_id,
        "content": text,
        "timestamp": time.time(),
        "source": "web",
        "origin": "person",
        **_local_authority,
    }
    request_id = client_request_id_of(req.cmd)
    if request_id is not None:
        user_msg["client_request_id"] = request_id
    model_text = _skill_model_text(req)
    if model_text is not None:
        # Later turns read the skill body from here; the transcript shows
        # what the user typed.
        user_msg["model_input"] = model_text
    if parsed["action"] == "spawn":
        # SYNC path only: tag the /task user msg so the DAG layout
        # treats it as a branch fork (main trunk stops here; the
        # spawned turn + sub-agent reply live on a new lane). Same
        # idea as git: /task probe → `git checkout -b probe`.
        # ASYNC path: don't tag — the spawned turn lives on its own
        # session (or independent branch), not as a fork of THIS
        # message. Marking it function="agent" made the user msg
        # surface in the Branches panel as a stray named branch
        # (with the raw command as its label) because lane.py
        # treated it as a fork tip with no follow-up.
        if parsed.get("wait", True):
            user_msg["function"] = "agent"
    extra_meta: dict = {}
    user_attachments = req.user_attachments
    if user_attachments:
        extra_meta["attachments"] = [
            {"type": a.get("type"), "media_type": a.get("media_type"),
             "size_b64": len(a.get("data") or "")}
            for a in user_attachments
        ]
    if req.recording_meta:
        extra_meta["recording"] = req.recording_meta
    text_elements = _pasted_text_elements(req.cmd.get("text_elements"), len(text))
    if text_elements:
        extra_meta["text_elements"] = text_elements
    if extra_meta:
        user_msg["extra"] = json.dumps(extra_meta, default=str)
    return user_msg


def _agent_event_sink(_s, session_id: str, msg_id: str, conv: dict):
    def _on_agent_event(env: dict) -> None:
        data = env.get("data") or {}
        if data.get("type") == "context_usage":
            try:
                _record_context_usage(
                    session_id, msg_id, conv, data.get("usage") or {},
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "failed to record in-flight context stats for %s", session_id,
                )
            return
        if hasattr(_s, "_broadcast_envelope"):
            _s._broadcast_envelope(env)
        else:
            _s._broadcast(json.dumps(env, default=str))
    return _on_agent_event


def _turn_request_payload(req: _ChatRequest, msg_id: str, run_cfg,
                          effective_permission, parsed: dict,
                          _local_authority: dict, surface_context) -> dict:
    session_id = req.session_id
    response_format = req.response_format
    from openprogram.runtime.conversation.session_config import tools_override_from_config
    _response_format_payload = (
        response_format.model_dump(mode="json")
        if hasattr(response_format, "model_dump") else response_format
    )
    from openprogram.runtime.permissions.rule import load_merged_rules as _load_merged_rules
    return {
        "session_id": session_id,
        "user_text": _skill_model_text(req) or parsed.get("raw") or req.text,
        "agent_id": _db_agent_id(session_id),
        "source": "web",
        "permission_mode": effective_permission,
        "permission_rules": _load_merged_rules(session_id),
        **_local_authority,
        # A typed /task or /merge is marked after the authority fields, which
        # also carry `interaction`. The admitted actor keeps the authority.
        **({"interaction": parsed["action"]}
           if parsed.get("action") in {"spawn", "merge"} else {}),
        "thinking_effort": run_cfg.thinking_effort,
        "service_tier": req.service_tier,
        "response_format": _response_format_payload,
        "tools_override": tools_override_from_config(run_cfg),
        "attachments": req.attachments,
        "user_msg_id": msg_id,
        "user_already_persisted": True,
        "surface_context": surface_context,
        "structured_output": (
            {
                "prompt": parsed.get("prompt") or "",
                "label": parsed.get("label") or "",
                "context": parsed.get("context") or "inherit",
                "wait": parsed.get("wait", True),
            }
            if parsed.get("action") == "spawn" else {
                "sub_sessions": parsed.get("sub_sessions") or [],
                "message": parsed.get("message") or "",
            }
            if parsed.get("action") == "merge" else None
        ),
        "additional_working_dirs": getattr(run_cfg, "additional_working_dirs", []),
    }


def _admit_turn(_s, req: _ChatRequest, conv: dict, msg_id: str, run_cfg,
                effective_permission, parsed: dict, _local_authority: dict,
                surface_context, _release_surface_bindings) -> _AdmittedTurn:
    # Admission is the sole source of execution identity. The message id is
    # retained only as transport/DAG provenance and never becomes ownership.
    session_id = req.session_id
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.runtime.conversation.production_driver import CanonicalAgentAdapter
    _adapter = CanonicalAgentAdapter(
        event_sink=_agent_event_sink(_s, session_id, msg_id, conv),
    )
    _request_payload = _turn_request_payload(
        req, msg_id, run_cfg, effective_permission, parsed,
        _local_authority, surface_context,
    )
    from ..agent_invocation import request_agent_invocation
    try:
        _request_payload.update(request_agent_invocation(session_id, req.agent_invocation))
        _request = TurnRequest(**_request_payload)
        _admission = _adapter.admit(
            _request,
            trusted_actor=_local_authority,
            user_message_id=msg_id,
            # The dispatcher writes this deterministic placeholder before
            # provider/tool callbacks.  Persist the same anchor at admission
            # so a resumed Agent checkpoint can fence it against immutable
            # execution input and finalize it exactly once.
            assistant_message_id=f"{msg_id}_reply",
            config_snapshot_ref=f"session:{session_id}",
        )
    except BaseException:
        _release_surface_bindings(surface_context)
        _s._release_run_reservation(session_id, msg_id)
        raise
    return _AdmittedTurn(
        session_id=session_id,
        msg_id=msg_id,
        conv=conv,
        adapter=_adapter,
        admission=_admission,
        surface_context=surface_context,
        release_surface_bindings=_release_surface_bindings,
        response_format=req.response_format,
        execution_id=_admission.execution_id,
    )


def _commit_user_message(_s, req: _ChatRequest, turn: _AdmittedTurn,
                         user_msg: dict) -> None:
    session_id, msg_id = turn.session_id, turn.msg_id
    # User/DAG content is committed only after the bounded canonical payload
    # has been admitted. If admission rejects an oversized or malformed
    # request, no user node is left behind without an execution record.
    try:
        _s._append_msg(turn.conv, user_msg, strict=True)
    except BaseException:
        turn.adapter.fail_admission(turn.admission, reason_code="user_persist_failed")
        turn.release_surface_bindings(turn.surface_context)
        _s._release_run_reservation(session_id, msg_id)
        raise

    # chat.before_send on the bus — plugin subscribers observe the
    # message about to enter the runtime. emit_safe swallows failures
    # so a bad subscriber can't poison the chat path.
    try:
        from openprogram.runtime.events import emit_safe
        emit_safe("chat.before_send", "user", {
            "session_id": session_id,
            "msg_id": msg_id,
            "text": req.text,
            "agent_id": _db_agent_id(session_id),
            "attachments": bool(req.attachments),
        }, {"session": session_id})
    except BaseException:
        turn.adapter.fail_admission(turn.admission, reason_code="chat_event_failed")
        turn.release_surface_bindings(turn.surface_context)
        _s._release_run_reservation(session_id, msg_id)
        raise


async def _send_chat_ack(ws, req: _ChatRequest, turn: _AdmittedTurn,
                         effective_permission) -> None:
    # Echo the STORED text back. The composer only knows the path-less
    # mention it wrote (the encoded absolute path is appended above, after the
    # bytes hit disk), so an optimistic bubble built from the client's
    # own draft has no path to open. Handing it the final text is what
    # makes an attachment clickable in the turn you sent it, instead of
    # only after a reload.
    first_read, end_parking = await _join_and_read(ws, turn.session_id)
    try:
        await ws.send_text(json.dumps({
            "type": "chat_ack",
            "data": _with_client_request_id({
                **first_read,
                "session_id": turn.session_id,
                "msg_id": turn.msg_id,
                "reply_id": f"{turn.msg_id}_reply",
                "text": req.text,
                "execution_id": turn.execution_id,
                "status_version": turn.admission.status_version,
                "permission_mode": effective_permission,
                "environment_id": turn.conv.get("environment_id"),
            }),
        }))
    except Exception:
        # The turn is already persisted. Losing its originating socket must
        # not leave that user message without a corresponding execution.
        _log.debug(
            "chat_ack not delivered for session %s", turn.session_id, exc_info=True)
    finally:
        end_parking()


async def _join_and_read(ws, session_id: str):
    """A send from a socket holding no view of the chat joins it, and the ack
    carries the first read: ``(fields for the ack, end of parking)``."""
    from openprogram.interfaces.server.transcript import publisher, reader, turn_index
    from openprogram.interfaces.server.ws_actions.session.load import _park_read
    from openprogram.runtime.context.session_db import default_db

    held = getattr(ws, "_transcript_views", None) or ()
    if getattr(ws, "_history_protocol", 0) != 3 or session_id in held:
        return {}, lambda: None
    end_parking = _park_read(ws, session_id)
    publisher.hold(ws, session_id)
    try:
        db = default_db()
        head = (db.get_session(session_id) or {}).get("head_id")
        view = await asyncio.to_thread(turn_index.get_view, db, session_id, head)
        turns, window = await asyncio.to_thread(reader.first_read, db, view)
    except Exception:
        _log.warning("first read for session %s failed", session_id, exc_info=True)
        return {}, end_parking
    return {"first_read": {"turns": turns, "window": window}}, end_parking
