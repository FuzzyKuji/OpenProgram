"""web use adapters tests."""
from __future__ import annotations
import pytest
import threading
import time
from ._support import _Controller, _PlaywrightClient


def test_official_playwright_adapter_binds_marker_and_routes_one_action(monkeypatch):
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSession,
    )
    from openprogram.programs.applications.browser.web_use.mcp_backends import (
        OfficialMCPPageBackend,
    )
    from openprogram.programs.applications.browser import chrome as _chrome_bootstrap

    controller = _Controller()
    client = _PlaywrightClient(controller.page)
    monkeypatch.setattr(_chrome_bootstrap, "desktop_app_ws_url", lambda: "ws://cdp")
    commands = []
    adapter = OfficialMCPPageBackend(
        "playwright_mcp", lambda: controller,
        client_factory=lambda command: commands.append(command) or client,
    )
    session = WebUseSession("cs-1", "playwright_mcp", "binding-1")

    observed = adapter.observe(session, {})
    assert observed["aria_snapshot"] == '- button "Save" [ref=e7]'
    assert session.state["upstream_page"] == 0
    assert session.state["target_id"] == "target-1"
    assert all(name != "browser_tabs" for name, _ in client.calls)
    assert "target-1" in commands[0]
    assert not any("bringToFront" in part for part in commands[0])
    acted = adapter.act(session, {
        "action": "click", "expected_frame_id": "frame-1", "ref": "e7",
    })
    assert acted["ok"] is True
    assert ("browser_click", {"target": "e7"}) in client.calls
    assert controller.invalidated == 1


def test_official_adapter_keeps_the_frame_for_form_fields(monkeypatch):
    from openprogram.programs.applications.browser.web_use.runtime import WebUseSession
    from openprogram.programs.applications.browser.web_use.mcp_backends import (
        OfficialMCPPageBackend, snapshot_roles,
    )
    from openprogram.programs.applications.browser import chrome as _chrome_bootstrap

    assert snapshot_roles(
        '- checkbox "Agree" [ref=e85]\n  - radio "Volunteer" [checked] [ref=e107]\n'
        '- button "Next" [ref=e9]\nuid=1_5 checkbox "Agree"'
    ) == {"e85": "checkbox", "e107": "radio", "e9": "button", "1_5": "checkbox"}
    controller = _Controller()
    client = _PlaywrightClient(controller.page)
    monkeypatch.setattr(_chrome_bootstrap, "desktop_app_ws_url", lambda: "ws://cdp")
    adapter = OfficialMCPPageBackend(
        "playwright_mcp", lambda: controller, client_factory=lambda command: client,
    )
    session = WebUseSession("cs-1", "playwright_mcp", "binding-1")
    adapter.observe(session, {})
    session.state["ref_roles"].update(e85="checkbox")
    for step in ({"action": "type", "ref": "e3", "text": "Ada"},
                 {"action": "click", "ref": "e85"},
                 {"action": "press", "ref": "e85", "key": "Space"},
                 {"action": "click", "ref": "e7"}):
        result = adapter.act(session, {"expected_frame_id": "frame-1", **step})
        assert result["ok"] is True
    # A field and a checkbox keep the observation; the Save button retires it.
    assert controller.kept == [True, True, True, False]
    # A key aimed at a ref goes to that element, not to whatever has focus.
    focus = client.calls.index(("browser_evaluate", {"target": "e85", "function": "(element) => element.focus()"}))
    assert client.calls[focus + 1] == ("browser_press_key", {"key": "Space"})
    assert controller.invalidated == 1



def test_sync_mcp_client_cleans_thread_when_start_fails(monkeypatch):
    from openprogram.programs.applications.browser.web_use import mcp_backends

    instances = []

    class _FailingClient:
        error = None

        def __init__(self, _config):
            self.stopped = False
            instances.append(self)

        async def start(self):
            raise RuntimeError("start failed")

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr(mcp_backends, "MCPClient", _FailingClient)
    before = {thread.ident for thread in threading.enumerate()}
    with pytest.raises(RuntimeError, match="start failed"):
        mcp_backends._SyncMCPClient(["missing"], timeout=0.1)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and any(
        thread.name == "web-use-mcp" and thread.ident not in before
        for thread in threading.enumerate()
    ):
        time.sleep(0.01)
    assert instances[0].stopped is True
    assert not any(
        thread.name == "web-use-mcp" and thread.ident not in before
        for thread in threading.enumerate()
    )



def test_official_backend_rejects_stale_frame_before_upstream_call(monkeypatch):
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSession,
    )
    from openprogram.programs.applications.browser.web_use.mcp_backends import (
        OfficialMCPPageBackend,
    )

    controller = _Controller()
    client = _PlaywrightClient(controller.page)
    adapter = OfficialMCPPageBackend(
        "playwright_mcp", lambda: controller,
        client_factory=lambda _command: client,
    )
    session = WebUseSession("cs-1", "playwright_mcp", "binding-1")
    session.controller = controller
    session.state["mcp_client"] = client
    before = list(client.calls)
    result = adapter.act(session, {
        "action": "click", "expected_frame_id": "old", "ref": "e7",
    })
    assert result["reason_code"] == "stale_observation"
    assert client.calls == before


@pytest.mark.parametrize("backend", ["playwright_mcp", "chrome_devtools_mcp"])
def test_official_backend_launch_uses_the_cached_pinned_package(backend):
    from openprogram.programs.applications.browser.web_use.mcp_backends import (
        OfficialMCPPageBackend,
    )

    adapter = OfficialMCPPageBackend(backend, _Controller)
    command = adapter._command("ws://cdp", "target-1")

    # Pinned versions never need a registry round trip when cached; without
    # --prefer-offline a slow network outlasts the MCP start timeout.
    assert command[:3] == ["npx", "--prefer-offline", "-y"]


class _DeadClient:
    def __init__(self) -> None:
        self.calls = []
        self.closed = 0

    def is_alive(self):
        return False

    def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        raise RuntimeError("mcp_server_unavailable:fatal")

    def close(self):
        self.closed += 1


def test_official_backend_observe_restarts_a_dead_mcp_client(monkeypatch):
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSession,
    )
    from openprogram.programs.applications.browser.web_use.mcp_backends import (
        OfficialMCPPageBackend,
    )
    from openprogram.programs.applications.browser import chrome as _chrome_bootstrap

    controller = _Controller()
    replacement = _PlaywrightClient(controller.page)
    started = []
    monkeypatch.setattr(_chrome_bootstrap, "desktop_app_ws_url", lambda: "ws://cdp")
    adapter = OfficialMCPPageBackend(
        "playwright_mcp", lambda: controller,
        client_factory=lambda command: started.append(command) or replacement,
    )
    dead = _DeadClient()
    session = WebUseSession("cs-1", "playwright_mcp", "binding-1")
    session.controller = controller
    session.state["mcp_client"] = dead

    observed = adapter.observe(session, {})

    assert observed["aria_snapshot"] == '- button "Save" [ref=e7]'
    assert len(started) == 1 and "target-1" in started[0]
    assert dead.closed == 1 and dead.calls == []
    assert session.state["mcp_client"] is replacement


def test_official_backend_act_never_writes_through_a_restarted_client(monkeypatch):
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSession,
    )
    from openprogram.programs.applications.browser.web_use.mcp_backends import (
        OfficialMCPPageBackend,
    )

    controller = _Controller()
    started = []
    adapter = OfficialMCPPageBackend(
        "playwright_mcp", lambda: controller,
        client_factory=lambda command: started.append(command),
    )
    dead = _DeadClient()
    session = WebUseSession("cs-1", "playwright_mcp", "binding-1")
    session.controller = controller
    session.state["mcp_client"] = dead

    result = adapter.act(session, {
        "action": "click", "expected_frame_id": "frame-1", "ref": "e7",
    })

    assert result["reason_code"] == "computer_use_backend_unavailable"
    assert result["action_dispatched"] is False
    assert result["observe_required"] is True
    assert "observe" in result["message"]
    assert dead.calls == [] and started == []
    assert controller.invalidated == 1
    assert "mcp_client" not in session.state


def test_sync_mcp_client_reaps_a_supervisor_that_missed_the_start_timeout(monkeypatch):
    import asyncio

    from openprogram.programs.applications.browser.web_use import mcp_backends

    instances = []

    class _HangingClient:
        def __init__(self, _config):
            self.error = None
            self.cancelled = threading.Event()
            instances.append(self)

        async def start(self):
            async def supervisor():
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    # stdio_client terminates the npx child in this cleanup.
                    self.cancelled.set()
                    raise

            self.task = asyncio.get_running_loop().create_task(supervisor())
            await asyncio.sleep(0)
            self.error = "server did not become ready within 0.1s"

        async def stop(self):
            pass

    monkeypatch.setattr(mcp_backends, "MCPClient", _HangingClient)
    with pytest.raises(RuntimeError, match="computer_use_backend_unavailable"):
        mcp_backends._SyncMCPClient(["npx"], timeout=0.1)

    assert instances[0].cancelled.is_set()

