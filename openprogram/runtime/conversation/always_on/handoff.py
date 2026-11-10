"""Hand work to another conversation: an asynchronous message and its reply.

An always-on conversation (or any chat with an always-on Agent) can give a
piece of work to another conversation of the same owner, the way one Grok
Bot messages another. The target handles the message as a wake turn, like a
waking reminder: it waits up to ten minutes for a running turn there, then
takes the run slot and runs under its own Agent and permission settings.
When that turn ends, its final answer comes back to the sender as a wake
turn of its own. Both show in the transcripts as ordinary user rows
starting with 📨 (the message) and ↩️ (the reply). A 📨 turn's answer goes to
the sender, not to the target's bound channel; a ↩️ turn's answer is how a
person on that channel hears the result, so it is sent there.

Loop protection: a conversation cannot message itself, a chain of handoffs
and replies carries a hop count and stops at ``MAX_HOPS``, a conversation
cannot message one that is waiting further up its own chain, one conversation
or chain sends at most ``MAX_SENDS_PER_WINDOW`` messages an hour, and sub-agent,
imported and archived conversations neither send nor receive. A Goal started by
a chain turn keeps that chain, so its later turns count against the same limit.

When a turn that owes a reply hands the work on (A to B to C), the reply it owed
moves with the work: the turn in B that receives C's answer owes A, so A gets
B's real answer rather than B's "I asked C".

Chains outlive a worker restart: every handoff and reply turn is saved in
``store``'s handoff file with its chain, hop, origin and the reply it owes,
and the worker loads them when it starts. A turn the restart cut off
continues as a new turn with a new message id; that turn names the message
it continues (``resumes_message_id``), keeps the chain's hop count, and when
it ends the reply it owed goes back to the sender. A cut-off turn that nothing
will continue tells the sender so. Each continuation closes only its own
entry, never another chain's in the same conversation.

A message or reply still waiting for a busy conversation is saved with its
rendered text. A worker going down starts nothing more: the next worker
delivers it once, after the restart has settled that conversation's own turns.

A turn that stops for an approval, or is held during a version switch, has
not ended: its entry stays ``paused`` and owes its reply until the turn runs
on and ends, keeping the same message id. A failed or stopped turn answers
with what happened instead of a reply.

Design: docs/reference/design/runtime/always-on-agents.html
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from openprogram.runtime.conversation.always_on import store

_log = logging.getLogger(__name__)

MAX_HOPS = 4
MESSAGE_MAX = 8000
REPLY_MAX = 8000
STOPPED_ANSWER = "(The turn here was stopped before it finished, so it has no answer.)"
CUT_OFF_ANSWER = "(A restart cut off the turn here before it answered, and it was not continued.)"
# ``_start``'s result when the worker went down first: the entry stays saved.
LEFT_FOR_NEXT_WORKER = "left-for-next-worker"
# ``_start``'s result when the conversation was archived or removed while it waited.
CONVERSATION_GONE = "conversation-gone"
# Rolling limit on messages from one conversation, and within one chain.
MAX_SENDS_PER_WINDOW = 20
SEND_WINDOW_S = 3600.0
_TITLE_SCAN = 500
# Chains older than this are forgotten.
CHAIN_TTL_S = 24 * 3600.0
# User message id of a handoff or reply turn → {chain, hop, origin,
# session_id, at, boot, phase, reply_to?, owed_after?, ancestors?, sender?, relay?,
# text?, message?}. ``phase`` is waiting, running, paused or done; ``reply_to`` is
# the sender a handoff turn still owes its answer; ``owed_after`` the conversations
# owed an answer after that one, nearest last; ``ancestors`` those waiting above
# this turn; ``sender`` the conversation that sent this message (messages only,
# what the rolling limit counts); ``relay`` marks a turn carrying an answer on;
# ``text`` and ``message`` are what a waiting entry delivers.
# Saved on every change and loaded by ``restore()`` when the worker starts.
_CHAINS: dict[str, dict[str, Any]] = {}
_CHAINS_MAX = 2000
# This worker process: a running entry of another one was cut off by a restart.
_BOOT = uuid.uuid4().hex[:12]
_loaded = False
_lock = threading.RLock()


class HandoffRefused(ValueError):
    """The handoff cannot be sent; the message says why."""


def _db():
    from openprogram.runtime.context.session_db import default_db
    return default_db()


def _title(session: dict[str, Any]) -> str:
    return str(session.get("title") or "").strip() or "Untitled conversation"


def _save() -> None:
    """Drop expired chains and write the rest. The caller holds ``_lock``."""
    cutoff = time.time() - CHAIN_TTL_S
    for msg_id in [key for key, entry in _CHAINS.items() if float(entry.get("at") or 0) < cutoff]:
        del _CHAINS[msg_id]
    while len(_CHAINS) > _CHAINS_MAX:
        _CHAINS.pop(next(iter(_CHAINS)))
    store.save_handoffs(_CHAINS)


def restore() -> int:
    """Load the chains an earlier worker saved, without those older than a day."""
    global _loaded
    with _lock:
        _CHAINS.clear()
        _CHAINS.update({key: entry for key, entry in store.load_handoffs().items()
                        if isinstance(entry, dict)})
        _loaded = True
        _save()
        return len(_CHAINS)


def _ensure_loaded() -> None:
    if not _loaded:
        restore()


def _remember(msg_id: str, session_id: str, row: dict[str, Any], text: str,
              reply_to: str | None = None, message: str | None = None,
              sent_by: str | None = None) -> None:
    _ensure_loaded()
    with _lock:
        _CHAINS[msg_id] = {"chain": row["chain"], "hop": row["hop"], "origin": row.get("origin"),
                           "handoff_id": row.get("id"), "session_id": session_id,
                           "at": time.time(), "boot": _BOOT, "phase": "waiting", "text": text}
        if reply_to:
            _CHAINS[msg_id].update(reply_to=reply_to, message=message)
        extra = {"sender": sent_by, "owed_after": row.get("owed_after"), "relay": row.get("relay"),
                 "ancestors": _above(row.get("ancestors"), session_id)}
        _CHAINS[msg_id].update({key: value for key, value in extra.items() if value})
        _save()


def _above(ancestors: list[str] | None, session_id: str) -> list[str]:
    """Those waiting above ``session_id``; an answer coming back drops what is below it."""
    path = list(ancestors or [])
    return path[:path.index(session_id)] if session_id in path else path


def _started(msg_id: str) -> None:
    with _lock:
        entry = _CHAINS.get(msg_id)
        if entry is not None and entry.get("phase") == "waiting":
            entry["phase"] = "running"
            entry.pop("text", None)
            entry.pop("message", None)
            _save()


def _ended(msg_id: str, *, ran: bool = True) -> str | None:
    """The turn ended (or never ran): returns the sender it still owed a reply, once."""
    with _lock:
        entry = _CHAINS.get(msg_id)
        if entry is None:
            return None
        if not ran:
            del _CHAINS[msg_id]
            _save()
            return None
        entry["phase"] = "done"
        entry.pop("text", None)
        entry.pop("message", None)
        reply_to = entry.pop("reply_to", None)
        _save()
        return reply_to


def turn_paused(msg_id: str) -> None:
    """The turn stopped at a safe point (an approval): it still owes its reply."""
    _ensure_loaded()
    with _lock:
        entry = _CHAINS.get(msg_id)
        if entry is not None and entry.get("phase") == "running":
            entry["phase"] = "paused"
            _save()


def turn_resumed(msg_id: str) -> None:
    """A paused turn runs again in this worker."""
    _ensure_loaded()
    with _lock:
        entry = _CHAINS.get(msg_id)
        if entry is not None and entry.get("phase") == "paused":
            entry.update(phase="running", boot=_BOOT)
            _save()


def turn_ended(msg_id: str, answer: str | None) -> None:
    """A resumed turn has ended: send the reply it still owes, at most once."""
    _ensure_loaded()
    with _lock:
        entry = dict(_CHAINS.get(msg_id) or {})
        owed = _ended(msg_id)
    if owed:
        _spawn_reply(entry, answer)


def _handoff_request(executions: Any, execution: Any) -> dict[str, Any] | None:
    """The saved request of a handoff or reply turn; ``None`` for any other execution."""
    from openprogram.runtime.permissions.identity import HANDOFF_TURNS
    request = (executions.get_agent_turn_input(execution.execution_id) or {}).get("request") or {}
    return request if request.get("automation") in HANDOFF_TURNS and request.get("user_msg_id") else None


def _closing_answer(execution: Any, result: Any = None) -> str | None:
    """What the sender reads about an execution that reached its end."""
    status = execution.status.value
    if status == "cancelled":
        return str(getattr(result, "final_text", "") or "").strip() or STOPPED_ANSWER
    if status == "completed" or getattr(result, "failed", False):
        return answer_of(result)
    return failure_answer(execution.reason_code)


def execution_closed(executions: Any, execution: Any) -> None:
    """A paused handoff turn ended with no turn running, as a stop does."""
    request = _handoff_request(executions, execution)
    if request is None:
        return
    if request.get("restart_resume"):
        # The chain's entry belongs to the turn this one continues.
        if execution.reason_code != "restart_new_turn":
            resumed_turn_ended(request.get("resumes_message_id"), _closing_answer(execution))
        return
    msg_id = str(request["user_msg_id"])
    _ensure_loaded()
    with _lock:
        entry = _CHAINS.get(msg_id)
        if entry is None:
            return
        # A turn a restart cut off has no turn left to report a stop.
        stopped_after_cut_off = (entry.get("phase") == "running" and entry.get("boot") != _BOOT
                                 and execution.status.value == "cancelled")
        if entry.get("phase") != "paused" and not stopped_after_cut_off:
            return
        if execution.reason_code == "restart_new_turn":
            # A new turn carries on from here and sends the reply when it ends.
            entry["phase"] = "running"
            _save()
            return
    turn_ended(msg_id, _closing_answer(execution))


def run_ended(executions: Any, execution: Any, result: Any) -> None:
    """A run this worker activated again has ended.

    The turn usually sent its reply already, and then this does nothing. It
    settles what a turn cannot: a first attempt run over again, which has no
    ``on_done`` left, and a raise outside the turn's loop.
    """
    from openprogram.runtime.scheduler.run_finish import has_ended
    request = _handoff_request(executions, execution)
    if request is None or execution.reason_code == "restart_new_turn" or not has_ended(result, execution):
        return
    if request.get("restart_resume"):
        resumed_turn_ended(request.get("resumes_message_id"), _closing_answer(execution, result))
    else:
        turn_ended(str(request["user_msg_id"]), _closing_answer(execution, result))


def restart_abandoned(executions: Any, execution: Any) -> None:
    """Nothing will continue this cut-off turn: its sender hears that now.

    A turn that is waiting on something of its own (``paused``) still owes
    its real answer, and is left alone.
    """
    request = _handoff_request(executions, execution)
    if request is not None:
        resumed_turn_ended(request.get("resumes_message_id") if request.get("restart_resume")
                           else str(request["user_msg_id"]), CUT_OFF_ANSWER)


def held_turn_ended(request: Any, result: Any) -> None:
    """A turn saved during a version switch has run after it: send what it owes."""
    from openprogram.runtime.scheduler.run_finish import has_ended
    from openprogram.runtime.permissions.identity import HANDOFF_TURNS
    if getattr(request, "automation", None) in HANDOFF_TURNS and has_ended(result, None):
        turn_ended(str(request.user_msg_id), answer_of(result))


def chain_of(msg_id: str | None, *, resumes: str | None = None) -> dict[str, Any] | None:
    """The chain a handoff or reply turn belongs to; ``None`` for any other turn.

    ``resumes``: the message of the turn this one continues after a worker
    restart cut it off, whose chain counts, as this turn has a new message id.
    """
    _ensure_loaded()
    with _lock:
        found = _CHAINS.get(msg_id or "") or _CHAINS.get(resumes or "")
        return {key: found.get(key) for key in ("chain", "hop", "origin")} if found else None


def chain_context(msg_id: str | None, *, resumes: str | None = None) -> dict[str, Any] | None:
    """The chain of a turn with who waits above it, which a message it sends continues."""
    _ensure_loaded()
    with _lock:
        found = _CHAINS.get(msg_id or "") or _CHAINS.get(resumes or "")
        if not found:
            return None
        return {"chain": found.get("chain"), "hop": found.get("hop"), "origin": found.get("origin"),
                "ancestors": list(found.get("ancestors") or [])}


def resumed_turn_ended(msg_id: str | None, answer: str | None) -> None:
    """The turn a worker restart cut off, saved under ``msg_id``, is over:
    finish its entry and send the reply it owed to its sender, once."""
    _ensure_loaded()
    with _lock:
        entry = _CHAINS.get(msg_id or "")
        if entry is None or entry.get("phase") != "running":
            return
        entry["phase"] = "done"
        owed = dict(entry, reply_to=entry.pop("reply_to")) if entry.get("reply_to") else None
        _save()
    if owed:
        _spawn_reply(owed, answer)


def _listed(rows: list[dict[str, Any]]) -> str:
    return ", ".join(f"“{_title(row)}” ({row['id']})" for row in rows[:10])


def _owner_target(session: dict[str, Any]) -> dict[str, Any]:
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation

    if not owner_conversation(session):
        raise HandoffRefused("That conversation cannot take handoffs: it is archived, "
                             "imported, a sub-agent's or a Try chat.")
    return session


def _target_at_head(session: dict[str, Any], head: str, to: str) -> dict[str, Any]:
    """``SID:HEAD``: the conversation, when ``head`` is on the line its next turn continues.

    A handoff runs as the conversation's next turn, so another branch of it
    (a sub-agent's, say) cannot be reached this way.
    """
    target = _owner_target(session)
    if not any(row.get("id") == head for row in _db().get_branch(target["id"]) or []):
        raise HandoffRefused(f"{to!r} is not on the current line of “{_title(target)}”, and a handoff "
                             "only reaches a conversation's current line. Pass its id for that line; "
                             "to message another branch, use send_message if you have it.")
    return target


def _agents_named(to: str) -> list[Any]:
    from openprogram.runtime.agent_registry import manager

    wanted = to.casefold()
    return [spec for spec in manager.list_all()
            if wanted in (str(spec.id).casefold(), str(spec.name or "").strip().casefold())]


def _your_conversations(sender_id: str, rows: list[dict[str, Any]]) -> str:
    """The choices a refusal offers. Not every Agent that has ``handoff`` has
    ``list_agents``, so the refusal itself has to name them."""
    known = "; ".join([f"{_title(row)} ({row['id']})" for row in rows if row["id"] != sender_id][:20])
    return (f"Your conversations: {known or 'none'}. "
            "list_agents scope=\"all\", if you have it, shows every Agent's conversations.")


def _target_of_agents(sender_id: str, agents: list[Any], everyone: list[dict[str, Any]]) -> dict[str, Any]:
    """The one conversation, other than the sender, of the Agent ``to`` names."""
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation

    # A list row can be older than the conversation's Try flag.
    rows = [row for spec in agents for row in _db().list_sessions(limit=_TITLE_SCAN, agent_id=spec.id)
            if owner_conversation(row) and row["id"] != sender_id
            and owner_conversation(_db().get_session(row["id"]))]
    if len(rows) == 1:
        return rows[0]
    name = str(agents[0].name or agents[0].id)
    if rows:
        raise HandoffRefused(f"Agent “{name}” has several conversations: {_listed(rows)}. "
                             "Pass the id of the one that should do this.")
    raise HandoffRefused(f"Agent “{name}” has no other conversation to hand this to, and only the user "
                         f"creates conversations. {_your_conversations(sender_id, everyone)}")


def resolve_target(sender_id: str, to: str) -> dict[str, Any]:
    """The conversation ``to`` names, in this order: its id, ``SID:HEAD``, its
    exact title (any case), then an Agent's id or name (any case)."""
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation

    to = (to or "").strip()
    if not to:
        raise HandoffRefused("Name who to hand this to: a conversation's id or title, "
                             "an Agent's name or id, or SID:HEAD from list_agents scope=\"all\".")
    db = _db()
    session = db.get_session(to)
    if session is not None:
        return _owner_target(session)
    conversation_id, colon, head = to.partition(":")
    addressed = db.get_session(conversation_id) if colon and head else None
    if addressed is not None:
        return _target_at_head(addressed, head, to)
    rows = [row for row in db.list_sessions(limit=_TITLE_SCAN) if owner_conversation(row)]
    # A list row can be older than the conversation's Try flag.
    matches = [row for row in rows if _title(row).casefold() == to.casefold()
               and owner_conversation(db.get_session(row["id"]))]
    if len(matches) == 1:
        return matches[0]
    if matches:
        listed = ", ".join(f"{row['id']}" for row in matches[:10])
        raise HandoffRefused(f"Several conversations are titled {to!r} ({listed}); pass the id instead.")
    agents = _agents_named(to)
    if agents:
        return _target_of_agents(sender_id, agents, rows)
    raise HandoffRefused(f"No conversation is titled {to!r} and no Agent has that name or id. "
                         f"{_your_conversations(sender_id, rows)}")


def handoff_text(sender: dict[str, Any], message: str) -> str:
    return (f"📨 Message from “{_title(sender)}” ({sender['id']}):\n\n{message}\n\n"
            "(Another of your conversations handed this to you. Handle it here; your final "
            "answer goes back to it on its own.)")


def reply_text(target: dict[str, Any], answer: str) -> str:
    return f"↩️ Reply from “{_title(target)}” ({target['id']}) to the message you sent it:\n\n{answer}"


def still_waiting_note(earlier: dict[str, Any]) -> str:
    return (f"(“{_title(earlier)}” ({earlier['id']}) is still waiting for this work. Your final "
            "answer here goes back to it on its own, so make it the full result.)")


def failure_answer(reason: Any) -> str:
    """What the sender reads when the turn it waited on failed."""
    from openprogram.runtime.execution.attempts import stored_failure_text
    return f"(The turn here failed before it answered: {stored_failure_text(str(reason or 'unknown error'))})"


def answer_of(result: Any) -> str | None:
    """A finished turn's answer; ``None`` when it never ran."""
    if result is None:
        return None
    if getattr(result, "failed", False):
        return failure_answer(getattr(result, "error", None))
    text = str(getattr(result, "final_text", "") or "")
    return STOPPED_ANSWER if getattr(result, "stopped", False) and not text.strip() else text


def busy_text(target: dict[str, Any], message: str) -> str:
    return (f"↩️ “{_title(target)}” ({target['id']}) stayed busy for ten minutes, so the "
            f"message you sent it was not delivered:\n\n{message}")


def undelivered_text(target: dict[str, Any], message: str) -> str:
    return (f"↩️ Something went wrong handing this to “{_title(target)}” ({target['id']}), "
            f"so the message you sent it was not delivered:\n\n{message}")


def gone_text(target: dict[str, Any], message: str) -> str:
    return (f"↩️ “{_title(target)}” ({target['id']}) was archived or removed while the message "
            f"waited, so the message you sent it was not delivered:\n\n{message}")


def relay_failed_text(target: dict[str, Any], why: str, answer: str) -> str:
    """An answer on its way back could not pass through ``target``; the earlier sender still hears."""
    return (f"↩️ “{_title(target)}” ({target['id']}) {why}, so it could not finish the work you "
            f"sent it. The last thing that came back to it:\n\n{answer}")


def _refuse_over_limit(sender_id: str, chain: str) -> None:
    """The caller holds ``_lock``."""
    cutoff = time.time() - SEND_WINDOW_S
    sent = [entry for entry in _CHAINS.values() if entry.get("sender") and float(entry.get("at") or 0) >= cutoff]
    if (sum(entry["sender"] == sender_id for entry in sent) >= MAX_SENDS_PER_WINDOW
            or sum(entry.get("chain") == chain for entry in sent) >= MAX_SENDS_PER_WINDOW):
        raise HandoffRefused(f"Too many handoffs: at most {MAX_SENDS_PER_WINDOW} an hour from one "
                             "conversation or in one chain. Finish the work here instead.")


def _take_over_owed_reply(row: dict[str, Any], msg_id: str | None, resumes: str | None) -> None:
    """The sending turn stops owing its reply: the work's answer will carry it. The caller holds ``_lock``."""
    entry = _CHAINS.get(msg_id or "") or _CHAINS.get(resumes or "")
    if entry and entry.get("reply_to"):
        row["owed_after"] = [*entry.pop("owed_after", []), entry.pop("reply_to")]
        _save()


def _goal_chain(session_id: str) -> dict[str, Any] | None:
    import openprogram.programs.tools.planning.goal as goals
    return (goals.load_goal(session_id) or {}).get("handoff_chain")


def send(sender_id: str, to: str, message: str, *, msg_id: str | None = None,
         advance_head: bool = True, resumes: str | None = None,
         goal_turn: bool = False) -> dict[str, Any]:
    """Hand ``message`` to the conversation ``to``; returns at once.

    ``msg_id`` is the sending turn's user message: when it is itself a
    handoff or reply turn, the new message continues its chain. ``resumes``:
    the message of the turn the sending turn continues after a restart.
    ``goal_turn``: a turn of the conversation's Goal, which stays in the chain
    that started the Goal although its own message id is new.
    """
    from openprogram.runtime.conversation.always_on.runtime import agent_for_session, owner_conversation

    message = (message or "").strip()
    if not message:
        raise HandoffRefused("The message is empty.")
    if len(message) > MESSAGE_MAX:
        raise HandoffRefused(f"Keep the message under {MESSAGE_MAX} characters.")
    sender = _db().get_session(sender_id)
    if not advance_head or not owner_conversation(sender):
        raise HandoffRefused("Only your own conversations can hand work over, not sub-agents "
                             "or imported conversations.")
    if agent_for_session(sender_id) is None:
        raise HandoffRefused("Handoffs work in conversations whose Agent is always-on.")
    target = resolve_target(sender_id, to)
    if target["id"] == sender_id:
        raise HandoffRefused("A conversation cannot hand work to itself.")
    chain = (chain_context(msg_id, resumes=resumes)
             or (_goal_chain(sender_id) if goal_turn else None)
             or {"chain": uuid.uuid4().hex[:12], "hop": 0, "origin": sender_id})
    hop = int(chain["hop"]) + 1
    if hop > MAX_HOPS:
        raise HandoffRefused(f"This chain of handoffs already has {MAX_HOPS} hops; finish the "
                             "work here instead of handing it on.")
    ancestors = [*(chain.get("ancestors") or []), sender_id]
    if target["id"] in ancestors:
        raise HandoffRefused(f"“{_title(target)}” is already waiting on this chain; your final "
                             "answer goes back to it on its own.")
    row = {"id": uuid.uuid4().hex[:12], "chain": chain["chain"], "hop": hop,
           "origin": chain.get("origin") or sender_id, "sender": sender, "target": target,
           "message": message, "ancestors": ancestors, "msg_id": uuid.uuid4().hex}
    # Saved before this returns, so parallel calls in one turn all count.
    with _lock:
        _refuse_over_limit(sender_id, chain["chain"])
        _take_over_owed_reply(row, msg_id, resumes)
        _remember(row["msg_id"], str(target["id"]), row, handoff_text(sender, message),
                  reply_to=sender_id, message=message, sent_by=sender_id)
    _spawn(row)
    return {"handoff_id": row["id"], "target_id": target["id"], "target_title": _title(target),
            "hop": hop, "max_hops": MAX_HOPS}


def _spawn(row: dict[str, Any]) -> None:
    """Deliver in the background: waiting for a busy target can take minutes."""
    threading.Thread(target=_deliver, args=(row,), name=f"handoff-{row['id']}", daemon=True).start()


def _worker_going_down() -> bool:
    """A restart's first step pauses running turns, which frees the very
    conversation a handoff waits for; a turn started now would read to the
    next worker as the user having moved on from the paused one."""
    from openprogram.runtime.conversation.run_control import is_worker_stopping
    from openprogram.runtime.jobs import runner
    return is_worker_stopping() or bool(getattr(runner.current_runner(), "_restart_shutdown", False))


def _takes_turns(session: dict[str, Any]) -> bool:
    """Read afresh on every poll: a conversation can be archived while a handoff waits for it."""
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation
    return owner_conversation(_db().get_session(str(session["id"])))


def _start(session: dict[str, Any], text: str, row: dict[str, Any], *,
           reply_to: str | None = None, on_reply=None, message: str | None = None,
           saved_msg_id: str | None = None) -> str | None:
    """A wake turn in ``session`` that belongs to the handoff's chain.

    ``reply_to``: the sender this turn owes its answer; ``on_reply`` gets the
    turn's result when it ends, at most once, unless a restart cut it off.
    ``saved_msg_id``: the waiting entry an earlier worker saved for this turn.
    """
    from openprogram.runtime.conversation.owner_turn import start_owner_turn_when_free
    from openprogram.runtime.permissions.identity import HANDOFF_MESSAGE
    msg_id = saved_msg_id or uuid.uuid4().hex
    if saved_msg_id is None:
        _remember(msg_id, str(session["id"]), row, text, reply_to=reply_to, message=message)

    def give_up() -> bool:
        return _worker_going_down() or not _takes_turns(session)

    def ended(result: Any) -> None:
        from openprogram.runtime.conversation.run_control import is_worker_stopping
        from openprogram.runtime.scheduler.run_finish import held_for_switch
        if getattr(result, "_execution_safe_point_handoff", False) or held_for_switch(result):
            # An approval or a version switch: the real end comes through turn_ended.
            turn_paused(msg_id)
            return
        if result is None and is_worker_stopping():
            return  # The next worker carries the turn on; it has not ended.
        if _ended(msg_id) and on_reply is not None:
            on_reply(result)
    try:
        started = start_owner_turn_when_free(
            str(session["id"]), str(session.get("agent_id") or "main"), text, msg_id=msg_id,
            name=f"handoff-{row['id']}", reason_code="handoff_activation_failed", on_done=ended,
            automation=HANDOFF_MESSAGE if reply_to else "handoff", give_up_when=give_up)
    except Exception:
        _ended(msg_id, ran=False)  # The next worker must not deliver it again.
        raise
    if started is None and _worker_going_down():
        return LEFT_FOR_NEXT_WORKER
    if started is None and not _takes_turns(session):
        _ended(msg_id, ran=False)
        return CONVERSATION_GONE
    if started is None:
        _ended(msg_id, ran=False)
    else:
        _started(msg_id)
    return started


def _reply(row: dict[str, Any], sender: dict[str, Any], target: dict[str, Any],
           answer: str | None) -> None:
    answer = "(The conversation could not run a turn for it.)" if answer is None else answer.strip()
    text = reply_text(target, answer[:REPLY_MAX] or "(No answer text.)")
    if _back_to_sender(row, sender, text, closing="(Carry on with your work; this needs no answer.)") is None:
        _log.info("%s: %s stayed busy; the reply stays in %s", row["id"], sender["id"], target["id"])


def _back_to_sender(row: dict[str, Any], sender: dict[str, Any], text: str, *,
                    closing: str | None = None) -> str | None:
    """A turn in ``sender`` about what came back. If it had passed the work on
    while owing an earlier conversation, this turn owes that conversation now,
    and is asked for the full answer; otherwise ``closing`` ends the text."""
    owed = list(row.get("owed_after") or [])
    if not owed:
        return _start(sender, f"{text}\n\n{closing}" if closing else text, row)
    earlier = _db().get_session(owed[-1]) or {"id": owed[-1]}
    carried = dict(row, owed_after=owed[:-1], message=text[:MESSAGE_MAX], relay=True)
    _deliver_message(carried, earlier, sender, f"{text}\n\n{still_waiting_note(earlier)}")
    return str(sender["id"])


def _tell(row: dict[str, Any], sender: dict[str, Any], target: dict[str, Any], plain: str, why: str) -> None:
    text = relay_failed_text(target, why, row["message"]) if row.get("relay") else plain
    _back_to_sender(row, sender, text)


def _deliver(row: dict[str, Any]) -> None:
    _deliver_message(row, row["sender"], row["target"], handoff_text(row["sender"], row["message"]),
                     saved_msg_id=row.get("msg_id"))


def _deliver_message(row: dict[str, Any], sender: dict[str, Any], target: dict[str, Any],
                     text: str, saved_msg_id: str | None = None) -> None:
    def answered(result: Any) -> None:
        _reply(row, sender, target, answer_of(result))

    try:
        started = _start(target, text, row, reply_to=str(sender["id"]), on_reply=answered,
                         message=row["message"], saved_msg_id=saved_msg_id)
        if started is None:
            _tell(row, sender, target, busy_text(target, row["message"]), "stayed busy for ten minutes")
        elif started == CONVERSATION_GONE:
            _tell(row, sender, target, gone_text(target, row["message"]), "was archived or removed")
    except Exception as exc:  # noqa: BLE001 - a background delivery never raises into the worker
        _log.warning("%s to %s failed: %s: %s", row["id"], target["id"], type(exc).__name__, exc,
                     exc_info=True)
        _tell_undelivered(row, sender, target)


def _tell_undelivered(row: dict[str, Any], sender: dict[str, Any], target: dict[str, Any]) -> None:
    try:
        _tell(row, sender, target, undelivered_text(target, row["message"]), "hit an error")
    except Exception as exc:  # noqa: BLE001
        _log.warning("%s: could not tell %s: %s: %s", row["id"], sender["id"], type(exc).__name__, exc)


def deliver_waiting() -> int:
    """Deliver what an earlier worker left waiting for a busy conversation.

    Only the worker's start calls this. A lazy ``restore()`` in any other
    path only reads chains, and must never start a turn.
    """
    _ensure_loaded()
    with _lock:
        waiting = {msg_id: entry for msg_id, entry in _CHAINS.items()
                   if entry.get("phase") == "waiting" and entry.get("boot") != _BOOT}
        claimed = []
        for msg_id, entry in waiting.items():
            if entry.get("text"):
                entry["boot"] = _BOOT
                claimed.append((msg_id, dict(entry)))
            else:
                del _CHAINS[msg_id]  # Saved before waiting entries carried their text.
        if waiting:
            _save()
    for msg_id, entry in claimed:
        _spawn_waiting(msg_id, entry)
    return len(claimed)


def _row_of(entry: dict[str, Any]) -> dict[str, Any]:
    return {"id": entry.get("handoff_id") or "resumed", "chain": entry["chain"], "hop": entry["hop"],
            "origin": entry.get("origin"), "message": entry.get("message") or "",
            "ancestors": entry.get("ancestors") or [], "owed_after": entry.get("owed_after") or [],
            "relay": entry.get("relay")}


def _spawn_waiting(msg_id: str, entry: dict[str, Any]) -> None:
    threading.Thread(target=_deliver_saved, args=(msg_id, entry),
                     name=f"handoff-{entry.get('handoff_id')}", daemon=True).start()


def _already_admitted(session_id: str, msg_id: str) -> bool:
    """The worker stopped between admitting the turn and marking it running."""
    from openprogram.runtime.execution.store import default_store
    return any(record.user_message_id == msg_id for record in default_store().list_inputs_for_session(session_id))


def _wait_for_restart_to_settle(session_id: str) -> None:
    """Let the restart continue this conversation's own turns first: a new
    turn here would read as the user having moved on from them."""
    from openprogram.runtime.conversation.owner_turn import WAKE_POLL_S, WAKE_WAIT_S
    from openprogram.runtime.execution.restart import conversation_settling
    from openprogram.runtime.execution.store import default_store
    deadline = time.monotonic() + WAKE_WAIT_S
    while conversation_settling(default_store(), session_id) and time.monotonic() < deadline:
        time.sleep(WAKE_POLL_S)


def _deliver_saved(msg_id: str, entry: dict[str, Any]) -> None:
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation
    session_id = str(entry["session_id"])
    row = _row_of(entry)
    try:
        if _already_admitted(session_id, msg_id):
            _started(msg_id)
            return
        session = _db().get_session(session_id)
        sender = _db().get_session(entry["reply_to"]) if entry.get("reply_to") else None
        if not owner_conversation(session) or (entry.get("reply_to") and not owner_conversation(sender)):
            _ended(msg_id, ran=False)
            if owner_conversation(sender) or row["owed_after"]:
                _tell_undelivered(row, sender or {"id": entry["reply_to"]}, session or {"id": session_id})
            return
        _wait_for_restart_to_settle(session_id)
        if sender is not None:
            _deliver_message(row, sender, session, entry["text"], saved_msg_id=msg_id)
        elif _start(session, entry["text"], row, saved_msg_id=msg_id) is None:
            _log.info("%s: %s stayed busy after the restart", row["id"], session_id)
    except Exception as exc:  # noqa: BLE001 - a background delivery never raises into the worker
        _log.warning("%s after the restart failed: %s: %s", row["id"], type(exc).__name__, exc,
                     exc_info=True)


def _spawn_reply(entry: dict[str, Any], answer: str | None) -> None:
    """Send the reply a cut-off handoff turn owed, in the background."""
    threading.Thread(target=_reply_after_restart, args=(entry, answer),
                     name=f"handoff-reply-{entry.get('handoff_id')}", daemon=True).start()


def _reply_after_restart(entry: dict[str, Any], answer: str | None) -> None:
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation
    try:
        sender, target = _db().get_session(entry["reply_to"]), _db().get_session(entry["session_id"])
        if target is None or (not owner_conversation(sender) and not entry.get("owed_after")):
            return
        _reply(_row_of(entry), sender or {"id": entry["reply_to"]}, target, answer)
    except Exception as exc:  # noqa: BLE001 - a background delivery never raises into the worker
        _log.warning("reply to %s failed: %s: %s", entry.get("reply_to"), type(exc).__name__, exc,
                     exc_info=True)
