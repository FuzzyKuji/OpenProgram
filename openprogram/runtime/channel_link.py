"""The link between the core and the chat channels (Telegram, Discord, Slack, WeChat).

Core code sends messages to a channel conversation, reads which channel
conversations an Agent is bound to, and posts into the chat of the channel
turn that is running, without importing the channels interface. The channels
package (``openprogram.interfaces.channels``) registers its implementation
with :func:`register` when it is imported; the worker, the Server and the
CLI's in-process turns import it at start.

With no channels registered every operation raises
:class:`ChannelsUnavailable`. A caller that can run without channels (a
reminder in a process that has none, an always-on report delivery) already
treats a failed send as a recorded failure, so the named error is the
outcome it reports.
"""
from __future__ import annotations

from typing import Any, Protocol


class ChannelsUnavailable(RuntimeError):
    """A call needs the chat channels and none are registered in this process."""


class SendOutcome(Protocol):
    """What a channel send returns: success, or a failure kind and detail."""

    ok: bool
    error_kind: str
    error_detail: str


class ChannelTurn(Protocol):
    """The chat a running channel turn came from."""

    channel: str
    account_id: str
    peer_id: str


class ChannelLink(Protocol):
    """The operations the channels interface implements for the core."""

    def send_message(self, channel: str, account_id: str, peer_id: str, text: str) -> SendOutcome:
        """Send ``text`` to one channel conversation through the outbound path."""

    def post_message(self, channel: str, account_id: str, peer_id: str, text: str) -> SendOutcome:
        """Post ``text`` into a chat directly through the platform transport."""

    def account_ids(self, channel: str) -> list[str]:
        """The account ids configured for ``channel``."""

    def peer_bindings(self, agent_id: str) -> list[dict[str, Any]]:
        """The routing bindings that send channel conversations to ``agent_id``."""

    def active_turn(self, session_id: str) -> ChannelTurn | None:
        """The channel turn running in ``session_id`` right now, if any."""

    def take_send(self, session_id: str) -> bool:
        """Count one message the running turn posts; False once its quota is used."""

    def sends_per_turn(self) -> int:
        """How many messages one channel turn may post on its own."""


_link: ChannelLink | Any | None = None


def register(link: ChannelLink | Any) -> None:
    """Make ``link`` the channel link of this process (the last one wins)."""
    global _link
    _link = link


def unregister(link: ChannelLink | Any | None = None) -> None:
    """Drop the registered link, or only ``link`` when it is the current one."""
    global _link
    if link is None or _link is link:
        _link = None


def current() -> ChannelLink | Any | None:
    return _link


def require() -> ChannelLink | Any:
    """The registered link, or :class:`ChannelsUnavailable` when there is none."""
    if _link is None:
        raise ChannelsUnavailable(
            "no channel interface is registered; import openprogram.interfaces.channels "
            "(the worker, the Server and CLI turns do) before using chat channels."
        )
    return _link


def send_message(channel: str, account_id: str, peer_id: str, text: str) -> SendOutcome:
    return require().send_message(channel, account_id, peer_id, text)


def post_message(channel: str, account_id: str, peer_id: str, text: str) -> SendOutcome:
    return require().post_message(channel, account_id, peer_id, text)


def account_ids(channel: str) -> list[str]:
    return list(require().account_ids(channel))


def peer_bindings(agent_id: str) -> list[dict[str, Any]]:
    return list(require().peer_bindings(agent_id))


def active_turn(session_id: str) -> ChannelTurn | None:
    return require().active_turn(session_id)


def take_send(session_id: str) -> bool:
    return bool(require().take_send(session_id))


def sends_per_turn() -> int:
    return int(require().sends_per_turn())


__all__ = [
    "ChannelLink", "ChannelTurn", "ChannelsUnavailable", "SendOutcome",
    "register", "unregister", "current", "require",
    "send_message", "post_message", "account_ids", "peer_bindings",
    "active_turn", "take_send", "sends_per_turn",
]
