"""An observation as the changes since the previous one of the same page.

Every observation still issues fresh refs for all its elements, so every
ref shown here is valid and refs from the earlier frame stay refused. Only
what is shown shrinks: an element that looks exactly as it did before is
one short line with its new ref, an unchanged text or ARIA snapshot is left
out, and elements that disappeared are named.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

MAX_REMOVED = 40
_SIGNATURE_FIELDS = ("role", "name", "label", "value", "disabled", "input_type")


def _signature(element: dict[str, Any]) -> tuple:
    return tuple(repr(element.get(field)) for field in _SIGNATURE_FIELDS)


def _label(element: dict[str, Any]) -> str:
    name = str(element.get("name") or element.get("label") or "").strip()
    role = str(element.get("role") or "element")
    return f"{role} {name!r}" if name else role


def changes(previous: dict[str, Any] | None, frame: dict[str, Any]) -> dict[str, Any]:
    """``frame`` reduced to what differs from ``previous``; whole when there is nothing to compare."""
    if not previous or previous.get("url") != frame.get("url"):
        return {**frame, "changes_only": False,
                "changes_note": "No earlier observation of this page; the whole frame is shown."}
    before = Counter(_signature(e) for e in previous.get("elements") or [])
    changed, unchanged = [], []
    for element in frame.get("elements") or []:
        signature = _signature(element)
        if before[signature] > 0:
            before[signature] -= 1
            unchanged.append(f"{element.get('ref')} {_label(element)}")
        else:
            changed.append(element)
    # An old element whose role and name reappear among the changed ones was changed, not removed.
    renewed = Counter(_label(e) for e in changed)
    removed = []
    for element in previous.get("elements") or []:
        signature, label = _signature(element), _label(element)
        if before[signature] <= 0:
            continue
        before[signature] -= 1
        if renewed[label] > 0:
            renewed[label] -= 1
        else:
            removed.append(label)
    out = {**frame, "elements": changed, "changes_only": True,
           "unchanged_elements": unchanged}
    if removed:
        out["removed_elements"] = removed[:MAX_REMOVED] + (
            [f"…and {len(removed) - MAX_REMOVED} more"] if len(removed) > MAX_REMOVED else [])
    for field in ("text", "aria_snapshot"):
        if frame.get(field) == previous.get(field):
            out.pop(field, None)
            out[f"{field}_unchanged"] = True
    return out


__all__ = ["changes"]
