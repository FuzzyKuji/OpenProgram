from __future__ import annotations

import json

from openprogram.interfaces.server.persistence import aggregate_tool_messages


def _tool(row_id, name, *, call_id=None):
    tool_use = {"name": name, "arguments": {}, "caller": "a1"}
    if call_id:
        tool_use["tool_call_id"] = call_id
    return {"id": row_id, "role": "tool", "function": name, "caller": "a1", "content": "out",
            "extra": json.dumps({"tool_use": tool_use})}


def test_a_call_attached_after_the_turn_is_shown_once_after_its_blocks():
    assistant = {"id": "a1", "role": "assistant", "content": "done", "extra": json.dumps({"blocks": [
        {"type": "text", "text": "running"},
        {"type": "tool", "tool": "bash", "tool_call_id": "call_1", "input": "{}", "result": "out"},
    ]})}
    rows = [assistant, _tool("a1_t_call_1", "bash", call_id="call_1"), _tool("su_result_x", "self_update_result")]

    [message] = aggregate_tool_messages(rows)

    tools = [(b["tool"], b["tool_call_id"]) for b in message["blocks"] if b["type"] == "tool"]
    assert tools == [("bash", "call_1"), ("self_update_result", "su_result_x")]
