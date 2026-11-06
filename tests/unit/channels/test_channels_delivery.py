"""Session generations behind /new and idle reset, and paragraph
streaming for platforms that cannot edit a sent message (WeChat).
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from openprogram.interfaces.channels import _session_routing as R
from openprogram.interfaces.channels._conversation import _BlockStreamer
from openprogram.interfaces.channels._transport import SendResult


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr("openprogram.state.paths.get_state_dir", lambda: state)


def _agent(**kw):
    base = dict(id="main", session_daily_reset="", session_idle_minutes=0)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Session generations
# ---------------------------------------------------------------------------

def test_new_moves_later_messages_to_a_new_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(R, "_last_activity", lambda key: 0.0)
    agent = _agent()
    assert R.apply_reset_policy(agent, "acct_direct_7") == "acct_direct_7"
    assert R.start_new_generation(agent, "acct_direct_7") == 1
    assert R.apply_reset_policy(agent, "acct_direct_7") == "acct_direct_7_n1"
    assert R.apply_reset_policy(agent, "acct_direct_7") == "acct_direct_7_n1"
    # Other peers and other agents keep their session.
    assert R.apply_reset_policy(agent, "acct_direct_8") == "acct_direct_8"
    assert R.apply_reset_policy(_agent(id="other"), "acct_direct_7") == "acct_direct_7"


def test_idle_reset_cuts_once_and_then_stays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = time.time()
    activity = {"acct_direct_7": now - 3600}
    monkeypatch.setattr(R, "_last_activity", lambda key: activity.get(key, 0.0))
    agent = _agent(session_idle_minutes=30)

    first = R.apply_reset_policy(agent, "acct_direct_7")
    assert first == "acct_direct_7_n1"
    activity[first] = now  # the new session gets a turn
    assert R.apply_reset_policy(agent, "acct_direct_7") == first


def test_daily_suffix_follows_the_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(R, "_last_activity", lambda key: 0.0)
    agent = _agent(session_daily_reset="04:00")
    R.start_new_generation(agent, "k")
    key = R.apply_reset_policy(agent, "k")
    assert key.startswith("k_n1_") and len(key) == len("k_n1_20260101")


@pytest.mark.parametrize("scope", ["main", "per-peer", "per-account-channel-peer"])
def test_two_agents_get_different_session_keys(scope: str) -> None:
    peer = {"kind": "direct", "id": "42"}
    k_main = R.session_key_for_agent(
        _agent(session_scope=scope), "telegram", "a1", peer)
    k_helper = R.session_key_for_agent(
        _agent(id="helper", session_scope=scope), "telegram", "a1", peer)
    assert k_main != k_helper
    assert k_helper.startswith("helper_")


def test_default_agent_keys_are_unchanged() -> None:
    peer = {"kind": "direct", "id": "42"}
    group = {"kind": "group", "id": "-100"}

    def key(scope, p=peer):
        return R.session_key_for_agent(
            _agent(session_scope=scope), "telegram", "a1", p)

    assert key("main") == "main"
    assert key("per-peer") == "peer_42"
    assert key("per-channel-peer") == "telegram_direct_42"
    assert key("per-account-channel-peer") == "a1_direct_42"
    assert key("main", group) == "telegram_a1_group_-100"


# ---------------------------------------------------------------------------
# Paragraph streaming
# ---------------------------------------------------------------------------

@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    out: list[str] = []
    monkeypatch.setattr(
        "openprogram.interfaces.channels._transport.post_message",
        lambda platform, account_id, target, text: out.append(text)
        or SendResult.success(""))
    return out


def test_paragraphs_leave_once_long_enough(posted) -> None:
    first = "a" * 250
    streamer = _BlockStreamer("wechat", "acct", "u1")
    for piece in (first[:100], first[100:], "\n\nshort", " tail"):
        streamer.feed(piece)
    streamer.close()
    assert posted == [first]
    assert streamer.unsent_part(first + "\n\nshort tail") == "short tail"


def test_text_before_a_tool_call_is_sent_first(posted) -> None:
    streamer = _BlockStreamer("wechat", "acct", "u1")
    streamer.feed("我查一下。")
    streamer.flush()
    streamer.feed("查到了：三条。")
    streamer.close()
    assert posted == ["我查一下。"]
    reply = "我查一下。查到了：三条。\n\n[attachment: a.txt @ /tmp/a.txt]"
    assert streamer.unsent_part(reply) == "查到了：三条。\n\n[attachment: a.txt @ /tmp/a.txt]"


def test_an_open_code_block_is_never_split(posted) -> None:
    streamer = _BlockStreamer("wechat", "acct", "u1")
    streamer.feed("```python\n" + "x = 1\n" * 60 + "\n\nmore code")
    streamer.flush()
    streamer.close()
    assert posted == []
    assert not streamer.sent_any


def test_nothing_streamed_leaves_the_whole_reply(posted) -> None:
    streamer = _BlockStreamer("wechat", "acct", "u1")
    streamer.close()
    assert streamer.unsent_part("whole reply") == "whole reply"
    streamer.send("late")
    assert posted == ["late"]
