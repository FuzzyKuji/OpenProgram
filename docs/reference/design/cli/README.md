# CLI / TUI

`openprogram` runs the same agent from a terminal that the desktop app and the Web UI run. Running it with no arguments opens the chat in a full-screen terminal UI; `openprogram --print "..."` sends one prompt, prints the reply and exits; `openprogram --resume <id>` continues an earlier session. Every other capability (providers, agents, sessions, Programs, skills, plugins, MCP servers, channels, settings) has its own subcommand, named by one rule so a new command can be guessed from known ones.

How it fits together today:

- **One backend.** A single long-lived Python worker serves every front end on one port. The terminal UI is a Node.js Ink program (`apps/cli/`) launched by `openprogram/interfaces/cli/ink.py`; it finds the running worker through `worker.pid` / `worker.port` and talks to it over WebSocket, so a chat started in the terminal is the same session the Web UI shows.
- **One settings schema.** Each setting is declared once; `openprogram config`, the TUI settings panel and the Web UI read and write it through the same schema, and every write to `config.json` goes through one atomic, locked entry point.
- **One slash-command registry.** Built-in commands, plugin commands, MCP prompts and skills are merged into one registry with one format, so `/` lists the same commands in the TUI and in the Web composer.
- **Transcript in the terminal.** Tool calls fold into one line, `ctrl+o` opens the full transcript, file edits render as diffs, and input typed during a run is queued.

## Documents

- [`naming.md`](naming.md) — the naming rule every `openprogram` subcommand follows.
- [`redesign.md`](redesign.md) — the configuration surface: command grammar, settings schema, TUI settings panel and transport.
- [`config-write-safety.md`](config-write-safety.md) — the single atomic entry point for writing `config.json`.
- [`drop-run-command.md`](drop-run-command.md) — one execution path for `Agent` methods, whether the user runs them or the model calls them.
- [`single-port.md`](single-port.md) — one process and one port, with the Python worker as the only origin.
- [`ports.md`](ports.md) — choosing, configuring and defending the Web UI port.
- [`slash-commands.md`](slash-commands.md) — the unified slash-command registry.
- [`slash-commands-references.md`](slash-commands-references.md) — how five other projects implement slash commands.
- [`tui-upgrade.md`](tui-upgrade.md) — TUI transcript rendering and interaction: tool-call folding, the `ctrl+o` transcript, diffs, queued input, keybindings.
