"""Without the browser application, the core runs and says the browser is not enabled.

The core reaches the built-in browser only through the ``browser``
service. These tests withdraw that service, and what the application's
``setup`` registered, and check that each place the core used to import
the browser degrades instead of failing.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def no_browser(monkeypatch):
    from openprogram.runtime.context import components
    from openprogram.programs._host import services as _services
    from openprogram.host.resources import registry as resources  # the global registry

    _services.load_programs()
    monkeypatch.delitem(_services._provided, "browser")
    monkeypatch.setitem(components._REGISTRY, "L2", [
        component for component in components._REGISTRY["L2"]
        if not component.name.startswith("application:browser:")
    ])
    providers = resources._providers
    if "web" in providers:
        monkeypatch.delitem(providers, "web")
    assert _services.lookup("browser") is None


_PAGE_CONTEXT = {
    "surfaces": [{
        "surface_key": "s1",
        "preview_status": "ready",
        "capabilities": ["observe"],
        "preview": {"visible_text_excerpt": "Example page"},
    }],
}


def test_the_service_names_its_members():
    from openprogram.programs._host import services as _services

    _services.load_programs()
    browser = _services.lookup("browser")
    assert browser is not None
    for member in (
        "pages", "tabs", "chrome", "extension", "user_browser_names",
        "web_use_parameters", "normalize_web_use_arguments",
        "execute_direct_web_use", "registry", "release_owner", "park_owner",
        "authorized_page", "browser_of",
    ):
        assert hasattr(browser, member), member


def test_the_call_gets_no_pages_section(no_browser):
    from openprogram.runtime.context.components import build_turn_sections

    assert build_turn_sections(
        {"id": "main"},
        {"surface_context": _PAGE_CONTEXT, "web_use_enabled": True},
    ) == ""


def test_the_turn_gets_no_web_use_tools(no_browser):
    from types import SimpleNamespace

    from openprogram.runtime.conversation.turn_runtime.loop_runner import _configure_web_use_tools

    tools = [SimpleNamespace(name="web_use"), SimpleNamespace(name="web_search")]
    configured, enabled = _configure_web_use_tools(tools, _PAGE_CONTEXT, enabled=True)
    assert enabled is False
    assert [tool.name for tool in configured] == ["web_search"]


def test_permission_policy_sees_no_user_browser(no_browser):
    from openprogram.runtime.permissions import policy

    assert policy._user_browser({"args": {"browser": "chrome"}}) == ""


def test_web_use_arguments_are_refused(no_browser):
    from openprogram.models.providers.types import Tool, ToolCall
    from openprogram.models.providers.utils.validation import validate_tool_arguments

    tool = Tool(name="web_use", description="", parameters={"type": "object"})
    call = ToolCall(id="call-1", name="web_use", arguments={"command": "list_pages"})
    with pytest.raises(ValueError, match="the browser is not enabled"):
        validate_tool_arguments(tool, call)


def test_mcp_lists_no_web_use_and_refuses_its_calls(no_browser):
    from mcp.shared.exceptions import McpError

    from openprogram.extensions.mcp.server import contracts

    assert "web_use" not in {tool.name for tool in contracts.get_mcp_tools()}
    with pytest.raises(McpError, match="the browser is not enabled"):
        contracts.validate_tool_call("web_use", {"command": "list_pages"})


def test_web_use_route_answers_browser_not_enabled(no_browser):
    from openprogram.interfaces.server.routes.execution.web_use import register

    app = FastAPI()
    register(app)
    response = TestClient(app).post("/api/web-use", json={
        "arguments": {"command": "list_pages"},
        "owner_id": "mcp:client:connection",
    })

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["is_error"] is True
    assert json.loads(result["content"][0]["text"])["reason_code"] == "browser_not_enabled"


def test_computer_use_reports_the_browser_target_unavailable(no_browser):
    from openprogram.programs.tools.computer_use.computer_use_agent import tool as entry
    from openprogram.programs.tools.computer_use.computer_use_agent.targets import browser

    assert browser.available() is False
    assert browser.actions() == ()
    result = entry.computer_use_agent(target="browser", action="tabs")
    assert result.is_error
    assert "the browser is not enabled" in result.text


def test_native_page_commands_are_refused(no_browser):
    from openprogram.programs._host.framework import web_interface

    with pytest.raises(ValueError, match="browser_not_enabled"):
        with web_interface.authorized_page({}, "window-1"):
            pass
