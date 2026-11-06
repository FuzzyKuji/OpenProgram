"""Switch the Agent a conversation uses.

The composer's Agent menu calls this for a conversation that already
exists; a draft keeps its pick locally and sends it with the first
message. The conversation takes the Agent's model when the Agent has one,
and joins always-on right away when the Agent is always-on.
"""
from __future__ import annotations

import logging
import asyncio
import json

from fastapi.responses import JSONResponse

from openprogram.runtime.events import emit_ws_frame

_log = logging.getLogger(__name__)


def _switch(session_id: str, agent_id: str) -> tuple[int, dict]:
    from openprogram.runtime.conversation import always_on
    from openprogram.runtime.agent_registry import manager
    from openprogram.runtime.context.session_db import default_db
    from openprogram.runtime.conversation.session_model import write_session_chat_model
    from openprogram.interfaces.server import server as _s

    spec = manager.get(agent_id)
    if spec is None:
        return 404, {"error": "agent not found"}
    db = default_db()
    if not db.is_created(session_id):
        return 404, {"error": "session not found"}
    if _s._is_run_active(session_id):
        return 409, {"error": "A turn is running in this conversation."}
    session = db.get_session(session_id) or {}
    model = {"provider": spec.model.provider or "", "id": spec.model.id or ""}
    if session.get("agent_id") == spec.id:
        return 200, {"session_id": session_id, "agent_id": spec.id, "model": model}

    db.update_session(session_id, agent_id=spec.id)
    with _s._sessions_lock:
        conv = _s._sessions.get(session_id)
        if conv is not None:
            conv["agent_id"] = spec.id
    if model["provider"] and model["id"]:
        write_session_chat_model(session_id, model["provider"], model["id"])
        if conv is not None:
            # Rebuilt on the next message, for the Agent's provider.
            old = conv.get("runtime")
            conv["runtime"] = None
            conv["provider_name"] = model["provider"]
            if old is not None and hasattr(old, "close"):
                try:
                    old.close()
                except Exception:
                    # The old runtime is dropped either way; the next message
                    # rebuilds one.
                    _log.debug(
                        "closing runtime of session %s failed", session_id, exc_info=True)
    always_on.join(session_id)
    _s._broadcast(json.dumps({
        "type": "session_updated",
        "data": {"id": session_id, "agent_id": spec.id},
    }))
    if model["provider"] and model["id"]:
        emit_ws_frame({"type": "provider_changed", "data": _s._get_provider_info(session_id)})
    return 200, {"session_id": session_id, "agent_id": spec.id, "model": model}


def register(app) -> None:
    @app.post("/api/sessions/{session_id}/agent")
    async def set_session_agent(session_id: str, body: dict | None = None):
        agent_id = str((body or {}).get("agent_id") or "").strip()
        if not agent_id:
            return JSONResponse(content={"error": "Missing agent_id"}, status_code=400)
        status, payload = await asyncio.to_thread(_switch, session_id, agent_id)
        return JSONResponse(content=payload, status_code=status)
