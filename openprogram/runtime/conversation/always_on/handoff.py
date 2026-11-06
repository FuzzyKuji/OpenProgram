"""Hand work to another conversation: an asynchronous message and its reply.

An always-on conversation (or any chat with an always-on Agent) can give a
piece of work to another conversation of the same owner, the way one Grok
Bot messages another. The target handles the message as a wake turn, like a
waking reminder: it waits up to ten minutes for a running turn there, then
takes the run slot and runs under its own Agent and permission settings.
When that turn ends, its final answer comes back to the sender as a wake
turn of its own. Both show in the transcripts as ordinary user rows
starting with 📨 (the message) and ↩️ (the reply).

Loop protection: a conversation cannot message itself, a chain of handoffs
and replies carries a hop count and stops at ``MAX_HOPS``, and sub-agent,
imported and archived conversations neither send nor receive.

Chains outlive a worker restart: every handoff and reply turn is saved in
``store``'s handoff file with its chain, hop, origin and the reply it owes,
and the worker loads them when it starts. A turn the restart cut off
continues as a new turn with a new message id; that turn keeps the chain's
hop count, and when it ends the reply it owed goes back to the sender.

Design: docs/reference/design/runtime/always-on-agents.md
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
_TITLE_SCAN = 500
# Chains older than this are forgotten.
CHAIN_TTL_S = 24 * 3600.0
# User message id of a handoff or reply turn → {chain, hop, origin,
# session_id, at, boot, phase, reply_to?}. ``phase`` is waiting, running or
# done; ``reply_to`` is the sender a handoff turn still owes its answer.
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


def _remember(msg_id: str, session_id: str, row: dict[str, Any], reply_to: str | None = None) -> None:
    _ensure_loaded()
    with _lock:
        _CHAINS[msg_id] = {"chain": row["chain"], "hop": row["hop"], "origin": row.get("origin"),
                           "handoff_id": row.get("id"), "session_id": session_id,
                           "at": time.time(), "boot": _BOOT, "phase": "waiting"}
        if reply_to:
            _CHAINS[msg_id]["reply_to"] = reply_to
        _save()


def _started(msg_id: str) -> None:
    with _lock:
        entry = _CHAINS.get(msg_id)
        if entry is not None and entry.get("phase") == "waiting":
            entry["phase"] = "running"
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
        reply_to = entry.pop("reply_to", None)
        _save()
        return reply_to


def chain_of(msg_id: str | None, *, session_id: str | None = None,
             resumed: bool = False) -> dict[str, Any] | None:
    """The chain a handoff or reply turn belongs to; ``None`` for any other turn.

    ``resumed``: the turn continues one a worker restart cut off in
    ``session_id``, so it has a new message id; the cut-off turn's chain counts.
    """
    _ensure_loaded()
    with _lock:
        found = _CHAINS.get(msg_id) if msg_id else None
        if found is None and resumed and session_id:
            found = max(_cut_off(session_id), key=lambda entry: entry.get("at") or 0, default=None)
        return {key: found.get(key) for key in ("chain", "hop", "origin")} if found else None


def _cut_off(session_id: str) -> list[dict[str, Any]]:
    """Turns in ``session_id`` that were running when an earlier worker stopped."""
    return [entry for entry in _CHAINS.values()
            if entry.get("session_id") == session_id and entry.get("phase") == "running"
            and entry.get("boot") != _BOOT]


def resumed_turn_ended(session_id: str, answer: str | None) -> None:
    """A turn that continued one a worker restart cut off has ended: finish
    that chain turn, and send the reply it owed to its sender."""
    _ensure_loaded()
    owed = []
    with _lock:
        cut_off = _cut_off(session_id)
        for entry in cut_off:
            entry["phase"] = "done"
            if entry.get("reply_to"):
                owed.append(dict(entry, reply_to=entry.pop("reply_to")))
        if cut_off:
            _save()
    for entry in owed:
        _spawn_reply(entry, answer)


def resolve_target(sender_id: str, to: str) -> dict[str, Any]:
    """The conversation ``to`` names: its id, or its exact title (any case)."""
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation

    to = (to or "").strip()
    if not to:
        raise HandoffRefused("Name the conversation to hand this to: its id or its title.")
    db = _db()
    session = db.get_session(to)
    if session is not None:
        if not owner_conversation(session):
            raise HandoffRefused("That conversation cannot take handoffs: it is archived, "
                                 "imported or a sub-agent's.")
        return session
    rows = [row for row in db.list_sessions(limit=_TITLE_SCAN) if owner_conversation(row)]
    matches = [row for row in rows if _title(row).casefold() == to.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        listed = ", ".join(f"{row['id']}" for row in matches[:10])
        raise HandoffRefused(f"Several conversations are titled {to!r} ({listed}); pass the id instead.")
    known = "; ".join([f"{_title(row)} ({row['id']})" for row in rows if row["id"] != sender_id][:20])
    raise HandoffRefused(f"No conversation is titled {to!r}. Your conversations: {known or 'none'}.")


def handoff_text(sender: dict[str, Any], message: str) -> str:
    return (f"📨 Message from “{_title(sender)}” ({sender['id']}):\n\n{message}\n\n"
            "(Another of your conversations handed this to you. Handle it here; your final "
            "answer goes back to it on its own.)")


def reply_text(target: dict[str, Any], answer: str) -> str:
    return (f"↩️ Reply from “{_title(target)}” ({target['id']}) to the message you sent it:\n\n"
            f"{answer}\n\n(Carry on with your work; this needs no answer.)")


def busy_text(target: dict[str, Any], message: str) -> str:
    return (f"↩️ “{_title(target)}” ({target['id']}) stayed busy for ten minutes, so the "
            f"message you sent it was not delivered:\n\n{message}")


def send(sender_id: str, to: str, message: str, *, msg_id: str | None = None,
         advance_head: bool = True, resumed: bool = False) -> dict[str, Any]:
    """Hand ``message`` to the conversation ``to``; returns at once.

    ``msg_id`` is the sending turn's user message: when it is itself a
    handoff or reply turn, the new message continues its chain. ``resumed``:
    the sending turn continues one a worker restart cut off.
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
    chain = (chain_of(msg_id, session_id=sender_id, resumed=resumed)
             or {"chain": uuid.uuid4().hex[:12], "hop": 0, "origin": sender_id})
    hop = int(chain["hop"]) + 1
    if hop > MAX_HOPS:
        raise HandoffRefused(f"This chain of handoffs already has {MAX_HOPS} hops; finish the "
                             "work here instead of handing it on.")
    row = {"id": uuid.uuid4().hex[:12], "chain": chain["chain"], "hop": hop,
           "origin": chain.get("origin") or sender_id,
           "sender": sender, "target": target, "message": message}
    _spawn(row)
    return {"handoff_id": row["id"], "target_id": target["id"], "target_title": _title(target),
            "hop": hop, "max_hops": MAX_HOPS}


def _spawn(row: dict[str, Any]) -> None:
    """Deliver in the background: waiting for a busy target can take minutes."""
    threading.Thread(target=_deliver, args=(row,), name=f"handoff-{row['id']}", daemon=True).start()


def _start(session: dict[str, Any], text: str, row: dict[str, Any], *,
           reply_to: str | None = None, on_reply=None) -> str | None:
    """A wake turn in ``session`` that belongs to the handoff's chain.

    ``reply_to``: the sender this turn owes its answer; ``on_reply`` gets the
    turn's result when it ends, at most once, unless a restart cut it off.
    """
    from openprogram.runtime.conversation.owner_turn import start_owner_turn_when_free
    msg_id = uuid.uuid4().hex
    _remember(msg_id, str(session["id"]), row, reply_to=reply_to)

    def ended(result: Any) -> None:
        if _ended(msg_id) and on_reply is not None:
            on_reply(result)
    started = start_owner_turn_when_free(
        str(session["id"]), str(session.get("agent_id") or "main"), text, msg_id=msg_id,
        name=f"handoff-{row['id']}", reason_code="handoff_activation_failed", on_done=ended)
    if started is None:
        _ended(msg_id, ran=False)
    else:
        _started(msg_id)
    return started


def _reply(row: dict[str, Any], sender: dict[str, Any], target: dict[str, Any],
           answer: str | None) -> None:
    answer = "(The conversation could not run a turn for it.)" if answer is None else answer.strip()
    if _start(sender, reply_text(target, answer[:REPLY_MAX] or "(No answer text.)"), row) is None:
        _log.info("%s: %s stayed busy; the reply stays in %s", row["id"], sender["id"], target["id"])


def _deliver(row: dict[str, Any]) -> None:
    sender, target = row["sender"], row["target"]

    def answered(result: Any) -> None:
        _reply(row, sender, target,
               None if result is None else str(getattr(result, "final_text", "") or ""))

    try:
        if _start(target, handoff_text(sender, row["message"]), row,
                  reply_to=str(sender["id"]), on_reply=answered) is None:
            _start(sender, busy_text(target, row["message"]), row)
    except Exception as exc:  # noqa: BLE001 - a background delivery never raises into the worker
        _log.warning("%s to %s failed: %s: %s", row["id"], target["id"], type(exc).__name__, exc,
                     exc_info=True)


def _spawn_reply(entry: dict[str, Any], answer: str | None) -> None:
    """Send the reply a cut-off handoff turn owed, in the background."""
    threading.Thread(target=_reply_after_restart, args=(entry, answer),
                     name=f"handoff-reply-{entry.get('handoff_id')}", daemon=True).start()


def _reply_after_restart(entry: dict[str, Any], answer: str | None) -> None:
    from openprogram.runtime.conversation.always_on.runtime import owner_conversation
    try:
        sender, target = _db().get_session(entry["reply_to"]), _db().get_session(entry["session_id"])
        if not owner_conversation(sender) or target is None:
            return
        row = {"id": entry.get("handoff_id") or "resumed", "chain": entry["chain"],
               "hop": entry["hop"], "origin": entry.get("origin")}
        _reply(row, sender, target, answer)
    except Exception as exc:  # noqa: BLE001 - a background delivery never raises into the worker
        _log.warning("reply to %s failed: %s: %s", entry.get("reply_to"), type(exc).__name__, exc,
                     exc_info=True)
