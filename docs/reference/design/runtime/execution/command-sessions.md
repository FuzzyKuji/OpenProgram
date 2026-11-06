# Command sessions

How the agent runs shell commands: `bash` and `write_stdin`, and how they relate to `terminal_use`. The model follows Codex's unified exec (`exec_command` / `write_stdin`) and Claude Code's background-task notice, on top of OpenProgram's managed-process supervisor.

## Two tool families, split by whose process it is

| Family | Tools | Owner of the process |
|---|---|---|
| Agent commands | `bash`, `write_stdin` | The agent. Results only reach the agent. |
| Terminal panel | `terminal_use` | A terminal tab: one the agent opened (`terminal-resource:` id) or one the user opened. |

Codex and Claude Code split the same way: Codex has `exec_command`/`write_stdin` for its own processes and only a read-only `read_thread_terminal` for the user's terminal; Claude Code has `Bash` for its own and the terminal panel tools for tabs. The split follows risk: an agent command affects only what the agent asked for, while a user's tab holds the user's sign-ins and running work.

## bash

`bash(command, workdir, yield_time_ms, tty, description)`:

1. `prepare_command` resolves `workdir` exactly as before (worktree, sandbox checks, remote `cd` guard).
2. `session.run` checks the 64-session cap, then `processes.start(command, cwd, tty=..., run_command=...)` launches the command under a detached supervisor.
3. `collect` reads unread output every 50 ms into a head/tail buffer (1 MiB, first and last halves kept) until the command ends or `yield_time_ms` passes (default 30000; clamp 250–30000, as Codex's exec_command).
4. Ended: the reply is `Process exited with code N` plus output, and the record is removed; its output is all in the reply. Still running: the record gets `background=True` and the reply is `Process running with session ID <id>`.

The reply header copies Codex's (`Wall time`, `Process exited with code` / `Process running with session ID`, `Output:`) and adds `cwd=` and a non-local `backend=`. stdout and stderr arrive as one stream. A nonzero exit or a supervisor failure is an error result; a running session is not. The sandbox explanation is appended when `is_sandbox_denial` matches the merged output of a sandboxed command.

Cancelling the turn during the first wait stops the command (the old foreground contract, checked by `check_cancelled` in the collect loop). A session already in the background is unaffected by later cancellations.

A call with no trusted conversation (a script or test calling the tool directly) runs once through `backend.run` with a ten-minute limit and the earlier `exit_code=` format.

## write_stdin

`write_stdin(session_id, chars, yield_time_ms)` finds the session in the conversation (same `session_id`, or an execution in its scope), then:

| `chars` | tty session | pipe session |
|---|---|---|
| empty | poll | poll |
| `"\x03"` | written to the terminal (line discipline sends SIGINT) | `interrupt` command: SIGINT to the process group |
| other | `write` command, raw bytes, then 100 ms before reading | refused: stdin is closed |

Yield: writes default 250 ms and clamp 250–30000; empty polls clamp 5000–300000 (Codex's values). A reply that shows the exit marks the record `reported`.

## Processes layer

- `group_guard` runs a pipe command with stdin `/dev/null` (Codex closes stdin for non-tty). For tty it opens a pty, makes it the controlling terminal of its own session (it is already a session leader), puts its group in the foreground, sets 30×120, and pumps master ↔ supervisor pipes. It ignores SIGINT as it ignores SIGTERM, so an interrupt reaches the command, not the guard.
- The supervisor's `write` command sends raw bytes (no newline added); `interrupt` sends SIGINT to the group (Windows: terminates the tree).
- `ProcessStore` records `tty`, `sandboxed`, `background`, `reported`, `last_used`; `take()` returns unread output and the bytes dropped before they were read; `live_count()` and `unreported_exits()` are single SQL queries.
- tty needs the local backend on macOS or Linux.

## Session cap

At most 64 live sessions per conversation (Codex `MAX_UNIFIED_EXEC_PROCESSES`). `live_count` gates the check cheaply; at the cap, the least recently used session outside the eight most recently used (`PROTECTED_RECENT`, as Codex) is stopped and marked `reported`, and the new command's reply names it. There is no idle timeout and no one-shot timeout mode.

## Exit notices

`runtime.conversation.process_notices.run_exit_notices` runs in the worker lifespan and sweeps every 2 s:

1. `unreported_exits()`: `background`, not `reported`, status `exited` or `failed`. A `stopped` command (the user's Stop, or the cap) sends nothing.
2. Skip while the conversation has a running turn or a nonterminal execution; it is retried after that turn.
3. Clone the conversation's newest chat request (its trusted actor and config snapshot, as Goal continuation does), set `source="process_exit"`, a fresh user message id and the notice text (command, exit code, duration, last 2000 characters of output), and admit it with key `process_exit:<id>`. A conversation with no chat execution is marked reported without a notice.
4. `process_exit` is a runtime source: the turn's user node is `display="runtime"` and memory skips it.

## Approvals

- `write_stdin` with empty chars or `"\x03"` is allowed without asking (`SESSION_POLL`); `bash` already approved the command. Other input follows the mode, as `bash`.
- `terminal_use` `input`, `interrupt` or `close` follows the permission mode, on the user's tabs and the agent's alike. When it asks, the card (`TerminalApproval`) names the tab, its current directory from shell integration, whether a command is running, unfinished human input, and the exact input with control characters spelled out.
- `write_stdin` is a risky tool wherever `process` was (Auto risk set, MCP/delegated hard constraints, dangerous allow rules).

## Interface

- Activity lists background sessions only (`background` true, or records from before this field); a command in its first wait shows as an active tool call.
- Resources lists running background sessions in the Terminal group as **Background terminal** (`backgroundTerminalRows`), and `BackgroundTerminalView` shows the retained output read-only in xterm with Stop. Output refreshes with the managed-process poll (3 s).
- Tool rows: `write_stdin` reads "Waited for output", "Interrupted" or "Typed"; `terminal_use` input reads "Typed in terminal".

## Implementation status

Implemented as described. Not adopted from Codex: zsh fork, shell snapshots, the `shell` / `login` / `max_output_tokens` parameters, and stdin approval on policy drift. Background terminal output refreshes by polling, not streaming.
