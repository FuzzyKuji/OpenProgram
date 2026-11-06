"""MCP startup outcomes through the owner-authenticated worker API."""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def startup_failure(monkeypatch):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import chrome as _chrome_bootstrap
    from openprogram.programs.applications.browser.web_use import mcp_backends, runtime as web_use_runtime
    from openprogram.interfaces.server.routes.execution.web_use import register

    controllers, clients, released = [], [], []

    class Controller:
        def __init__(self):
            self.markers = {}
            self.closed = 0
            controllers.append(self)

        def execute(self, *, action, before_dispatch=None):
            assert action == "observe"
            if before_dispatch is not None:
                before_dispatch()
            return {"frame_id": "frame-1", "target": {"target_id": "target-1"}}

        def evaluate_bound_page(self, script, argument):
            if "Object.defineProperty" in script:
                self.markers[argument[0]] = argument[1]
            elif "delete globalThis" in script:
                self.markers.pop(argument, None)

        def close(self):
            self.closed += 1

    class FailingClient:
        error = None

        def __init__(self, config):
            self.config = config
            self.stopped = False
            self.loop = None
            clients.append(self)

        async def start(self):
            self.loop = asyncio.get_running_loop()
            self.error = "npm ETIMEDOUT https://registry.example.test/?token=private-fixture-token"

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr(mcp_backends, "MCPClient", FailingClient)
    monkeypatch.setattr(_chrome_bootstrap, "desktop_app_ws_url", lambda: "ws://fixture-cdp")
    context = {
        "context_id": "fixture-context",
        "surfaces": [{"surface_key": "page-1", "binding_id": "binding-1",
                      "page_key": "page-key-1", "capabilities": ["observe"]}],
    }
    monkeypatch.setattr(surface_context, "capture_pages", lambda: context)
    registry = web_use_runtime.WebUseSessionRegistry(
        controller_factory=Controller,
        binding_validator=lambda _binding: {"ok": True},
        binding_revision_resolver=lambda _binding: {},
        page_key_resolver=lambda _binding: "page-key-1",
        release_context=lambda value: released.append(value),
    )
    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: registry)
    app = FastAPI()
    register(app)
    fixture = SimpleNamespace(app=app, registry=registry, controllers=controllers,
                              clients=clients, released=released)
    try:
        yield fixture
    finally:
        registry.close_all()
        # Close any loop leaked by the RED candidate; this fixture owns it.
        for client in clients:
            if client.loop is not None and not client.loop.is_running():
                client.loop.close()


def _observe(client, backend):
    inventory = client.post("/api/web-use", json={
        "owner_id": "mcp:fixture:connection", "arguments": {"command": "list_pages"},
    })
    assert inventory.status_code == 200
    page = json.loads(inventory.json()["result"]["content"][0]["text"])["pages"][0]
    arguments = {"command": "observe", "page_context_token": page["page_context_token"]}
    if backend:
        arguments["backend"] = backend
    return client.post("/api/web-use", json={
        "owner_id": "mcp:fixture:connection", "arguments": arguments,
    })


@pytest.mark.parametrize("backend", ["", "chrome_devtools_mcp"])
def test_public_api_reports_selected_mcp_backend_unavailable(startup_failure, backend):
    fixture = startup_failure
    with TestClient(fixture.app) as client:
        response = _observe(client, backend)
    assert response.status_code == 200
    normalized = response.json()["result"]
    assert normalized["is_error"] is True
    failure = json.loads(normalized["content"][0]["text"])
    assert failure["ok"] is False
    assert failure["reason_code"] == "computer_use_backend_unavailable"
    assert failure["availability"] == "unavailable"
    assert failure["backend"] == (backend or "playwright_mcp")
    assert failure["closed"] is True
    assert failure["web_session_id"].startswith("cs_")
    assert "private-fixture-token" not in response.text
    assert len(fixture.controllers) == len(fixture.clients) == 1
    assert fixture.controllers[0].closed == 1
    assert fixture.clients[0].stopped is True
    assert fixture.registry._sessions == fixture.registry._page_leases == {}
    assert len(fixture.released) == 1


@pytest.mark.parametrize("backend", ["", "chrome_devtools_mcp"])
def test_public_startup_failure_closes_owned_loop_and_binding_marker(startup_failure, backend):
    fixture = startup_failure
    before = {thread.ident for thread in threading.enumerate()}
    with TestClient(fixture.app) as client:
        _observe(client, backend)
    assert fixture.clients[0].stopped is True
    assert not any(thread.name == "web-use-mcp" and thread.ident not in before
                   for thread in threading.enumerate())
    assert fixture.controllers[0].markers == {}
    assert fixture.clients[0].loop.is_closed()



def test_public_api_cleans_chrome_marker_when_endpoint_is_unavailable(startup_failure, monkeypatch):
    from openprogram.programs.applications.browser import chrome as _chrome_bootstrap

    fixture = startup_failure
    monkeypatch.setattr(_chrome_bootstrap, "desktop_app_ws_url", lambda: "")
    with TestClient(fixture.app) as client:
        response = _observe(client, "chrome_devtools_mcp")
    assert response.status_code == 200
    failure = json.loads(response.json()["result"]["content"][0]["text"])
    assert failure["reason_code"] == "computer_use_backend_unavailable"
    assert failure["backend"] == "chrome_devtools_mcp"
    assert failure["closed"] is True
    assert fixture.clients == []
    assert fixture.controllers[0].markers == {}
    assert fixture.controllers[0].closed == 1
    assert fixture.registry._sessions == fixture.registry._page_leases == {}
    assert len(fixture.released) == 1
