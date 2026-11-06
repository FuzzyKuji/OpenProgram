"""web use page commands tests."""

from __future__ import annotations
import asyncio
import pytest
from ._support import _Adapter, _NativeObserveAdapter, _allow_binding, _public_open_transport


def test_list_pages_returns_group_aware_snapshot_with_page_tokens():
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
    )

    registry = WebUseSessionRegistry(
        adapters={
            name: _Adapter(name)
            for name in (
                "playwright_mcp",
                "chrome_devtools_mcp",
                "open_claude_chrome",
            )
        },
        binding_validator=_allow_binding,
    )
    context = {
        "context_id": "ctx-pages",
        "window_id": "window-1",
        "primary_surface_key": "p4",
        "inventory_revision": 9,
        "active_tab_entry_id": "group:g3",
        "focused_page": "p4",
        "tab_entries": [
            {
                "id": "group:g3",
                "mode": "split",
                "pages": ["p3", "p4"],
                "split": {
                    "axis": "horizontal",
                    "ratio": 0.5,
                    "panes": [
                        {"pane_id": "pane:g3:0", "order": 0, "page": "p3"},
                        {"pane_id": "pane:g3:1", "order": 1, "page": "p4"},
                    ],
                },
            }
        ],
        "windows": [
            {
                "window_id": "window-1",
                "inventory_revision": 9,
                "active_tab_entry_id": "group:g3",
                "focused_page": "p4",
                "tab_entries": [
                    {
                        "id": "group:g3",
                        "mode": "split",
                        "pages": ["p3", "p4"],
                    }
                ],
                "pages": ["p3", "p4"],
            }
        ],
        "surfaces": [
            {
                "surface_key": "p3",
                "window_id": "window-1",
                "binding_id": "binding-3",
                "tab_entry_id": "group:g3",
                "placement": {"mode": "split", "pane_id": "pane:g3:0", "order": 0},
            },
            {
                "surface_key": "p4",
                "window_id": "window-1",
                "binding_id": "binding-4",
                "tab_entry_id": "group:g3",
                "placement": {"mode": "split", "pane_id": "pane:g3:1", "order": 1},
                "focused": True,
            },
        ],
    }

    result = registry.list_pages(context=context, owner_id="owner-1")

    assert result["browser_context_id"] == "ctx-pages"
    assert result["window_id"] == "window-1"
    assert result["inventory_revision"] == 9
    assert result["active_tab_entry_id"] == "group:g3"
    assert result["focused_page"] == "p4"
    assert result["tab_entries"] == context["tab_entries"]
    assert result["windows"] == context["windows"]
    assert [page["page"] for page in result["pages"]] == ["p4", "p3"]
    assert [page["window_id"] for page in result["pages"]] == [
        "window-1",
        "window-1",
    ]
    assert all(
        page["page_context_token"].startswith("pct_") for page in result["pages"]
    )
    assert result["pages"][0]["placement"] == {
        "mode": "split",
        "pane_id": "pane:g3:1",
        "order": 1,
    }


def test_public_close_confirms_native_page_and_releases_owned_session(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as browser_module
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime
    from openprogram.interfaces.server import server
    from openprogram.interfaces.server.ws_actions import webtab

    connection = object()
    owner = "public-close-owner"
    current_owner = [owner]
    adapter = _NativeObserveAdapter("open_claude_chrome")
    released = []
    native_closes = []

    def release_context(context):
        released.append(context)
        surface_context.release_bindings(context)

    registry = web_use_runtime.WebUseSessionRegistry(
        adapters={name: adapter for name in web_use_runtime.SUPPORTED_BACKENDS},
        release_context=release_context,
    )
    webtab.ensure_connection_revision(connection)
    webtab._desktop_windows[connection] = "win"
    monkeypatch.setattr(server, "_ws_connections", [connection])
    base_transport = _public_open_transport(webtab)

    def request_on_ws(ws, command, timeout=15):
        if command.get("op") == "close":
            assert ws is connection
            native_closes.append(dict(command))
            return {"ok": True}
        return base_transport(ws, command, timeout)

    monkeypatch.setattr(webtab, "request_on_ws", request_on_ws)
    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: registry)
    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(
        surface_context, "web_use_owner_id", lambda context=None: current_owner[0],
    )

    def invoke(**request):
        result = browser_module.web_use(**request)
        return result.json_data if hasattr(result, "json_data") else result

    try:
        observed = invoke(
            command="observe", backend="open_claude_chrome",
            arguments={"url": "http://127.0.0.1:62147/page/1"},
        )
        session_id = observed["web_session_id"]
        session = registry._sessions[session_id]
        assert registry._page_leases[session.page_key] == session_id
        assert webtab.binding_connection(session.binding_id) is connection

        current_owner[0] = "foreign-owner"
        rejected = invoke(command="close", web_session_id=session_id)
        assert rejected["reason_code"] == "web_session_owner_mismatch"
        assert rejected["page_closed"] is False
        assert native_closes == []
        assert registry._sessions[session_id] is session
        assert adapter.calls == ["observe"]

        current_owner[0] = owner
        closed = invoke(command="close", web_session_id=session_id)
        assert closed == {
            "ok": True, "closed": True, "page_closed": True,
            "web_session_id": session_id,
        }
        assert native_closes == [{"op": "close", "tab_id": "tab-opened"}]
        assert adapter.calls == ["observe", "close"]
        assert released == [session.page_context]
        assert session.closed is True
        assert not registry._sessions
        assert not registry._page_leases
        assert not registry._page_capabilities
        assert webtab.binding_connection(session.binding_id) is None

        repeated = invoke(command="close", web_session_id=session_id)
        assert repeated["reason_code"] == "web_session_not_found"
        assert repeated["page_closed"] is False
        assert len(native_closes) == 1
        assert adapter.calls == ["observe", "close"]
    finally:
        registry.release_owner(owner)
        webtab.release_connection(connection)


def test_closing_one_page_session_keeps_sibling_page_binding_alive(monkeypatch):
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
    )
    from openprogram.interfaces.server.ws_actions import webtab

    owner = object()
    binding_1 = webtab.register_binding(owner, "window-1", "tab-1", "target-1")
    binding_2 = webtab.register_binding(owner, "window-1", "tab-2", "target-2")
    monkeypatch.setattr(
        webtab,
        "request_on_ws",
        lambda _ws, command, _timeout=5.0: {
            "ok": True,
            "window_id": "window-1",
            "tab_id": command["tab_id"],
            "target_id": "target-1" if command["tab_id"] == "tab-1" else "target-2",
        },
    )
    registry = WebUseSessionRegistry(
        adapters={
            name: _Adapter(name)
            for name in (
                "playwright_mcp",
                "chrome_devtools_mcp",
                "open_claude_chrome",
            )
        },
    )
    context = {
        "context_id": "ctx-pages",
        "surfaces": [
            {
                "surface_key": "p1",
                "aliases": ["p1"],
                "binding_id": binding_1,
                "tab_id": "tab-1",
                "page_key": webtab.binding_page_key(binding_1),
                **webtab.binding_revisions(binding_1),
            },
            {
                "surface_key": "p2",
                "aliases": ["p2"],
                "binding_id": binding_2,
                "tab_id": "tab-2",
                "page_key": webtab.binding_page_key(binding_2),
                **webtab.binding_revisions(binding_2),
            },
        ],
    }
    listed = registry.list_pages(context=context, owner_id="owner-1")
    first = registry.execute(
        command="observe",
        backend="open_claude_chrome",
        owner_id="owner-1",
        page_context_token=listed["pages"][0]["page_context_token"],
    )
    second = registry.execute(
        command="observe",
        backend="open_claude_chrome",
        owner_id="owner-1",
        page_context_token=listed["pages"][1]["page_context_token"],
    )

    registry.execute(
        command="close",
        web_session_id=first["web_session_id"],
        owner_id="owner-1",
    )
    acted = registry.execute(
        command="act",
        web_session_id=second["web_session_id"],
        owner_id="owner-1",
        arguments={
            "action": "click",
            "expected_frame_id": "frame-1",
        },
    )

    assert acted["ok"] is True
    assert webtab.binding_revisions(binding_1) == {}
    assert webtab.binding_revisions(binding_2)
    registry.release_owner("owner-1")


def test_direct_list_pages_returns_empty_inventory_without_mounted_page(monkeypatch):
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.interfaces.server import server
    from openprogram.interfaces.server.ws_actions import webtab

    class _Owner:
        pass

    owner = _Owner()
    monkeypatch.setattr(server, "_ws_connections", [owner])
    asyncio.run(
        webtab.handle_webtab_register(
            owner,
            {
                "action": "webtab_register",
                "window_id": "window-1",
            },
        )
    )
    monkeypatch.setattr(
        webtab,
        "request_on_ws",
        lambda ws, command, timeout=5.0: {
            "ok": True,
            "window_id": "window-1",
            "pages": [],
        },
    )

    result = module.execute_direct_web_use(
        {"command": "list_pages"},
        owner_id="mcp:empty-window",
    )

    assert result["ok"] is True
    assert result["pages"] == []
    assert result["tab_entries"] == []
    assert result["active_tab_entry_id"] == ""
    assert result["focused_page"] == ""

    monkeypatch.setattr(
        webtab,
        "request_on_ws",
        lambda ws, command, timeout=5.0: {
            "ok": True,
            "window_id": "window-1",
            "pages": [{}],
        },
    )
    with pytest.raises(RuntimeError, match="no valid Page"):
        module.execute_direct_web_use(
            {"command": "list_pages"},
            owner_id="mcp:invalid-window",
        )
    webtab.release_connection(owner)


def test_public_page_token_keeps_the_turn_owner_across_calls(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.runtime.execution.run_control import (
        reset_current_session_id,
        set_current_session_id,
    )
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.programs.applications.browser.web_use import (
        runtime as web_use_runtime,
    )
    from openprogram.state.store import _current_turn_id

    turn_context = {"context_id": "turn-1", "surfaces": []}
    inventory_context = {"context_id": "inventory-1", "surfaces": []}

    class _Registry:
        def __init__(self):
            self.owners = []

        def list_pages(self, **kwargs):
            self.owners.append(kwargs["owner_id"])
            return {"ok": True, "pages": [{"page_context_token": "pct-popup"}]}

        def execute(self, **kwargs):
            self.owners.append(kwargs["owner_id"])
            return {"frame_id": "frame-popup", "web_session_id": "cs-popup"}

    registry = _Registry()
    captures = []
    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: registry)
    monkeypatch.setattr(surface_context, "current", lambda: turn_context)

    def capture_pages(context=None):
        captures.append(context)
        return inventory_context

    monkeypatch.setattr(surface_context, "capture_pages", capture_pages)

    session_token = set_current_session_id("chat-1")
    turn_token = _current_turn_id.set("turn-1")
    try:
        listed = module.web_use(command="list_pages")
        observed = module.web_use(
            command="observe",
            backend="playwright_mcp",
            page_context_token=listed["pages"][0]["page_context_token"],
        )
    finally:
        _current_turn_id.reset(turn_token)
        reset_current_session_id(session_token)

    assert observed["web_session_id"] == "cs-popup"
    assert registry.owners == ["turn:chat-1:turn-1", "turn:chat-1:turn-1"]
    assert captures == [None]


def test_list_pages_preserves_origin_window_for_subprocess_bridge(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime

    origin_context = surface_context.window_context("window-1")
    inventory_context = {
        "context_id": "inventory-1",
        "window_id": "window-1",
        "surfaces": [],
    }
    captures = []

    class _Registry:
        def list_pages(self, **kwargs):
            assert kwargs["context"] is inventory_context
            return {"ok": True, "pages": []}

    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: _Registry())
    monkeypatch.setattr(surface_context, "current", lambda: origin_context)

    def capture_pages(context=None):
        captures.append(context)
        return inventory_context

    monkeypatch.setattr(surface_context, "capture_pages", capture_pages)

    result = module.web_use(command="list_pages")

    assert result["ok"] is True
    assert captures == [origin_context]


def test_list_pages_round_trips_origin_window_through_child_bridge(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime
    from openprogram.interfaces.server.ws_actions import webtab

    origin_context = surface_context.window_context("window-1")
    inventory_context = {
        "context_id": "inventory-1",
        "window_id": "window-1",
        "surfaces": [],
    }
    calls = []

    class _Registry:
        def list_pages(self, **kwargs):
            assert kwargs["context"] is inventory_context
            return {"ok": True, "pages": []}

    def bridge_request(command, timeout):
        calls.append((command, timeout))
        return {"ok": True, "context": inventory_context}

    monkeypatch.setenv("OPENPROGRAM_IN_AGENTIC_SUBPROCESS", "1")
    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: _Registry())
    monkeypatch.setattr(surface_context, "current", lambda: origin_context)
    monkeypatch.setattr(webtab, "_request", bridge_request)

    result = module.web_use(command="list_pages")

    assert result["ok"] is True
    assert calls == [({"op": "capture_pages", "window_id": "window-1"}, 5.0)]


def test_same_owner_repeated_observe_reuses_exact_page_session():
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
    )

    released = []
    registry = WebUseSessionRegistry(
        adapters={
            name: _Adapter(name)
            for name in (
                "playwright_mcp",
                "chrome_devtools_mcp",
                "open_claude_chrome",
            )
        },
        release_context=lambda context: released.append(context["context_id"]),
        binding_validator=_allow_binding,
    )
    first = registry.execute(
        command="observe",
        backend="playwright_mcp",
        binding_id="binding-1",
        page_key="page-1",
        owner_id="turn:one",
        page_context={"context_id": "ctx-first"},
    )
    repeated = registry.execute(
        command="observe",
        backend="playwright_mcp",
        binding_id="binding-2",
        page_key="page-1",
        owner_id="turn:one",
        page_context={"context_id": "ctx-unused"},
    )
    other_owner = registry.execute(
        command="observe",
        backend="playwright_mcp",
        binding_id="binding-3",
        page_key="page-1",
        owner_id="turn:two",
        page_context={"context_id": "ctx-other"},
    )

    assert repeated["web_session_id"] == first["web_session_id"]
    assert repeated["session_reused"] is True
    assert other_owner["ok"] is False and other_owner["reason_code"] == "page_in_use"
    registry.execute(
        command="close",
        web_session_id=first["web_session_id"],
        owner_id="turn:one",
    )
    assert released == ["ctx-first"]


def test_act_fills_expected_frame_id_and_resolves_pending_session():
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
    )

    adapters = {
        name: _Adapter(name)
        for name in (
            "playwright_mcp",
            "chrome_devtools_mcp",
            "open_claude_chrome",
        )
    }
    registry = WebUseSessionRegistry(
        adapters=adapters,
        binding_validator=_allow_binding,
    )
    observed = registry.execute(
        command="observe",
        backend="playwright_mcp",
        binding_id="binding-1",
        owner_id="owner-1",
    )
    acted = registry.execute(
        command="act",
        web_session_id="pending",
        owner_id="owner-1",
        arguments={"action": "click", "ref": "e1"},
    )
    assert acted["ok"] is True
    assert acted["web_session_id"] == observed["web_session_id"]
    assert adapters["playwright_mcp"].calls[-1] == (
        "act",
        {"action": "click", "expected_frame_id": "frame-1", "ref": "e1"},
    )
    assert (
        registry.execute(
            command="act",
            web_session_id="pending",
            owner_id="owner-missing",
            arguments={"action": "click", "ref": "e1"},
        )["reason_code"]
        == "web_session_not_found"
    )


def test_observe_with_page_token_does_not_capture_active(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime

    captures = []
    calls = []

    class _Registry:
        def execute(self, **kwargs):
            calls.append("execute")
            return {"ok": False, "reason_code": "page_context_not_found"}

        def list_pages(self, **kwargs):
            calls.append("list_pages")
            return {"ok": True, "pages": [{
                "page": "p1", "tab_id": "tab-1", "window_id": "main",
                "page_context_token": "pct_fresh",
            }]}

    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: _Registry())
    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(
        surface_context,
        "capture_active",
        lambda: captures.append("active") or {"context_id": "ctx"},
    )
    monkeypatch.setattr(
        surface_context,
        "capture_pages",
        lambda *_args, **_kwargs: captures.append("pages") or {"context_id": "ctx"},
    )

    result = module.web_use(
        command="observe",
        backend="playwright_mcp",
        page_context_token="page_ctx_deadbeef",
    )
    assert result.is_error is True
    result = result.json_data
    assert result["reason_code"] == "page_context_not_found"
    # The token observe itself never captures; only the failure lists the
    # current pages so the next call can observe with a fresh token.
    assert "active" not in captures
    assert calls == ["execute", "list_pages"]
    assert result["pages"][0]["page_context_token"] == "pct_fresh"
    assert result["recovery_command"] == "observe"


def test_observe_with_url_opens_desktop_tab_when_no_page(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime

    opens = []

    class _Registry:
        def list_pages(self, **kwargs):
            return {
                "ok": True,
                "pages": [{"page_context_token": "pct_opened"}],
            }

        def execute(self, **kwargs):
            return {
                "ok": True,
                "web_session_id": "cs_opened",
                "frame_id": "frame-1",
                "command": kwargs["command"],
            }

    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: _Registry())
    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(
        surface_context,
        "open_page",
        lambda url, **kwargs: opens.append((url, kwargs))
        or {
            "context_id": "page_ctx_opened",
            "surfaces": [{"binding_id": "surface_opened"}],
        },
    )
    monkeypatch.setattr(
        surface_context,
        "capture_active",
        lambda: (_ for _ in ()).throw(AssertionError("should open, not capture")),
    )

    result = module.web_use(
        command="observe",
        backend="playwright_mcp",
        arguments={"url": "https://example.test/form"},
    )
    assert opens == [("https://example.test/form", {"background": True})]
    assert result["ok"] is True
    assert result["web_session_id"] == "cs_opened"
    assert result["frame_id"] == "frame-1"
    assert "page_context_token" not in result

    opens.clear()
    acted = module.web_use(
        command="act",
        web_session_id=result["web_session_id"],
        arguments={"action": "click", "expected_frame_id": "frame-1"},
    )
    assert opens == []
    assert acted["ok"] is True
    assert acted["web_session_id"] == "cs_opened"
    assert "page_context_token" not in acted
    assert acted.get("closed") is not True


def test_observe_with_url_opens_it_when_bound_pages_are_elsewhere(monkeypatch):
    """After list_pages binds other pages, an explicit URL still opens."""
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime

    opens, executed = [], []
    bound = {
        "context_id": "page_ctx_listed",
        "surfaces": [{"binding_id": "surface_sheet", "origin": "https://doc.weixin.qq.com"}],
    }

    class _Registry:
        def list_pages(self, **kwargs):
            return {"ok": True, "pages": [{"page_context_token": "pct_opened"}]}

        def execute(self, **kwargs):
            executed.append(kwargs.get("page_context_token"))
            return {"ok": True, "web_session_id": "cs_opened", "frame_id": "frame-1"}

    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: _Registry())
    monkeypatch.setattr(surface_context, "current", lambda: bound)
    monkeypatch.setattr(
        surface_context,
        "open_page",
        lambda url, **kwargs: opens.append((url, kwargs))
        or {"context_id": "page_ctx_opened", "surfaces": [{"binding_id": "surface_opened"}]},
    )

    result = module.web_use(
        command="observe",
        arguments={"url": "https://form.feishu.test/share/base/form/x"},
    )
    assert opens == [("https://form.feishu.test/share/base/form/x", {"background": True})]
    assert executed == ["pct_opened"]
    assert result["web_session_id"] == "cs_opened"

    # A bound page already on that origin is observed instead of a duplicate tab.
    assert not module._bound_page_shows_origin(bound, "https://form.feishu.test/share/base/form/x")
    bound["surfaces"].append({"binding_id": "surface_form", "origin": "https://form.feishu.test"})
    assert module._bound_page_shows_origin(bound, "https://form.feishu.test/share/base/form/x")


def test_resource_web_open_creates_a_background_page(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs._host.runtime import _allowed_tool_names
    from openprogram.programs.applications.browser.web_use import page_recovery
    from openprogram.programs.applications.browser import resource as builtin

    opens = []
    monkeypatch.setattr(
        surface_context,
        "open_page",
        lambda url, **kwargs: opens.append((url, kwargs))
        or {
            "context_id": "resource-opened",
            "surfaces": [{"binding_id": "resource-surface"}],
        },
    )
    monkeypatch.setattr(
        page_recovery,
        "_start_session_on_opened_page",
        lambda **kwargs: {"ok": True, "web_session_id": "resource-session"},
    )

    token = _allowed_tool_names.set({"web_use"})
    try:
        result = builtin._web("open", {"url": "https://example.test/"})
    finally:
        _allowed_tool_names.reset(token)

    assert result["ok"] is True
    assert opens == [("https://example.test/", {"background": True})]


@pytest.mark.parametrize("entry", ["web_use", "direct"])
def test_public_url_observe_keeps_binding_for_first_session_act(
    monkeypatch,
    entry,
):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime
    from openprogram.programs.applications.browser.web_use.runtime import (
        SUPPORTED_BACKENDS,
        WebUseSessionRegistry,
    )
    from openprogram.interfaces.server import server
    from openprogram.interfaces.server.ws_actions import webtab

    adapters = {name: _NativeObserveAdapter(name) for name in SUPPORTED_BACKENDS}
    registry = WebUseSessionRegistry(
        adapters=adapters,
        release_context=surface_context.release_bindings,
    )
    owner = object()
    webtab.ensure_connection_revision(owner)
    webtab._desktop_windows[owner] = "win"
    open_commands = []
    monkeypatch.setattr(server, "_ws_connections", [owner])
    monkeypatch.setattr(
        webtab,
        "request_on_ws",
        _public_open_transport(webtab, open_commands),
    )
    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: registry)
    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(
        surface_context,
        "web_use_owner_id",
        lambda context=None: "owner-native",
    )
    url = "http://127.0.0.1:62147/page/1"
    try:
        if entry == "web_use":
            observed = module.web_use(
                command="observe",
                backend="open_claude_chrome",
                arguments={"url": url},
            )
        else:
            observed = module.execute_direct_web_use(
                {
                    "command": "observe",
                    "backend": "open_claude_chrome",
                    "arguments": {"url": url},
                },
                owner_id="owner-native",
            )
        assert "ok" not in observed or observed.get("ok") is not False
        assert observed.get("ok") is not False
        assert observed["frame_id"] == "frame_1_b6a848a6"
        assert observed["web_session_id"].startswith("cs_")
        assert observed.get("closed") is not True
        assert "page_context_token" not in observed
        assert open_commands == [
            {
                "op": "open",
                "url": url,
                "background": True,
            }
        ]
        assert webtab._bindings
        binding_id = next(iter(webtab._bindings))
        assert webtab.request_bound_tab(binding_id).get("ok") is True

        if entry == "web_use":
            acted = module.web_use(
                command="act",
                backend="open_claude_chrome",
                web_session_id=observed["web_session_id"],
                arguments={
                    "action": "click",
                    "expected_frame_id": observed["frame_id"],
                },
            )
        else:
            acted = module.execute_direct_web_use(
                {
                    "command": "act",
                    "backend": "open_claude_chrome",
                    "web_session_id": observed["web_session_id"],
                    "arguments": {
                        "action": "click",
                        "expected_frame_id": observed["frame_id"],
                    },
                },
                owner_id="owner-native",
            )
        assert acted.get("ok") is not False
        assert acted.get("closed") is not True
        assert acted["web_session_id"] == observed["web_session_id"]
        assert adapters["open_claude_chrome"].calls[-1][0] == "act"
        assert webtab._bindings
    finally:
        for binding_id in list(webtab._bindings):
            webtab.release_binding(binding_id)
        webtab.release_connection(owner)
        registry.close_all()


def test_invalid_arguments_keep_live_session_unmarked_closed():
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
    )

    adapters = {
        name: _Adapter(name)
        for name in (
            "playwright_mcp",
            "chrome_devtools_mcp",
            "open_claude_chrome",
        )
    }
    registry = WebUseSessionRegistry(
        adapters=adapters,
        binding_validator=_allow_binding,
    )
    observed = registry.execute(
        command="observe",
        backend="open_claude_chrome",
        binding_id="binding-1",
        owner_id="owner-1",
        page_context={"context_id": "ctx-1"},
    )
    rejected = registry.execute(
        command="act",
        web_session_id=observed["web_session_id"],
        owner_id="owner-1",
        arguments={},
    )
    assert rejected["reason_code"] == "invalid_arguments"
    assert rejected.get("closed") is not True
    assert rejected["web_session_id"] == observed["web_session_id"]
    still = registry.execute(
        command="observe",
        web_session_id=observed["web_session_id"],
        owner_id="owner-1",
    )
    assert still.get("ok") is not False
    assert still.get("closed") is not True


def test_act_with_url_rejects_non_http_scheme(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module

    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(
        surface_context,
        "open_page",
        surface_context.open_page,
    )
    result = module.web_use(
        command="act",
        arguments={"action": "navigate", "url": "ftp://example.com/file.txt"},
    )
    assert result.is_error is True
    result = result.json_data
    assert result["ok"] is False
    assert result["reason_code"] == "unsupported_url"
    assert "SCHEME_FORBIDDEN" in result["error"]


def test_file_url_opens_only_a_readable_local_file(monkeypatch, tmp_path):
    from openprogram.runtime.conversation import surface_context
    import openprogram.host.sandbox as sandbox

    missing = surface_context._local_file_url((tmp_path / "gone.html").as_uri())
    assert missing["reason_code"] == "unsupported_url"
    assert "not found" in missing["error"]

    page = tmp_path / "report page.html"
    page.write_text("<h1>ok</h1>")
    opened = surface_context._local_file_url(page.as_uri() + "#results")
    assert opened == {"ok": True, "url": page.resolve().as_uri() + "#results"}

    monkeypatch.setattr(sandbox, "validate_read_path", lambda _path: "outside the workspace")
    denied = surface_context._local_file_url(page.as_uri())
    assert denied["error"] == "sandbox policy: outside the workspace"
    assert surface_context._local_file_url("https://example.com") is None


def test_act_with_url_reports_desktop_unavailable(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module

    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(
        surface_context,
        "open_page",
        lambda url, **_kwargs: {
            "ok": False,
            "reason_code": "desktop_unavailable",
            "error": surface_context.DESKTOP_UNAVAILABLE_ERROR,
        },
    )
    result = module.web_use(
        command="act",
        arguments={"action": "navigate", "url": "https://example.test/"},
    )
    assert result.is_error is True
    result = result.json_data
    assert result["ok"] is False
    assert result["reason_code"] == "desktop_unavailable"
    assert "Launch the desktop app" in result["error"]
    assert "background web tab" in result["error"]


@pytest.mark.parametrize("entry", ["web_use", "direct"])
def test_open_page_cleanup_contract_reaches_public_web_use_entries(
    monkeypatch,
    entry,
):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as module

    cleanup = {
        "ok": False,
        "status": "infeasible",
        "success": False,
        "infeasible_declared": True,
        "reason_code": "page_cleanup_failed",
        "error": "close rejected",
        "summary": "The background Page could not be closed.",
        "handoff_instruction": "Close the remaining background Page.",
    }
    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(
        surface_context,
        "open_page",
        lambda _url, **_kwargs: cleanup,
    )
    arguments = {
        "command": "act",
        "arguments": {"action": "navigate", "url": "https://example.test/"},
    }

    result = (
        module.web_use(**arguments)
        if entry == "web_use"
        else module.execute_direct_web_use(arguments, owner_id="owner-test")
    )

    if entry == "web_use":
        assert result.is_error is True
        result = result.json_data
    assert result == cleanup


@pytest.mark.parametrize("subprocess_mode", [False, True])
@pytest.mark.parametrize("session_id", ["resource-owner-session", ""])
def test_public_web_use_open_carries_trusted_resource_owner(
    monkeypatch, subprocess_mode, session_id
):
    from openprogram.runtime.conversation import surface_context
    from openprogram.runtime.execution.run_control import (
        set_current_session_id,
        reset_current_session_id,
    )
    from openprogram.programs.applications.browser import web_use as module
    from openprogram.interfaces.server import server
    from openprogram.interfaces.server.ws_actions import webtab

    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setenv(
        "OPENPROGRAM_IN_AGENTIC_SUBPROCESS", "1" if subprocess_mode else "0"
    )
    ws = object()
    monkeypatch.setattr(server, "_ws_connections", {ws})
    monkeypatch.setattr(webtab, "registered_desktop_windows", lambda: [(ws, "main", 1)])
    commands = []

    def request(command, *args, **kwargs):
        commands.append(command)
        return {"ok": False, "error": "test transport stopped after capture"}

    monkeypatch.setattr(webtab, "_request", request)
    monkeypatch.setattr(
        webtab, "request_on_ws", lambda ws, command, **kw: request(command)
    )
    token = set_current_session_id(session_id)
    try:
        module.web_use(
            command="observe", arguments={"url": "https://example.test/resource-owner"}
        )
    finally:
        reset_current_session_id(token)
    assert len(commands) == 1
    assert commands[0]["op"] == "open"
    assert commands[0].get("session_id") == (session_id or None)


def test_observe_reports_the_page_so_the_preview_follows_reads(monkeypatch):
    import openprogram.programs.applications.browser.pages as browser_resources
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
    )

    reported = []
    monkeypatch.setattr(
        browser_resources, "report_browser_operation",
        lambda page_key, operation, *, follow, execution_id=None:
            reported.append((page_key, operation["action"], operation["phase"], follow)),
    )
    registry = WebUseSessionRegistry(
        adapters={
            name: _Adapter(name)
            for name in ("playwright_mcp", "chrome_devtools_mcp", "open_claude_chrome")
        },
        binding_validator=_allow_binding,
    )
    observed = registry.execute(
        command="observe", backend="playwright_mcp", binding_id="binding-1",
        page_key="page-1", owner_id="owner-1",
    )

    assert observed.get("ok") is not False
    # A read moves the preview but does not claim the page as Agent-controlled.
    assert reported == [("page-1", "observe", "acknowledged", False)]


def test_the_next_result_names_a_popup_the_page_opened(monkeypatch):
    import openprogram.programs.applications.browser.pages as browser_resources
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
    )

    monkeypatch.setattr(
        browser_resources, "report_browser_operation",
        lambda *args, **kwargs: None,
    )
    registry = WebUseSessionRegistry(
        adapters={
            name: _Adapter(name)
            for name in ("playwright_mcp", "chrome_devtools_mcp", "open_claude_chrome")
        },
        binding_validator=_allow_binding,
    )
    first = registry.execute(
        command="observe", backend="playwright_mcp", binding_id="binding-1",
        page_key="page-1", owner_id="owner-1",
    )
    assert "opened_pages" not in first
    popup = {"window_id": "win", "tab_id": "popup", "url": "https://visa.test/apply", "title": "Apply"}
    browser_resources.note_opened_page(["page-1"], popup)

    second = registry.execute(
        command="observe", web_session_id=first["web_session_id"], owner_id="owner-1",
    )
    third = registry.execute(
        command="observe", web_session_id=first["web_session_id"], owner_id="owner-1",
    )

    # Told once, with how to continue there instead of repeating the flow.
    assert second["opened_pages"] == [popup]
    assert "list_pages" in second["opened_pages_note"]
    assert "opened_pages" not in third
