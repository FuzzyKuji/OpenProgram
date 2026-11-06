"""surface runtime tests."""
from __future__ import annotations
from ._support import (
    REPO_ROOT,
)


def test_built_in_pages_are_a_target_of_the_one_screen_tool():
    from openprogram.programs import (
        DEFERRED_DEFAULT_TOOLS,
        DEFAULT_TOOLS,
        agent_tools,
        apply_tool_policy,
    )

    # web_use stays registered for workflows and MCP, but the model sees one screen tool.
    assert "web_use" not in DEFAULT_TOOLS
    assert "computer_use_agent" in DEFAULT_TOOLS
    assert "computer_use_agent" not in DEFERRED_DEFAULT_TOOLS
    tool = next(item for item in agent_tools(names=["computer_use_agent"]) if item.name == "computer_use_agent")
    assert "browser" in tool.parameters["properties"]["target"]["enum"]
    assert apply_tool_policy([tool], source="plan") == []



def test_surface_tool_is_injected_after_tools_are_resolved():
    source = (REPO_ROOT / "openprogram/runtime/conversation/turn_runtime/loop_runner.py").read_text(
        encoding="utf-8"
    )

    resolve_at = source.index(
        "tools = _resolve_tools(agent_profile, req.tools_override, source=req.source)"
    )
    inject_at = source.index(
        "tools, web_use_enabled = _configure_web_use_tools"
    )
    assert resolve_at < inject_at



def test_resume_keeps_the_browser_tools_of_a_turn_without_pages():
    from openprogram.runtime.conversation.turn_runtime.loop_runner import _saved_web_use

    def contract(*names):
        return {"tools": [{"name": name} for name in names]}

    assert _saved_web_use(contract("bash")) is False
    assert _saved_web_use(contract("bash", "computer_use_agent")) is True
    assert _saved_web_use(contract("bash", "web_use")) is True
    assert _saved_web_use(None) is None


def test_a_turn_with_named_tools_gets_the_screen_tool_only_when_named():
    from types import SimpleNamespace

    from openprogram.runtime.conversation.turn_runtime.loop_runner import _configure_web_use_tools

    screen = SimpleNamespace(name="computer_use_agent")
    read = SimpleNamespace(name="read")
    # An always-on check-in names read-only tools: open Pages add nothing to it.
    tools, enabled = _configure_web_use_tools([read, screen], None, enabled=True, tools_override=["read", "grep"])
    assert [tool.name for tool in tools] == ["read"]
    assert enabled is False
    # Without a named list the Pages rule decides as before.
    tools, enabled = _configure_web_use_tools([read], None, enabled=True, tools_override=None)
    assert [tool.name for tool in tools] == ["read", "computer_use_agent"]
    assert enabled is True
