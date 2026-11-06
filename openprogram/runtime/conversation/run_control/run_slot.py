"""The conversation run slot, as a port the hosting server fills.

One conversation runs one turn at a time. The web server owns that slot
(its run reservation, the running task it shows and the guard every chat
entry point takes), so a turn the runtime starts on its own, such as a
reminder wake or an always-on check-in, must take the same slot or it runs
on top of the owner's turn. The runtime cannot import the server; the
server registers itself here instead. Without a host the slot falls back
to the in-process turn registry.
"""
from __future__ import annotations

from typing import Any, Protocol


class RunSlotPort(Protocol):
    def reserve(self, session_id: str, owner: str) -> bool: ...

    def activate(self, session_id: str, owner: str, *, execution_id: str,
                 status_version: int, runner: Any) -> bool: ...

    def finish(self, session_id: str, owner: str, *, execution_id: str) -> None: ...

    def release(self, session_id: str, owner: str) -> None: ...


class RunSlotBusy(RuntimeError):
    """The conversation is already running a turn."""


_port: RunSlotPort | None = None


def register_run_slot(port: RunSlotPort | None) -> None:
    """Make ``port`` the run slot of this process (``None`` drops it)."""
    global _port
    _port = port


def reserve(session_id: str, owner: str) -> bool:
    if _port is None:
        from .turns import is_turn_running
        return not is_turn_running(session_id)
    return _port.reserve(session_id, owner)


def activate(session_id: str, owner: str, *, execution_id: str,
             status_version: int, runner: Any) -> bool:
    if _port is None:
        return True
    return _port.activate(session_id, owner, execution_id=execution_id,
                          status_version=status_version, runner=runner)


def finish(session_id: str, owner: str, *, execution_id: str) -> None:
    if _port is not None:
        _port.finish(session_id, owner, execution_id=execution_id)


def release(session_id: str, owner: str) -> None:
    if _port is not None:
        _port.release(session_id, owner)


__all__ = [
    "RunSlotBusy", "RunSlotPort", "activate", "finish", "register_run_slot",
    "release", "reserve",
]
