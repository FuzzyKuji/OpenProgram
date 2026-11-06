# Runtime

Agent execution runtime — the run loop, worktrees, async tasks, streaming/resume, the DAG model, and revert layers.

For API usage, see [Runtime API](../../api/runtime.md). The following sections explain the runtime contracts and their design choices.

## Package layout

`openprogram/runtime/` is split by concept. Each package answers one question:

| Package | What it is |
| --- | --- |
| `agent/` | One model call. The `Agent` class and how it uses a `Context`, the `agent()` and `llm()` functions, the tool loop (`loop/`: `loop.py`, `LoopDriver` in `driver.py`, `AgentSession`, tool and event types, retry), and `Runtime`. This is the code of Agentic Programming. |
| `conversation/` | Chats and their turns, built on `Agent`: `turn_runtime/` runs one turn, `chat.py` is `ChatAgent`, `production_driver/` drives a turn as a canonical execution, `run_control/` tracks the running turn, plus session settings, inbox, open work, rewind and always-on agents. |
| `jobs/` | Background runs: the job store, the runner pool, and `resource_governance/` (admission and limits). |
| `agent_registry/` | Saved Agent configurations: which Agents exist, their model, tools and workspace. |
| `permissions/` | What a tool call may do: policy, approval, audit, `authority` (who is asking) and `attended` mode (no questions when nobody is watching). |
| `context/` | The `Context` class (`model.py`) and everything that decides what the model sees: rendering, compaction, the system prompt, `session_db.py`. |
| `execution/` | The control plane for pause, cancel and recovery: the execution store, revisions, waits and checkpoints. |
| `events/` | The event bus. |
| `scheduler/`, `proactive/`, `commands/` | Timed runs, proactive policies and slash commands. |

Dependencies point one way: the features (`conversation`, `jobs`, `agent_registry`,
`scheduler`, `proactive`, `commands`) build on `agent`, and `agent` builds on
`context`, `permissions`, `events` and `execution`. `execution`, `context`,
`permissions` and `events` do not import `agent`.
`tests/contracts/repository/test_runtime_layering.py` checks these directions;
the imports that break them today are a frozen list that may only shrink.
`context` and `permissions` already keep these directions in full. When a lower
package needs something only a higher one knows, the higher one registers it on
import: `conversation/context_registration.py` adds the `open_work` system-prompt
section and the Agent profile loader for context breakdowns, and
`conversation/permission_registration.py` supplies the session and turn facts
that `permissions/session_facts.py` reads. Task-local call state that `Context`
reads (`_call_id`, the workflow call site) lives in `context/scope.py`, and the
call core imports it from there.

`agent` never imports a feature package. What the call core needs from the
engine above it goes through one registration port,
`openprogram/runtime/agent/engine_link.py`: running a persistent turn or a
saved continuation (`Agent.run_turn` / `resume_turn`) and the Agent profile it
starts from, a saved Agent's tools, binding the pre-approved question wait of
a resumed tool call, whether the worker is stopping, the running background
job's activity and operation timeout, and the runtime contract a resumable
tool loop checkpoints. What sits beside or below the core is imported
directly and behaves the same with or without a registered engine: the bound
session and execution, nested-call admission and terminal marking
(`execution/run_control/`), approval gating
(`permissions.approval.wrap_with_approval`) and the pre-approved wait id
(`permissions.session_facts`).
`conversation/engine_registration.py` implements the port and registers it
when `openprogram.runtime.conversation` is imported; the worker and the Server
import it at start. With nothing registered the core behaves as a plain
library: the worker is not stopping, no background job runs, and
`Agent.run_turn` raises `EngineUnavailable`. `TurnRequest` and the request in
force (`agent/turn_request.py`) are call-core types the engine builds and
binds, and callers import them from there. A module exports only the names
it owns: the execution binding names come from
`openprogram.runtime.execution.run_control`, the permission vocabulary from
`permissions/modes.py`, the tool contract (`AgentTool`, `AgentToolResult`)
from `openprogram.models.providers.types`, and the call-scope ContextVars from
`context/scope.py`; `tests/contracts/repository/test_no_transitional_reexports.py`
keeps the moved names from coming back. Importing `openprogram.runtime.conversation`
also imports `conversation/run_control`, which claims the core's cancellation
check. `process_runner.py`, which
runs a turn's Agent method tools in a subprocess, is engine code and lives in
`conversation/`.

![Runtime packages by concept](execution/agent-code-structure.svg)

<div id="runtime-design-rationale"></div>

## 1 runtime = 1 session

Each `Runtime` instance is bound to one provider session, with a 1:1 lifecycle:

```
create_runtime()      = open session
runtime.exec()        = send one request within the session
runtime.close()       = close session
```

There is no `reset()` / `new_session()`; to get a new session, call `create_runtime()` again.

**Why not let one Runtime reuse multiple sessions?**

- For CLI providers (Claude Code / Codex / Gemini CLI), session state lives in the subprocess.
  Reusing would require hanging mutable state like "which session id is current" on the Runtime, introducing concurrency races.
- API providers are themselves stateless; doing "multiple sessions" is just an upper-layer dict, equivalent to "multiple Runtimes" —
  no new capability.
- ContextVar auto-injection (next item) relies on the simple model of "the runtime is bound to the current function tree";
  multiple sessions would complicate the injection semantics.

The cost: a user who wants to run two independent conversations has to manage two runtime objects. This is acceptable, because such scenarios are rare.

## ContextVar auto-injects the runtime

The Agent method execution reads the `_current_runtime` ContextVar; if the current function
was not passed a `runtime=` argument, it uses that. If the entry function has none either, it automatically calls `create_runtime()`.

**Why not have functions declare the runtime explicitly?**

With explicit declaration, every agentic function would have to add `runtime: Runtime` to its signature,
and every nested call would have to explicitly pass `runtime=runtime` through — pure plumbing
boilerplate unrelated to the function logic. ContextVar hides it away: a child function naturally inherits its parent's
runtime, one is created automatically at the entry point, and it is closed automatically at exit.

**Why not use a module-level singleton?**

A singleton is shared across threads / coroutines, so two concurrent agents would step on each other's session state.
ContextVar is isolated per thread + coroutine, making it naturally concurrency-safe.

## Session-provider and API-provider share one abstraction

Whether the backend is the Claude Code CLI (has a session) or the Anthropic API (no session),
`Agent` method authors see the same interface, `llm(...)` / `agent(...)`, both of which end in `runtime.exec`.
The framework uses the `has_session` attribute to distinguish the two provider classes and take different internal paths:

| | session provider (CLI) | API provider |
|---|---|---|
| Conversation memory | managed by the subprocess itself | none; each exec is independent |
| Context injection | skips DAG render, sends only the docstring + the current content | assembles history from the DAG via `render_context` + `render_dag_messages` |
| `render_range.subcalls` | no effect (the session remembers the conversation itself) | takes effect (used to bound the window of injected history) |

**Why not split into two separate Runtime classes?**

When writing `paper_agent`, the author should not care which kind of provider the backend is. Forcing a split would require two
implementations per function, violating the layering of "functions describe the task, providers describe the execution channel." The cost of the shared abstraction is
the single `has_session` conditional branch — worth it.

## Retry lives in the runtime layer, not the provider layer

`exec()` / `async_exec()` have a built-in `max_retries`, defaulting to 2, so any provider
gets retries.

**Why not add retry to each provider class separately?**

- The retry policy is consistent across all providers (network timeout / rate limit / 5xx); no need to duplicate it
- Failure reports have a uniform format (`Attempt N: ErrorType: msg`), which aids debugging
- Programming errors like `TypeError` / `NotImplementedError` are uniformly not retried (only the
  runtime layer knows "this is a provider implementation bug, retrying won't help")

The provider layer only cares about "send the request out, get the reply back." Cross-cutting concerns like retry / throttling / caching
all live in the runtime.

## DAG writes: entering and exiting a function both write a code node, exec writes an llm node

```
enter Agent method       → write a code node (status=running)
                              → set the _call_id ContextVar to point at this node
runtime.exec() in the body    → write an llm node under the current _call_id
                              → the node's caller = _call_id
exit the function (return / except) → backfill the same code node's output / status
```

When `expose="hidden"`, the code node write is skipped (but a phantom `_call_id`
is still set, so that LLM calls inside the function body have a frame to reference).

**Why not write a single completed-state node only on exit?**

- While the function is still running, the webui visualizer needs to immediately show "it's running" (display a spinner)
- On an exceptional exit there must also be a node present (so the error information can be recorded)

Writing twice (entry + exit backfill) suits real-time observability better than writing once (on completion).

## Embedding seams

The core runs embedded in a host that is not OpenProgram — somebody else's
service or agent framework using `Agent` method + the execution DAG as a
component (see
[Embedding in your own stack](../../../capabilities/agentic-programming/embedding-in-your-own-stack.md)).
The contract, executed by `tests/component/runtime/test_standalone_embed.py` rather than
stated in prose only:

- **The library face never imports a UI surface.** `import openprogram` and a
  full `Runtime(call=...).exec()` round trip must not pull in `webui`, FastAPI,
  Uvicorn or Textual.
- **No implicit state paths.** With `SessionStore(root_path=...)` +
  `session_scope(store, session_id)` the run never consults
  `openprogram.state.paths` (`~/.openprogram`); with no store bound it runs and
  persists nothing.

Where the platform needs to reach into the core, the direction is inverted
into registration hooks, mirroring `add_pre_invocation_hook`:

| Seam | Core default | Platform registration |
|---|---|---|
| `set_cancellation_check` (`openprogram.host.cancellation`) | no-op — nothing cancels | `openprogram.runtime.conversation.run_control` registers the exact execution check at import |
| `set_session_id_provider` | `None` — `runtime.can_ask()` is `False` | `openprogram.runtime.conversation.run_control` provides the active session id |
| `session_scope(store, id)` | unset — no persistence | the dispatcher binds the per-turn store itself |

**Why hooks instead of a web UI cancellation module?** The previous
session-scoped module duplicated cancellation state and made the core depend
on the Web UI. The hook keeps the dependency one-way while `run_control`
checks the exact execution token.

**`ImportError` during `exec()` is permanent, not transient.** The retry loop
classifies it as non-retryable: a missing subsystem does not appear by
retrying, and burning the full backoff schedule turned a 0-second failure into
a ~52-second one.

## Related implementation files

- `openprogram/runtime/agent/runtime/` — Runtime base class, `exec` / `_call` protocol, retry loop
- `openprogram/runtime/agent/call_state.py` — decorator / `_inject_runtime` / `_call_id` / `_current_runtime` ContextVar
- `openprogram/models/providers/catalog/registry.py` — `detect_provider` auto-detection and the built-in `PROVIDERS` table
- `openprogram/runtime/agent/runtime/factory.py` — `create_runtime`, which builds a Runtime from that detection
- `openprogram/runtime/agent/provider_runtimes/` — the dedicated Runtime subclasses of the subscription / CLI-credential providers (`openai_codex.py`, `google_gemini_cli.py`) and the `PROVIDER_RUNTIMES` table `create_runtime` reads; every other provider runs on the base Runtime. The provider packages under `openprogram/models/providers/adapters/<vendor>/` hold only the model, auth and wire code
- `openprogram/runtime/context/nodes.py` `render_context` — DAG → reads computation (the actual semantics of `render_range`)
- `openprogram/runtime/context/render.py` `render_dag_messages` — reads → provider messages conversion

## Related designs

- [`dag/overview.md`](dag/overview.md) — **authoritative**: the execution-record data model (one single graph / three node roles user·llm·code / caller+predecessor edges / render_context retrieval)
- [`dag/rendering.md`](dag/rendering.md) — **authoritative rendering spec**: layout / edges / legend / default visibility, 12 scenarios
- [`dag/branch-collaboration.md`](dag/branch-collaboration.md) — branch collaboration (communication / dispatch / merge) design and implementation steps
- [`execution/agent-call-flow.md`](execution/agent-call-flow.md) — the call-flow skeleton (turn / loop, orthogonal to the node model)
- [`execution/agent-worktree.md`](execution/agent-worktree.md)
- [`execution/async-job-lifecycle.md`](execution/async-job-lifecycle.md)
- [`execution/control.html`](execution/control.html) — **authoritative**: unified pause, continue, step, steering, cancellation, checkpoint, revision, and recovery contract
- [`execution/dispatcher-split.md`](execution/dispatcher-split.md) — how `conversation/turn_runtime/` splits a chat turn into one module per responsibility (no-1000-line rule)
- [`operations/file-management.html`](operations/file-management.html) — authoritative file attribution, Review, Undo, Restore, branch alignment, and multi-agent ownership
- [`session/`](session/) — the session subsystem: data model, storage, naming, listing, lifecycle, broadcast
- [Nested `llm()` streaming design](https://github.com/FuzzyKuji/OpenProgram/blob/main/docs/reference/design/runtime/execution/agentic-llm-streaming.zh.html) — **Full design** (zh): per-node token streaming (protocol, FE buffer, persistence, cancel/reconnect, in-process+subprocess)
- [`operations/streaming-resume.md`](operations/streaming-resume.md)
- [`operations/user-input-requests.md`](operations/user-input-requests.md) — pause a running function to ask the user (`runtime.ask`/`confirm`), question registry + WS/REST protocol + subprocess bridge
- [`agent-collaboration.md`](collaboration/agent-collaboration.md) — **authoritative**: agent collaboration as one cross-branch communication primitive — the four domains, the tool surface, the three budgets ([the tool surface rendered](collaboration/agent-collab-architecture.html), [the eight reference implementations compared](collaboration/agent-collab-comparison.html))
- [`sandbox-architecture.html`](security/sandbox-architecture.html) — the canonical execution-security design: authority tiers, permission modes and approval, sandbox enforcement, framework comparison, and implementation evidence. [`permission-model.md`](security/sandbox-architecture.html) and [`sandbox.md`](security/sandbox-architecture.html) remain stable link targets.

- [Nested LLM node content (ordered chat blocks)](https://github.com/FuzzyKuji/OpenProgram/blob/main/docs/reference/design/runtime/dag/nested-llm-node-content.zh.html)
