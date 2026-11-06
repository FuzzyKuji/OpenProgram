# Outbound Hold

What an Agent sends for the user, an email, a chat message, a comment, goes to people who did not ask the Agent anything. The hold keeps each such call as a draft the user approves, in every permission mode.

## Which calls are held

The MCP adapter decides once per tool, when it registers it (`mcp/adapter.py`, `sends_on_behalf`), and stores the answer as `_sends_on_behalf` on the AgentTool. A tool sends when:

- the server does not declare `readOnlyHint: true`, and
- its raw name, split on punctuation and camelCase, does not start with a read verb (`get`, `list`, `read`, `search`, `fetch`, `find`, `query`, `view`, `describe`, `count`, `check`, `lookup`), and
- it contains a sending verb (`send`, `reply`, `respond`, `post`, `publish`, `forward`, `invite`, `share`, `comment`, `tweet`, `broadcast`, `notify`, `dm`), or starts with a create verb (`create`, `add`, `new`, `write`, `compose`) followed by an outbound noun (message, email, mail, comment, reply, post, tweet, invite, dm).

So `send_email`, `chat.postMessage` and `create_comment` are held; `list_messages`, `get_posts` and `create_draft` are not. MCP's `openWorldHint` defaults to true and most servers leave it unset, so it does not separate a send from a read and is not used. Built-in tools are not held: `chat_send` speaks in the conversation's own chat, and `send_message` talks to other OpenProgram sessions.

## Where the hold applies

`permissions/policy.py`:

- `permission_decision` checks `_held_outbound(name, req)` after deny rules and mandatory approvals and before the mode, allow rules and the Auto classifier. A held call is `ask` with reason `OUTBOUND_HOLD` in Bypass, Auto, Ask, Accept edits and with an allow rule. A non-interactive source (scheduler, cron, agent_spawn, mcp) turns that into the usual `APPROVAL_UNAVAILABLE_NON_INTERACTIVE` denial.
- `_held_outbound` reads the turn's Agent (`req.agent_id`, `main` when absent): `AgentSpec.hold_outbound`, default `true`. An unknown Agent holds.
- `one_shot_approval` includes every sending tool, held or not, so an approval never offers "always" and never writes an allow rule: each message is approved on its own.

The approval card already shows the tool name and its full arguments (`approval._approval_detail` does not truncate one-shot calls), which is the draft. **Deny with a note** returns the user's changes to the model as the tool result; the model's next call is a new draft that asks again.

## Configuration

`hold_outbound` is a top-level boolean on `agent.json`, accepted by `PATCH /api/agents/{id}`. A missing value reads as `true`; only an explicit `false` turns the hold off, and then the call follows the conversation's mode and rules like any other tool.

## Implementation status

Implemented: MCP tool classification, the hold in every mode, one-shot approvals, the per-Agent setting through `agent.json` and the HTTP API. Not implemented: a switch in the Agents page, and holding actions done through computer use or the browser (a click on a page's Send button is not recognizable as a send from the call).
