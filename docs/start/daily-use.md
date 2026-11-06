# Daily Use

This page covers the operations you'll use every day once installed: the two entry points (terminal and web), resuming and managing sessions, and branching / rollback in the web UI.

## Two entry points, one set of sessions

- `openprogram` — terminal chat interface (TUI).
- `openprogram web` — browser interface, http://localhost:18100.

Session data lives in each project's folder, `~/.openprogram/projects/<project-id>/chats/<session-id>/`; sessions with no project belong to the home project (id `default`, named after your home folder). The terminal and the web see the same history: a session started in the terminal shows up in the web sidebar, and vice versa. Working folders hold project files, not conversation repositories.

One-off questions don't need an interface:

```bash
openprogram --print "Summarise this error message for me: ..."
```

Common commands for the background service:

```bash
openprogram status      # is the service running (PID, ports, uptime)
openprogram restart     # restart after code or config changes
openprogram stop        # stop
```

## Resuming sessions

```bash
openprogram sessions list          # list all sessions across all agents
openprogram --resume <session_id>  # resume a session in the terminal
```

Session ids are also visible in the web sidebar. There is also `openprogram sessions resume`, used to answer a session that is currently waiting for user input.

## Binding sessions to channels

If you have configured a chat channel (Telegram / Discord / Slack / WeChat), you can pin a channel user's messages to a specific session:

```bash
openprogram sessions attach    # route a channel user's messages into a given session
openprogram sessions detach    # unbind, back to default routing
openprogram sessions aliases   # list all session-to-channel-user bindings
```

## Session operations in the web UI

Session history is stored as a conversation DAG (git-style: commits, branches, forks), and branches are first-class. Hovering over any message reveals action buttons:

- **Copy** — copy the message content.
- **Regenerate** (replies) — run the reply again as a new version.
- **Pin as chapter** (replies) — mark the turn so its tick on the message rail at the chat's left edge is drawn longer and thicker in purple, and the reply keeps its action row shown; choose **Unpin chapter** to remove the mark.
- **Edit message** (your messages) — modify a message you sent and regenerate.
- **Rewind to here** (your messages) — reset the session, files included, to the state at this message.

After an edit or a regenerate, the same slot holds multiple versions — switch with the previous / next version arrows beside the message. The branch menu in the top bar lists and switches the current session's branches. To quote part of a message, select the text and choose **Add to chat**. **Copy conversation** in the ⋯ menu at the top right of the chat makes a new conversation with the same history, which then runs on its own.

The right sidebar is the session's DAG view: each node is a user message, an LLM call, or a function call. The view scrolls with the chat, and clicking a node scrolls the conversation to the corresponding message. Branches that touch files run in isolated git worktrees under the hood, so concurrent work on different branches never fights over the same source tree.
