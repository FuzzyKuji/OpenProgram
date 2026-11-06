"""DAG node deletion WS actions — delete selected nodes, undo a delete.

Wire format::

    in:  {"action": "delete_nodes", "session_id": "...", "node_ids": [...]}
    out: {"type": "nodes_deleted",
          "data": {"session_id", "ok", "op_id", "deleted", "error"}}

    in:  {"action": "restore_deleted_nodes", "session_id": "...", "op_id": "..."}
    out: {"type": "nodes_restored",
          "data": {"session_id", "ok", "op_id", "error"}}

The store does the splice and keeps the journal
(``session_store/node_deletion.py``); this layer only refuses while a
turn runs, re-syncs the server's head/message cache, and tells every
client to reload the session so transcript and graph both redraw.
"""
from __future__ import annotations

import asyncio
import json


def _after_graph_change(session_id: str, head_after) -> None:
    from openprogram.interfaces.server import server as _s

    # Always through _set_active_head, even when HEAD stayed: a splice
    # rewrites the active branch itself, and only that call re-reads
    # conv["messages"] (invalidating alone leaves the deleted rows in it).
    _s._set_active_head(session_id, head_after)
    _s.refresh_context_stats(session_id)
    _s._broadcast(json.dumps({
        "type": "session_reload",
        "data": {"session_id": session_id, "reason": "delete_nodes"},
    }, default=str))


async def _run(ws, cmd: dict, reply_type: str, op) -> None:
    from openprogram.interfaces.server import server as _s
    from openprogram.state.store.session.session_store.node_deletion import NodeDeletionError

    session_id = cmd.get("session_id")
    data = {"session_id": session_id, "ok": False, "error": None}
    if not session_id:
        data["error"] = "session_id required"
    elif _s._is_run_active(session_id):
        # The in-flight turn may be writing under the nodes we'd remove.
        data["error"] = _s.RUN_ACTIVE_ERROR
    else:
        try:
            journal = await asyncio.to_thread(op, session_id)
            from openprogram.runtime.context.session_db import default_db
            head = (default_db().get_session(session_id) or {}).get("head_id")
            _after_graph_change(session_id, head)
            data.update(ok=True, op_id=journal.get("op_id"),
                        deleted=len(journal.get("deleted") or []))
        except NodeDeletionError as e:
            data["error"] = str(e)
        except Exception as e:  # noqa: BLE001
            data["error"] = f"{type(e).__name__}: {e}"
    await ws.send_text(json.dumps({"type": reply_type, "data": data}, default=str))


async def handle_delete_nodes(ws, cmd: dict) -> None:
    from openprogram.runtime.context.session_db import default_db

    ids = [str(x) for x in (cmd.get("node_ids") or []) if x]
    await _run(ws, cmd, "nodes_deleted",
               lambda sid: default_db().delete_nodes(sid, ids))


async def handle_restore_deleted_nodes(ws, cmd: dict) -> None:
    from openprogram.runtime.context.session_db import default_db

    op_id = str(cmd.get("op_id") or "")
    await _run(ws, cmd, "nodes_restored",
               lambda sid: default_db().restore_deleted_nodes(sid, op_id))


ACTIONS = {
    "delete_nodes": handle_delete_nodes,
    "restore_deleted_nodes": handle_restore_deleted_nodes,
}
