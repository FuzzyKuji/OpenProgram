"""WebSocket action for a same-session Agent spawn."""
from __future__ import annotations

import logging
import asyncio
import json

_log = logging.getLogger(__name__)


def _run(
    session_id: str,
    parent_msg_id: str | None,
    prompt: str,
    agent_id: str,
    label: str | None,
    context: str,
) -> dict:
    from openprogram.runtime.conversation.sub_agent_run import run_agent_turn

    branch_from = parent_msg_id if context == "inherit" else None
    result = run_agent_turn(
        session_id=session_id,
        prompt=prompt,
        agent_id=agent_id,
        branch_from=branch_from,
        label=label,
    )
    return {
        "context": context,
        "head_id": result.head_id,
        "final_text": result.final_text,
        "failed": result.failed,
        "error": result.error,
    }


async def handle_spawn_agent(ws, cmd: dict) -> None:
    session_id = (cmd.get("session_id") or "").strip()
    parent_msg_id = (cmd.get("parent_msg_id") or "").strip() or None
    prompt = cmd.get("prompt") or ""
    agent_id = (cmd.get("agent_id") or "main").strip() or "main"
    label = cmd.get("label")
    if isinstance(label, str):
        label = label.strip() or None
    context = "clean" if (cmd.get("context") or "inherit").strip().lower() == "clean" else "inherit"

    if not session_id or not prompt:
        payload = {
            "session_id": session_id,
            "parent_msg_id": parent_msg_id,
            "context": context,
            "head_id": None,
            "final_text": "",
            "failed": True,
            "error": "session_id and prompt are required",
        }
    elif context == "inherit" and not parent_msg_id:
        payload = {
            "session_id": session_id,
            "parent_msg_id": parent_msg_id,
            "context": context,
            "head_id": None,
            "final_text": "",
            "failed": True,
            "error": "parent_msg_id is required when context='inherit'",
        }
    else:
        # The sub-agent runs for as long as its turn takes. The handler
        # returns at once so this socket keeps serving its other actions;
        # the result frame follows when the run ends.
        task = asyncio.create_task(_run_and_reply(
            ws, session_id, parent_msg_id, prompt, agent_id, label, context,
        ))
        _spawn_tasks.add(task)
        task.add_done_callback(_spawn_tasks.discard)
        return

    await ws.send_text(json.dumps({
        "type": "spawn_agent_result",
        "data": payload,
    }, default=str))


_spawn_tasks: set[asyncio.Task] = set()


async def _run_and_reply(ws, session_id: str, parent_msg_id: str | None, prompt: str,
                         agent_id: str, label: str | None, context: str) -> None:
    try:
        result = await asyncio.to_thread(
            _run, session_id, parent_msg_id, prompt, agent_id, label, context,
        )
    except Exception as exc:  # noqa: BLE001 - the caller still gets an answer
        result = {
            "context": context, "head_id": None, "final_text": "",
            "failed": True, "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        await ws.send_text(json.dumps({
            "type": "spawn_agent_result",
            "data": {"session_id": session_id, "parent_msg_id": parent_msg_id, **result},
        }, default=str))
    except Exception:
        # The requesting socket closed; the sub-agent's turn is already in
        # the session and shows on the next load.
        _log.debug(
            "spawn_agent_result not delivered for session %s", session_id, exc_info=True)


def _branch_tip(messages: list[dict], head_id: str) -> str:
    """Follow a sub-agent branch to its newest turn.

    Later messages to the same agent continue its branch from its last
    reply, so the branch tip moves past the head its spawn recorded.
    """
    turns: dict[str, list[dict]] = {}
    for message in messages:
        parent = message.get("predecessor")
        if (
            parent
            and message.get("role") in ("user", "assistant")
            and message.get("display") != "runtime"
            and message.get("function") != "attach"
        ):
            turns.setdefault(parent, []).append(message)
    tip, seen = head_id, set()
    while tip in turns and tip not in seen:
        seen.add(tip)
        tip = max(
            turns[tip],
            key=lambda message: message.get("created_at") or message.get("timestamp") or 0,
        )["id"]
    return tip


def _transcript(session_id: str, job_id: str, head_id: str) -> tuple[str, list[dict]]:
    from openprogram.runtime.context.session_db import default_db
    from openprogram.runtime.context.git import active_branch_chain
    from openprogram.interfaces.server.persistence import aggregate_tool_messages

    if not head_id and job_id:
        from openprogram.runtime.execution import default_store

        record = default_store().get_execution_input(job_id)
        if record is not None and record.session_id == session_id:
            head_id = record.assistant_message_id or ""
    db = default_db()
    messages = aggregate_tool_messages(db.get_messages(session_id) or [])
    if not head_id or head_id not in {message.get("id") for message in messages}:
        return head_id, []
    tip = _branch_tip(messages, head_id)
    # get_branch walks root-first; a reply placeholder can be written before
    # its prompt, so the branch order, not storage order, places each turn.
    order = {
        message.get("id"): index
        for index, message in enumerate(db.get_branch(session_id, tip) or [])
    }
    chain = active_branch_chain(messages, set(order), tip)
    return tip, sorted(
        (
            message for message in chain
            if message.get("role") in ("user", "assistant")
            and message.get("function") != "attach"
        ),
        key=lambda message: order.get(message.get("id"), len(order)),
    )


async def handle_load_sub_agent_transcript(ws, cmd: dict) -> None:
    """One sub-agent's own conversation, read without moving the session head."""
    session_id = (cmd.get("session_id") or "").strip()
    job_id = (cmd.get("job_id") or "").strip()
    head_id = (cmd.get("head_id") or "").strip()
    data = {
        "session_id": session_id,
        "job_id": job_id,
        "head_id": head_id,
        "messages": [],
        "request_id": cmd.get("request_id"),
        "action": "load_sub_agent_transcript",
    }
    if session_id and (job_id or head_id):
        try:
            data["head_id"], data["messages"] = await asyncio.to_thread(
                _transcript, session_id, job_id, head_id,
            )
        except Exception as exc:
            data["error"] = f"{type(exc).__name__}: {exc}"
    else:
        data["error"] = "session_id and job_id or head_id are required"
    await ws.send_text(json.dumps(
        {"type": "sub_agent_transcript", "data": data},
        ensure_ascii=False, default=str,
    ))


ACTIONS = {
    "spawn_agent": handle_spawn_agent,
    "load_sub_agent_transcript": handle_load_sub_agent_transcript,
}
