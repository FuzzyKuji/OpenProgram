"""Every registered entry carries one exposure tier (program-model.md §5)."""
from __future__ import annotations

import openprogram.programs as programs
from openprogram.programs._host.runtime import (
    Tier, _open_applications, all_tools, as_resident, install_open_applications, owner_kind,
    split_tools_for_dispatch, tool_owner, tool_tier,
)


def test_every_registered_entry_has_a_tier():
    for tool in all_tools():
        assert isinstance(tool._tier, Tier), tool.name
        assert tool._defer is (tool._tier is Tier.DEFERRED), tool.name


def test_application_entries_are_deferred_and_tools_follow_the_resident_set():
    for tool in all_tools():
        if getattr(tool, "_is_agent_method", False):
            continue  # an Agent method states its own ``defer``
        kind = owner_kind(tool_owner(tool))
        if kind == "application":
            assert tool_tier(tool) is Tier.DEFERRED, tool.name
        elif tool_tier(tool) is not Tier.HIDDEN:
            expected = Tier.RESIDENT if tool.name in programs.RESIDENT_TOOLS | {"tool_search"} else Tier.DEFERRED
            assert tool_tier(tool) is expected, tool.name
    owners = {tool_owner(t) for t in all_tools()}
    assert "application:browser" in owners


def test_owner_kinds():
    assert owner_kind("") == owner_kind("tool:goal") == "tool"
    assert owner_kind("plugin:x") == "plugin"
    for owner in ("application:browser", "external:some_harness", "weekly_report"):
        assert owner_kind(owner) == "application"


def test_an_open_application_makes_only_its_own_entries_resident():
    web_use = programs.get_agent_tool("web_use")
    fetch = programs.get_agent_tool("web_fetch")
    assert split_tools_for_dispatch([web_use, fetch])[0] == []
    token = install_open_applications({"browser"})
    try:
        assert split_tools_for_dispatch([web_use, fetch])[0] == [web_use]
    finally:
        _open_applications.reset(token)


def test_a_resident_copy_leaves_the_registered_tool_deferred():
    web_use = programs.get_agent_tool("web_use")
    copy = as_resident(web_use)
    assert copy is not web_use and tool_tier(copy) is Tier.RESIDENT and not copy._defer
    assert tool_tier(web_use) is Tier.DEFERRED


def test_programs_list_shows_tiers_and_builtin_settings():
    from openprogram.interfaces.cli.commands.programs import program_rows
    rows = {(r["kind"], r["name"]): r for r in program_rows()}
    assert rows[("tool", "bash")]["tiers"] == {"bash": "resident"}
    browser = rows[("application", "browser")]
    assert browser["tiers"] == {"web_use": "deferred"} and browser["enabled"] is True
    assert browser["note"] == "built in"
