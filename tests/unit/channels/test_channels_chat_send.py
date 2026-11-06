"""chat_send — the agent posting into the chat a channel turn came from —
and the rule that only the speaker whose turn raised a question may
answer it in a group.
"""
from __future__ import annotations

import pytest

from openprogram.runtime.permissions.authority import paired_channel_authority
from openprogram.runtime.permissions.tool_authority import decide_tool_authority
from openprogram.interfaces.channels import _active_turns
from openprogram.interfaces.channels._transport import SendResult
from openprogram.programs.tools.interaction import chat_send as tool


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    out: list[tuple] = []
    monkeypatch.setattr(
        "openprogram.interfaces.channels._transport.post_message",
        lambda platform, account_id, target, text: out.append(
            (platform, account_id, target, text)) or SendResult.success(""))
    return out


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("openprogram.runtime.execution.run_control.get_current_session_id",
                        lambda: "s1")
    _active_turns.begin("s1", _active_turns.ActiveTurn(
        channel="telegram", account_id="acct1", peer_id="-100",
        peer_kind="group", speaker_id="701", ambient=True))
    yield "s1"
    _active_turns.end("s1")


def test_posts_to_the_chat_of_the_running_turn(session, posted) -> None:
    assert tool._chat_send_impl("  noon works  ") == "Posted to the telegram chat."
    assert posted == [("telegram", "acct1", "-100", "noon works")]


def test_refuses_outside_a_channel_turn(posted, monkeypatch) -> None:
    monkeypatch.setattr("openprogram.runtime.execution.run_control.get_current_session_id",
                        lambda: "web-session")
    assert tool._chat_send_impl("hi").startswith("Error:")
    assert tool._chat_send_impl("") == "Error: text is required."
    assert posted == []


def test_a_turn_has_a_send_quota(session, posted) -> None:
    for _ in range(_active_turns.MAX_SENDS_PER_TURN):
        assert not tool._chat_send_impl("x").startswith("Error:")
    assert tool._chat_send_impl("one more").startswith("Error: already posted")
    assert len(posted) == _active_turns.MAX_SENDS_PER_TURN


def test_a_failed_post_is_an_error(session, monkeypatch) -> None:
    monkeypatch.setattr(
        "openprogram.interfaces.channels._transport.post_message",
        lambda *a: SendResult.fail("rate_limit", "429"))
    assert tool._chat_send_impl("hi") == (
        "Error: the telegram message was not sent (rate_limit).")


def test_a_paired_speaker_may_use_it_and_only_channels_see_it() -> None:
    from openprogram.runtime.permissions.classifier import SAFE_AUTO_ALLOWLIST
    auth = paired_channel_authority("telegram", "acct1", "701", "Ada")
    decision = decide_tool_authority(auth, "chat_send")
    assert decision.allowed and decision.capability == "reply"
    assert "chat_send" in SAFE_AUTO_ALLOWLIST
    assert tool.CHANNEL_SOURCES == {"telegram", "discord", "slack", "wechat"}


def test_only_the_asker_answers_in_a_group(monkeypatch) -> None:
    from openprogram.interfaces.channels import _conversation as C
    monkeypatch.setattr(C, "_route", lambda *a: ("main", "s1", "s1"))
    handled: list[str] = []
    monkeypatch.setattr(
        "openprogram.interfaces.channels._question_commands.try_handle_question_command",
        lambda text, key, actor: handled.append(text) or "✓ 已记录你的回答。")
    _active_turns.begin("s1", _active_turns.ActiveTurn(
        channel="telegram", account_id="acct1", peer_id="-100",
        peer_kind="group", speaker_id="701"))
    try:
        def answer(speaker: str) -> str | None:
            return C.dispatch_inbound(
                channel="telegram", account_id="acct1", peer_kind="group",
                peer_id="-100", user_text="/answer q1 1", speaker_id=speaker)
        assert answer("702") == "只有发起这个问题的人可以回答它。"
        assert handled == []
        assert answer("701") == "✓ 已记录你的回答。"
    finally:
        _active_turns.end("s1")
