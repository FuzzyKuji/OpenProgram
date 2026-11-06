# Channels

Channels let you talk to your agents from Telegram, Discord, Slack and personal WeChat. A message sent to the bot on one of those platforms starts a turn for the agent the account is bound to, and the reply goes back to the same chat. Channels run inside the background worker that `openprogram` starts; they need no public webhook, because every adapter connects outward (Telegram long-poll, Discord Gateway, Slack Socket Mode, WeChat iLink long-poll).

How a message travels today:

1. A platform adapter in `openprogram/interfaces/channels/implementations/` parses the native event into one `ChannelMessage` (text, attachment metadata, quoted text).
2. `base.Channel.handle_inbound` runs the shared pipeline: the pairing gate (unknown senders get a one-hour code that only the owner can approve, from the CLI or the loopback Web UI), attachment download, and the quoted block.
3. `dispatch_inbound` picks the agent from the bindings, computes the session key, runs the turn under a per-session lock, and broadcasts the turn so the Web UI and TUI show it live.
4. Replies leave through one transport module that owns chunking, per-platform formatting (Telegram HTML, Slack mrkdwn, plain text for WeChat), rate-limit retry and file upload. Where the platform allows edits, progress is streamed into one placeholder message.

Scripts, scheduled jobs and agent methods can also send a one-shot message with `outbound.send(...)` without a running worker. Accounts, pairing and routing are managed with `openprogram channels setup`, `accounts`, `access` and `bindings`.

## Documents

- [`design.md`](design.md) — structure and message flow: the two send paths, `dispatch_inbound`, the transport layer, supported platforms and user entry points.
- [`audit.md`](audit.md) — requirements and invariants the layer holds to, compared with OpenClaw and Hermes.
- [`chat-bots.md`](chat-bots.md) — how an agent behaves in a chat room: when it answers, how it shows progress, and what group chats ask of it.
