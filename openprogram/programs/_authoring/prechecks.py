"""Argument checks that run before a call asks for approval.

A tool whose calls need the owner's approval registers a check here, so a
call that would fail on its arguments is refused before the approval card is
shown: the owner never approves a call that cannot run, and the model gets
the problem back at once. The check is pure: it reads the arguments only and
returns the problem as text, or ``None`` when the call may proceed.
"""
from __future__ import annotations

from typing import Callable, Optional

Check = Callable[[dict], Optional[str]]

_registry: dict[str, Check] = {}


def register(tool: str, check: Check) -> None:
    _registry[tool] = check


def problem(tool: str, args: dict) -> Optional[str]:
    """What is wrong with ``args`` for ``tool``, or ``None``."""
    check = _registry.get(tool)
    if check is None:
        return None
    try:
        return check(args if isinstance(args, dict) else {})
    except Exception:  # noqa: BLE001 — a broken check must not block the call
        return None


__all__ = ["problem", "register"]
