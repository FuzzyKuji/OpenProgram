"""Message helpers for a model request: the latest user text, memory prefetch injection and durable message dicts."""
from __future__ import annotations

import json
from typing import Any

from contextvars import ContextVar


def _latest_user_text(messages: list) -> str:
    """Walk back from the end and return the last user-role text.

    Memory prefetch uses this as the recall query for the upcoming
    turn. Empty string if no user message is present (e.g. on the
    first model warmup call).
    """
    for msg in reversed(messages):
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role != "user":
            continue
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for c in content:
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, dict):
                    if c.get("type") == "text" or "text" in c:
                        parts.append(str(c.get("text", "")))
                else:
                    text = getattr(c, "text", None)
                    if text:
                        parts.append(str(text))
            joined = " ".join(p for p in parts if p)
            if joined.strip():
                return joined.strip()
        return ""
    return ""


# A workflow role call turns recalled memory off: its request holds only
# what the workflow put there.
memory_prefetch_enabled: ContextVar[bool] = ContextVar("memory_prefetch_enabled", default=True)


def _inject_memory_prefetch(llm_messages: list, block: str) -> bool:
    """Prepend ``block`` to the last user message's text, in place.

    dag/overview.md §7 — prefetched memory belongs to the turn that recalled
    it, not to the session-constant system prompt. Tool results carry role
    ``toolResult``, so the last ``role == "user"`` message is always the
    conversational turn. Returns True when a message was modified.
    """
    prefix = block.rstrip() + "\n\n"
    for msg in reversed(llm_messages or []):
        role = getattr(msg, "role", None) or (
            msg.get("role") if isinstance(msg, dict) else None)
        if role != "user":
            continue
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if isinstance(content, str):
            _set_content(msg, prefix + content)
            return True
        if isinstance(content, list):
            for part in content:
                ptype = getattr(part, "type", None) or (
                    part.get("type") if isinstance(part, dict) else None)
                if ptype != "text":
                    continue
                if isinstance(part, dict):
                    part["text"] = prefix + str(part.get("text") or "")
                else:
                    part.text = prefix + (getattr(part, "text", "") or "")
                return True
            # Image/file-only turn: no text part to prefix — leave it alone
            # rather than inventing a block ordering the provider may reject.
        return False
    return False


def _set_content(msg, value) -> None:
    if isinstance(msg, dict):
        msg["content"] = value
    else:
        msg.content = value


def _durable_message(message: Any) -> dict[str, Any]:
    """Return JSON data only; checkpoints never retain provider objects."""
    if hasattr(message, "model_dump"):
        try:
            value = message.model_dump(mode="json")
        except Exception:
            # AgentTool contains its executable callback, which is not a
            # durable value.  A checkpoint needs the resolved public schema,
            # not a repr of that callback or a process-local object address.
            if all(hasattr(message, field) for field in ("name", "description", "parameters")):
                value = {
                    "name": message.name,
                    "description": message.description,
                    "parameters": message.parameters,
                }
            else:
                value = {"repr": str(message)}
    elif isinstance(message, dict):
        value = dict(message)
    else:
        value = {"repr": str(message)}
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
