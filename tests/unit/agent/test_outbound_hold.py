"""An Agent holds what it sends for the user as a draft the user approves."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from openprogram.extensions.mcp.adapter import sends_on_behalf


def _tool(name: str, read_only: bool | None = None):
    return SimpleNamespace(name=name, annotations=SimpleNamespace(readOnlyHint=read_only))


@pytest.mark.parametrize("name", [
    "send_email", "chat.postMessage", "reply_to_thread", "create_comment",
    "gmail_send_message", "slack_post_message", "addComment", "forward_email",
])
def test_tools_that_send_are_marked(name):
    assert sends_on_behalf(_tool(name))


@pytest.mark.parametrize("name", [
    "list_messages", "get_posts", "search_email", "create_draft", "create_issue",
    "read_thread", "get_share_link", "update_page",
])
def test_reads_and_drafts_are_not(name):
    assert not sends_on_behalf(_tool(name))


def test_a_read_only_hint_wins():
    assert not sends_on_behalf(_tool("send_digest", read_only=True))


@pytest.fixture
def decide(monkeypatch):
    from openprogram.runtime.permissions import tool_authority
    from openprogram.runtime.permissions import policy, recovery
    from openprogram.runtime.agent_registry import manager

    monkeypatch.setattr(policy, "_hard_constraint_violation", lambda *a, **k: None)
    monkeypatch.setattr(tool_authority, "decide_tool_authority",
                        lambda *a, **k: SimpleNamespace(allowed=True, reason_code="", capability=""))
    monkeypatch.setattr(recovery, "approval_context", lambda *a, **k: None)
    tools = {"mail__send_email": SimpleNamespace(name="mail__send_email", _sends_on_behalf=True),
             "mail__list_messages": SimpleNamespace(name="mail__list_messages", _sends_on_behalf=False)}
    monkeypatch.setattr("openprogram.programs._host.runtime.get", tools.get)
    held = {"scout": True}
    monkeypatch.setattr(manager, "get", lambda agent_id: SimpleNamespace(hold_outbound=held[agent_id]))

    def run(name, *, mode="bypass", allow=(), source="web"):
        rules = SimpleNamespace(allow=list(allow), ask=[], deny=[])
        req = SimpleNamespace(permission_mode=mode, permission_rules=rules, session_id="s1",
                              source=source, surface_context=None, agent_id="scout")
        return policy.permission_decision(tools[name], req, {"to": "dana@example.com"})[:2]
    run.held = held
    return run


def test_a_send_asks_in_every_mode_even_with_an_allow_rule(decide):
    for mode in ("bypass", "auto", "ask", "acceptEdits"):
        assert decide("mail__send_email", mode=mode, allow=["mail__send_email"]) == ("ask", "OUTBOUND_HOLD")
    assert decide("mail__list_messages")[0] == "allow"


def test_nobody_can_approve_a_send_from_a_scheduled_run(decide):
    assert decide("mail__send_email", source="scheduler")[0] == "deny"


def test_turning_the_hold_off_restores_the_mode(decide):
    decide.held["scout"] = False
    assert decide("mail__send_email")[0] == "allow"


def test_each_draft_is_approved_alone(monkeypatch):
    from openprogram.runtime.permissions.policy import one_shot_approval
    monkeypatch.setattr("openprogram.programs._host.runtime.get",
                        lambda name: SimpleNamespace(_sends_on_behalf=name == "mail__send_email"))
    assert one_shot_approval("mail__send_email", {})
    assert not one_shot_approval("mail__list_messages", {})
