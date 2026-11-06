# P3 — Complete three-surface synchronization and expose P1/P2 on all surfaces

Research correction: the existing three-surface synchronization implementation is much more complete than expected; only a small gap remains.

## Existing capabilities (no work needed)

| Capability | Current implementation | file:line |
|---|---|---|
| Single worker + shared git SessionDB | All three surfaces connect to the same worker and read the same source of truth | worker/lock.py, context/session_db.py |
| Running status | `_running_tasks` registry + `running_task`/`running_task_clear` broadcasts (drive the sidebar running indicator and composer state) | webui/server.py:187-224 |
| History recovery on reconnect | `handle_sync(session_id, known_seqs)` resends missing message frames | ws_actions/runtime.py:436-450 |
| Event broadcast | EventBus + _broadcast: one emission reaches every WS client | events/bus.py, server.py `_broadcast` |

A turn initiated on one surface **already** sends the same stream events to the other surfaces; reconnecting **already** restores history and the running indicator. Thus, “an action on one surface is invisible on another” generally does not apply to the webui/TUI paths, which both use worker WS.

## Remaining gaps (P3 work)

### G1 — Reconnection does not restore running_task state
`handle_sync` restores message frames, but not the current `running_task` indicator. Newly connected or reconnected clients must wait for the next `_emit_running_task_event` to see that execution is running.
**Fix**: call `_emit_running_task_event` for the session at the end of `handle_sync` (or send the current running_task snapshot directly to that ws). This is a one-line-scale change.

### G2 — Expose the P1 attended toggle on all surfaces (WS action + session state)
attended is currently a process-level flag used by the CLI. To allow TUI/web switching:
- WS action `{action:"set_attended", session_id, attended: bool}` → call `attended.set_attended` and broadcast an `attended_changed` state frame, so all three surfaces display the current mode.
- Note: attended is currently **process-global**, not per-session. A global switch affects other sessions in the webui single-worker, multi-session configuration. **Decision**: P3 changes attended to **session-scoped** (dict[session_id]→bool); the CLI passes its own session.
- Frontends: a TUI toggle key plus status display, and a web toggle button.

### G3 — Expose P2 steer on all surfaces (WS action)
steer currently exists only as a CLI subcommand that writes to a file inbox. Add:
- WS action `{action:"steer", session_id, message}` → `steering.push(session_id, message)` (already a file inbox: the worker writes and the executing process reads) plus a receipt frame broadcast.
- Subprocess case: paper_agent runs in a subprocess, and its file inbox uses the same session_dir. The subprocess can read it — **no additional IPC is needed**, because files are accessible across processes. This is simpler than expected.
- Frontends: a TUI/web “Send steering instruction” input available while the task runs.

## Order
G1 (one line) → G2 (session-scoped attended + WS action + frontend toggle) → G3 (steer WS action + frontend input).

## Decisions pending
- Make attended per-session: confirmation required (a global switch affects other sessions with a single worker). The default remains unattended.
- Frontend changes: both TUI (Ink, apps/cli/src) and web (web/) need a toggle/input. Most work is here. Implement backend WS actions first (shared by all surfaces and testable), then the frontend UI.
