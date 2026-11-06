"""Per-session run settings: additional working directories and the Sandbox override."""
from __future__ import annotations

import json


# ── 会话额外工作目录（additional-working-directories.md §3.2）──
# 整表替换语义：前端算好增删后发完整列表，幂等、无"重复添加/删不存在"分支。
# 校验失败整帧拒绝（error 帧带原因），不做部分写入。

async def handle_set_working_dirs(ws, cmd: dict):
    """整表替换会话的额外工作目录。dirs 逐条 expanduser + 必须是存在的目录，
    非法条目整帧拒绝，全部合法才落库并广播 working_dirs 帧。"""
    from pathlib import Path
    from openprogram.interfaces.server import server as _s
    session_id = (cmd.get("session_id") or "").strip()
    raw_dirs = cmd.get("dirs")
    if not session_id or not isinstance(raw_dirs, list):
        await ws.send_text(json.dumps({
            "type": "error",
            "data": {"message": "set_working_dirs requires session_id and dirs (list)"},
        }))
        return
    dirs: list[str] = []
    for d in raw_dirs:
        expanded = Path(str(d)).expanduser()
        if not expanded.is_dir():
            await ws.send_text(json.dumps({
                "type": "error",
                "data": {"message": f"Not a directory: {d}"},
            }))
            return
        # 存 expanduser 后的绝对路径字符串（不 realpath——用户看到自己选的
        # 路径，归一化交给 check_path_safety 消费端）。
        dirs.append(str(expanded))
    from openprogram.runtime.conversation.session_config import save_session_run_config
    from openprogram.interfaces.server.ws_actions.chat import _db_agent_id
    save_session_run_config(
        session_id,
        agent_id=_db_agent_id(session_id),
        additional_working_dirs=dirs,
    )
    _s._broadcast(json.dumps({"type": "working_dirs", "data": {
        "session_id": session_id, "dirs": dirs,
    }}))


async def handle_set_sandbox(ws, cmd: dict):
    """Read or set the session Sandbox override. Missing sandbox_enabled
    is a read. Response includes backend availability so the Plus menu
    can disable itself when sandbox-exec / bwrap is missing."""
    from openprogram.runtime.conversation.session_config import (
        load_session_run_config,
        save_session_run_config,
    )
    from openprogram.host.sandbox import ui_state
    from openprogram.interfaces.server import server as _s
    from openprogram.interfaces.server.ws_actions.chat import _db_agent_id

    session_id = (cmd.get("session_id") or "").strip()
    override = None
    requested = cmd.get("sandbox_enabled") if "sandbox_enabled" in cmd else None
    if session_id:
        if "sandbox_enabled" in cmd:
            save_session_run_config(
                session_id,
                agent_id=_db_agent_id(session_id),
                sandbox_enabled=requested,
            )
        override = load_session_run_config(session_id).sandbox_enabled
    # Draft chats have no session row yet, so save is a no-op. Echo the
    # requested override anyway — otherwise ui_state(None) reports the
    # configured default and the Plus-menu switch snaps back.
    if override is None and isinstance(requested, bool):
        override = requested
    data = {"session_id": session_id or None, **ui_state(override),
            "request_id": cmd.get("request_id"), "action": "set_sandbox"}
    frame = json.dumps({"type": "sandbox_changed", "data": data})
    await ws.send_text(frame)
    if "sandbox_enabled" in cmd:
        # Reads are request-local. Broadcast only mutations, without the caller's ID.
        broadcast = {k: v for k, v in data.items() if k != "request_id"}
        _s._broadcast(json.dumps({"type": "sandbox_changed", "data": broadcast}))
