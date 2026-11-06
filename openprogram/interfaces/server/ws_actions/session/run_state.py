"""Run-state probe and follow-up answers for a running function."""
from __future__ import annotations

import json


async def handle_get_run_state(ws, cmd: dict):
    """Report run state without changing this socket's focused session."""
    from openprogram.interfaces.server import server as _s
    session_id = cmd.get("session_id")
    run_seq = _s._next_run_seq()
    run_active = bool(session_id and _s._is_run_active(session_id))
    await ws.send_text(json.dumps({
        "type": "run_state",
        "data": {
            "session_id": session_id,
            "run_active": run_active,
            "run_task": _s._run_identity(session_id) if run_active else None,
            "run_seq": run_seq,
        },
    }))


async def handle_follow_up_answer(ws, cmd: dict):
    """User answered a follow-up question from a running function."""
    from openprogram.interfaces.server import server as _s
    fq_session_id = cmd.get("session_id", "")
    answer = cmd.get("answer", "")
    with _s._follow_up_lock:
        fq = _s._follow_up_queues.get(fq_session_id)
    if fq is not None:
        fq.put(answer)
