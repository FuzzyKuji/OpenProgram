"""Event-stream tap — incremental tool-node persistence (dispatcher-split).

Wraps the caller's ``on_event`` so tool_execution_end envelopes are
sniffed and each completed tool row is written to the DB incrementally —
without changing ``_run_loop_blocking``'s signature (test mocks wrap it
positionally and would break on a new kwarg).
"""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Callable
from dataclasses import dataclass

if TYPE_CHECKING:
    from openprogram.runtime.conversation.turn_runtime.types import EventCallback
    from openprogram.runtime.agent.turn_request import TurnRequest

_log = logging.getLogger(__name__)


def utf16_length(text: str) -> int:
    """Length in UTF-16 units, the unit a browser's string offsets use."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def block_item_id(blocks: list[dict], index: int) -> str:
    """The stable id of a text or thinking block.

    ``<type>:<n>`` counts runs of that type; a later block in the same run
    is ``<type>:<n>.<k>``, so a block the tap merged keeps its id when the
    final write segments it.
    """
    kind = blocks[index].get("type")
    run = -1
    position = 0
    for i in range(index + 1):
        if blocks[i].get("type") != kind:
            continue
        if i == 0 or blocks[i - 1].get("type") != kind:
            run += 1
            position = 0
        else:
            position += 1
    return f"{kind}:{run}.{position}" if position else f"{kind}:{run}"


def naming_reply_row(on_event: "EventCallback", session_id: str, user_msg_id: str, reply_row_id: str) -> "EventCallback":
    """Stamp the reply's row id on every frame of this turn that lacks one.

    A client looks up the reply a result, error or retry frame answers by
    this ``row_id``; it never builds the id from ``msg_id`` itself.
    """
    def emit(env: dict) -> None:
        data = env.get("data") if env.get("type") == "chat_response" else None
        if (isinstance(data, dict) and "row_id" not in data and data.get("msg_id") == user_msg_id
                and data.get("session_id") in (None, session_id) and data.get("type") != "user_message"):
            env = {**env, "data": {**data, "row_id": reply_row_id}}
        on_event(env)
    return emit


@dataclass
class StreamTap:
    callback: Callable[[dict], None]
    flush: Callable[[], None]
    blocks: list[dict]

    def __call__(self, env: dict) -> None:
        self.callback(env)


def final_blocks(tap: StreamTap, ordered: list[dict], cancel_event) -> list[dict]:
    """The blocks a reply's terminal write keeps.

    A Stop keeps the partial text the tap received. Otherwise the loop's
    ordered blocks win, and the tap's trace stands in when it has none.
    """
    if cancel_event is not None and cancel_event.is_set():
        return tap.blocks
    return ordered or tap.blocks


def make_stream_tap(
    *,
    on_event: "EventCallback",
    req: "TurnRequest",
    assistant_msg_id: str,
    placeholder_inserted: bool,
    agentic_tool_names: set[str],
) -> StreamTap:
    """Return the wrapped ``on_event`` used for the agent-loop run.

    ``agentic_tool_names`` is the (shared, mutable) set the loop runner
    fills once it resolves the tool list — Agent method calls are
    rendered as a runtime-block row (persisted by the wrapper in
    ``_wrap_agentic_runtime_block``), so the tap skips them here to
    avoid duplicating the call in chat.

    Every ``stream_event`` frame of this reply gets a ``seq`` one higher
    than the last, and the persisted row records the ``stream_seq`` its
    content already reflects. A client that loads the row mid-turn applies
    only frames with a higher ``seq``, so no delta is shown twice or lost.
    """
    _tool_args_by_id: dict[str, dict] = {}
    from openprogram.runtime.context.session_db import default_db
    from openprogram.state.store import SessionNodeWriter
    store = default_db()
    writer = SessionNodeWriter(store, req.session_id)
    # A resumed execution reuses its placeholder and its earlier display trace.
    node = next((n for n in store.get_nodes(req.session_id) if n.id == assistant_msg_id), None)
    existing = (node.metadata or {}) if node else {}
    extra = existing.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (ValueError, TypeError):
            extra = {}
    blocks: list[dict] = [dict(b) for b in extra.get("blocks", [])] if isinstance(extra, dict) else []
    for block in blocks:
        if block.get("type") == "tool" and block.get("tool_call_id"):
            _tool_args_by_id[block["tool_call_id"]] = block
    # A resumed execution continues its reply's numbering.
    stream_seq = int(extra.get("stream_seq") or 0) if isinstance(extra, dict) else 0
    dirty = False

    from openprogram.state.memory.policy import stamp as _memory_stamp

    def flush(*, quiet: bool = False) -> None:
        nonlocal dirty
        if not dirty or not placeholder_inserted:
            return
        try:
            fields = {
                "output": "".join(b["text"] for b in blocks if b["type"] == "text"),
                "metadata": {**_memory_stamp(req), "extra": json.dumps({
                    **(extra if isinstance(extra, dict) else {}),
                    "blocks": blocks, "stream_seq": stream_seq,
                }, default=str)},
            }
            if quiet:
                store.update_stream_progress(req.session_id, assistant_msg_id, **fields)
            else:
                writer.update(assistant_msg_id, **fields)
            dirty = False
        except Exception:
            _log.warning("failed to persist chat progress for session %s", req.session_id, exc_info=True)

    def _owns(payload: dict) -> bool:
        # Runtime children share this callback but own different rows.
        if payload.get("session_id") not in (None, req.session_id):
            return False
        return payload.get("msg_id") in (
            None, req.user_msg_id, assistant_msg_id.removesuffix("_reply"),
            assistant_msg_id,
        )

    def _on_event_persist(env: dict) -> None:
        nonlocal dirty, stream_seq
        payload = env.get("data") if env.get("type") == "chat_response" else None
        if (isinstance(payload, dict) and payload.get("type") == "stream_event"
                and _owns(payload)):
            stream_seq += 1
            payload["seq"] = stream_seq
        # A frame sent before a read is reflected in that read, so the row
        # is written first. A failed write still emits; the offset shows it.
        _persist(env)
        on_event(env)

    def _persist(env: dict) -> None:
        nonlocal dirty
        if not placeholder_inserted:
            return
        try:
            if env.get("type") != "chat_response":
                return
            payload = env.get("data") or {}
            if (payload.get("type") == "user_message" and payload.get("steering")
                    and payload.get("assistant_msg_id") == assistant_msg_id
                    and payload.get("session_id") == req.session_id):
                if not any(b.get("type") == "steering" and b.get("message_id") == payload.get("msg_id") for b in blocks):
                    blocks.append({"type":"steering", "message_id":payload["msg_id"],
                                   "text":payload.get("content", ""), "timestamp":payload.get("timestamp")})
                    dirty = True
                    flush()
                return
            if payload.get("type") != "stream_event" or not _owns(payload):
                return
            evt = payload.get("event") or {}
            etype = evt.get("type")
            if etype in {"thinking", "text", "tool_use", "tool_result"}:
                if etype in {"thinking", "text"}:
                    delta = evt.get("text") or ""
                    if blocks and blocks[-1].get("type") == etype:
                        offset = utf16_length(blocks[-1]["text"])
                        blocks[-1]["text"] += delta
                    else:
                        offset = 0
                        blocks.append({"type": etype, "text": delta})
                    payload.update(
                        row_id=assistant_msg_id,
                        item_id=block_item_id(blocks, len(blocks) - 1),
                        item_index=len(blocks) - 1,
                        offset=offset,
                    )
                elif etype == "tool_use":
                    tid = evt.get("tool_call_id")
                    if not tid or not any(b.get("type") == "tool" and b.get("tool_call_id") == tid for b in blocks):
                        card = {
                            "type": "tool", "tool": evt.get("tool"),
                            "tool_call_id": tid,
                            "input": evt.get("input"), "result": None,
                            "is_error": False,
                        }
                        if evt.get("provider_executed"):
                            card["provider_executed"] = True
                        blocks.append(card)
                else:
                    for block in reversed(blocks):
                        if (block.get("type") == "tool"
                                and block.get("tool_call_id") == evt.get("tool_call_id")):
                            block.update(result=evt.get("result"),
                                         is_error=bool(evt.get("is_error")),
                                         outcome=evt.get("outcome"))
                            if evt.get("provider_executed"):
                                # The query of a provider search is often
                                # known only when it ends.
                                block["provider_executed"] = True
                                if evt.get("input"):
                                    block["input"] = evt.get("input")
                            break
                    else:
                        if evt.get("provider_executed"):
                            blocks.append({
                                "type": "tool", "tool": evt.get("tool"),
                                "tool_call_id": evt.get("tool_call_id"),
                                "provider_executed": True,
                                "input": evt.get("input"),
                                "result": evt.get("result"),
                                "is_error": bool(evt.get("is_error")),
                                "outcome": evt.get("outcome"),
                            })
                dirty = True
                flush(quiet=etype in {"thinking", "text"})
            if etype == "text_end" and evt.get("citations"):
                for index in range(len(blocks) - 1, -1, -1):
                    if blocks[index].get("type") == "text":
                        blocks[index]["citations"] = list(evt["citations"])
                        payload.update(row_id=assistant_msg_id, item_id=block_item_id(blocks, index))
                        dirty = True
                        flush()
                        break
                return
            if evt.get("provider_executed"):
                # The provider ran this search; the reply's blocks carry it
                # and no local tool node (a ToolCall on replay) is written.
                return
            if etype == "tool_use":
                tid = evt.get("tool_call_id")
                if tid:
                    _tool_args_by_id[tid] = {
                        "tool": evt.get("tool"),
                        "input": evt.get("input"),
                    }
            elif etype == "tool_result":
                tid = evt.get("tool_call_id")
                if not tid:
                    return
                meta = _tool_args_by_id.get(tid, {})
                # Agent method tool calls are rendered as a
                # runtime-block row (persisted by the wrapper in
                # _wrap_agentic_runtime_block) — don't ALSO persist
                # them as collapsed role=tool entries, that would
                # duplicate the call in chat.
                _tname = meta.get("tool") or evt.get("tool") or ""
                if _tname in agentic_tool_names:
                    return
                from openprogram.runtime.context.session_db import (
                    default_db as _db,
                )
                from openprogram.state.store.session.nodes import Call, ROLE_CODE
                from openprogram.state.store import SessionNodeWriter

                _tool_name = (meta.get("tool")
                              or evt.get("tool") or "")
                _node_id = f"{assistant_msg_id}_t_{tid}"
                _store = _db()
                if _store.message_exists(req.session_id, _node_id):
                    return
                _node = Call(
                    id=_node_id,
                    created_at=time.time(),
                    role=ROLE_CODE,
                    name=_tool_name,
                    input=meta.get("input") or {},
                    output=str(evt.get("result") or ""),
                    caller=assistant_msg_id,
                    metadata={
                        **_memory_stamp(req),
                        "tool_call_id": tid,
                        "is_error": bool(evt.get("is_error")),
                        "outcome": evt.get("outcome"),
                    },
                )
                SessionNodeWriter(
                    _store, req.session_id,
                ).append(_node)
        except Exception:
            # Event-tap boundary: this runs inside the provider's stream
            # callback, so raising here would abort a turn that is
            # otherwise fine. A dropped tool node costs history fidelity,
            # which is worth a log line.
            _log.warning(
                "failed to persist tool node for session %s",
                req.session_id, exc_info=True,
            )

    return StreamTap(_on_event_persist, flush, blocks)
