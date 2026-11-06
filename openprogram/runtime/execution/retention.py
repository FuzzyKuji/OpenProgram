"""Retention for finished executions.

An effect carries what its boundary needed to replay the step: the
provider's whole message context, the tool's whole arguments. A finished
execution is never replayed (a branch from one of its checkpoints renders
its context from the conversation graph when the effect holds none), so
on a long conversation every model call leaves hundreds of kilobytes of
dead weight, and the store grows by gigabytes. Compaction keeps each
effect's identity (kind, hashes, tool name, call id, the wait it opened)
and drops the replay payload, then lets go of the execution's state blobs
that nothing references any more. An effect whose outcome is still unknown
(no receipt) keeps its payload: that is what the user reconciles it from.

Compaction runs once per execution when it reaches a terminal state, and
a sweep at worker start catches up on executions that finished before
this existed or while the worker was down. ``execution_retention`` lists
the executions already compacted, so the sweep never reads an effect
twice; a dropped payload is not rebuilt.
"""
from __future__ import annotations

from contextlib import closing
import json
import logging
import threading
import time
from typing import Any, Callable

from .model import TERMINAL_EXECUTION_STATUSES

_log = logging.getLogger(__name__)

# The payload keys a finished execution no longer needs, per effect kind.
REPLAY_KEYS: dict[str, tuple[str, ...]] = {
    "provider.before": ("context", "resolved_snapshot", "dispatch_candidates"),
    "tool.before": ("arguments", "resolved_snapshot"),
}
# Bumped whenever REPLAY_KEYS grows: a store compacted under an earlier pass
# forgets its ``execution_retention`` rows once, so the sweep revisits every
# finished execution and sheds the newly listed keys. A payload already gone
# costs the revisit nothing.
COMPACTION_PASS = 2
_PASS_KEY = "retention_pass"
# Delivered projection outbox rows are only history; they go after a week.
OUTBOX_RETENTION_SECONDS = 7 * 86400
OUTBOX_PURGE_BATCH = 5000
# Free pages handed back to the file system per sweep, at most (4 KiB each).
RECLAIM_PAGES_PER_SWEEP = 65536
RECLAIM_PAGES_PER_STEP = 1024
# A sweep pauses this long between executions so it never competes with a
# live turn for the store.
SWEEP_PAUSE_SECONDS = 0.05
# An execution just finished is still being read by its terminal
# projections and settlers; compaction waits this long after the end.
SETTLE_SECONDS = 60.0


def _terminal_statuses() -> tuple[str, ...]:
    return tuple(status.value for status in TERMINAL_EXECUTION_STATUSES)


def compact_effects(store: Any, execution_id: str) -> int:
    """Drop the replay payloads of a finished execution's effects.

    Returns the number of effects rewritten; 0 when the execution is not
    terminal or was compacted before. A compacted execution is listed in
    ``execution_retention`` so the sweep never reads its effects again.
    """
    with store._transaction() as connection:
        execution = store._require_execution(connection, execution_id)
        if execution.status not in TERMINAL_EXECUTION_STATUSES:
            return 0
        if connection.execute(
            "SELECT 1 FROM execution_retention WHERE execution_id = ?", (execution_id,),
        ).fetchone() is not None:
            return 0
        rows = connection.execute(
            "SELECT effect_id, metadata_json FROM effects "
            "WHERE execution_id = ? AND resolved_at IS NOT NULL",
            (execution_id,),
        ).fetchall()
        changed = 0
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            if not isinstance(metadata, dict):
                continue
            payload = metadata.get("payload")
            keys = REPLAY_KEYS.get(str(metadata.get("kind") or ""), ())
            if not isinstance(payload, dict) or not any(key in payload for key in keys):
                continue
            for key in keys:
                payload.pop(key, None)
            connection.execute(
                "UPDATE effects SET metadata_json = ? WHERE effect_id = ?",
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), default=str), row["effect_id"]),
            )
            changed += 1
        connection.execute(
            "INSERT OR REPLACE INTO execution_retention (execution_id, compacted_at) VALUES (?, ?)",
            (execution_id, time.time()),
        )
        return changed


def compact_execution(store: Any, execution_id: str) -> dict[str, int]:
    """Compact one finished execution: its effects, then its state blobs."""
    effects = compact_effects(store, execution_id)
    try:
        blobs = int(store.gc_state_blobs(execution_id))
    except Exception as exc:  # the execution is not terminal, or gone
        _log.debug("state blob gc skipped for %s: %s", execution_id, exc)
        blobs = 0
    return {"effects": effects, "blobs": blobs}


def executions_to_compact(store: Any, *, limit: int = 200, now: float | None = None) -> list[str]:
    """Finished executions not compacted yet, oldest first."""
    cutoff = (time.time() if now is None else now) - SETTLE_SECONDS
    placeholders = ",".join("?" for _ in _terminal_statuses())
    with store._transaction() as connection:
        rows = connection.execute(
            "SELECT execution_id FROM executions "
            f"WHERE status IN ({placeholders}) AND updated_at < ? "
            "AND execution_id NOT IN (SELECT execution_id FROM execution_retention) "
            "ORDER BY updated_at LIMIT ?",
            (*_terminal_statuses(), cutoff, int(limit)),
        ).fetchall()
    return [str(row[0]) for row in rows]


def begin_pass(store: Any) -> bool:
    """Forget earlier compactions once when REPLAY_KEYS grew since; True when it did."""
    with store._transaction() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = connection.execute("SELECT value FROM store_meta WHERE key = ?", (_PASS_KEY,)).fetchone()
        try:
            recorded = int(row[0]) if row is not None else 1
        except (TypeError, ValueError):
            recorded = 1
        if recorded >= COMPACTION_PASS:
            return False
        forgotten = connection.execute("DELETE FROM execution_retention").rowcount
        connection.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_PASS_KEY, str(COMPACTION_PASS)),
        )
        return forgotten > 0


def purge_delivered_outbox(store: Any, *, older_than: float = OUTBOX_RETENTION_SECONDS,
                           batch: int = OUTBOX_PURGE_BATCH, pause: float = SWEEP_PAUSE_SECONDS,
                           now: float | None = None, stop: threading.Event | None = None) -> int:
    """Delete projection outbox rows delivered more than ``older_than`` seconds ago.

    Every canonical event fans out to one outbox row per projection kind;
    once delivered the row is spent, and nothing reads it again. Rows go in
    batches so a live turn never waits long for the write lock.
    """
    cutoff = (time.time() if now is None else now) - older_than
    deleted = 0
    while stop is None or not stop.is_set():
        with store._transaction() as connection:
            count = connection.execute(
                "DELETE FROM execution_projection_outbox WHERE rowid IN ("
                "SELECT rowid FROM execution_projection_outbox "
                "WHERE state = 'delivered' AND delivered_at < ? LIMIT ?)",
                (cutoff, int(batch)),
            ).rowcount
        deleted += max(0, int(count))
        if count < batch:
            break
        if pause:
            time.sleep(pause)
    return deleted


def reclaim_free_pages(store: Any, *, max_pages: int = RECLAIM_PAGES_PER_SWEEP,
                       step: int = RECLAIM_PAGES_PER_STEP, pause: float = SWEEP_PAUSE_SECONDS,
                       stop: threading.Event | None = None) -> int:
    """Hand free pages back to the file system in short steps.

    Works on a store whose ``auto_vacuum`` is incremental (see
    ``ExecutionStore.maintain_file``); elsewhere it does nothing. Returns
    the number of pages the file shrank by.
    """
    reclaimed = 0
    with closing(store._connect()) as connection:
        if int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]) != 2:
            return 0
        while reclaimed < max_pages and (stop is None or not stop.is_set()):
            free = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            if free <= 0:
                break
            wanted = min(step, free, max_pages - reclaimed)
            connection.execute(f"PRAGMA incremental_vacuum({int(wanted)})").fetchall()
            after = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            if after >= free:
                break
            reclaimed += free - after
            if pause:
                time.sleep(pause)
    return reclaimed


def sweep(store: Any, *, limit: int = 200, pause: float = SWEEP_PAUSE_SECONDS,
          stop: threading.Event | None = None) -> dict[str, int]:
    """Compact every finished execution the store still holds at full size."""
    totals = {"executions": 0, "effects": 0, "blobs": 0}
    try:
        if begin_pass(store):
            _log.info("execution retention: compaction pass %d revisits every finished execution",
                      COMPACTION_PASS)
    except Exception:
        _log.exception("execution retention: could not record the compaction pass")
    for execution_id in executions_to_compact(store, limit=limit):
        if stop is not None and stop.is_set():
            break
        try:
            result = compact_execution(store, execution_id)
        except Exception:
            _log.exception("compacting execution %s failed", execution_id)
            continue
        totals["executions"] += 1
        totals["effects"] += result["effects"]
        totals["blobs"] += result["blobs"]
        if pause:
            time.sleep(pause)
    return totals


def _in_thread(name: str, target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name=name).start()


class _Deferred(threading.Thread):
    """A daemon thread that runs ``target`` after ``delay`` unless cancelled."""

    def __init__(self, name: str, target: Callable[[], None], delay: float) -> None:
        super().__init__(name=name, daemon=True)
        self._deferred_target = target
        self._delay = delay
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        if not self._cancelled.wait(self._delay):
            self._deferred_target()


def _after_settling(name: str, target: Callable[[], None]) -> None:
    _Deferred(name, target, SETTLE_SECONDS).start()


# Tests replace this to run compaction inline.
defer: Callable[[str, Callable[[], None]], None] = _after_settling


def compact_later(store: Any, execution: Any) -> None:
    """Compact a just-finished execution once its end has settled.

    ``execution`` is the record or its id; nothing happens for ``None``.
    """
    if store is None or execution is None:
        return
    execution_id = str(getattr(execution, "execution_id", execution))
    if not execution_id:
        return

    def run() -> None:
        try:
            compact_execution(store, execution_id)
        except Exception:
            _log.exception("compacting execution %s failed", execution_id)

    defer(f"execution-compaction-{execution_id[:12]}", run)


def start_sweep(store: Any, *, delay: float = 15.0) -> threading.Event:
    """Run one catch-up sweep in the background; the event stops it early."""
    stop = threading.Event()

    def run() -> None:
        if stop.wait(delay):
            return
        started = time.monotonic()
        totals = sweep(store, limit=100000, stop=stop)
        if totals["executions"]:
            _log.info(
                "execution retention: compacted %d executions (%d effects, %d state blobs) in %.1fs",
                totals["executions"], totals["effects"], totals["blobs"], time.monotonic() - started,
            )
        if stop.is_set():
            return
        try:
            purged = purge_delivered_outbox(store, stop=stop)
            reclaimed = reclaim_free_pages(store, stop=stop)
        except Exception:
            _log.exception("execution retention: store housekeeping failed")
            return
        if purged or reclaimed:
            _log.info(
                "execution retention: dropped %d delivered outbox rows and returned %d pages to the file system",
                purged, reclaimed,
            )

    _in_thread("execution-retention-sweep", run)
    return stop


__all__ = [
    "COMPACTION_PASS",
    "REPLAY_KEYS",
    "begin_pass",
    "compact_effects",
    "compact_execution",
    "compact_later",
    "executions_to_compact",
    "purge_delivered_outbox",
    "reclaim_free_pages",
    "start_sweep",
    "sweep",
]
