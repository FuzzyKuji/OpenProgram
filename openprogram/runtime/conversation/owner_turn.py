"""Start an owner chat turn in a conversation without a client sending it.

Always-on check-ins, reminders that wake the agent and messages handed over
from another conversation all need a turn the owner sees in the
conversation, under that conversation's own permission settings, as if the
owner had typed ``text``. The turn runs on a daemon thread; ``on_done``
receives its result (``None`` when it never ran).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

# Modes that would run an outside event's turn without asking the owner.
UNTRUSTED_DOWNGRADE = frozenset({"bypass", "auto", "acceptEdits"})
# A wake waits this long for a running turn in its conversation.
WAKE_WAIT_S = 600.0
WAKE_POLL_S = 2.0


def start_owner_turn_when_free(session_id: str, agent_id: str, text: str, *,
                               wait_s: float = WAKE_WAIT_S, poll_s: float = WAKE_POLL_S,
                               **options: Any) -> str | None:
    """Wait for the conversation's current turn, then start ``text`` as the next one.

    The wake takes the run slot itself, so it never runs beside another
    turn. Blocks the calling thread; returns the execution id, or ``None``
    when the conversation stayed busy for ``wait_s``.
    """
    from openprogram.runtime.conversation.run_control import is_turn_running
    from openprogram.runtime.conversation.run_control.run_slot import RunSlotBusy

    deadline = time.monotonic() + wait_s
    while True:
        if not is_turn_running(session_id):
            try:
                return start_owner_turn(session_id, agent_id, text, **options)
            except RunSlotBusy:
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_s)


def start_owner_turn(
    session_id: str, agent_id: str, text: str, *,
    tools: list[str] | None = None,
    name: str = "owner-turn",
    reason_code: str = "owner_turn_activation_failed",
    on_done: Callable[[Any], None] | None = None,
    untrusted: bool = False,
    msg_id: str | None = None,
    quiet_finish: bool = False,
) -> str:
    """Admit the turn now and run it in the background; return its execution id.

    ``untrusted``: outside text (a webhook body, a watched change) is part of
    ``text``. Such a turn never runs without asking: a conversation in Bypass,
    Auto or Accept-edits runs it in Ask, so every change waits for the owner.

    ``msg_id`` names the turn's user message, so a caller can recognise the
    turn from inside it (``TurnRequest.user_msg_id``); a new id by default.

    ``quiet_finish``: the turn's end does not mark the conversation unread
    (``TurnRequest.quiet_finish``); a failure still does.

    The turn takes the conversation's run slot like a typed message does and
    holds it until it ends. Raises :class:`RunSlotBusy` when another turn
    holds it; nothing is admitted then.
    """
    import asyncio
    import threading
    from openprogram.runtime.permissions.authority import local_owner_authority
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.runtime.conversation.production_driver import CanonicalAgentAdapter
    from openprogram.runtime.conversation.session_config import load_session_run_config, permission_from_config
    from openprogram.runtime.events import emit_ws_frame
    from openprogram.runtime.permissions.rule import load_merged_rules
    from openprogram.runtime.conversation.run_control import run_slot
    msg_id = msg_id or uuid.uuid4().hex
    if not run_slot.reserve(session_id, msg_id):
        raise run_slot.RunSlotBusy(session_id)
    try:
        config = load_session_run_config(session_id)
        authority = local_owner_authority()
        permission_mode = permission_from_config(config)
        if untrusted and permission_mode in UNTRUSTED_DOWNGRADE:
            permission_mode = "ask"
        request = TurnRequest(
            session_id=session_id, user_text=text, agent_id=agent_id, source="web",
            user_msg_id=msg_id, permission_mode=permission_mode,
            tools_override=tools, thinking_effort=config.thinking_effort,
            permission_rules=load_merged_rules(session_id),
            additional_working_dirs=config.additional_working_dirs,
            quiet_finish=quiet_finish, **authority,
        )
        adapter = CanonicalAgentAdapter(event_sink=emit_ws_frame)
        admission = adapter.admit(request, trusted_actor=authority, user_message_id=msg_id,
                                  assistant_message_id=f"{msg_id}_reply",
                                  config_snapshot_ref=f"session:{session_id}")
    except BaseException:
        run_slot.release(session_id, msg_id)
        raise

    def activate():
        result = None
        try:
            _active, result = asyncio.run(adapter.activate(admission))
        except Exception:
            adapter.fail_admission(admission, reason_code=reason_code)
        finally:
            run_slot.finish(session_id, msg_id, execution_id=admission.execution_id)
        if on_done is not None:
            on_done(result)
    try:
        thread = threading.Thread(target=activate, name=name, daemon=True)
        if not run_slot.activate(session_id, msg_id, execution_id=admission.execution_id,
                                 status_version=getattr(admission, "status_version", 0),
                                 runner=thread):
            raise run_slot.RunSlotBusy(session_id)
        thread.start()
    except BaseException:
        adapter.fail_admission(admission, reason_code=reason_code)
        run_slot.finish(session_id, msg_id, execution_id=admission.execution_id)
        run_slot.release(session_id, msg_id)
        raise
    return admission.execution_id


__all__ = ["WAKE_WAIT_S", "start_owner_turn", "start_owner_turn_when_free"]
