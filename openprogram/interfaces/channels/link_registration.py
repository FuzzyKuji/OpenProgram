"""The channels interface's implementation of the core's channel link.

``openprogram.runtime.channel_link`` is how core code sends to a channel
conversation, reads an Agent's channel bindings and posts into the running
channel turn's chat without importing this interface. This module implements
it with :mod:`.outbound`, :mod:`._transport`, :mod:`.accounts`,
:mod:`.bindings` and :mod:`._active_turns`, and registers it when
``openprogram.interfaces.channels`` is imported.

Every operation looks its implementation up when it runs, so a test that
patches one of those modules is seen.
"""
from __future__ import annotations

from typing import Any

from openprogram.runtime import channel_link


class Channels:
    """Outbound sends, account and binding lookups, and the running channel turn."""

    def send_message(self, channel: str, account_id: str, peer_id: str, text: str) -> Any:
        from openprogram.interfaces.channels import outbound
        return outbound.send_full(channel, account_id, peer_id, text)

    def post_message(self, channel: str, account_id: str, peer_id: str, text: str) -> Any:
        from openprogram.interfaces.channels import _transport
        return _transport.post_message(channel, account_id, peer_id, text)

    def account_ids(self, channel: str) -> list[str]:
        from openprogram.interfaces.channels import accounts
        return [account.account_id for account in accounts.list_accounts(channel)]

    def peer_bindings(self, agent_id: str) -> list[dict[str, Any]]:
        from openprogram.interfaces.channels import bindings
        return bindings.list_for_agent(agent_id)

    def active_turn(self, session_id: str) -> Any:
        from openprogram.interfaces.channels import _active_turns
        return _active_turns.get(session_id)

    def take_send(self, session_id: str) -> bool:
        from openprogram.interfaces.channels import _active_turns
        return _active_turns.take_send(session_id)

    def sends_per_turn(self) -> int:
        from openprogram.interfaces.channels import _active_turns
        return _active_turns.MAX_SENDS_PER_TURN


channel_link.register(Channels())
