# Routing overview

The Overview pane of Settings → Providers answers one question: which session, and which branch of it, is talking to which model, and what happened when a model failed. It is a view over records the runtime already keeps; nothing is collected for it alone except the failover switches.

## Sources

`GET /api/routing/overview?window=<seconds>` (`openprogram/interfaces/server/routes/settings/routing.py`) joins:

| Source | What it gives |
|---|---|
| Session index (`list_sessions`) | title, `source` / `channel`, the `running` status of the current turn |
| Session node graph (`list_branches`, `SessionNodeWriter.load`) | every open branch tip, the model of the last reply on it, whether the tip starts at a sub-agent spawn root |
| Usage ledger `usage_events` | provider calls per session and model in the window; rows whose `parent_session_id` is another session are that session's child sessions |
| Usage ledger `route_events` | one row per failover switch: calling session, failed `provider/model`, next `provider/model`, reason |
| Credential store | each account of a provider in use: status and the end of its rate-limit cooldown |

A session is listed when its turn is running, it was updated inside the window, or the ledger has a call for it there. At most eight are listed, running ones first, then by latest activity; the rest are counted as idle. Each session shows at most four branches, the active one first.

## Lanes

A session's rows are *lanes*, each wired to one model:

- `branch` — an open branch tip. The tip with the longest chain is the trunk and is labelled `main`; others use their branch name.
- `sub_agent` — a tip whose chain starts at a sub-agent spawn root.
- `children` — child sessions grouped by the model they called, with a count.
- `calls` — a session with no reply node but with ledger calls (a program calling models directly).
- `background` — ledger calls that no listed session accounts for: program runtimes with their own `op-…` ids, titling, memory upkeep. They are grouped by model under one *Background calls* entry, so the map adds up to the call count above it.

A lane is live when it is the active tip and the session's turn is running, or when it has a ledger call in the last 90 seconds. Opening a session reads its whole node graph from disk, file by file. Every read gives up the GIL, and while other server threads are busy each one waits to get it back, so a cold open can take seconds. Two rules keep the request fast: a session and its lanes are cached per `(session, index updated_at)`, so an unchanged session is never opened again; and cold sessions open on one background thread, with the request waiting at most 1.5 s for them. A session not ready by then is shown from its index row and its ledger calls, and the response carries `partial: true` so the client asks again two seconds later.

## Failover switches

`stream_with_failover` appends a `route_events` row each time it moves from a failing candidate to the next one, tagged with the session from the usage context. The Overview draws a dashed edge from the active lane to the failed model when the session's latest switch landed on the lane's model, marks the failed model with the reason, and lists recent switches under the map. Switches only exist when fallback models are configured; a failure that is shown to the user without a switch is not recorded here.

## Client

`apps/web/components/settings/providers/routing-overview.tsx` renders two HTML columns and an SVG layer behind them. Edge end points are measured from the rendered rows after layout and on resize, so names can be any length. Switching the time window cancels the previous window's request and dims the shown content until the new window arrives. Live edges carry a moving dot; hovering a lane or model keeps its edges and dims the rest. Below 560 px of pane width there is no room for two columns and the edges between them; the pane hides the map and asks the user to collapse the sidebars or widen the window.
