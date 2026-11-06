"""Rewind actions: list points, plan and apply."""
from __future__ import annotations

import json


async def handle_rewind_list(ws, cmd: dict):
    """List available rewind points for the session."""
    session_id = (cmd.get("session_id") or "").strip()
    if not session_id:
        await ws.send_text(json.dumps({
            "type": "rewind_points",
            "data": {"session_id": session_id or None, "points": [],
                     "error": "No session_id provided"},
        }))
        return
    try:
        from openprogram.runtime.conversation.rewind import list_rewind_points
        import asyncio
        loop = asyncio.get_event_loop()
        points = await loop.run_in_executor(
            None, lambda: list_rewind_points(session_id),
        )
        await ws.send_text(json.dumps({
            "type": "rewind_points",
            "data": {"session_id": session_id, "points": points},
        }, default=str))
    except Exception as e:
        await ws.send_text(json.dumps({
            "type": "rewind_points",
            "data": {"session_id": session_id, "points": [],
                     "error": f"{type(e).__name__}: {e}"},
        }))


async def handle_rewind(ws, cmd: dict):
    """Rewind code + conversation to a chosen point."""
    session_id = (cmd.get("session_id") or "").strip()
    target_msg_id = (cmd.get("target_msg_id") or "").strip()
    if not session_id or not target_msg_id:
        await ws.send_text(json.dumps({
            "type": "rewind_result",
            "data": {"session_id": session_id or None,
                     "error": "session_id and target_msg_id are required"},
        }))
        return
    from openprogram.interfaces.server import server as _s
    if _s._is_run_active(session_id):
        await ws.send_text(json.dumps({
            "type": "rewind_result",
            "data": {"session_id": session_id, "error": _s.RUN_ACTIVE_ERROR,
                     "code": "run_active"},
        }))
        return
    try:
        from openprogram.runtime.conversation.rewind import (
            list_rewind_points,
            plan_rewind,
            rewind_to,
        )
        import asyncio
        loop = asyncio.get_event_loop()
        if target_msg_id.startswith("__by_index__"):
            idx = int(target_msg_id.removeprefix("__by_index__"))
            points = await loop.run_in_executor(
                None, lambda: list_rewind_points(session_id),
            )
            if idx < 1 or idx > len(points):
                await ws.send_text(json.dumps({
                    "type": "rewind_result",
                    "data": {"session_id": session_id,
                             "error": f"Invalid index {idx}. Available: 1-{len(points)}"},
                }))
                return
            target_msg_id = points[idx - 1]["msg_id"]
        phase = (cmd.get("phase") or "plan").strip().lower()
        mode = (cmd.get("mode") or "code_and_conversation").strip()
        if phase == "plan":
            result = await loop.run_in_executor(
                None, lambda: plan_rewind(session_id, target_msg_id, mode=mode),
            )
        elif phase == "apply":
            idempotency_key = (cmd.get("idempotency_key") or "").strip()
            plan_hash = (cmd.get("plan_hash") or "").strip()
            if not idempotency_key or not plan_hash:
                await ws.send_text(json.dumps({
                    "type": "rewind_result",
                    "data": {
                        "session_id": session_id,
                        "status": "error",
                        "error": "apply requires idempotency_key and plan_hash",
                    },
                }))
                return
            result = await loop.run_in_executor(
                None, lambda: rewind_to(
                    session_id,
                    target_msg_id,
                    idempotency_key=idempotency_key,
                    expected_plan_hash=plan_hash,
                    mode=mode,
                ),
            )
        else:
            await ws.send_text(json.dumps({
                "type": "rewind_result",
                "data": {
                    "session_id": session_id,
                    "status": "error",
                    "error": f"unknown rewind phase {phase!r}",
                },
            }))
            return
        # The transaction moves HEAD only after every file action verifies.
        # Mirror that committed CAS, including a valid move to ``None``.
        if result.get("head_changed"):
            _s._set_active_head(session_id, result.get("new_head_id"))
            _s.refresh_context_stats(session_id)
        await ws.send_text(json.dumps({
            "type": "rewind_result",
            "data": {**result, "session_id": session_id},
        }, default=str))
    except Exception as e:
        await ws.send_text(json.dumps({
            "type": "rewind_result",
            "data": {"session_id": session_id,
                     "error": f"{type(e).__name__}: {e}"},
        }))
