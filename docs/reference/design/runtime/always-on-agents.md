# Always-on Agents

An always-on assistant keeps working without the user present: it holds a standing goal, wakes on a schedule, does read-only research while it has nothing assigned, and reports what it found. The reference products are OpenAI's dots and xAI's Grok Bot. Both give one agent a persistent goal, its own place to work, memory that improves with feedback, and rules for what it may do alone.

OpenProgram builds this from existing parts and splits it the way the rest of the product is split: an Agent is configuration, and a conversation is where work happens. Always-on is the `always_on` section of a saved Agent (`AgentSpec`). Every conversation that uses that Agent is one always-on assistant: it wakes, keeps its own Goal, check-ins, [open work](../../../capabilities/agents.md#open-work) and reports, and runs with the Agent's model, instructions, tools, memory space and the conversation's permission rules. There is no assistant object apart from the conversation and no settings apart from the Agent's. The always-on code (`openprogram/runtime/conversation/always_on/`) only decides which conversations wake and when, what each wake does, and where reports go.

## Pieces

| Piece | Where it lives | Reused from |
| --- | --- | --- |
| Configuration | `AgentSpec.always_on` in `agent.json` | Agent management, revisioned saves |
| The assistant | Each owner conversation that uses the Agent | Session store, chat UI |
| Standing goal | A chat Goal in the conversation | Goal continuation, verification, budgets |
| Wake schedule | `openprogram/runtime/conversation/always_on/ticker.py`, a worker thread | Worker service startup |
| Quiet hours and wake days | `openprogram/runtime/conversation/always_on/schedule.py` | Local clock |
| Check-in turn | An ordinary turn with a read-only tool list | `owner_turn.start_owner_turn`, `TurnRequest.tools_override` |
| Reports | `always_on_report` tool, the conversation's report file, `always_on_report` frame | Desktop notification bridge |
| Channel delivery | `openprogram/runtime/conversation/always_on/delivery.py` | `channels.outbound.send_full`, bindings, channel sessions |
| Team handoffs | `handoff` tool, `openprogram/runtime/conversation/always_on/handoff.py` | The waking-reminder path: `owner_turn.start_owner_turn_when_free` |
| Learning | The Agent's own memory space | Memory policy and session-end extraction |
| Rules | The conversation's permission mode and rules | Permission rules, approval cards |
| Status and Wake now | The conversation's Activity panel | Activity rows and pages |

## Configuration

`always_on` is part of the Agent configuration, so it saves through the Agent editor's single draft and revision check:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | Conversations with this Agent wake on schedule |
| `goal` | string, at most 4000 characters | `""` | Standing objective; empty means research only |
| `wake_minutes` | int, 5–10080 | `60` | Interval between scheduled wakes |
| `research` | bool | `true` | Run a check-in when no Goal is unfinished |
| `autonomy` | `"report"` or `"act"` | `"report"` | Whether a check-in may start a Goal itself |
| `channels` | list of `{channel, account_id, peer_id, label}`, at most 10 | `[]` | Channel conversations that also get each report |
| `quiet_hours` | `{start, end}` local `"HH:MM"` times that differ, or `null` | `null` | Daily stretch without scheduled wakes; an end before the start crosses midnight |
| `wake_days` | non-empty list of weekdays, Monday `0` to Sunday `6` | all seven | Days scheduled wakes may happen on |

`validate_always_on()` in `agent_registry/manager.py` normalizes the section the same way `validate_memory_config()` normalizes memory. Older `agent.json` files without the section load as disabled. Duplicating an Agent copies the section with `enabled` forced off, so a copy never starts waking unasked.

## Runtime state

Runtime state is kept apart from configuration so that wakes never bump the configuration revision or conflict with an open editor draft.

Each conversation keeps its own, next to its messages in the session directory:

- `always_on.json`: `joined_at`, `applied_goal` (the objective text and Goal id last started from configuration), `last_check_in_at`, `last_wake` (`at`, `reason`, `outcome`) and `next_wake_at`.
- `always_on_reports.jsonl`: one report per line (`id`, `at`, `title`, `body`, `links`, `session_id`, and `deliveries` when channels were picked), trimmed to the newest 200.

The Agent keeps one fact: `enabled_at` in `<agent dir>/always_on/state.json`, the moment the ticker first saw always-on turned on. It is cleared when always-on is turned off.

Handoff chains span conversations, so the worker keeps them in one file, `<state dir>/always_on/handoffs.json` (see [Handoffs](#handoffs)).

All files are written atomically under a lock per conversation (per Agent for `enabled_at`, one for the handoff file). Deleting a conversation deletes its state and reports with it.

## Which conversations wake

A conversation wakes when it is an owner conversation of an always-on Agent and has joined:

- **Owner conversation**: not archived, and a web chat (source empty or `web`), a channel conversation, or a home conversation from older versions (source `always_on`). Sub-agent (`agent`) and imported conversations never wake.
- **Joined**: it has wake state, or it was updated after `enabled_at`, or it was just switched to the Agent. `POST /api/sessions/{id}/agent` calls `join()`, which schedules the first wake one interval after the switch. The ticker records `joined_at` and schedules the first wake one interval later, so a chat the user just opened is not interrupted and conversations nobody has used since always-on was turned on stay quiet. Turning always-on on for Main therefore does not wake every old chat.

Archiving a conversation is how the user stops one; it needs no setting of its own. When always-on is turned on again, a conversation whose `next_wake_at` predates the new `enabled_at` counts its interval from that moment instead of waking at once.

Older versions kept one home conversation per Agent and its state in `<agent dir>/always_on/state.json`. On the first tick after always-on is seen enabled, `_adopt_home()` copies that state (`applied_goal`, `last_check_in_at`, `last_wake`, `next_wake_at`) into the home conversation, which then wakes like any other.

## Wake

`wake(session_id, reason)` runs on every scheduled tick and on **Wake now**. It always records `last_wake` and schedules the next wake: `next_wake_after()` takes `now + wake_minutes` and moves it with `schedule.next_allowed()` to the first moment outside quiet time. One wake does at most one thing, decided in this order:

1. **disabled**: the conversation's Agent has `always_on.enabled` off. A scheduled wake stops here; **Wake now** is refused.
2. **quiet**: a scheduled wake (not **Wake now**) falls in quiet hours or on a day missing from `wake_days`, which happens when the schedule was saved before the setting or the clock moved. Nothing starts, and the next wake is the end of the quiet time.
3. **busy**: a turn is already running in the conversation, or one takes the run slot before the check-in does. Nothing starts.
4. **goal started**: the standing `goal` is non-empty and differs from the conversation's `applied_goal`, and no Goal in the conversation is unfinished. The runtime creates a chat Goal with that objective (`origin: "always_on"`) and starts it with `goal.chat.start_from_controls()`. From then on the ordinary Goal continuation drives the work turn after turn, and verification decides completion. Continuation and verification turns of such a Goal carry `goal.chat.STANDING_GOAL_NOTE`: the standing goal is one objective, finished once its requirements hold, and anything recurring belongs to check-ins. Without it a standing goal written as a routine ("check the build and report") was never submitted as complete and the Goal repeated the check every turn.
5. **goal in progress** or **goal paused**: a Goal is unfinished. The wake leaves it alone. Automatic continuation belongs to the Goal runtime, and a user's pause is never overridden.
6. **check-in**: `research` is on. The runtime starts one check-in turn (below).
7. **idle**: nothing to do.

Quiet time only holds back scheduled wakes. A running Goal continues through it, and handoffs and **Wake now** run in it. `schedule.py` reads the worker's local clock: a moment is quiet when its weekday is not in `wake_days` or its time of day is in `[start, end)` (wrapping past midnight when `end < start`). Quiet time ends only at a midnight or at `end`, so `next_allowed()` checks those boundaries over the next eight days.

A changed standing goal therefore takes effect in each conversation once its current Goal ends. The user can end it from the conversation (`/goal clear`) to switch immediately.

## Check-in turn

A check-in is an ordinary owner chat turn in the conversation (source `web`), with the conversation's own permission mode and rules. Goal continuation, verification and approval cards therefore treat it exactly like a chat the owner started. Its prompt names the time of the previous check-in, the standing goal and the autonomy setting, and asks the agent to:

- review its memory, its open work and the conversation for open threads;
- look for anything new that matters to the goal, using only read-only tools;
- call `always_on_report` when it found something the user should see, and stay silent otherwise.

`tools_override` limits the turn to read-only tools: `read`, `grep`, `glob`, `list`, `web_search`, `web_fetch`, `read_conversation`, `memory_search`, `memory_get`, `todo_list`, `open_work`, `get_goal` and `always_on_report`. With `autonomy="act"`, `create_goal`, `todo_create`, `todo_update` and `handoff` are added, so the agent can turn a finding into its own Goal, which then runs under normal tools and permissions, or hand it to the conversation that owns it. MCP tools are not included, because a server's tool cannot be classified as read-only from its name. `open_work` writes only to the conversation's own list.

A per-turn tool list given by name ships every tool with its full schema (`model_tools.resolve_tools`): the list has no `tool_search`, so a deferred tool in it could never be loaded. The readers a check-in uses and the report itself (`get_goal`, `read_conversation`, `always_on_report`) are on the permission classifier's safe list, so an unattended check-in in Ask or Auto mode runs without an approval card or a review call. The `act` additions keep the conversation's permission mode. The screen tool that open browser Pages add to a turn (`loop_runner._configure_web_use_tools`) stays out of a turn whose tools are given by name unless the list names it: a check-in that reached it waited on a Screen Recording prompt nobody was there to answer.

## Reports

`always_on_report(title, body, links)` is a tool in its own `always_on` toolset, outside the default set. `loop_runner` offers it only in a conversation whose Agent is always-on (checked with `agent_for_session()`) and removes it everywhere else; called outside one, it refuses. A report is appended to the conversation's report file and broadcast as an `always_on_report` frame carrying `session_id`. The desktop shell turns that frame into a system notification through the existing attention bridge (kind `report`, keyed by report id, shown only while no App window has focus). Clicking the notification opens the conversation. The report also stays in the transcript as the tool call that produced it, and the Activity panel lists it. It also gives the conversation the sidebar's unread dot at once: `turn_writer.mark_session_unread()` sets `unread` and broadcasts a `session_updated` row unless a client shows the conversation, the same rule `mark_session_finished()` applies when a turn ends. A check-in turn is started with `TurnRequest.quiet_finish`, so its end records `done` without touching `unread`: the report is the only thing that marks it, and a check-in that finds nothing leaves the dot alone. `last_wake` still records the `check_in` outcome for the Activity panel, and a failed check-in still gets the red dot.

## Handoffs

Several conversations work as a team through `handoff(to, message)`, a tool in the `always_on` toolset. `loop_runner` offers it where it offers `always_on_report`, except in a turn that does not advance the head or was spawned from another session (a sub-agent's turn). `to` is a conversation id or an exact title (case-insensitive); an ambiguous title is refused with the matching ids, and an unknown one lists the owner's conversations. The target may use any Agent.

`handoff.send()` checks and returns at once; delivery runs on a daemon thread:

1. The target gets a wake turn through `owner_turn.start_owner_turn_when_free()`, the path waking reminders use: it waits up to ten minutes for a running turn, then takes the conversation's run slot, under the target's own Agent and permission settings. The turn's text starts `📨 Message from “<sender title>” (<sender id>):` and says the answer goes back on its own.
2. When that turn ends, its final text goes back to the sender as another wake turn starting `↩️ Reply from “<target title>” (<target id>)`. A reply needs no answer and starts no further reply.
3. When the target stays busy past the wait, the sender gets the undelivered message back as a `↩️` turn instead.

Both rows are ordinary user messages in the transcripts, like a reminder's ⏰ wake. Loop protection: the sender and the target must be owner conversations (not sub-agent, imported or archived), the sender's Agent must be always-on, the target is never the sender, and a chain carries a hop count. Each handoff and reply turn is started with a known user message id that `handoff.py` maps to its chain and hop; a handoff sent from such a turn (the tool reads `TurnRequest.user_msg_id`) is one hop further, and the fifth is refused (`MAX_HOPS = 4`). Any other turn starts a new chain. `handoff` is not on the safe list: in Ask mode the send waits for approval, and in Auto mode it is reviewed.

Chains survive a worker restart. Each chain turn is an entry in `handoffs.json`, keyed by its user message id: `chain`, `hop`, `origin` (the conversation that started the chain), `handoff_id`, `session_id`, `at`, `boot` (the worker process that started it), `phase` (`waiting`, `running` or `done`) and, on a handoff turn, `reply_to`, the sender it still owes its answer. Every change rewrites the file, dropping entries older than a day; `ticker.start_in_worker()` loads it through `handoff.restore()`. A turn the restart cut off continues as a turn with `restart_resume` and a new message id. In it, the tool passes `resumed=True` and the chain is the latest `running` entry of an earlier worker in that conversation, so the hop count carries on. When that turn ends, success or failure, `turn_runtime` calls `handoff.resumed_turn_ended()`, which marks those entries `done` and sends the reply each one owed. The reply is popped from its entry under the lock before it is sent, by this path or by the live `on_done`, so it goes out at most once.

## Built-in Agents

Grok Bot ships bot templates: one assistant per job, each with a job statement, a deliverable, boundaries, a done condition and a first task, and they hand work to each other. Here a template is simply a **built-in Agent**: a complete configuration in `agent_registry/builtin_agents.py`, installed as an ordinary saved Agent and shown on the Agents page like any other. There is no separate catalog, picker or team object; the Agents list is the list of templates, and the New Agent dialog creates a blank record. The sources studied for them are in [Bot template references](agent-configuration/bot-template-references.md).

Installation is `create_builtin_agents()`. The registry index carries `builtins`, the ids this instance has installed at some point (`manager.installed_builtins()`, `manager.record_builtins()`); the function creates the built-ins that are neither saved nor on that list, leaves every existing record as it is, edits included, then records all built-in ids. A built-in the user deleted is therefore not recreated. The server runs it in its startup sequence, but only once a default Agent exists, because the first record created becomes the default and that must be Main; setup runs it right after creating Main. Registry reads never install anything.

Three built-ins are the fixed-parameter specialists (Decision, Lightweight helper, Coordinator) without a prompt. The job Agents each carry:

- A system prompt in a fixed shape: `Job`, `Deliverable`, `Never` (a list), `Done when`, `Working style` (a list, ending with how to hand a step to another Agent's conversation) and `First task`. The prompt is English in both languages; names and descriptions are bilingual, and the install language picks which the record gets.
- A `selected` tool policy naming built-in tools only, so the Agent works on a fresh install. The producer may edit; the verifier has no `edit`, `write` or `apply_patch`.
- A memory mode on the Agent's own space (`self`): off for the engineering Agents, read-only for the writing ones, read and write for the ones that learn the user's preferences.
- Always-on defaults: `enabled` off, `autonomy: "report"`, and per Agent `research` and `wake_minutes` (30 for Inbox Triage, 120 for Chief of Staff, 240 for Research Desk, 720 for Career Scout, 1440 for Knowledge Keeper; research off for the engineering Agents and Writer).
- `hold_outbound` on, so anything the Agent sends for the user waits as a draft.

The built-ins work together through [handoffs](#handoffs) between their conversations; the installation creates no conversations or titles, the user does.

The autonomy levels the templates speak of map onto existing controls rather than a new field: observe only is `always_on.research` on with `autonomy: "report"` in Ask mode; draft is the same with `hold_outbound` (the default); act with approval is `autonomy: "act"` in Ask mode, where every outbound action is an approval card; scheduled unattended work is `autonomy: "act"` in Auto mode with a standing `goal`.

## Channel delivery

`always_on.channels` lists the channel conversations that also get each report, from any conversation with the Agent. `channel` is one of `telegram`, `slack`, `discord` or `wechat`. `peer_id` is the target the channel transport expects: the same id channel sessions store, so a Slack or Discord target is the scoped `<channel>_<user>` id. `validate_always_on()` rejects unknown channels and empty ids and drops duplicates of one (channel, account, peer).

The Always-on tab offers targets from `delivery.channel_targets()`, which `GET /api/agents/{id}/always-on` returns as `channel_targets`:

- the Agent's channel conversations (session rows with `channel`, `account_id` and `peer_id`), labelled with the peer's display name;
- the Agent's peer bindings. A binding without an account expands to every account of that channel.

A binding to a whole channel or account names no peer, so it contributes nothing until someone talks to the Agent there.

When the Agent has targets, `runtime.report()` saves the report with one `deliveries` row per target in status `sending` and broadcasts it as before. It then calls `delivery.deliver()`, which sends from a daemon thread so the tool returns at once. Retries and rate limits can take tens of seconds. The thread sends one Markdown message per target through `channels.outbound.send_full()`: the bold `<Agent name> · <title>`, the body, then the links as a list. The channel transport renders it per platform and splits long text. Each row becomes `sent`, or `failed` with the transport's `error_kind` and a one-line `detail`. An exception counts as `unknown`. The thread then writes the rows back with `store.update_report()` and broadcasts `always_on_update` with the conversation's `session_id`, so an open Activity panel refreshes. A failed send never removes the report or fails the tool.

## Learning from feedback

The agent learns through the Agent's configured memory. With Memory set to **Read and write** on **This Agent**, the session-end writer extracts preferences and corrections from its conversations into the Agent's own space, and every later turn reads them back. What one conversation owes the user stays in that conversation's open work; what every conversation should know goes to memory. The Always-on tab says so when memory is not read-write; it never changes the memory setting itself.

## Rules

What the agent may do alone is the conversation's permission mode plus the saved permission rules, the same controls every conversation has. Approvals a turn needs wait in the conversation as approval cards and raise a needs-input notification. Check-ins add no permissions; they only narrow the tool list.

## Schedule

`ticker.py` starts with the worker's other services. Every 30 seconds, for each Agent with `always_on.enabled`, it records `enabled_at` if missing, lists the Agent's conversations (at most 500 per Agent), joins the newly eligible ones and wakes each conversation whose `next_wake_at` has passed. Every `next_wake_at` it or `join()` writes is already moved past quiet time. A worker restart keeps the saved schedule instead of waking everything at once, and the per-conversation lock never runs two wakes for one conversation at the same time. For Agents with always-on off it clears `enabled_at`.

## Surfaces

- **Agents → Always-on tab**: configuration only: the fields above and the channel targets to pick.
- **Activity panel**: an **Always-on** row in each conversation whose Agent is always-on, with what it is doing and the next wake (marked while quiet hours hold wakes back). Its page shows the standing goal, the current Goal, the wake days and quiet hours, the last wake and its outcome, the reports with their deliveries, and **Wake now**. `status()` returns `next_wake_at` moved past quiet time and `quiet_now`.
- **HTTP**: `GET /api/agents/{id}/always-on` returns the saved configuration and `channel_targets`; `PATCH /api/agents/{id}` accepts `always_on` like any other section. `GET /api/sessions/{id}/work` returns the conversation's always-on status and reports, together with its open work and Scheduler tasks; `POST /api/sessions/{id}/always-on/wake` wakes it now; `POST /api/sessions/{id}/agent` switches the conversation's Agent from the composer's Agent chip.
- **WebSocket**: `always_on_report` and `always_on_update` frames carry `session_id`.
- **Python**: `openprogram.runtime.conversation.always_on` exposes `wake()`, `status()`, `report()`, `join()`, `agent_for_session()` and `channel_targets()`; `always_on.handoff.send()` hands a message over and `always_on.schedule` answers `is_quiet()` and `next_allowed()`.

## Alternatives

Open-source always-on agents compared with this design: Daimon (an MIT skeleton with scheduled background passes that speak up only when something matters), Gobii (per-agent schedules and SMS, email, webhook and cron triggers), aidaemon (a background daemon with goal scheduling and heartbeat checks) and OpenClaw's `HEARTBEAT.md` file-driven check-ins. OpenAI Codex's persistent mode records goal, status, completion criteria and the next check-in before sleeping; ChatGPT's scheduled tasks pair a task with an ongoing goal; Claude Code's routines run on a schedule in the cloud. They agree on the shape this design has: a goal that ends, periodic check-ins decided by code rather than by the model, and reports only when there is something to say. None is reused as code because each is a product of its own around one chat channel, while here the parts (Goal, owner turn, reports, permission rules, channels) already existed.

The three desktop agent products this design is measured against, on the two questions that matter here:

| | Claude Code | Codex | DeepSeek Harness | OpenProgram |
| --- | --- | --- | --- | --- |
| Work while you are away | Routines: runs on a schedule in the cloud; no standing goal | Persistent mode: goal, status, completion criteria and the next check-in written before it sleeps; Automations run scheduled local tasks | Scheduled tasks plugin (experimental): a delay, a time, an interval of a minute or more, daily, weekly or cron with an IANA time zone; each run is an instruction delivered back into the original conversation; runs only while the app is open and cannot be paused | Always-on Agents: one standing goal per conversation, check-ins decided by code, reports only when there is something to say, delivered to channels, quiet hours |
| Seeing what is scheduled | A list of routines | A list of automations; no calendar | An automation tasks page with delivery records; no calendar | The Scheduler page: a list and a calendar (month, week, day, agenda) drawn with Schedule-X, an open-source component reused as is |

Where they agree with each other and differ from this design, the design follows them: a standing goal is one objective that ends, not a routine that repeats, which is what Codex's persistent mode and ChatGPT's task-plus-goal pairing both do. Where they are thinner than this design (no check-ins by code, no delivery to channels, no calendar), the design keeps its choice. DeepSeek Harness has no standing goal or background agent, so there is nothing of its shape to adopt.

The two reference products, feature by feature, and what carries each one here:

| Feature | Grok Bot | dots | Here |
| --- | --- | --- | --- |
| One job per assistant | Each Bot has one job | One personal assistant with a goal | `always_on.goal`: one standing goal per conversation, started as a Goal and finished by verification |
| Works on a schedule | Routines | Proactive research on a cadence | `wake_minutes`, `wake_days` and `quiet_hours`; the ticker wakes each joined conversation |
| Looks through what it knows | — | Memory, past chats and connected apps | A check-in reads with `memory_search`, `memory_get`, `read_conversation`, `open_work`, `web_search` and `web_fetch`; MCP tools stay out |
| Speaks first | Messages land in the Bot's own chat | Texts the user | `always_on_report`: the report in the conversation, the unread dot, a desktop notification, and the Agent's channel targets |
| Assistants work together | Bots message each other and hand off work | — | `handoff(to, message)` between owner conversations, with a hop limit |
| Does little on its own | Outgoing email and Slack wait as drafts for approval | Conservative, read-only defaults | `autonomy: "report"` by default; a check-in's tools are read-only; `handoff` and anything under `act` keep the conversation's permission mode and approval cards |

## Implementation status

Implemented: configuration, per-conversation wakes and state, the built-in Agents installed at server start (`builtin_agents.py`), joining by use after enabling, migration of older home conversations, check-in, reports with desktop notifications and the unread dot, channel delivery, quiet hours and wake days, handoffs between conversations with chains that survive a worker restart, ticker, HTTP, Python API, the configuration tab and the Activity panel's always-on page.

Checked on a running instance, feature by feature against the table above: a standing goal starts a Goal and later wakes report `goal_in_progress`, then `idle` once it is done; a check-in on an Agent told to always report ran with `always_on_report` as its only tool call, wrote the report and set the unread dot on a conversation nobody had open; quiet hours covering the present make `quiet_now` true and move the next wake to their end while **Wake now** still runs; a handoff reaches its target and the reply comes back. Before the screen-tool rule above, one check-in called `computer_use_agent` and paused on a Screen Recording prompt, after which every wake reported `busy` until the execution was cancelled; a paused turn still blocks wakes by design, so a check-in must never reach a tool that waits on the owner.

Not implemented:

- A dedicated cloud computer per conversation. Work runs on this machine with the conversation's working folder and sandbox.
- A handoff still waiting for a busy target, or a reply still waiting for a busy sender, when the worker restarts is not delivered; neither is a reply whose sender stays busy for ten minutes.
