# Controllability of long-running agent tasks and consistency across three interfaces

User requirements (organized from the original request):
1. **Attendance switch**: do not ask the user while unattended (for example, while asleep); questions are allowed while the user is observing. Selected approach: **exclude the ask-user tool from the agent when unattended**. Without the tool it cannot ask; uncertain output may remain for subsequent model reasoning to resolve.
2. **Intervention and direction changes during execution**: when a running task takes the wrong approach, the user can insert an instruction to adjust it. Selected direction: **use the event layer** to monitor external events and inject additional user messages.
3. **Questions during execution**: questions from the agent must be visible and answerable in all three interfaces.
4. **Session synchronization across three interfaces**: sessions running in the background in one interface must appear consistently in CLI, TUI and Web; actions must not remain invisible in another interface.

## Existing reusable capabilities

| Capability | Current state | file:line |
|---|---|---|
| Steering injection points | agent_loop has three message-injection checkpoints: turn start, after each tool, and before follow-up | `agent/loop/loop.py` |
| Question framework | QuestionRegistry (process-wide, thread-safe, claim-once), two transports (EventLayer / Queue), and a subprocess bridge | `agent/questions.py:34-198`, `conversation/process_runner.py` answer_queue/QueueTransport |
| Event broadcasting | EventBus + emit_ws_frame: one emit reaches all WS clients | `openprogram/runtime/events/bus.py`, `webui/server.py` `_broadcast` |
| Shared storage | Git-backed SessionDB shared by all three interfaces; singleton worker (WorkerLock) | `context/session_db.py`, `worker/lock.py` |
| Tool catalog policy | apply_tool_policy supports deny/allow; toolset levels exclude ask_user_question from default and include it in full | `functions/__init__.py` apply_tool_policy |
| Cancellation / graceful stop | End-to-end cancel_event and subprocess graceful-stop IPC (added in this iteration) | `conversation/process_runner.py` request_graceful_stop |

**Key conclusion**: the three interfaces share worker, DB and EventBus, so synchronization already has shared infrastructure. Steering and question delivery mechanisms exist. Missing pieces are policy enforcement and coordination.

## Where the attendance switch belongs

The autonomous paper_harness loop **already operates unattended**:
- `oversight="interactive"` already excludes socratic_plan and similar tools from the catalog (`registry.py:357`).
- Experiment subfunctions use `toolset="default"`, which **does not include** `ask_user_question`.

Thus excluding ask tools while unattended **already holds** for the autonomous paper_harness path. The attendance switch matters in the **general OpenProgram chat/agent path**, where the `full` toolset includes `ask_user_question` and clarification tools.

→ P1 belongs in dispatcher tool selection for each turn: the session-level `attended` flag determines whether to deny `ask_user_question` and clarification tools.

## Staged plan (each step independently verifiable and deliverable)

### P1 — Attendance switch (attended/unattended)
- **Session-level flag** `attended` (default attended=True, allowing questions). Store in session metadata (SessionDB) and memory; all three interfaces can read and update it.
- **Policy enforcement**: while dispatcher assembles turn tools, `attended=False` applies `apply_tool_policy(deny=["ask_user_question","clarify",...])` for question tools. An agent without these tools cannot ask.
- **Controls in all interfaces**: CLI flag (`--unattended`), a TUI shortcut/status, and a Web toggle. All update the same session flag through the worker.
- **Verification**: run a task that would normally ask a question while unattended; verify the catalog excludes ask tools, no question appears, and output is still produced.

### P2 — Intervention during execution (event-injected steering)
- **Mechanism**: represent an intervening user message as an event. At loop checkpoints (the max_runtime_s/stop_event checks), paper_agent / agent_loop polls a **session-level steering queue** and injects any message as a new instruction into the next context or re-runs _pick_stage.
- **Entry**: intervention message from any interface → WS/CLI → session steering queue (reuse server `_follow_up_queues` or create one).
- **Injection semantics**: let the current step finish, then include the new user instruction in the next stage decision (for example, “The user requested X during execution; adjust accordingly”).
- **Reuse**: agent_loop already has steering_messages. Add a `_steering_pending()` check beside `_stop_requested()` in the paper_agent loop.
- **Verification**: at stage 2, send “Stop writing experiments; review the literature first.” Verify the next stage decision receives and follows it.

### P3 — Complete synchronization across interfaces
- **Running state**: add a session execution marker identifying the running task and stage, include it in broadcast session state, and show that the session is busy in all interfaces.
- **Replay on connection**: when a new WS client joins a streaming turn, send prior intermediate events, or at least the running state and current stage. New connections currently see only final output.
- **Verification**: start in interface A and connect B during execution. B must show running state and progress instead of waiting on a blank view until final output.

### P4 — Consistent question presentation
- CLI / TUI render `question.asked` as answerable cards (already present on Web). CLI uses stdin prompts; TUI uses the follow_up card component.
- **Verification**: in attended mode, all interfaces display and accept answers to agent questions, returning the answer to the same registry.

## Cross-cutting principle: consistency across all interfaces
The P1 switch, P2 interventions and P4 questions all hold **session-level state** in the worker and DB. The interfaces show the same state. Every interface action goes through the worker, broadcast and synchronization; no interface-local unsynchronized state is introduced.

## Design decisions awaiting the user
- P1 default: attended=True (questions allowed) or unattended=True (do not interrupt by default)?
- P2 timing: inject only at step boundaries (recommended), or also support immediately interrupting the current step?
- Order: proceed P1 → P2 → P3 → P4?
