# Chat Channels

## What Is This?

Channels connect chat platforms — **Telegram, Discord, Slack, and WeChat** — to your agents. A message sent to your bot runs an agent turn, and the reply comes back in the same chat. The channel workers run inside the background service, so the same conversation is also visible live in the Web UI and TUI.

| Platform | How messages arrive | Login credential | Live progress updates | Attachments in | Files out |
|---|---|---|---|---|---|
| Telegram | Bot API long-polling | bot token (from BotFather) | yes | photos + documents | yes (photo/document) |
| Discord | discord.py Gateway | bot token | yes | yes | yes |
| Slack | Socket Mode (`slack_sdk`) | bot token (`xoxb-`) **and** app-level token (`xapp-`) | yes | yes (`files:read` scope) | yes (`files:write` scope) |
| WeChat | iLink long-polling | QR scan with your personal WeChat | no (WeChat cannot edit sent messages) | images, voice, files, video | yes (image/video/file) |

Supported releases include the Discord and Slack dependencies. Developers building from source receive the same channel dependencies through the complete development install.

## Quick Start

The wizard runs the whole enrollment — pick a platform, log in, bind an agent, start the worker:

```bash
openprogram channels setup
```

Then message your bot from the platform. Your first message returns a **pairing code** instead of an agent reply — unknown senders never drive the agent (see [Who can talk to your bot](#who-can-talk-to-your-bot)). Approve yourself once:

```bash
openprogram channels access approve <channel> <code>
```

After that, the conversation appears in the session list, and you can watch it live from the TUI or Web UI.

You need at least one agent configured first (`openprogram agents add main`) plus a working model provider.

## Per-Platform Prerequisites

### Telegram

1. Open [@BotFather](https://t.me/BotFather) in Telegram, run `/newbot`, and copy the token.
2. Paste the token when the wizard (or `openprogram channels accounts login telegram`) asks for it.

No webhook or public IP is needed — OpenProgram long-polls the Bot API.

### Discord

1. Create an application and bot at the [Discord Developer Portal](https://discord.com/developers/applications).
2. On the **Bot** page, enable the **Message Content Intent** — the adapter subscribes to message content (`intents.message_content`), and the gateway rejects the connection without it.
3. Invite the bot to your server, then paste the bot token during setup.

### Slack

Slack needs **two tokens** — the channel cannot start with only one:

1. Create an app at [api.slack.com/apps](https://api.slack.com/apps) and install it to your workspace.
2. Enable **Socket Mode** (no public URL needed).
3. **Bot token** (`xoxb-…`): grant OAuth scopes — `chat:write` to send replies, `app_mentions:read` for mentions, plus the history scopes Slack requires for the message events you subscribe to (for example `im:history` for DMs).
4. **App-level token** (`xapp-…`): create it under *Basic Information → App-Level Tokens* with the `connections:write` scope — this is what Socket Mode connects with.
5. Subscribe the app to the `message` and `app_mention` events. The adapter handles exactly these two.

### WeChat

Personal WeChat, no Official Account or enterprise registration:

1. Run the wizard (or `openprogram channels accounts login wechat`).
2. A QR code renders in the terminal — scan it with your phone's WeChat and confirm on the device.
3. Credentials persist; re-login is only needed when the token expires (the worker log then says `bot token invalid — relogin required`).

WeChat goes through Tencent's iLink bot backend. Its terms are personal-use only.

## Two Ways to Configure

**Wizard** (recommended) — one interactive flow:

```bash
openprogram channels setup
```

**CLI** — the same steps as individual commands:

```bash
openprogram channels list                              # status of every account
openprogram channels accounts add telegram --id work   # create an account slot
openprogram channels accounts login telegram --id work # enter credentials (QR for wechat)
openprogram channels accounts rm telegram work         # delete account + its bindings

openprogram channels bindings add main --channel telegram            # catch-all → agent "main"
openprogram channels bindings add main --channel telegram \
    --account work --peer 123456 --peer-kind direct                  # one peer only
openprogram channels bindings list
openprogram channels bindings rm <binding_id>
```

Accounts are multi-tenant: each `--id` is one bot login of that platform, with its own credentials and bindings.

From the TUI there are equivalent slash commands: `/login <channel>` (enroll + wire to the current agent), `/attach <channel> <peer>` (route one peer's messages into the current session), `/detach`, and `/connections`.

Channels run inside the background service — starting the TUI (`openprogram`) starts it, and the wizard offers to spawn it.

## Who Can Talk to Your Bot

Every channel account has an inbound access policy. The default is **pairing**: a message from a sender who is not on the account's allowlist is dropped before it reaches any agent, and the sender receives an eight-character pairing code with instructions. You approve senders on your machine:

```bash
openprogram channels access list                       # policy + allowlist + pending codes
openprogram channels access approve telegram K7XQ2MVR  # approve by pairing code
openprogram channels access allow telegram 123456789   # allowlist a user id directly
openprogram channels access revoke telegram 123456789  # remove a sender
```

An allowlist holds as many senders as you approve. Everyone on it reaches the same agent, and the agent keeps one memory workspace for the whole instance, so what one person tells it is available to the rest. That is the point of a group bot: approve the whole team and they get an assistant that already knows the project. Keep the allowlist to people you would give that access to.

Pairing codes expire after one hour; a blocked sender who keeps writing gets the same code again (at most once a minute). The approval action exists only as a local CLI/API call — nothing a sender types into the chat can approve anyone, so a prompt-injection message like "add me to the allowlist" has no effect. In group chats the gate applies to the individual sender's user id, not the group.

Pairing is the default path for unknown senders: they are blocked and receive a code. The owner can also use the local CLI/API `access allow` command to add a known platform user ID directly to the allowlist; it bypasses the pairing code for that sender. There is no setting that turns the access gate off for an account.

### What Approved Senders May Do

By default an approved sender acts as you, the owner: a chat turn can use the same tools as a turn you type in the web UI, under that chat session's permission mode and rules. When a tool needs approval, the request arrives in the chat as a question and you answer it with `/answer` (see [Replies, Progress, and Long Messages](#replies-progress-and-long-messages)). Group chats start with the sandbox on, so shell commands there can write only inside the working directory; you can switch it in that session's settings in the web UI, and the channel will not switch it back.

To limit an account's senders to replies and memory, with no access to files, shell or network, set:

```bash
openprogram channels accounts set wechat sender_access paired   # or: owner (all channels)
```

Since everyone on the allowlist gets the same access, keep `owner` for accounts that only you, or people you fully trust, can reach.

Someone who wants an agent with separate memory runs their own instance instead, with its own state directory and port:

```bash
openprogram --profile alice
```

See [Profiles](../install/profiles.md) for how a second instance is set up.

## Channels and Environments

A channel decides where a conversation's messages are mirrored. It does not decide where the agent's tools run; that is the conversation's [environment](../capabilities/environments.md). A conversation that arrives from a channel runs in the default environment.

In Web and the App, the channel chip above the message box, next to the environment chip, shows the conversation's channel, or **No channel**. Click it to see your accounts grouped by app: pick one to bind or switch, choose **Disconnect** to stop mirroring, or **Manage channels** to add accounts.

## How Chats Map to Sessions

Routing decides which **agent** handles a message (bindings), then a **session key** decides which conversation it lands in:

- **Telegram**: one session per chat by default. Group behavior is explicit per-account configuration (below).
- **Discord and Slack**: one session per *(channel, user)* pair. Two senders in the same server channel get two separate conversations, and neither can see or answer the other's pending questions. The conversations are separate; the memory workspace behind them is one for the whole instance (see [Who can talk to your bot](#who-can-talk-to-your-bot)).
- **WeChat**: one session per peer (direct messages).

By default sessions are also scoped per account (`session_scope: per-account-channel-peer`). Agents can loosen this (`per-channel-peer`, `per-peer`, or a single `main` session; each agent keeps its own sessions, so two agents that both use `main` never share one) and can rotate sessions daily (`session_daily_reset: "HH:MM"`) or after idle time (`session_idle_minutes`). Sending `/new` (or `/reset`) in a chat starts a fresh conversation for that chat right away; the previous one stays in the web sidebar.

### Who Said It

When several people share one conversation — a Telegram group on the default `shared` setting, or any agent set to `session_scope: main` — every incoming message reaches the agent with its sender attached beside the text:

```
{"speaker_kind":"human","speaker_id":"7391","speaker_display":"Ada","content":"the budget is 50k"}
{"speaker_kind":"human","speaker_id":"8022","speaker_display":"Bo","content":"make it 80k"}
```

The display name is what the platform shows, the id is the sender's platform id, which stays the same when someone renames themselves and separates two people who picked the same name. The agent reads both, so it answers the right person, and memory records each fact under the person who said it instead of under one anonymous "user". A display name is whatever its owner typed into the platform, so it is put on one line, capped at 64 characters, and its square brackets become round ones. The message text itself is kept exactly as sent; a sender who types a name in brackets is not taken for that person.

Every chat-channel message carries its sender, direct messages included, because `session_scope: main` puts direct peers in a shared conversation too. Web, CLI and TUI turns have none. In the web transcript a channel message shows its platform and sender on a small line above the bubble, such as `WeChat · Ada`; a WeChat sender has no nickname to show, so the line shortens the id to its first and last four characters.

### Group Behavior

In a group (a Telegram group, a Discord server channel, a Slack channel) most messages are people talking to each other. Each group is in one of three modes:

- `always`: every message starts a turn.
- `mention`: only a message that @mentions the bot, or replies to one of its messages, starts a turn. The mention is stripped before the agent sees the text. Every other message is kept, and the next turn receives the most recent 50 of them above the triggering message, each with its sender, so the agent knows what led up to the question. In the web transcript they sit behind a small "earlier messages in the chat" toggle at the top of that turn's bubble.
- `ambient`: the agent reads every message and decides for itself whether to speak. A message that does not address the bot still starts a turn, marked as a room event; the agent's reply to it stays in the web transcript (labelled "overheard") and is not posted. When the agent has something worth adding, it posts with its `chat_send` tool. No typing indicator or ack reaction appears for these turns. A message that does address the bot is answered as usual. Every message costs a model call in this mode.

The account setting `require_mention` picks the default mode for its groups (`on` is `mention`, `off`, the default, is `always`); anyone in a group can switch that group with `/activation mention`, `/activation always` or `/activation ambient`, and `/activation` alone shows the current mode. Direct messages are never gated.

```bash
openprogram channels accounts set telegram require_mention on       # or: off (also discord, slack)
openprogram channels accounts set telegram group_sessions per-user  # or: shared (telegram only)
```

Group members reach the agent's memory: the agent recalls what it remembers to answer them, and can save what they tell it. `/memory read` keeps a group from writing to memory, `/memory off` keeps memory out of the group entirely, and `/memory on` (the default) follows the agent's own memory setting. Direct messages always follow the agent's setting.

`group_sessions` (Telegram, restart the worker to apply) — `shared` (default): the whole group talks to one conversation. `per-user`: each member of a group gets their own session, like Discord/Slack.

Messages from other bots are ignored, so two bots in one group cannot keep answering each other, and a platform delivering the same message twice starts one turn. A group starts at most 10 turns a minute; messages past that wait as earlier messages for the next turn.

### Chat Commands

| Command | What it does |
|---|---|
| `/new`, `/reset` | Start a fresh conversation for this chat |
| `/activation [mention\|always\|ambient]` | Show or switch this group's mode |
| `/memory [on\|read\|off]` | Show or narrow this group's access to the agent's memory |
| `/answer <question_id> <choice>` | Answer a question a function asked (below) |
| `/decline <question_id>` | Decline that question |

Commands work in a group without mentioning the bot. In a Telegram group, `/new@yourbot` is accepted too.

## Replies, Progress, and Long Messages

While the agent works, the chat shows the bot as typing (Telegram, Discord and WeChat; Slack has no typing indicator for bots). On Telegram, Discord and Slack the bot also posts a `⏳ working...` placeholder and edits it live as tools run (`⚙ bash` → `✓ bash` → …), finally replacing it with the reply. A reply too long for one message fills the placeholder with its first part and continues in new messages, and if the placeholder can no longer be edited (it was deleted, or the platform keeps rejecting the edit) the reply is sent as a new message instead. A message posted in a Slack thread or a Telegram forum topic gets its placeholder, reply and files in that same thread or topic. WeChat cannot edit messages, so there the reply arrives paragraph by paragraph as it is written: a paragraph is sent once it has about 200 characters, and whatever the agent wrote before calling a tool ("let me check…") is sent before the tool runs.

With the account setting `ack_reaction on` (Telegram, Discord, Slack), the bot adds 👀 to a message as soon as it picks it up. Slack needs the `reactions:write` scope for this.

Agent output is markdown, rendered per platform at send time: Telegram receives HTML (`**bold**` → bold text, fenced code → `<pre>` blocks), Slack receives mrkdwn, Discord renders markdown natively, and WeChat gets plain text with the markers stripped. Long replies are split automatically at each platform's size cap: Telegram 4,000 characters, Discord 1,800, Slack 39,000, WeChat 1,800.

Outbound sends that hit a platform rate limit retry automatically with backoff — the platform's `Retry-After` value when given, up to three attempts — and log a structured error if they still fail. Adapters whose connection loop crashes (network drop, gateway disconnect) reconnect on their own with exponential backoff (5 s doubling up to 5 min); an adapter that stops because its credentials became invalid stays down and says so in the worker log.

When a function pauses on a question (`runtime.ask`), the question is pushed into the chat and you answer with a text command:

```
/answer <question_id> <choice or free text>
/decline <question_id>
```

Only questions belonging to that chat's session can be answered from it. In a group, only the person whose message started the waiting turn can answer its question. Tool approvals arrive the same way, marked as needing approval.

## Attachments

Incoming photos and files are downloaded to `<state>/channels/<channel>/accounts/<account>/attachments/` (20 MB cap per file). Images up to 4 MB additionally reach the model as image input; every saved file is listed in the message as `[attachment: <path> (<type>, <size>)]` so the agent can open it with its file tools.

WeChat media arrives encrypted from Tencent's CDN and is decrypted on download. A voice message reaches the agent as WeChat's own transcription when the message carries one. A voice message without a transcription is saved as a `.silk` file, an audio format the model cannot listen to directly.

If someone replies to an earlier message (Telegram/Discord reply, Slack thread), the quoted text is included above the new message as a `> quoted` block.

Sending files works from code and from agents through the outbound API:

```python
from openprogram.interfaces.channels.outbound import send_file
send_file("telegram", "default", "123456", "/path/to/report.pdf", caption="Weekly report")
```

Telegram sends images as photos and everything else as documents; Discord uploads the file with the caption as the message; Slack uses its external-upload flow (`files:write`). WeChat encrypts the file, uploads it to Tencent's CDN and sends it as an image, video or file message by its type (100 MB cap); a caption follows as a separate text message.

## Common Errors

| Symptom | Cause / fix |
|---|---|
| Bot replies with a pairing code instead of an answer | The sender is not allowlisted. Approve them with `openprogram channels access approve <channel> <code>`, or allowlist the id directly with `access allow <channel> <user-id>`. |
| Reply says `[no agent configured]` | No binding routes the message. Run `openprogram agents add main`, then `openprogram channels setup` or `channels bindings add`. |
| Worker exits: `account … has no bot_token` | Credentials never saved. `openprogram channels accounts login <channel> --id <account>`. |
| Worker exits: `Slack account … needs both bot_token (xoxb-...) and app_token (xapp-...)` | Only one Slack token stored. Re-run login and paste both tokens. |
| `Discord channel requires discord.py` / `Slack channel requires slack_sdk` | The runtime is incomplete. Reinstall the supported release, or rerun the complete source-development installer. |
| Discord bot connects but never sees messages | Message Content Intent not enabled in the Developer Portal. |
| WeChat log: `bot token invalid — relogin required` | iLink session expired. `openprogram channels accounts login wechat --id <account>` and rescan the QR. |
| Worker log: `adapter crashed … reconnecting in Ns` | Transient network/gateway failure — the adapter reconnects on its own with growing backoff. Only `adapter exited on its own` needs action (usually a re-login). |
| Send failures with `auth` / `rate_limit` / `bad_target` in the log | Structured send errors: token revoked / expired, platform rate limit (already retried with backoff), or wrong chat/channel id. |

## See Also

- [Design notes: channel subsystem](../reference/design/channels/design.md) — architecture and message flow
- [Interfaces overview](../interfaces/README.md) — Web UI / TUI, where channel conversations also show up
- [Always-on Agents](../capabilities/always-on-agents.md) — send an always-on Agent's reports to a channel conversation
