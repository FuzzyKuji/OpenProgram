# User input requests

Running Python Workflows can call `ask_user(question)` or `runtime.ask(...)` to display a question and wait for its answer in the same process. This does not save or resume the Workflow call stack. Restarting the worker interrupts this execution; it must not replay prior work. Refreshing a browser preserves the pending question while its owner remains active.

## Reference designs (what we take)

- **opencode**: tool calls `ctx.ask(...)` → server-side Deferred + pending
  map → event `permission.asked` down, REST reply up, **plus a list
  endpoint** so a reconnecting client can recover pending questions. Reject
  may carry a message that becomes the tool-error text the model sees.
- **Claude Code**: AskUserQuestion rides the permission pipeline; options +
  always-present "Other" free-text; pending request *snapshot* persisted in
  session metadata so remote UIs can redraw it (execution stack never
  persisted); tools that require interaction are disabled when no human is
  attached.
- **openclaw**: 30-min timeout with an explicit fallback (never silent);
  channel buttons whose value is a plain text command (`/approve <id> …`)
  so text-only channels work identically; for channel-initiated runs, the
  tool returns "pending" immediately and the result is re-injected later
  (non-blocking mode).
- **MCP elicitation**: the three-outcome protocol — accept / decline /
  cancel — and flat-object schema constraints for form-style asks.

## API and outcomes

```python
from openprogram.programs.tools.interaction.ask_user import ask_user
answer = ask_user("Who wrote this report?")
```

`runtime.ask(prompt, options=None, multi=False, allow_custom=True, timeout=300.0, default=None)` returns an answer, raises `UserDeclined`, or raises `AskTimeout` when no timeout default is supplied. `runtime.confirm` and `runtime.form` share the question transport. Cancellation raises the execution cancellation exception.

`ask_user` retains its global CLI handler and TTY fallback. A `run_with_follow_up` handler is scoped to the execution context and inherits that context in its background thread; it does not replace the frontend handler or capture another concurrent Workflow's question. Each `FollowUp` accepts one answer, and a repeated answer fails immediately. In a runtime with a question transport it calls `runtime.ask`; an explicit decline or timeout maps to `None` for compatibility. Unexpected runtime, persistence and transport errors propagate. Headless calls without a handler or usable runtime still return `None`.

## Live Workflow ownership

The subprocess runner binds execution ID, attempt ID, generation and producer identity for the lifetime of the call. A runtime without this binding cannot create a live question. Creation and answer transactions verify that the execution is running, the attempt remains the current active owner and its lease is valid. Live questions cannot grant tool permissions.

The canonical wait store retains only the question, policy and eventual answer. Live waits have no checkpoint. Answer commands do not create another attempt. The original function receives the answer through its existing call stack. No model or completed tool is replayed.

A child publishes `question.asked` through `QueueTransport`. Its parent projects the stored request into the frontend event and relays the canonical answer notification. The registry is only a local wake notifier; SQLite is the answer authority. Duplicate answers and replies from another execution are rejected by the existing command protocol.

## Browser and process lifecycle

The existing question card displays the prompt. Session loading replays open questions after refresh. The question endpoints and execution answer command use the same record and authorization checks.

Stopping an execution cancels its open questions. Child exit closes only that producer's live questions. Owner-loss reconciliation cancels abandoned live questions; stale replies cannot continue an ended call. A worker restart does not restore a Python Workflow stack. Durable Agent questions remain available through their separate checkpoint contract.

## Declared Agent questions

Agent tool interactions with a declared pre-wait still use the checkpoint transaction: pause the execution, end the prior attempt and continue from that checkpoint after an answer. A preapproved wait takes precedence over the live binding and must exactly match the requested presentation. Live Workflow support does not weaken this validation or change permission approvals.

## Verification

Tests exercise public `ask_user` with the real Runtime, canonical wait commands, same-call continuation, cancellation, invalid owner/session, transport failure and producer cleanup. Native acceptance requires a question in the installed App, browser refresh and an answer that lets the Workflow finish. A returned `WAITING_USER` object is not evidence that the UI interaction worked.

## Scope

Workflow restart recovery is outside this contract. A live question retains its request and answer, not the Workflow execution state.
