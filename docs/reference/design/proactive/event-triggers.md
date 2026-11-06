# Event Triggers

A Scheduler task normally fires at a time. Two triggers fire it when something happens: a **watch** on a recurring or monitor task runs the task only when a command's output changed, and a **webhook** task runs when an outside service POSTs to it. Both reuse the task's signed execution spec and hand the run an *event*, the outside text that started it.

| Piece | Where |
| --- | --- |
| Task types, `watch` field, hook key | `openprogram/runtime/scheduler/service.py` |
| Signed spec carries `watch` | `programs/tools/jobs/cron/cron.py` (`_build_execution_spec`, `_verify_execution_spec`) |
| Watch checks, event delivery | `programs/tools/jobs/cron/worker.py` (`_check_watch`, `watch_change`, `event_note`, `fire_event`) |
| Webhook verification and rate limit | `openprogram/runtime/scheduler/hooks.py` |
| HTTP route | `POST /hooks/{task_id}` in `webui/routes/execution/scheduler.py` |
| Login exemption | `webui/owner_auth.py` |
| Untrusted wake turns | `conversation/owner_turn.py` (`untrusted`), `scheduler/reminders.py` |

## Watch

`watch` is a shell command stored on the task and frozen into the signed execution spec next to the body, so editing the task file cannot change what runs on every tick. On a due tick `_tick` calls `_check_watch` instead of `_spawn`: it verifies the spec, then a daemon thread runs the command with `_invocation(..., force_sandbox=True)` under the task's sandbox policy, with a 120 s timeout. `watch_change` keeps, per task, the SHA-256 of the command, the SHA-256 of the output and the output itself (first 20,000 characters) in `<schedule dir>/watch-state.json`, under the store lock. The first check of a command is the baseline; a different command starts a new one; an unchanged digest starts nothing. A changed digest returns the event `{"source": "watch", "text": <command and unified diff, at most 6,000 characters>}` and the thread calls `_spawn` with it. A failing or timed-out check is logged and leaves the baseline alone. The claim for the minute is taken as for any task, so a tick checks each watch once.

## Webhook

A `webhook` task has neither `cron` nor `run_at`, so `_entry_due` never fires it. Creation stores a random `hook_key` (24 bytes, URL-safe) on the entry; the tool's create result prints the URL (`hooks.url`, from the active Web access snapshot) and the key. `POST /hooks/{task_id}` is the one HTTP path `OwnerAuthMiddleware` passes without the owner login, and only for `POST` with exactly that shape; the Host and Origin checks still run. The route reads at most 64 KB and calls `hooks.receive` on a worker thread:

1. An unknown task, a task of another type, and a wrong key all answer `404`, so the route does not reveal which ids exist. The key is accepted from `X-OpenProgram-Key`, or as the HMAC-SHA256 secret of `X-Hub-Signature-256` (GitHub); both compare in constant time.
2. A paused task answers `409`.
3. One task fires at most once per 10 s per process (`429` otherwise).
4. `worker.fire_event` calls `_spawn` with `{"source": "webhook", "text": ...}`: the body, pretty-printed when it is JSON, prefixed with `X-GitHub-Event` when present, cut to 8,000 characters. `202` means the run started.

## The event reaches the run as data

`_spawn` passes the event to each body kind:

- **prompt**: `_run_prompt_job` appends `event_note(event)`: the text inside `<event source="…" trust="untrusted">`, with any `</event>` in it escaped, followed by a line telling the agent the text is data and to do only its task. The run is the usual non-interactive scheduler turn (`source="scheduler"`, permission mode `ask`), so any call that needs approval is denied.
- **reminder**: `reminders.fire` adds `event` to the `reminder.fired` payload. A waking reminder's text then names the event source and carries the same note, and `_wake` calls `start_owner_turn(..., untrusted=True)`. An untrusted owner turn runs in `ask` when the conversation's mode is `bypass`, `auto` or `acceptEdits` (`UNTRUSTED_DOWNGRADE`); `ask` and `plan` stay as they are. The approvals then wait in that conversation like any other.
- **command**: the process gets `OPENPROGRAM_EVENT` and `OPENPROGRAM_EVENT_SOURCE` in its environment.

The task log records the event under `# started by <source>:`.

## Implementation status

Implemented: watch, webhook (key header and GitHub signature), event delivery to all three body kinds, untrusted wake turns, Scheduler page labels. Not implemented: a Scheduler page form for creating watch and webhook tasks (they are created through the `scheduler` tool or `POST /api/scheduler/tasks` with `watch` or `"type": "webhook"`), and showing a webhook's URL and key again after creation (the key is in the task, `GET /api/scheduler/tasks/{id}`).
