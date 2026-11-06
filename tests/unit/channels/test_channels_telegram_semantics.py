"""Telegram adapter semantics: explicit group-session config, mention
detection, attachment/quote parsing, and the per-user target split in
_transport. Whether an unmentioned group message starts a turn is the
room layer's call (test_channels_rooms.py).
"""
from __future__ import annotations

import pytest

from openprogram.interfaces.channels import accounts as _accounts
from openprogram.interfaces.channels.implementations.telegram import TelegramChannel


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr("openprogram.state.paths.get_state_dir", lambda: state)


def _adapter(**settings) -> TelegramChannel:
    _accounts.save_credentials("telegram", "a1", {"bot_token": "TOK"})
    for k, v in settings.items():
        _accounts.set_setting("telegram", "a1", k, v)
    return TelegramChannel(account_id="a1")


def _update(text="hello", *, chat_type="group", reply_from_id=None,
            photo=False, document=False, caption=None):
    msg = {
        "chat": {"id": -100123, "type": chat_type, "title": "Team"},
        "from": {"id": 777, "username": "alice"},
        "date": 1716000000,
    }
    if text is not None:
        msg["text"] = text
    if caption is not None:
        msg["caption"] = caption
    if reply_from_id is not None:
        msg["reply_to_message"] = {
            "message_id": 5, "from": {"id": reply_from_id},
            "text": "earlier words",
        }
    if photo:
        msg["photo"] = [
            {"file_id": "small", "file_size": 10},
            {"file_id": "big", "file_size": 999},
        ]
    if document:
        msg["document"] = {"file_id": "doc1", "file_name": "notes.pdf",
                           "mime_type": "application/pdf", "file_size": 5}
    return {"update_id": 1, "message": msg}


def _capture(ch: TelegramChannel, upd: dict):
    got: list = []
    ch.handle_inbound = lambda m: got.append(m)  # type: ignore[method-assign]
    ch._handle_update(upd)
    return got


# ---------------------------------------------------------------------------
# settings are explicit config
# ---------------------------------------------------------------------------

def test_settings_validation() -> None:
    _accounts.save_credentials("telegram", "a1", {"bot_token": "TOK"})
    with pytest.raises(ValueError):
        _accounts.set_setting("telegram", "a1", "group_sessions", "sometimes")
    with pytest.raises(ValueError):
        _accounts.set_setting("telegram", "a1", "unknown_key", "on")
    with pytest.raises(ValueError):
        _accounts.set_setting("discord", "a1", "group_sessions", "shared")


def test_defaults_shared_session_every_message_reaches_base() -> None:
    ch = _adapter()
    assert ch.group_sessions == "shared"
    got = _capture(ch, _update("plain group chatter"))
    assert len(got) == 1
    assert got[0].chat_type == "group"
    assert got[0].mentioned is False


def test_per_user_group_sessions_scope_peer_id() -> None:
    ch = _adapter(group_sessions="per-user")
    got = _capture(ch, _update("hi"))
    assert ch.peer_id_for(got[0]) == "-100123_777"
    # DM unaffected
    dm = _capture(ch, _update("hi", chat_type="private"))
    assert ch.peer_id_for(dm[0]) == "-100123"


@pytest.mark.parametrize(("sender", "expected"), [
    ({"id": 666, "username": "alice", "first_name": "Ignored"}, "alice"),
    ({"id": 777, "first_name": "Alice", "last_name": "Ng"}, "Alice Ng"),
    ({"id": 888}, "888"),
])
def test_group_sender_display_never_falls_back_to_the_chat(
    sender: dict, expected: str,
) -> None:
    ch = _adapter()
    update = _update("hi")
    update["message"]["from"] = sender
    update["message"]["chat"]["username"] = "team_handle"

    got = _capture(ch, update)

    assert got[0].user_display == expected


def test_transport_splits_per_user_target() -> None:
    from openprogram.interfaces.channels._transport import _tg_chat_id
    assert _tg_chat_id("-100123_777") == -100123
    assert _tg_chat_id("42") == 42
    assert _tg_chat_id("@channelname") == "@channelname"


# ---------------------------------------------------------------------------
# mention detection
# ---------------------------------------------------------------------------

def test_unaddressed_group_message_is_not_mentioned() -> None:
    ch = _adapter(require_mention="on")
    ch.bot_username = "mybot"
    ch.bot_user_id = "999"
    got = _capture(ch, _update("just chatting"))
    assert [m.mentioned for m in got] == [False]


def test_mention_is_detected_and_stripped() -> None:
    ch = _adapter()
    ch.bot_username = "mybot"
    got = _capture(ch, _update("@MyBot run the report"))
    assert (got[0].text, got[0].mentioned) == ("run the report", True)


def test_group_command_suffix_counts_as_mention() -> None:
    ch = _adapter()
    ch.bot_username = "mybot"
    got = _capture(ch, _update("/activation@mybot always"))
    assert (got[0].text, got[0].mentioned) == ("/activation always", True)


def test_reply_to_bot_counts_as_mention() -> None:
    ch = _adapter()
    ch.bot_username = "mybot"
    ch.bot_user_id = "999"
    got = _capture(ch, _update("and this too", reply_from_id=999))
    assert (got[0].text, got[0].mentioned) == ("and this too", True)


def test_bot_sender_is_flagged() -> None:
    ch = _adapter()
    update = _update("beep")
    update["message"]["from"] = {"id": 5, "username": "otherbot", "is_bot": True}
    assert _capture(ch, update)[0].from_bot is True


# ---------------------------------------------------------------------------
# attachments + quoted parse
# ---------------------------------------------------------------------------

def test_photo_and_document_parsed_with_caption() -> None:
    ch = _adapter()
    got = _capture(ch, _update(text=None, caption="see these",
                               photo=True, document=True))
    assert len(got) == 1
    m = got[0]
    assert m.text == "see these"
    kinds = [(a.file_id, a.mime, a.name) for a in m.attachments]
    assert kinds == [
        ("big", "image/jpeg", "photo.jpg"),      # largest photo size
        ("doc1", "application/pdf", "notes.pdf"),
    ]


def test_attachment_only_message_not_dropped() -> None:
    ch = _adapter()
    got = _capture(ch, _update(text=None, photo=True))
    assert len(got) == 1
    assert got[0].text == ""
    assert got[0].attachments


def test_quoted_text_from_reply() -> None:
    ch = _adapter()
    got = _capture(ch, _update("what about that?", reply_from_id=123))
    assert got[0].quoted_text == "earlier words"
    assert got[0].reply_to_id == "5"


def test_text_free_update_ignored() -> None:
    ch = _adapter()
    assert _capture(ch, _update(text=None)) == []
