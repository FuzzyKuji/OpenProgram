# Agent collaboration: branches, executions and messages

An agent can hand work to sub-agents. `agent(prompt=...)` starts a sub-agent on a new branch of the conversation — from a clean slate, from the caller's history, or from any earlier message — and either waits for its reply or runs it in the background and returns an `execution_id`. The sub-agent works with its own context and tool loop; the caller gets back only its result, as the tool result or as a completion notice when a background run ends, with the address of the full transcript if it needs more. Agents address existing branches by name with `agent(to=...)` and `send_message`, discover them with `list_agents`, read them with `read_conversation` and archive them with `archive_agent`; every run is a tracked Job with admission limits and cancellation. A sub-agent that changes code can isolate its edits in a Git worktree with the [worktree tools](../execution/agent-worktree.md).

This document defines that collaboration contract; the remaining gaps are listed in §7. The saved Agent configuration contract is maintained in [Agent configuration](../agent-configuration/agent-configuration-ui.html); admission, resource accounting and cancellation limits are maintained in [resource governance](../reliability/agent-resource-governance.html). A saved AgentSpec is reusable configuration. A runtime branch is conversation state, and one branch can execute multiple Jobs. Creating a branch does not create a new saved AgentSpec.

## 0. Shared delivery, distinct lifecycle

Collaboration reuses branch addressing, turn dispatch and the existing event layer. The operation decides whether a branch is created and whether work is submitted immediately or after inbox delivery. These choices do not imply a separate execution engine.

| Operation | Branch effect | Execution effect |
|---|---|---|
| `agent(prompt=..., start_from=...)` | Create a branch and run the supplied prompt in one call | Both admit a Job; foreground waits and returns the reply, background returns `execution_id` immediately |
| `agent(prompt=..., to=...)` | Continue an existing branch | Admit a tracked Job, then run or queue its turn; return `execution_id` |
| `send_message(message=..., to=...)` | Continue an existing branch | Deliver a message; an actual async turn still creates a Job. An inbox receipt alone does not prove execution admission |

The target completion contract returns nonempty results to the caller without requiring the recipient to call `send_message` explicitly, in the same conversation and across conversations alike. Every terminal path queues that return as a completion notice (§2.7). The recipient answers in its final reply; a `send_message` back would deliver the answer twice, so the receipt says not to. Do not interpret message delivery as a guarantee that the target model will follow the message or produce a reply.

`attach` is a stored pointer and a DAG presentation relationship for a newly created branch. It is neither a message nor a separate execution.

## 1. Four object domains and their operations

The domains distinguish objects, not mutually exclusive operations. `agent` can create a branch and submit an execution in the same call. Querying or cancelling that execution belongs to execution control; moving branch creation into a second task tool adds no capability.

| Domain | Object | Public surface | Responsibility |
|---|---|---|---|
| Planning | `todo` | `todo_create` / `todo_update` / `todo_list` | Record intended work; a checklist entry starts nothing |
| Execution | `Job` / canonical execution | `list_jobs`, `job_output`; control action `execution.cancel` | Observe or control accepted execution, including queued and terminal states |
| Conversation | Runtime Agent branch | `agent`, `list_agents`, `archive_agent` | Create/continue/address/archive branches, not the saved Agent configuration registry |
| Communication | Message | `send_message`, `read_conversation` | Deliver content or read authorized history; the triggered turn has its own execution accounting |

Background Agent calls return `execution_id`. The current runner uses `execution_id == Job.id`; the `job_output(job_id=...)` parameter and its `details.job_id` field retain that name. This is one identity, not two independent tasks. The public tools are `list_jobs` and `job_output`, not `list_tasks` or `task_output`. There is no registered `job_stop` or `task_stop` tool in the current catalog. UI/API cancellation uses the existing `execution.command` envelope with `action="execution.cancel"`, `command_id`, `execution_id`, `expected_version` and an empty `payload`; authentication and action authorization remain mandatory. See [execution control](../execution/control.html).

A branch is addressed by `"SID:HEAD"` or an unambiguous branch name. A saved `agent_id` selects configuration; it is not this branch address. The term “task” may describe work in prose, but public identifiers and tool names use the actual schemas above.

### `agent` modes and one-call fork

| Call | Behavior |
|---|---|
| `agent(prompt=...)` | Create and execute a new branch; foreground reply by default, background execution ID when requested |
| `agent(prompt=..., start_from="SID:MSG", description="review")` | Fork the exact historical node, assign a label and execute the prompt immediately |
| `agent(prompt=..., to="review")` | Submit another execution to the existing branch; no new branch or saved configuration |

With `to`, `start_from="inherit"` and `start_from="SID:MSG"` are rejected. The API's default `"clean"` is a placeholder in this mode and does not clear the target's history. `description` names a new branch; `to` always addresses an existing one. There is no need to call both modes to fork and execute:

```python
agent(prompt="Review the result from this node",
      start_from="SID:MSG", description="review",
      run_in_background=True)
```

`job_output` checks the current session/job relationship (§5.10). Cancellation uses canonical execution authorization, not a tool-name alias or knowledge of an ID. `send_message` lacks the explicit assignment semantics of `agent(to=...)`, but its execution does not bypass admission, cancellation or resource accounting merely because it began as a message.

### Reference naming

The comparison with other frameworks is maintained in [Agent collaboration comparison](agent-collab-comparison.html). It supplies design context, not a guarantee that another product exposes identical tool names or semantics. This repository's registered tools and canonical execution interface define the public names used here.

## 2. Tools and branch addressing

These entries reuse existing branches, Jobs and execution control. How a finished background agent reports back is §2.7; the remaining gaps are listed in §7.

### 2.1 The tools

The existing `agent` entry accepts `prompt`, optional `description`, `agent_id`, `start_from="clean"`, `run_in_background=False`, `to=""` and `archive_when_done=False`. `agent_id` selects a saved configuration; the configuration resolver contract is specified separately. Foreground creation calls `run_agent_turn`, which persists a Job through `spawn_job(wait=True)` and waits for its result. Background creation and existing-branch dispatch also admit Jobs. The foreground tool returns final text rather than the immediate execution-ID response; return shape does not change resource admission.

`start_from` selects a new root (`clean`), the caller's history (`inherit`), or the exact predecessor `SID:MSG`. Existence and history-read authorization must be checked before execution; §7 distinguishes current existence checks from the target shared visibility policy. Archived history may be a fork source because forking creates a new branch instead of delivering to the archived branch.

For a caller node A in session S and `start_from="T:M"`, the new branch executes in T. A background Job records `parent_session_id=T`, `parent_msg_id=M`, `caller_session_id=S`, `caller_msg_id=A`. The attach pointer itself is stored in S beside A; its payload `attach.session_id=T` and terminal `attach.head_id` identify the target result.

| Render/read operation | Identity to use |
|---|---|
| Locate the pointer card and its caller | The stored message/WS envelope's source `session_id` plus pointer ID/caller metadata |
| Load the attached result | `extra.attach.session_id` plus `extra.attach.head_id`; never search the source DAG for the target node |
| Draw same-session branch relationships | Only use local DAG edges when source and target sessions match |
| Present a cross-session attachment | Use the external-attachment card; retain source placement and target session/head references |

The UI already separates local attach relationships from external cards. Current full AttachCard navigation opens T without explicitly selecting H; the execution strip can select (T,H). The target is consistent exact-head navigation, with this difference recorded in §7. Neither attach creation nor terminal update moves the selected HEAD of S or T; a later authorized follow-up is a separate turn. The source identity is owned by the stored message/envelope, not duplicated as an independently writable target payload field. Validate both identities when projecting; reject mismatches instead of choosing one arbitrarily. See [DAG attach rendering](../dag/rendering.md).

`agent(to=...)` admits a Job for an existing branch; a busy branch queues it. The branch is resolved to its current tip, and ambiguous names fail with candidates. It creates no new attach pointer. `archive_when_done=True` is invalid with `to`; only a call that creates a branch can declare this completion policy.

`send_message(message, to, agent_id="main", notify_when_idle=False)` uses the same existing-target resolver. A direct async delivery creates a Job and returns a `delivery_id` identifying that run; a busy target first receives an inbox entry, whose delivery receipt is distinct from a later execution ID. No new branch is created. Old `to="new"` forms are invalid; creation belongs to `agent(start_from=..., prompt=...)`. Delivery and admission limits are specified in §5.1–5.2.

An explicit message carries a sender address and says that the delivery's final reply returns to the sender automatically (§2.7). A message from another conversation also says it is another agent's input, not the recipient's user: runtime authority already limits what it may do, and the note keeps the model from reading it as an instruction from its own user. An empty `message` with `notify_when_idle=True` delivers nothing: it answers at once with the target's latest reply when the target is idle, and otherwise registers one idle watch (§2.7). A missing target never silently creates a branch.

### 2.2 Referencing other branches

A message is plain text, exactly like a user message. When the target should
consider other branches, the sender writes that into `message`: quote the
conclusion directly (each branch's reply already flowed back to the sender via
reply-back), or name the branch (`SID:HEAD` or its name) and the target reads
it itself with `read_conversation`. The target model selects the amount to read,
subject to the output limits in §5.6 and read authorization in §5.9; no dedicated
aggregation parameter is added.

### 2.3 `list_agents` — discover addressable branches

```
list_agents(scope="session", limit=20, agent_id?, source?) -> str   # db.list_sessions + db.list_branches
```

`scope` picks the view: `"session"` (default) lists the current session's
branches — the agents spawned here; `"all"` widens to every session, most
recently active first, without previews; `"archived"` lists the current
session's archived branches (§2.6), which the other two scopes hide.

An agent's conversation is stored as a branch in the session DAG, so "which
agents can I talk to" = "which sessions exist, and which branches does each
one have". One call lists them all, grouped by session: each session line
carries its id, title, agent, and busy/idle status
(`run_control.is_turn_running`; omitted when the probe fails), and each
branch line carries its name (if any), a ready-to-use `to="SID:HEAD"`
address, its turn count and approximate size (`— 3 turns, ~2k chars`; sizes
under 1000 characters show as `<1k chars`), and a preview of its tip. The
size lets the model pick a sensible `max_chars` before reading the branch
with `read_conversation`. This is the entry point for "two agents seeing
each other".

A spawned agent keeps the name its `agent` call gave it (`description`) as an
address for its whole life (`addressing.agent_tips`, from the session's
spawn Jobs). Stage 2 naming (§2.4) may rename its branch, and a finished
agent's branch is retired from the tip list, yet `to="scout"` still reaches
the branch's current tip, and `list_agents` still lists it, marked
`(agent «scout»)` when the branch name differs. As in Claude Code, a finished
agent can be messaged again by the name it was spawned with.

### 2.4 New branches must have names

Every time the `agent` tool creates a branch,
**the branch must be given a name** — otherwise the web UI can only show an
8-digit hex short id and a pile of branches becomes indistinguishable.

- **Named immediately (Stage 1)**: at creation, pass a short label to
  `run_agent_turn(... label=…)` → `store.set_branch_name`. The label is taken
  from the delivered prompt (truncated to ~24 characters), or the model
  supplies a name explicitly in the call (`description`). This way a branch has a readable name
  from the moment it is created, with no wait on an LLM.
- **Renamed automatically in the background (Stage 2)**: once the branch is
  actually in conversation, `finalize_turn` fires when `turns` hits the
  thresholds `{1,6,16,40}`, and a background thread uses an LLM to generate a
  more fitting title from the branch content, overwriting the Stage 1 temporary
  name. The rules are in [branch-naming](../operations/branch-naming.md), which
  defines the naming tiers, locks, and trigger points. This section only
  stresses one thing: **branches spawned by the agent tool and branches the user
  forks by hand use the same naming path (both get a Stage 1 placeholder name
  plus Stage 2 automatic renaming); neither may be skipped.**

### 2.5 Reply placement: the initiator's current HEAD, serialized

For the asynchronous reply-back, `_dispatch_followup` submits the
notice for one or more finished jobs to the delivery session as a
**synthetic user-role turn** (`source="job_followup"`); §2.7 says when. **Key rule: the reply-back `TurnRequest` leaves `branch_from` unset
(INHERIT_PARENT) — the dispatcher resolves it to the delivery session's
current HEAD and advances it.** A per-delivery-session follow-up lock
(`JobRunner._followup_lock`) serialises concurrent completions, so N
sub-tasks finishing produce one serial chain
`… → notice₁ → answer₁ → notice₂ → answer₂` — each follow-up reads a HEAD
that already contains the previous answer.

The reply does not use the spawn node (`caller_msg_id`) as its predecessor:
with N parallel subtasks forked from one turn, every reply would otherwise
create a sibling under that node, answering the initiating user message N
times on N branches. Using the current HEAD serializes all N completions on
one conversation branch.

The **attach pointer** written at spawn time retains
`predecessor = caller_msg_id`, so the DAG preserves the initiating turn and
source branch of each result. The sub-branch stays independent and **does not
merge into the initiator's branch**.

For a cross-session spawn, the pointer remains in the initiator's session but
references the target `(session_id, head_id)`. Terminal finalisation reads the
target branch and its ContextCommit in the target session, then patches the
card in the initiator's session. The source-side initiating node is marked
`spawn_out`; the target-side first `agent_spawn` user node records
`caller=<source node>` plus `metadata.spawned_from_session=<source session>`
and is projected as `spawn_remote`. Because the source session has a real
attach pointer, its asynchronous follow-up consumes the result through the
attach report (§2.7) rather than duplicating the reply inline. `send_message` and
`agent(to=...)` create no branch and no attach pointer, so their replies remain
inline and receive neither spawn marker.

### 2.6 Archiving: a global branch state

Archiving writes `archived: true` to the target branch's metadata. It is global within that local state store, not a caller-to-target visibility relation. If A archives B, C's subsequent `list_agents(scope="session"/"all")` also omits B. `scope="archived"` explicitly lists archived branch records. Existing history is retained; archive is not data deletion or storage compaction.

“One-way” refers only to the state transition: the current toolset has no unarchive operation. It does not mean “hidden for the caller only.” Reusing archived history is a new `agent(start_from="SID:MSG", prompt=...)` call with a distinct branch lifecycle. A branch left idle but never archived can still appear; explicit/manual completion policy, not caller-specific filtering, decides that state.

| Operation on an archived branch | Contract |
|---|---|
| Normal `list_agents` views | Hidden for every caller using the same store |
| `scope="archived"` | Visible in the archive view, including archived records whose heads were merged |
| New `send_message` / `agent(to=...)` | Refused by the shared existing-target resolver |
| Already running execution | Continues; archive does not cancel it |
| `read_conversation` / historical fork | Permitted only under the applicable history visibility policy; archive itself is not an access grant |

Merging and archiving remain separate: a merged branch may leave the live-tip list without being marked archived. The archive view reads stored branch records; a merged head must resolve to its own branch when archiving, not to the branch that absorbed it.

Two entry points share the target archive state:

- `archive_agent(to, reason="")` archives an existing branch. Repeating the manual operation is idempotent. The current implementation allows any local session with the tool capability to archive another branch and does not impose a creator-only check; this is a shared local trust boundary, not multi-user isolation. The target lifecycle action must use the same scoped authorization framework as other branch operations.
- `agent(archive_when_done=True)` declares a terminal archive policy only for a branch created by that call. It is invalid with `to`. The synchronous path writes the flag in the tool; the asynchronous path writes it from the terminal hook in §2.7.

If manual archiving happens first, the executing Job is not cancelled and terminal handling never reopens the branch. The target shared archive operation preserves the first `archived_at` and an explicit manual reason; a later automatic request may fill missing fields but not overwrite them. The asynchronous terminal hook leaves an already archived branch untouched; the synchronous tool-local write can still refresh the timestamp. Failure to persist automatic archive is reported separately from the execution result and must not turn a successful result into a failure. Accepted-but-not-started deliveries recheck the target archive state before starting; rejecting them terminates their Job/receipt with an explicit reason rather than silently losing it.

### 2.7 Completion notices, idle watches and the attach report

A background job — `agent(run_in_background=True)`, `agent(to=...)` or a
`send_message` delivery — that completes or fails tells the conversation that
sent it, in the style of Claude Code's background-task notifications
(`openprogram/runtime/jobs/notices.py`):

- **Queueing.** Every terminal path passes through
  `JobRunner._update_attach_card`, which patches the card, applies
  `archive_when_done`, and then queues a notice entry in the delivery
  session's `notices.json` (`caller_session_id or parent_session_id`). Only
  `wait=False` jobs that completed or errored qualify: a waited-on job already
  returned its result, and a cancelled one was stopped on purpose. The file
  also remembers the last 500 settled job ids, so a second terminal
  projection of the same job cannot notify twice.
- **Consumption.** `job_output` on a terminal job settles its entry: the caller
  already has the result, and the notice would only repeat it. A
  `send_message` delivery result names `job_output` as the way to wait for
  the reply in-turn, so a sender that needs it now does not poll the target.
  An idle `notify_when_idle` watch answers with the target node's reply and
  settles the entries of finished jobs that ended on that node
  (`notices.consume_reply`).
- **Delivery.** The worker loop `run_job_notices` (started in the server
  lifespan beside the process-exit notices) sweeps every 2 s. A session is
  busy while any of its nonterminal executions is not a background job, and
  while the agent that dispatched a pending job is still running (it may still
  read the result itself). Background agents running in the same session do
  not count, so a conversation waiting on three agents hears from each as it
  ends. Everything pending in an idle session goes into **one** notice turn.
- **Text.** The notice says it is automated, not a message from the user. Per
  job it names the agent, its outcome, the job id and the task; a spawn's
  report is already in context through its attach pointer, while a delivery
  to an existing branch carries the reply inline (capped at 20,000 characters)
  plus the `send_message` address to continue with it.
- **Idle watch.** `send_message(to=..., message="", notify_when_idle=True)`
  queues a watch entry in the sender's `notices.json`. When the target is no
  longer busy (`inbox.target_busy`, §5.4), the watch becomes one notice
  carrying the target's latest reply and is settled.

**Attach report.** The caller's context does not receive a sub-agent's
transcript. For a spawn pointer — any attach pointer that is not a merge
(`is_base` / `merge_temp`) or a user's manual attach (`manual`) — the context
commit generator emits one user-role item (`reason="attached_report"`): the
task, the final reply (the pointer's `content`) and the
`read_conversation(session_id, head_id)` address of the full transcript. A
synchronous spawn already returned its reply as the `agent` tool result, so
its pointer (`delivery="tool_result"`) carries only the address. Merges and
manual attaches keep the full, delimited expansion described in
[context overview §4](../../context/overview.md).

## 3. What collaboration looks like while it happens

Collaboration runs on the framework's shared event layer, so it is visible
live rather than only in hindsight. Four effects follow from that, and they
are the whole of what a user or an agent needs to know about it:

- **Both sides update in real time.** A message delivered to another
  session appears in that session's UI as it lands, and the reply appears in
  the sender's UI when it comes back. Neither side has to reload.
- **Agent traffic reads as rows, not as user bubbles.** Nothing an agent
  sends looks like something the user typed. In the sender's chat the send
  is the tool's own row ("Sent to …"). A completion notice draws one line
  per finished agent — "*scout* finished; its report went back to the
  agent", "Branch “frontend” replied", "Branch “frontend” is idle" — from
  the `notice` items `notice_items` stamps on the notice's user message;
  opening a line shows the reply (or, for a report, the task it was given).
  In the receiving branch a delivered message is one line named after its
  sender ("Message from the main conversation"), read from the receipt
  header `[message|task from SID:HEAD (sender)]`. The sender is a
  background agent's name when one of its jobs sends, else the main
  conversation, named by its title when the receiver is another
  conversation. A delivery's job is named after the target branch, so the
  reply line says which branch answered.
- **Everything is on the record.** Deliveries, branch state changes and
  listings are written to the session's event log
  (`~/.openprogram/projects/<project-id>/chats/<sid>/events.jsonl`, always on), so a
  collaboration can be replayed and audited after the fact.
- **A delivery can be held for confirmation.** Under an unattended policy
  that denies side effects, `send_message` is stopped before it delivers and
  waits for approval. Sub-agents are held by the same gate, and
  `permission_mode=bypass` does not turn it off.

The event layer itself — the bus, the event model, the registry, the veto
protocol — is documented in
[proactive/event-layer](../../proactive/event-layer.md).


## 4. End-to-end target sequence

1. Resolve an existing visible target from `list_agents` or an explicit authorized address.
2. Submit `send_message` or `agent(to=...)`. Acknowledge inbox receipt separately from Job admission; a rejected admission returns its reason without claiming work started.
3. Run the target turn under its configured context, resource limits and execution authority. A busy target follows the shared serialization/queue policy; the sender need not block.
4. For an admitted managed execution, commit terminal result and attach state first. The target completion policy schedules at most one idempotent nonempty follow-up to the caller; failure or empty output must not create an unbounded reply cycle.
5. Read the result via authorized `job_output`/execution resources even when delegation allowance is exhausted. New dispatches recheck topology, resource, archive and authorization constraints.

Automatic follow-up wiring is a required public-entry acceptance item, not proven by a test that calls the helper directly.

## 5. Robustness and safety

Communication creates branches, triggers other branches to run, and writes
across sessions. Those side effects need boundaries.

### 5.1 Topology limits and exact exhaustion behavior

Depth, message count and fan-out constrain collaboration topology. They are not token budgets, aggregate session admission counts or permissions. [Resource governance](../reliability/agent-resource-governance.html) owns the separate live/queue/cumulative and token/cost/runtime/idle constraints.

| Limit | Current setting / default | Scope and accounting |
|---|---|---|
| Spawn depth | `agent.max_spawn_depth=1` | Generation along a lineage path; only a newly created branch increases it |
| Messages | `agent.max_messages=8` | Message depth along a lineage path; a delivery passes sender count + 1 to its target, without incrementing the sender's sibling calls |
| Fan-out | `agent.max_spawn_fanout=8` | New branches per caller `(session, turn)`; existing-branch dispatch and messages do not spend it |

A topology setting of `0` disables that check; propagated context counters may still exist. Resource limits have different syntax: `null` means unset/inherit and a configured numeric value must be positive. Do not transfer the topology convention `0=unlimited` to the resource schema.

The follow-up binds the completed Job's `chain_messages` unchanged (the largest one when several jobs share a notice) and restores `caller_chain_generations`; it does not add another message or generation for reading the result. Thus the message setting is not a shared quota counting all branches' traffic. Fan-out and session admission counts constrain sibling/cumulative work separately.

| Attempt when a limit is exhausted | Required behavior |
|---|---|
| New branch with exhausted message, depth or fan-out allowance | Reject this creation with its reason; no new branch/Job from the rejected attempt |
| `agent(to=B)` or `send_message(to=B)` with exhausted message allowance | Reject this delivery even though no branch is created; depth/fan-out alone do not block it |
| Existing Job, caller's current turn, local nondelegation tools | Do not automatically cancel them merely because a topology count reached its limit |
| `job_output`, execution snapshots or `execution.cancel` | Remain available under their normal authorization; observation and stopping work consume no delegation allowance |

Current `agent`/`send_message` admission checks enforce the new-delivery limits. `job_output` remains available after message exhaustion and retains its normal session and ancestor ownership checks. Reading a result does not spend a message or create a delivery. There is no registered `job_stop` tool; UI/API cancellation uses the existing `execution.cancel` command.

A spawn consumes message depth and generation, plus caller-turn fan-out. Existing-branch dispatch consumes only message depth among these three, but still admits a new execution under §5.2. A later independent user turn gets its own topology context; accepted Jobs continue to count in the session's cumulative resource total. Direct self-delivery is independently rejected.

The reference comparisons for the chosen defaults remain in [collaboration comparison](agent-collab-comparison.html); current enforcement follows the source and schema above rather than an assumed equivalence to another product.

### 5.2 Live, queued and cumulative execution resources

Resource checks apply in addition to §5.1, not as alternative names for its counters.

| Resource limit | Accounting | At the boundary |
|---|---|---|
| `max_live_per_session` and `OPENPROGRAM_JOB_WORKERS` | Active execution in the target session / global worker capacity | An admitted Job waits queued while no execution capacity is available |
| `max_queued_per_session` | Accepted execution waiting for capacity | A full queue rejects admission with `quota.queue_full`, normally retryable; no Job is fabricated |
| `max_jobs_per_session` | Cumulative successful Job admissions in the target session, including later terminal Jobs | Reject with `quota.jobs_exhausted`; terminal completion does not refund the count |
| token / cost / runtime / idle | Governed execution and inherited budget scopes | Apply the resource-governance reservation, cancellation and accounting contract |

The current governor attributes these session counters to `Job.parent_session_id`, the session in which the execution runs. For a cross-session call S→T, that is T; `caller_session_id=S` identifies the caller and does not silently move the admission charge to S. Caller-turn fan-out and parent budget scopes remain separate constraints. `max_jobs_per_session` therefore is not a renamed depth or fan-out budget.

Background creation, `agent(to=...)` and actual async turns triggered by `send_message` all reach Job admission. A busy `agent(to=...)` already has an admitted Job before its inbox wait; a busy ordinary message can have only a delivery receipt until its turn is submitted. Do not display that receipt as accepted execution or consume a second cumulative admission when an existing queued Job starts.

Foreground branch creation also admits a Job through `run_agent_turn` → `spawn_job(wait=True)` and therefore participates in Job resource limits. Ordinary main chat and other direct runtime entry points must be assessed separately; the name “foreground” alone does not determine accounting.

Setting the topology limits to zero does not disable resource governance or cancellation. “Spawn 30 Jobs and they all queue” is not a universal guarantee: fan-out or queue/cumulative limits can reject requests before capacity queueing.

### 5.3 Cancellation propagation

Use the existing canonical execution cancellation path and `parent_job_id` lineage. Parent cancellation must prevent unstarted descendants from running, request cancellation of active descendants, and preserve stopping state until actual exit is acknowledged. Queued-work withdrawal must not issue a session-wide stop that interrupts another execution. A terminal Job remains queryable and its cumulative admission is not refunded.

The user-visible distinction is requested cancellation versus confirmed termination. Resource release, worker loss, non-preemptible operations and reconciliation follow [resource governance](../reliability/agent-resource-governance.html); a fixed watchdog timeout alone is not proof that a thread or subprocess exited. Session-wide Stop has broader scope than cancelling one addressed execution, and inbox withdrawals must leave an explicit delivery outcome.

### 5.4 Sending to a branch that is "already running" (race)

When A messages B, B may be mid-turn. **Do not interrupt, do not drop — queue.**
The busy check is `inbox.target_busy(target_session, head, sender_session)`:

- **Cross-session target**: `run_control.is_turn_running(target)` — every
  concurrent turn entry point (webui chat, task runner workers) registers its
  cancel token in `execution/run_control/tokens.py` (`_current_tokens`) and unregisters it in a
  finally block, so presence there is the authoritative in-process "a turn is
  running" signal. The entry is queued with `scope="session"`.
- **Same-session target**: the sender's own turn always holds that session's
  token, so only the addressed branch counts — `inbox.branch_busy` is true
  while an unfinished job's `target_branch_head_id`, `head_id` or
  `parent_msg_id` is the branch tip. The entry is queued with
  `scope="branch"` and later continues that branch's current tip, never the
  session's main head.

- **Queueing**: a busy target's message is persisted to the target session's
  inbox (`<session-repo>/inbox.json`, `openprogram/runtime/conversation/inbox.py` — same
  placement pattern as `jobs.json`), recording the delivery body, sender
  `SID:HEAD`, sender agent, the chain's message count at send time, and
  enqueue time. The sender immediately gets back "target busy, message
  queued, processed when its current turn ends".
- **Draining**: `inbox.drain` delivers each entry whose target is free now
  (session scope: no running turn; branch scope: the branch is no longer
  busy) as one async turn through the normal async execution path, and the
  reply returns as a completion notice (§2.7). It runs at turn end
  (`_process_turn_once` → `_drain_send_message_inbox`, on both the success
  and the error return) and from the worker sweep every 2 s, which also
  catches a turn that ended without draining (cancelled, crashed, worker
  restart). Entries the turn end found not yet ready wait for the sweep. Delivery-then-delete: an entry is
  removed only after its delivery turn was submitted — a crash between the two
  may re-deliver (acceptable); the reverse order could lose a message (not
  acceptable). A queued hop spends the message budget exactly like a direct
  one (§5.1).
- **Limits**: at most 50 pending entries per target — a full inbox drops
  the oldest and leaves a system notice in the dropped message's sender
  session; an identical message from the same sender within 60s of a
  still-queued copy is rejected as a duplicate, and the sender is told
  so. 50 is Claude Code's number for the same structure, a 50-entry ring
  that drops the oldest, and it is the only reference implementation
  with a mailbox to compare against. The 60s window has no equivalent
  anywhere: Claude Code dedups by message uuid and weclaw by inbound
  message id, both of which only catch a byte-identical retransmission
  of one message object and never a model that composed the same text
  twice. The check fires only against entries that are still queued, so
  the window bounds one thing, how long a sender waits before the same
  text counts as a deliberate resend instead of a retry loop.

If B is idle, delivery is immediate (the pre-queue behavior).

### 5.5 Failure reply-back

If the sub/target branch fails (crash / timeout / model error), **it still
replies back**, with `is_error` and the reason in the content ("B failed:
<reason>"), and the caller's model decides for itself whether to resend, reroute,
or give up. **No automatic task resubmission is implied.** A new dispatch requires the normal authorization and remaining limits; provider transport retries retain their existing independent policy.

### 5.6 Result truncation and persisted full text

The current generic string/`ToolReturn` normalizer defaults to 30,000 characters, may reduce the effective cap for context capacity, retains a head/tail excerpt, and optionally writes the full UTF-8 result under `<state_dir>/tool_results/` with an opaque, independently created `.txt` filename derived from existing ownership plus an exclusive suffix. Raw provider call IDs may recur; a new save does not overwrite a file referenced by an earlier receipt. Existing receipt paths remain readable without rewriting legacy files. The default profile resolves this to `~/.openprogram/tool_results/...`; it is a state-directory file, not an OS temporary file. Its path is reported only after a successful write. A write failure must not fabricate a path.

This is not currently a universal guarantee for Job results: `job_output` returns `AgentToolResult`, which the shared normalizer passes through without applying its cap; the follow-up helper can also inline full `result_text`. No automatic TTL/garbage collection or target-session ACL for these files is established by the inspected helper.

The target result contract applies one bounded excerpt to `job_output` and inline follow-up, while retaining the canonical result in the execution/session store. A full-text artifact records execution ID, owning session/project, media type, byte length and content hash; reads use the same visibility checks as the result. Generic filesystem access is not made private merely by omitting its path. Artifact retention follows the owning execution's configured retention; archive alone does not delete it. Until that resource/retention integration exists, report the present path and unknown lifetime without claiming automatic expiry or isolation. Tests must cover cap application to structured results, write failure, authorized reread and retained-file cleanup.

### 5.7 Configuration, context and authority

`agent_id` selects saved execution configuration, independently of branch identity. The saved/inline override and model-selection design is defined in [Agent configuration](../agent-configuration/agent-configuration-ui.html); selecting another configuration cannot expand the caller's enforced authority. `clean` omits inherited conversation messages, while `inherit` and an exact `SID:MSG` include only authorized chosen history. None of these modes removes system policy or establishes filesystem isolation. Do not describe every child as seeing only its prompt when the caller explicitly selected historical context.

### 5.8 Unattended interception + validation

- Under an unattended policy that denies side effects, `send_message` is held
  for confirmation before it delivers (§3). Sub-branches are held by the same
  gate, which `permission_mode=bypass` does not turn off.
- A `to` that names nothing is an error, never a silent creation. The regular
  permission gating applies on top.

### 5.9 History visibility and archive authority

The target shared visibility policy covers `read_conversation`, source history for `start_from`, selected context, attach expansion and result-artifact reads. Validate the caller's principal and project/session scope before loading content. Branch addresses, saved `agent_id` and tool availability alone are not access grants; denied targets must not expose preview, titles or existence through fallback reads. Archiving requires the corresponding lifecycle permission and affects the globally stored branch state (§2.6).

Current `read_conversation` resolves a session/head and reads that branch from the local store without a target-level owner/project ACL. Tool capability gating is therefore a broad local trust boundary, not per-Agent privacy. Existing history-read and archive tools must integrate the shared authorization before isolated-Agent or cross-user privacy is claimed. An “internal” branch presentation flag controls UI listing only; it is not an authorization boundary and does not prevent `agent(to=...)` from addressing an otherwise accessible branch.

### 5.10 Result ownership and execution control

Current `job_output` uses `_ownership.check_job_ownership`: a session matching the Job's execution session (`parent_session_id`), caller session, or an ancestor relation may read it. The helper walks at most 64 ancestors with cycle protection. With no current session context it returns no denial; that helper alone does not authenticate a user or an API request.

Canonical execution read/control authorization is a separate existing boundary: validate owner authority, target project/session membership, action grants and the required capability (`runtime.control` for control). `execution.cancel` uses the current execution version and a command ID; it is not a `job_stop` alias. Knowing an execution ID does not grant authority. The target history policy in §5.9 reuses this authorization framework instead of assuming all local branch readers are execution owners.

Cancellation follows [execution control](../execution/control.html) and [resource governance](../reliability/agent-resource-governance.html). Queued cancellation prevents starting that execution without stopping an unrelated turn on the same target. Running cancellation moves through stopping and releases resources only after confirmed exit; terminal cancellation is idempotent. Do not promise that any Python thread disappears immediately or that accepting a cancel request proves completion.

### 5.11 Explicitly out of scope (and why)

- **An extra parentID field**: `(session_id, head_id)` plus caller/predecessor
  already forms the tree and the DAG already draws it, so no redundant field.
- **ID prefix classification** (fork_/msg_): existing id + name are enough for
  addressing, so no.
- **Retry / circuit-breaker policy**: failures are replied back to the model and
  the model decides; no fixed built-in policy (see §5.5).
- **Built-in aggregation functions** (voting, all-succeeded, etc.): synthesis
  means naming the branches in `message` and letting the target model read and
  synthesize them (§2.2). A model synthesizing is more flexible than a preset
  aggregation, so no fixed aggregation operators.


## 6. Public-entry acceptance

These are required observations, not a claim that all cases have already passed.

| Case | Observable result |
|---|---|
| C1 Names and identity | Registered tools are `list_jobs`/`job_output`; foreground and background both admit a Job; canonical cancellation uses the versioned execution command |
| C2 Fork and run | One `agent(start_from="T:M", prompt=..., description=...)` call creates a branch at M and executes its prompt; `to` does not create missing targets |
| C3 Global archive | After A archives B, C's normal list omits B; archive view retains it and new deliveries fail; history retention does not imply permission to read |
| C4 Completion archive | Manual-before-terminal, terminal-before-manual and retries preserve the first archive timestamp/manual reason; active work is not cancelled by archive; async public completion actually executes archive policy |
| C5 Topology exhaustion | Exhausted messages reject `agent(to=B)` without cancelling accepted work; exhausted depth/fan-out reject only branch creation; observation and cancellation remain authorized and available |
| C6 Resource interaction | Cross-session runs charge target admission; queue-full and cumulative-full report distinct errors; existing queued Jobs do not count twice; synchronous Agent runs obey admission too |
| C7 Attach location | The card remains in S, while result lookup uses (T,H); both full AttachCard and execution strip select the exact target head without searching S for H |
| C8 History privacy | Denied `read_conversation`, historical fork, selected context and attach expansion do not expose target content or metadata; permitted equivalents still work |
| C9 Full result | Structured Job results and inline follow-up are capped, full text can be reread only with authorization, storage failure produces no false path, retention removes only owned eligible artifacts |
| C10 Completion notifications | Calling the public async Agent/message entry reaches canonical completion and emits the intended follow-up once; empty results, retry, error and cancellation do not generate endless follow-up turns |

## 7. Implementation status and evidence

The table records what the source implements today and what still needs acceptance through the public tool entries. Helper-level tests or source definitions alone do not prove public-entry integration; resource gates are governed by the linked resource design.

| Area | Source-observed state | Remaining acceptance |
|---|---|---|
| Names / foreground admission | Registered `list_jobs` and `job_output`; both synchronous `run_agent_turn` and async wrappers call Job admission | Keep tool, UI and docs schema names aligned; no reintroduction of retired stop aliases |
| Fork / global archive | One-call historical fork and globally stored archive flag are present | Preserve first archive metadata across manual/automatic writes; verify queued delivery recheck |
| Async follow-up and auto-archive | Every terminal path calls `_update_attach_card`, which applies `archive_when_done` (keeping a first manual `archived_at`) and queues the completion notice; the server worker delivers notices and idle watches (§2.7). Unit tests cover queueing, consumption, coalescing, busy rules and watches | End-to-end acceptance through the public tool entries in a running worker |
| Mid-turn delivery | A message to a busy agent waits for its turn to end; it is not injected between the running turn's tool calls | Steering an agent message into a running execution needs a non-user actor on the execution command path |
| Message exhaustion | New delegation is gated; `job_output` is also hidden by the same gate | Preserve authorized result/control access at exhausted delegation allowance |
| History visibility | `read_conversation` reads the local store without target-level owner/project ACL | Integrate shared visibility and verify all history-consuming entries |
| Cross-session attach | Source placement and target lookup are separate in the data/UI; full-card navigation does not explicitly select H | Align exact-head navigation with execution strip and test both |
| Result truncation | Generic string wrapper persists full text; structured Job output and inline follow-up are not uniformly capped | Unified cap, authorized artifacts and explicit retention integration |

Source evidence:

- [Agent tool](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/agent/agent/agent.py)
- [Synchronous and asynchronous admission](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/conversation/sub_agent_run.py)
- [Archive](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/send_message/archive_agent/archive_agent.py)
- [Message delivery](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/send_message/send_message/send_message.py)
- [Job output](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/agent/job_output/job_output.py)
- [History read](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/knowledge/read_conversation.py)
- [Execution authorization](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/execution/authorization.py)
- [Completion helpers](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/jobs/runner/progress.py)
- [Canonical completion](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/jobs/runner/dispatch.py)
- [Borrowed-claim completion](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/jobs/runner/borrowed.py)
- [Result persistence](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/_host/execution.py)
