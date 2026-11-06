"""Large tool outputs are loaded lazily over the session WebSocket."""

from __future__ import annotations

import asyncio
import json

import pytest

from openprogram.state.store import SessionStore
from openprogram.interfaces.server.ws_actions import session as ws_session


class FakeWS:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.frames.append(json.loads(text))


@pytest.fixture
def session_with_tool_outputs(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr("openprogram.runtime.context.session_db.default_db", lambda: store)
    store.create_session("session-1", "main")
    large = 'x"\\\n' * (ws_session.TOOL_OUTPUT_INLINE_MAX_BYTES // 2)
    store.append_message(
        "session-1",
        {
            "id": "user-1",
            "role": "user",
            "content": "inspect",
        },
    )
    store.append_message(
        "session-1",
        {
            "id": "assistant-1",
            "role": "assistant",
            "content": "done",
            "predecessor": "user-1",
            "extra": json.dumps(
                {
                    "blocks": [
                        {
                            "type": "tool",
                            "tool": "read",
                            "tool_call_id": "tool-large",
                            "input": '{"path": "x"}',
                            "result": large,
                            "is_error": False,
                        }
                    ]
                }
            ),
        },
    )
    for node_id, result in (("tool-large", large), ("tool-small", "small")):
        store.append_message(
            "session-1",
            {
                "id": node_id,
                "role": "tool",
                "content": result,
                "function": "read",
                "caller": "assistant-1",
                "extra": json.dumps(
                    {
                        "tool_use": {"name": "read", "arguments": {"path": "x"}},
                    }
                ),
            },
        )

    from openprogram.interfaces.server import server

    with server._sessions_lock:
        server._sessions["session-1"] = {"id": "session-1"}
    monkeypatch.setattr(server, "_get_provider_info", lambda _sid=None: {})
    monkeypatch.setattr(server, "_is_run_active", lambda _sid: False)
    monkeypatch.setattr(server, "refresh_context_stats", lambda _sid: None)
    yield store, large
    with server._sessions_lock:
        server._sessions.pop("session-1", None)


def test_session_loaded_truncates_only_oversized_tool_output(
    session_with_tool_outputs,
):
    store, large = session_with_tool_outputs
    ws = FakeWS()

    asyncio.run(
        ws_session.handle_load_session(
            ws,
            {"session_id": "session-1", "request_id": "history-read-1"},
        )
    )

    loaded = next(frame for frame in ws.frames if frame["type"] == "session_loaded")
    assert loaded["data"]["request_id"] == "history-read-1"
    assert loaded["data"]["action"] == "load_session"
    assistant = next(
        message
        for message in loaded["data"]["messages"]
        if message["id"] == "assistant-1"
    )
    calls = {call["tool_call_id"]: call for call in assistant["tool_calls"]}
    truncated = calls["tool-large"]
    assert truncated["truncated"] is True
    assert truncated["total_bytes"] == len(
        json.dumps(large, ensure_ascii=False).encode("utf-8")
    )
    assert truncated["message_id"] == "assistant-1"
    assert truncated["node_id"] == "tool-large"
    assert large.startswith(truncated["result"])
    assert (
        len(
            json.dumps(
                truncated["result"],
                ensure_ascii=False,
            ).encode("utf-8")
        )
        <= ws_session.TOOL_OUTPUT_INLINE_MAX_BYTES
    )
    assert calls["tool-small"] == {
        "tool_call_id": "tool-small",
        "tool": "read",
        "input": '{"path": "x"}',
        "result": "small",
        "is_error": False,
    }
    block = assistant["blocks"][0]
    assert block["truncated"] is True
    assert block["total_bytes"] == truncated["total_bytes"]
    assert block["message_id"] == "assistant-1"
    assert block["node_id"] == "tool-large"
    assert large.startswith(block["result"])
    persisted = {message["id"]: message for message in store.get_messages("session-1")}
    assert persisted["tool-large"]["content"] == large
    assert persisted["assistant-1"]["blocks"][0]["result"] == large


def test_session_load_repairs_stale_restart_marker_from_canonical_pause(
    session_with_tool_outputs,
    monkeypatch,
):
    store, _ = session_with_tool_outputs
    store.update_session("session-1", status="running")
    from openprogram.state.store.session.nodes import Call, ROLE_CODE
    from openprogram.runtime.execution import CapabilitySet, ExecutionStore, ExecutionStatus
    from openprogram.state.store import SessionNodeWriter

    node_id = "system-access-node"
    SessionNodeWriter(store, "session-1").append(
        Call(
            id=node_id,
            role=ROLE_CODE,
            name="agentic_workflow",
            output="",
            metadata={
                "status": "interrupted",
                "error": "Worker restarted before this turn finished",
                "interrupted_at": 1.0,
                "execution_kind": "agent_method",
            },
        )
    )
    executions = ExecutionStore(store.root_path.parent / "executions.sqlite")
    revision = executions.create_revision(manifest={"entrypoint": "agent"})
    execution = executions.admit_execution(
        execution_id="execution-system-access-load",
        run_id="run-system-access-load",
        session_id="session-1",
        revision_id=revision.revision_id,
        input_ref="input:system-access-load",
        input_hash="hash:system-access-load",
        entrypoint="openprogram.runtime.conversation.production_driver:AgentProductionDriver",
        trusted_actor={"subject": "owner"},
        config_snapshot_ref="config:system-access-load",
        assistant_message_id=node_id,
        capabilities=CapabilitySet(pause=True),
    )
    executions.transition_execution(
        execution.execution_id,
        expected_version=execution.status_version,
        target=ExecutionStatus.PAUSED,
        reason_code="system_access_required",
    )
    monkeypatch.setattr("openprogram.runtime.execution.default_store", lambda: executions)

    ws = FakeWS()
    from openprogram.interfaces.server import server

    monkeypatch.setattr(server, "_get_provider_info", lambda _sid=None: {})
    monkeypatch.setattr(server, "_is_run_active", lambda _sid: False)
    asyncio.run(ws_session.handle_load_session(ws, {"session_id": "session-1"}))

    loaded = next(frame for frame in ws.frames if frame["type"] == "session_loaded")
    node = next(
        message for message in loaded["data"]["messages"] if message["id"] == node_id
    )
    assert node["status"] == "paused"
    assert "Worker restarted" not in str(node)
    assert loaded["data"]["status"] == "idle"
    assert loaded["data"]["run_active"] is False


def test_get_full_tool_output_returns_original_content(
    session_with_tool_outputs,
):
    _, large = session_with_tool_outputs
    ws = FakeWS()

    asyncio.run(
        ws_session.handle_get_full_tool_output(
            ws,
            {
                "session_id": "session-1",
                "message_id": "assistant-1",
                "node_id": "tool-large",
                "request_id": "request-1",
            },
        )
    )

    assert ws.frames == [
        {
            "type": "full_tool_output",
            "data": {
                "session_id": "session-1",
                "message_id": "assistant-1",
                "node_id": "tool-large",
                "request_id": "request-1",
                "result": large,
            },
        }
    ]


def test_paged_load_preserves_all_rows_and_does_not_move_head_or_focus(
    session_with_tool_outputs,
):
    store, _ = session_with_tool_outputs
    from openprogram.interfaces.server import server

    prev = "assistant-1"
    for i in range(65):
        mid = f"history-{i}"
        store.append_message(
            "session-1",
            {
                "id": mid,
                "role": "user",
                "content": "中" * 9000,
                "predecessor": prev,
            },
        )
        prev = mid
    store.update_session("session-1", head_id=prev)
    ws = FakeWS()
    ws._history_protocol = 1

    async def scenario():
        await ws_session.handle_load_session(ws, {"session_id": "session-1"})
        first = next(f["data"] for f in ws.frames if f["type"] == "session_loaded")
        assert len(first["messages"]) < 50
        assert first["history"]["before"]
        ids = [m["id"] for m in first["messages"]]
        cursor = first["history"]["before"]
        ws._focused_session_id = "another-session"
        server._sessions["session-1"]["head_id"] = "new-live-head"
        while cursor:
            ws.frames.clear()
            await ws_session.handle_load_session(
                ws,
                {
                    "session_id": "session-1",
                    "history_before": cursor,
                    "history_head": first["history"]["head_id"],
                    "request_id": "request",
                },
            )
            assert [f["type"] for f in ws.frames] == ["session_history_page"]
            page = ws.frames[0]["data"]
            assert page["action"] == "load_session"
            assert page["request_id"] == "request"
            ids += [m["id"] for m in page["messages"]]
            assert page["history"]["before"] != cursor
            cursor = page["history"]["before"]
        assert len(ids) == len(set(ids))
        assert all(f"history-{i}" in ids for i in range(65))
        assert "assistant-1" in ids and "user-1" in ids
        assert ws._focused_session_id == "another-session"
        assert server._sessions["session-1"]["head_id"] == "new-live-head"

    asyncio.run(scenario())


def test_deleted_session_history_request_does_not_rehydrate_empty_session(
    session_with_tool_outputs,
):
    from openprogram.interfaces.server import server
    from openprogram.interfaces.server.ws_errors import OperationError

    store, _ = session_with_tool_outputs
    store.delete_session("session-1")
    server._sessions.pop("session-1", None)
    ws = FakeWS()
    ws._history_protocol = 1
    ws._focused_session_id = "another-session"
    with pytest.raises(OperationError, match="invalid_request"):
        asyncio.run(
            ws_session.handle_load_session(
                ws,
                {
                    "session_id": "session-1",
                    "history_before": "assistant-1",
                    "history_head": "assistant-1",
                    "request_id": "stale-page",
                },
            )
        )
    assert ws.frames == []
    assert ws._focused_session_id == "another-session"


def test_ten_thousand_node_session_loads_recent_page_without_recursion(
    session_with_tool_outputs,
):
    from openprogram.state.store.session.nodes import Call, ROLE_USER, ROLE_LLM

    store, _ = session_with_tool_outputs
    sid = "long-session"
    store.create_session(sid, "main")
    _, index = store._open(sid)
    count = 10_000
    # Exercise the production store's warm index without 10,000 unrelated
    # filesystem writes; storage persistence has separate component coverage.
    for i in range(count):
        pred = str(i - 1) if i else None
        node = Call(
            id=str(i),
            role=ROLE_LLM if i % 2 else ROLE_USER,
            output=f"message {i}",
            predecessor=pred,
            created_at=float(i + 1),
        )
        index.append(node, predecessor=pred, caller=None)
    store.set_head(sid, str(count - 1))
    from openprogram.interfaces.server import server

    server._sessions[sid] = {"id": sid, "messages": [], "head_id": str(count - 1)}
    try:
        ws = FakeWS()
        ws._history_protocol = 1
        asyncio.run(ws_session.handle_load_session(ws, {"session_id": sid}))
        data = next(f["data"] for f in ws.frames if f["type"] == "session_loaded")
        assert [m["id"] for m in data["messages"]] == [
            str(i) for i in range(count - 12, count)
        ]
        assert data["history"]["before"] == str(count - 12)
        assert data["history"]["start"] == count - 12
        assert data["history"]["end"] == data["history"]["total"] == count
        assert len(data["graph"]) == count
        assert data["graph"][-1]["_depth"] == count - 1
        ws.frames.clear()
        asyncio.run(
            ws_session.handle_load_session(
                ws,
                {
                    "session_id": sid,
                    "history_before": data["history"]["before"],
                    "history_head": data["history"]["head_id"],
                    "history_snapshot": data["history"]["snapshot"],
                },
            )
        )
        assert [f["type"] for f in ws.frames] == ["session_history_page"]
        older = next(
            f["data"] for f in ws.frames if f["type"] == "session_history_page"
        )
        assert [m["id"] for m in older["messages"]] == [
            str(i) for i in range(count - 62, count - 12)
        ]
        assert older["history"]["before"] == str(count - 62)
        assert older["history"]["end"] == data["history"]["start"]
        assert older["history"]["snapshot"] == data["history"]["snapshot"]
    finally:
        server._sessions.pop(sid, None)


def test_indexed_pages_reuse_snapshot_without_full_hydration(
    session_with_tool_outputs, monkeypatch
):
    from openprogram.interfaces.server.session_history import close_snapshots

    store, _ = session_with_tool_outputs
    previous = "assistant-1"
    for i in range(120):
        mid = f"page-{i}"
        store.append_message(
            "session-1",
            {"id": mid, "role": "user", "content": str(i), "predecessor": previous},
        )
        previous = mid
    store.update_session("session-1", head_id=previous)
    ws = FakeWS()
    ws._history_protocol = 1

    async def scenario():
        await ws_session.handle_load_session(ws, {"session_id": "session-1"})
        first = next(f["data"] for f in ws.frames if f["type"] == "session_loaded")

        def forbidden(*args, **kwargs):
            raise AssertionError("Paging must not rebuild the transcript or graph")

        monkeypatch.setattr(store, "get_messages", forbidden)
        import openprogram.state.store.session.graph.builder as graph_builder

        monkeypatch.setattr(graph_builder, "build_session_graph", forbidden)
        ws.frames.clear()
        await ws_session.handle_load_session(
            ws,
            {
                "session_id": "session-1",
                "history_before": first["history"]["before"],
                "history_snapshot": first["history"]["snapshot"],
                "history_head": first["history"]["head_id"],
            },
        )
        older = ws.frames[0]["data"]
        assert older["history"]["end"] == first["history"]["start"]
        ws.frames.clear()
        await ws_session.handle_load_session(
            ws,
            {
                "session_id": "session-1",
                "history_after": older["history"]["after"],
                "history_snapshot": older["history"]["snapshot"],
                "history_head": older["history"]["head_id"],
            },
        )
        assert ws.frames[0]["data"]["messages"] == first["messages"]

    try:
        asyncio.run(scenario())
    finally:
        close_snapshots(ws)


def test_expired_snapshot_renews_around_anchor_on_the_requested_branch(
    session_with_tool_outputs,
):
    from openprogram.interfaces.server.session_history import close_snapshots

    ws = FakeWS()
    ws._history_protocol = 1

    async def scenario():
        await ws_session.handle_load_session(ws, {"session_id": "session-1"})
        initial = next(f["data"] for f in ws.frames if f["type"] == "session_loaded")
        anchor = initial["messages"][0]["id"]
        close_snapshots(ws)
        ws.frames.clear()
        ws._focused_session_id = "other-session"
        # Cursor-free renewal retains the requested branch head, as the Web loader does.
        await ws_session.handle_load_session(ws, {
            "action": "load_session", "session_id": "session-1",
            "history_head": initial["history"]["head_id"],
            "history_around": anchor, "request_id": "renewal",
        })
        assert [frame["type"] for frame in ws.frames] == ["session_history_page"]
        page = ws.frames[0]["data"]
        assert page["request_id"] == "renewal"
        assert page["history"]["head_id"] == initial["history"]["head_id"]
        assert anchor in {message["id"] for message in page["messages"]}
        assert ws._focused_session_id == "other-session"

    try:
        asyncio.run(scenario())
    finally:
        close_snapshots(ws)


def test_search_session_finds_text_on_the_loaded_branch_snapshot(
    session_with_tool_outputs,
):
    from openprogram.interfaces.server.ws_errors import OperationError

    store, _ = session_with_tool_outputs
    store.append_message(
        "session-1",
        {"id": "user-2", "role": "user", "content": "Where is the Needle?", "predecessor": "assistant-1"},
    )
    store.append_message(
        "session-1",
        {"id": "assistant-2", "role": "assistant", "content": "needle here, and another needle", "predecessor": "user-2"},
    )
    store.update_session("session-1", head_id="assistant-2")
    ws = FakeWS()
    ws._history_protocol = 1

    async def scenario():
        await ws_session.handle_load_session(ws, {"session_id": "session-1"})
        loaded = next(f["data"] for f in ws.frames if f["type"] == "session_loaded")
        snapshot = loaded["history"]["snapshot"]
        ws.frames.clear()
        await ws_session.handle_search_session(ws, {
            "session_id": "session-1", "history_snapshot": snapshot,
            "query": " NEEDLE ", "request_id": "find-1",
        })
        [frame] = ws.frames
        assert frame["type"] == "session_search_results"
        data = frame["data"]
        assert data["action"] == "search_session" and data["request_id"] == "find-1"
        assert [(m["message_id"], m["count"]) for m in data["matches"]] == [("user-2", 1), ("assistant-2", 2)]
        assert data["total"] == 3
        # The tool row's output (x"\\...) is never searched as conversation text.
        ws.frames.clear()
        await ws_session.handle_search_session(ws, {
            "session_id": "session-1", "history_snapshot": snapshot, "query": 'x"',
        })
        assert ws.frames[0]["data"]["matches"] == []
        with pytest.raises(OperationError, match="invalid_request"):
            await ws_session.handle_search_session(ws, {
                "session_id": "session-1", "history_snapshot": "stale", "query": "needle",
            })

    asyncio.run(scenario())
