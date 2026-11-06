# Error Handling — Discipline and Gate

> What may be caught, what must be said about it, and which paths a linter
> enforces it on.

## 1. The rule

**Catch what you can handle, and leave a record of what you swallowed.**

A caught exception that produces no log, no comment and no fallback is
indistinguishable from a bug that has not been found yet. Most of the cost of a
silent handler is paid later, by whoever is trying to work out why a write
never landed.

Three concrete obligations:

1. **Catch specifically.** File IO raises `OSError`; JSON raises `ValueError`
   (and `json.JSONDecodeError`); `ContextVar.reset` raises `ValueError` for a
   foreign token and `RuntimeError` for a spent one. Name everything the
   operation actually raises.
2. **Never swallow a programmer error.** `AttributeError`, `TypeError`,
   `NameError` and friends are defects in our own code, not conditions to
   tolerate. A handler broad enough to hide one must either be narrowed until
   it cannot, or log so the defect is visible.
3. **Say why.** Every remaining swallow carries either a log line with context,
   or a comment stating why ignoring it is correct. Preferably both when the
   reasoning is not obvious.

## 2. Boundaries

A broad `except Exception` is legitimate at a boundary — a place where letting
the exception propagate would take down something larger than the failed
operation:

- **WebSocket handlers and HTTP routes**, where an exception would drop the
  connection rather than return an error.
- **Thread and worker entry points**, where an exception dies unobserved.
- **Callback invocation**, where caller-supplied code runs inside our loop.
- **Optional subsystems** (memory, project git, usage metering), where absence
  degrades a feature rather than failing the turn.
- **Best-effort bookkeeping** that the next turn re-derives anyway.

A boundary catch still logs with enough context to identify the session or the
operation. "Boundary" is a reason to keep running, never a reason to stay
quiet.

## 3. Choosing the log level

| Level | When |
|---|---|
| `error` | A failure the user will notice and has to act on: a channel message not delivered after its retries, an MCP server that did not start, an adapter that stopped for good. |
| `warning` | Something was lost that the user could notice: a write that did not land, a status left stale, a record that will be missing. |
| `info` | An expected degraded path in a running process: a network wait, a retry, a failover to the next model, a reconnect. |
| `debug` | An optional path degraded as designed: an absent subsystem, a best-effort cache, a fallback that worked. Developer traces too. |

Use `exc_info=True` so the traceback survives, and include the session id or
equivalent identifier — a log line that cannot be tied to a session is close to
useless when several agents run at once.

## 4. What good handlers look like

Silent loss of a durable write, made visible:

```python
except OSError:
    _log.warning(
        "index.json not saved for session %s", session_id, exc_info=True)
```

A narrow catch where a broad one was hiding defects:

```python
except (ValueError, RuntimeError):
    # ContextVar.reset raises ValueError for a token minted in another
    # context and RuntimeError for one already spent. Narrowing to only
    # the first lets a cancelled turn's spent token escape and replace
    # the CancelledError.
    _log.debug("context var token already spent or foreign", exc_info=True)
```

Narrowing is only correct once you know the full set. Check what the call
actually raises — `ContextVar.reset` above raises two unrelated types, and a
handler that names one of them turns a swallowed failure into an escaping
one.

An optional subsystem, with the reason stated:

```python
except Exception:
    # Memory is optional: an unavailable provider degrades to no memory
    # block, never a failed turn.
    _log.debug("memory system prompt block unavailable", exc_info=True)
```

Handlers that guard an operation which already swallows its own errors, or that
catch something the code cannot raise, are deleted rather than annotated.

## 5. The gate

`ruff` enforces three rules, configured in `pyproject.toml`:

| Rule | What it catches |
|---|---|
| `E722` | A bare `except:`, which also swallows `KeyboardInterrupt` and `SystemExit`. |
| `S110` | `try` / `except` / `pass` — an exception discarded with no log, no comment and no fallback. |
| `T201` | A `print` call: library code logs through `logging` (section 6). |

Run it with:

```bash
.venv/bin/ruff check .
```

### Scope

The gate covers the whole `openprogram/` package. Only `tests/` and `scripts/`
are muted through `per-file-ignores`: a test that swallows an exception on
purpose is asserting on what follows, and the scripts are run by hand.
`T201` alone is also muted for the command-line surfaces listed in section 6.

A `per-file-ignores` pattern matches the whole path and its `*` crosses `/`,
so `openprogram/*.py` would mute every module in the package rather than the
top-level ones. Check any new pattern against a nested file before trusting
it: a pattern that mutes too much turns the gate off without failing anything.

`BLE001` (blind `except Exception`) is deliberately not enabled. A boundary
handler that logs and degrades is correct design, and flagging every one of
them would produce noise rather than signal. Section 2 governs those by
review instead.

Ruff is scoped to this gate alone. Formatting and import order are left alone
on purpose — this is a correctness rule, not a style regime.

## 6. Logging, not print

Library code reports through `logging`: one module logger,
`_log = logging.getLogger(__name__)`, and the level from section 3. The logger
name says where a record came from, so messages carry no `[module]` prefix;
a bracketed tag stays only when it carries data, such as
`[wechat:<account>]`. Arguments go through `%s` formatting, not f-strings,
and logging chooses the stream.

`print` is for three things only, and each such call outside the muted paths
says which with `# noqa: T201 - <reason>`:

- **command output** — what a command prints as its result (`openprogram cron list`, a
  shell command the sandbox emulates, an `assets.py` subcommand);
- **a stdout protocol** — JSON lines or a sentinel another process reads;
- **a terminal prompt or status** — a human at a terminal being walked through a
  QR login or an OAuth URL, or told that a foreground run is online and how to stop it.

`per-file-ignores` mutes `T201` for whole command-line surfaces whose prints
are all output: `openprogram/interfaces/cli/**`, the `openprogram worker ...`
commands (`operations/worker/lifecycle.py`, `runner.py`, `startup_log.py`,
`services/**`), the upgrade commands (`operations/self_update/**`) and the
developer tools `models/providers/recording/**` and `**/probe_thinking.py`.

Nothing in the library configures logging. Each process entry point calls
`configure_process_logging()` from `openprogram/host/process_logging.py`
once; it attaches one stderr handler to the root logger with the format
`%(asctime)s %(levelname)s %(name)s: %(message)s` and holds the per-request
loggers of `httpx`, `httpcore`, `websockets`, `asyncio` and `mcp` at `WARNING`:

| Process | Default level | Why |
|---|---|---|
| Worker (`run_foreground`) | `INFO` | Its stdout and stderr are the worker log, so records land beside the `[worker +12.3s]` status lines. |
| Standalone scheduler (`run_forever`) | `INFO` | Its terminal is its running log. |
| Foreground Server (`python -m openprogram.interfaces.server`) | `INFO` | Same. |
| CLI (`interfaces/cli/application.py` `main`) | `WARNING` | The interactive chat shares the terminal; only warnings and errors may appear there. |

A later call in the same process moves the level and adds no handler, so the
worker started through the CLI logs at `INFO`. A root logger configured by
someone else (an embedding host, pytest) keeps its handlers.
`OPENPROGRAM_LOG_LEVEL` (a level name, any case) overrides the default level
in every process; an invalid value is ignored.

## Appendix: Implementation Status

Implemented. The whole package passes `E722` and `S110`; `ruff` is in the
`dev` extra and configured under `[tool.ruff]` in `pyproject.toml`, and CI
runs it over `openprogram`, `tests` and `scripts`. Every former
`try`/`except`/`pass` site now names its exceptions where the set is known,
or keeps the broad catch with a comment saying why and a log line
(`warning` for a lost write or stale status, `debug` for a path that degraded
as designed); handlers around calls that cannot raise, or that already
swallow their own errors (`emit_safe`, `emit_ws_frame`), were deleted.

`T201` passes too: the diagnostics that used to be `print` calls in the
runtime, providers, MCP, channels, Server, scheduler and speech code log
through their module loggers, and the remaining calls are command output,
stdout protocols or terminal prompts, either marked `# noqa: T201` or in a
muted command-line path. The `print` inside the Server's own runtime-log
functions (`interfaces/server/runtime_management.py`,
`server_runtime/broadcasts.py`), which also write `runtime.log`, stays as it
is and is marked.

## Related Files

- [Unified execution control](runtime/execution/control.html) — pause, continue, step, steering, cancellation, and why `CancelledError` is a `BaseException`
- [`runtime/dag/overview.md`](runtime/dag/overview.md) — error as a terminal node status
