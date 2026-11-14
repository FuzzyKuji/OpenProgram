"""Single-host, cross-process lock serializing a session's Goal admission and mutations."""
from __future__ import annotations

import errno
import hashlib
from contextlib import contextmanager

from openprogram.host._platform import locking


@contextmanager
def goal_owner(store, session_id: str):
    """Try once; an OS-released lock never needs stale-PID guessing or polling.

    The lock is separate from snapshot locks so answering and editing remain
    asynchronous. Keep the file in place: unlinking it permits two owners.
    """
    root = store.root_path.resolve() / ".goal-locks"
    root.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(session_id.encode()).hexdigest()
    with (root / f"{name}.lock").open("a+", encoding="utf-8") as handle:
        try:
            locking.flock(handle.fileno(), locking.LOCK_EX | locking.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            yield False
            return
        try:
            yield True
        finally:
            locking.flock(handle.fileno(), locking.LOCK_UN)

