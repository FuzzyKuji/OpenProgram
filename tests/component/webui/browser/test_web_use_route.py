from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_worker_web_use_route_preserves_images_and_server_owner(monkeypatch):
    from openprogram.programs import ToolReturn
    from openprogram.programs.applications.browser.service import BrowserService
    from openprogram.interfaces.server.routes.execution.web_use import register

    calls = []

    def execute(arguments, *, owner_id):
        calls.append((arguments, owner_id))
        return ToolReturn(
            text="viewport",
            images=[b"png-bytes"],
            json_data={"frame_id": "frame-1"},
        )

    monkeypatch.setattr(BrowserService, "execute_direct_web_use", staticmethod(execute))
    app = FastAPI()
    register(app)
    response = TestClient(app).post("/api/web-use", json={
        "arguments": {"command": "act"},
        "owner_id": "mcp:client:connection",
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert [item["type"] for item in payload["result"]["content"]] == [
        "text", "image",
    ]
    assert payload["result"]["details"]["json"] == {"frame_id": "frame-1"}
    assert calls == [({"command": "act"}, "mcp:client:connection")]


def test_worker_web_use_route_marks_known_tool_failure_as_error(monkeypatch):
    from openprogram.programs.applications.browser.service import BrowserService
    from openprogram.interfaces.server.routes.execution.web_use import register

    failure = {
        "ok": False,
        "reason_code": "desktop_unavailable",
        "error": "desktop web tab did not expose a CDP target",
    }
    monkeypatch.setattr(
        BrowserService,
        "execute_direct_web_use",
        staticmethod(lambda _arguments, *, owner_id: failure),
    )
    app = FastAPI()
    register(app)

    response = TestClient(app).post("/api/web-use", json={
        "arguments": {"command": "observe"},
        "owner_id": "mcp:client:connection",
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["result"]["is_error"] is True
    assert json.loads(payload["result"]["content"][0]["text"]) == failure


def test_worker_web_use_route_rejects_non_mcp_owner():
    from openprogram.interfaces.server.routes.execution.web_use import register

    app = FastAPI()
    register(app)
    response = TestClient(app).post("/api/web-use", json={
        "arguments": {"command": "list_pages"},
        "owner_id": "turn:forged",
    })

    assert response.status_code == 400


def test_legacy_computer_use_route_is_hidden_and_maps_session_field(monkeypatch):
    from openprogram.programs.applications.browser.service import BrowserService
    from openprogram.interfaces.server.routes.execution.web_use import register

    calls = []

    def execute(arguments, *, owner_id):
        calls.append((arguments, owner_id))
        return {"ok": True, "web_session_id": "cs-legacy"}

    monkeypatch.setattr(BrowserService, "execute_direct_web_use", staticmethod(execute))
    app = FastAPI()
    register(app)
    response = TestClient(app).post("/api/computer-use", json={
        "arguments": {
            "command": "close", "computer_session_id": "cs-legacy",
        },
        "owner_id": "mcp:client:connection",
    })

    assert response.status_code == 200
    assert calls == [(
        {"command": "close", "web_session_id": "cs-legacy"},
        "mcp:client:connection",
    )]
    assert json.loads(response.json()["result"]["content"][0]["text"]) == {
        "ok": True, "computer_session_id": "cs-legacy",
    }
    assert "/api/computer-use" not in app.openapi()["paths"]


def test_internal_release_pages_route_revokes_exact_owner_tokens(monkeypatch):
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime
    from openprogram.interfaces.server.routes.execution.web_use import register

    calls = []

    class Registry:
        def release_page_capabilities(self, tokens, *, owner_id):
            calls.append((list(tokens), owner_id))
            return len(tokens)

    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: Registry())
    app = FastAPI()
    register(app)
    response = TestClient(app).post("/api/web-use/release-pages", json={
        "owner_id": "mcp:client:connection",
        "page_context_tokens": ["pct-1", "pct-2"],
    })

    assert response.json() == {"ok": True, "released": 2}
    assert calls == [(["pct-1", "pct-2"], "mcp:client:connection")]
    assert "/api/web-use/release-pages" not in app.openapi()["paths"]
