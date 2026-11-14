"""Move what the removed ``handoff`` tool left waiting onto ``send_message``.

The always-on hand-off saved every message and reply turn in
``<state>/always_on/handoffs.json`` (``handoff.py``). The model now reaches
another conversation with ``send_message``, whose delivery is a tracked Job
and whose reply comes back as a notice with no timeout. This moves the
entries that were still **waiting** for a busy conversation onto that path;
everything else stays where it was:

* a waiting message (``reply_to`` set) is delivered by ``send_message``
  from its sender to its target, carrying its hop count;
* a waiting reply is delivered by ``send_message`` from the conversation
  that answered (named in the reply's own text) to the one that asked;
* a waiting message that also owes earlier conversations an answer
  (``owed_after``) stays for the old replay, which carries that chain on;
* a delivery ``send_message`` refuses (``[send_message error]``) stays
  pending under a new Job id and is tried again at the next Worker start;
* a turn already running or paused keeps its entry in ``handoffs.json``,
  so the reply it owes is still sent when it ends (``handoff.turn_ended``),
  and finished entries stay there until they age out as before.

Every entry moved is kept, as it was, in ``handoffs.migrated.json`` beside
its delivery's state and ``execution_id``, and ``handoffs.json`` is copied
once to ``handoffs.before-migration.json`` before anything changes, so old
hand-offs stay readable. The transcripts' 📨 and ↩️ rows are not touched.

A dry run (the default of :func:`migrate`) only reports. Applying is
repeatable: each delivery admits a Job with an id fixed by its entry, and a
Job that already exists is not admitted again, so a Worker that stops
midway delivers each entry once on its next start.

Design: docs/reference/design/runtime/collaboration/agent-collaboration.html#stored-handoffs
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from openprogram.runtime.conversation.always_on import store

_log = logging.getLogger(__name__)

MIGRATED_NAME = "handoffs.migrated.json"
BACKUP_NAME = "handoffs.before-migration.json"
#: ``“Title” (conversation id)``, as every ↩️ text names the conversation it came from.
_FROM = re.compile(r"“[^”]*” \(([^()\s]+)\)")

Send = Callable[[dict[str, Any]], tuple[str, Optional[str], str]]


def _paths() -> tuple[Path, Path, Path]:
    current = store._handoffs_path()  # noqa: SLF001 - the hand-off file this module retires
    return current, current.with_name(MIGRATED_NAME), current.with_name(BACKUP_NAME)


def job_id_for(msg_id: str) -> str:
    """The delivery Job's id for one stored entry, the same on every run."""
    return "j_" + hashlib.sha256(f"handoff:{msg_id}".encode("utf-8")).hexdigest()[:14]


def plan(chains: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """``(deliveries, kept)``: what moves to ``send_message`` and what stays."""
    deliveries: dict[str, dict[str, Any]] = {}
    kept: dict[str, Any] = {}
    for msg_id, entry in chains.items():
        if (not isinstance(entry, dict) or entry.get("phase") != "waiting" or not entry.get("text")
                or entry.get("owed_after")):
            # An entry that owes earlier conversations an answer after its
            # own (``owed_after``) has no send_message equivalent: the old
            # replay carries that chain on.
            kept[msg_id] = entry
            continue
        hop = int(entry.get("hop") or 0)
        if entry.get("reply_to"):
            deliveries[msg_id] = {
                "kind": "message", "from": str(entry["reply_to"]), "to": str(entry["session_id"]),
                "message": str(entry.get("message") or entry["text"]), "hop": hop,
            }
            continue
        answered_by = _FROM.search(str(entry["text"]))
        if answered_by is None:
            # No conversation to send it from: the old replay delivers it.
            kept[msg_id] = entry
            continue
        deliveries[msg_id] = {
            "kind": "reply", "from": answered_by.group(1), "to": str(entry["session_id"]),
            "message": str(entry["text"]), "hop": hop,
        }
    for msg_id, delivery in deliveries.items():
        delivery.update(job_id=job_id_for(msg_id), status="pending")
    return deliveries, kept


def _record(path: Path) -> dict[str, Any]:
    record = store._read_json(path)  # noqa: SLF001
    return {"version": 1, "original": dict(record.get("original") or {}),
            "deliveries": dict(record.get("deliveries") or {})}


def migrate(*, apply: bool = False, deliver: bool = True, send: Send | None = None) -> dict[str, Any]:
    """Report, and with ``apply`` carry out, the move. Returns the counts.

    ``deliver=False`` moves the entries without sending them yet (the Worker
    sends them on a thread, :func:`deliver_pending`).
    """
    current, migrated, backup = _paths()
    with store.lock("handoffs"):
        chains = store._read_json(current)  # noqa: SLF001
        record = _record(migrated)
        deliveries, kept = plan(chains)
        report = {"messages": sum(d["kind"] == "message" for d in deliveries.values()),
                  "replies": sum(d["kind"] == "reply" for d in deliveries.values()),
                  "kept": len(kept),
                  "pending": sum(d.get("status") == "pending" for d in record["deliveries"].values()),
                  "applied": False}
        if not apply:
            return report
        if deliveries:
            if current.exists() and not backup.exists():
                shutil.copy2(current, backup)
            for msg_id, delivery in deliveries.items():
                record["original"].setdefault(msg_id, chains[msg_id])
                record["deliveries"].setdefault(msg_id, delivery)
            # The record first: a stop before the next write leaves the entry
            # in both files, and the next run moves it once.
            store._write_json(migrated, record)  # noqa: SLF001
            store.save_handoffs(kept)
        report["applied"] = True
    if deliver:
        report.update(deliver_pending(send=send))
    return report


def deliver_pending(*, send: Send | None = None, settle: Callable[[str], None] | None = None) -> dict[str, int]:
    """Send every moved entry not delivered yet; returns how many went and how many could not."""
    _current, migrated, _backup = _paths()
    send = send or send_with_send_message
    with store.lock("handoffs"):
        pending = {msg_id: dict(delivery) for msg_id, delivery in _record(migrated)["deliveries"].items()
                   if delivery.get("status") == "pending"}
    done = failed = 0
    for msg_id, delivery in pending.items():
        if settle is not None:
            settle(delivery["to"])
        try:
            status, execution_id, note = send(delivery)
        except Exception as exc:  # noqa: BLE001 - one entry never stops the others
            _log.warning("hand-off %s not delivered: %s: %s", msg_id, type(exc).__name__, exc)
            status, execution_id, note = "pending", None, f"{type(exc).__name__}: {exc}"
        with store.lock("handoffs"):
            record = _record(migrated)
            entry = record["deliveries"].get(msg_id)
            if entry is None:
                continue
            entry.update(status=status, note=note, at=time.time())
            if execution_id:
                entry["execution_id"] = execution_id
            if status == "retry":
                # send_message refused it this time (it may have admitted and
                # cancelled its Job): the next Worker start tries again under
                # a new id, so that Job is not taken for a delivery.
                attempts = int(entry.get("attempts") or 0) + 1
                entry.update(status="pending", attempts=attempts,
                             job_id=job_id_for(f"{msg_id}#{attempts}"))
            store._write_json(migrated, record)  # noqa: SLF001
        done += status == "delivered"
        failed += status == "failed"
    return {"delivered": done, "failed": failed}


_EXECUTION_ID = re.compile(r"execution_id=(\S+)")


def send_with_send_message(delivery: dict[str, Any]) -> tuple[str, Optional[str], str]:
    """Deliver one moved entry as ``send_message`` does: a tracked Job on
    the target, its reply back to the sender as a notice."""
    from openprogram.programs.tools.agents.send_message.send_message.dispatch import deliver
    from openprogram.runtime.context.session_db import default_db
    from openprogram.runtime.jobs import get_runner
    from openprogram.runtime.permissions.authority import authority_from_message, local_owner_authority

    job_id = delivery["job_id"]
    if get_runner().get_job(job_id) is not None:
        return "delivered", job_id, "admitted by an earlier run"
    db = default_db()
    sender, target = db.get_session(delivery["from"]), db.get_session(delivery["to"])
    if sender is None or target is None:
        gone = delivery["from"] if sender is None else delivery["to"]
        return "failed", None, f"conversation {gone} no longer exists"
    anchor = str(sender.get("head_id") or "")
    authority = authority_from_message(delivery["from"], anchor) or local_owner_authority()
    text = deliver(
        message=delivery["message"], sid=delivery["from"], aid=anchor,
        parent_agent=sender.get("agent_id"), chosen_agent=str(target.get("agent_id") or "main"),
        run_session=delivery["to"], target_tip=str(target.get("head_id") or ""),
        caller_authority=authority, messages=int(delivery.get("hop") or 0), generations=0,
        job_id=job_id,
    )
    found = _EXECUTION_ID.search(text)
    if found is None:
        if text.startswith("[send_message error]"):
            return "retry", None, text[:500]
        if "duplicate message ignored" in text:
            return "delivered", None, text[:200]
        return "failed", None, text[:500]
    return "delivered", found.group(1), text.splitlines()[0][:200]


def migrate_in_worker() -> None:
    """At Worker start: move the waiting entries now, before the old replay
    reads the file, and send them once each conversation's restart settled."""
    report = migrate(apply=True, deliver=False)
    if not report["messages"] and not report["replies"] and not report["pending"]:
        return
    from openprogram.runtime.conversation.always_on.handoff import _wait_for_restart_to_settle

    threading.Thread(target=deliver_pending, kwargs={"settle": _wait_for_restart_to_settle},
                     name="handoff-migration", daemon=True).start()


__all__ = ["deliver_pending", "job_id_for", "migrate", "migrate_in_worker", "plan",
           "send_with_send_message"]
