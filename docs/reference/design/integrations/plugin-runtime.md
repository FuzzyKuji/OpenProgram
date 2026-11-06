# Plugin Runtime

How an enabled plugin's contents are mounted inside the worker, and how everything it adds is taken back out. The manifest forms, sources, marketplaces and trust levels are covered in [Skills & Plugins](skills-and-plugins.md); this record covers what happens between enable and disable.

A plugin is declarative: a manifest in the Claude Code, Codex, OpenCode or Hermes format naming skills, slash commands, agents, hooks, MCP servers and provider directories (see [Program Model](../function/program-model.md#4-plugins)). The host mounts those contents itself through one `ProgramContext`; every registration is an *effect* with a disposer, and disposing the context undoes the plugin completely. No plugin code is imported. Nothing is a separate plugin-only registry: each effect writes into the registry the host already uses for that kind of thing.

## 1. Lifecycle

```
rescan ──► Plugin(manifest, error=code refusal)   enabled set: ~/.openprogram/plugins-enabled.json
load_plugin(name)
  _check: no code, trust, compatibility, requires (every dependency loaded first)
  _activate:
     ProgramContext(name, root, options)          owner plugin:<name>
     manifest keys ──► ctx effects (skills, commands, hooks, mcpServers, providers, agents)
     any exception ──► ctx.dispose(), error kept on the plugin
  emit plugin.enable, broadcast plugins:changed
unload_plugin(name)
  emit plugin.disable ──► ctx.dispose() (effects in reverse order)
reload_plugin(name) = unload + rescan + load   (the plugin stays enabled if the new files fail)
```

- **Startup.** `openprogram/interfaces/server/server.py` runs `_load_plugins` after the MCP servers start: it hands the event loop to `programs._host.context.set_host_loop` and calls `loader.load_enabled()` on a thread, which loads the enabled set in dependency order and logs each failure without stopping the others.
- **Rescan keeps running plugins.** A rescan that finds a loaded plugin at the same root keeps its context; a changed root deactivates it first.
- **Sources.** npm (`~/.openprogram/plugins/node_modules/`), path (`~/.openprogram/plugins/<name>`) and project pins; later ones win a name clash. `install path <dir>` symlinks `~/.openprogram/plugins/<name>` to the directory, so edits take effect on reload and uninstall removes only the link.

## 2. Code is refused

`plugins/manifest.py` parses every form into one `PluginManifest` and records in `code` the keys that name code: `python`, `module`, `setup`, `main`, `tools`, `client`, `web`, `sidebar`, a `hooks` value of the form `module:name`, and an `__init__.py` beside a Hermes `plugin.yaml`. `code_refusal(manifest)` turns them into one message that names the keys and says to add an `application.json` and run `openprogram programs install <dir>`. The refusal applies at every entry:

- `installer.install` refuses a `path` install, removes a git clone and uninstalls an npm package whose manifest names code; `pip` is not a plugin source.
- `rescan` lists such a plugin with the refusal as its error; `_check` and `_activate` raise `PluginContainsCode` (a `PermissionError`), which the toggle route answers with `403` and `code: "contains_code"`.

## 3. The context

`openprogram/programs/_host/context.py` defines `ProgramContext`, the registration interface every Program and plugin shares. The plugin loader uses these effects:

| Manifest key | Effect | Host registry | Undo |
|---|---|---|---|
| `skills` | `ctx.skills(dir)` | `skills` plugin source | unregister the source |
| `commands` | `ctx.command(name, prompt, description)` | `contrib["_commands"]`, read by the commands registry adapter | cleared with the contributions |
| `hooks` | `ctx.gate` / `ctx.on` with a shell gate or notifier | `EventBus.subscribe_gate` / `subscribe` | the subscription's disposer |
| `mcpServers` | `ctx.mcp_server(name, config)` | `mcp` manager `add_server` as `<plugin>_<name>`, scheduled on the host loop; never written to `mcp_servers.json` | `remove_server` |
| `providers` | `ctx.provider_root(dir)` | `providers/catalog/plugin_dirs.py`, the search path behind `provider.json` lookups | remove the root |
| `agents` | `manager.create` | the Agent registry | none (below) |

`ctx.dispose()` runs the disposers in reverse order, collects their errors instead of stopping, and empties `ctx.contributions`, the per-kind record the Plugins page and the `plugin` tool show.

Agents declared in the manifest are created as `<plugin>-<name>` when missing and are **not** removed on disable: deleting an agent deletes its sessions. Shipped provider directories win a name clash with a plugin's.

## 4. Hooks

`plugins/hooks.py` reads the `hooks` value, inline or from a JSON file, in OpenProgram's shape (`{event: [{command, timeout}]}`, the same as the `hooks` key of `config.json`) or Claude Code's (`{hooks: {PreToolUse: [{matcher, hooks: [{type: "command", command}]}]}}`). `CLAUDE_EVENTS` maps `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop` and `SessionStart` onto `tool.before`, `tool.after`, `chat.before_send`, `turn.stop` and `session.start`; `${CLAUDE_PLUGIN_ROOT}` becomes the plugin directory; `matcher` is a regular expression over the event's `tool`. Each command is wrapped by `events/shell_hooks.py` (the event as JSON on stdin; on a gate event exit 2 denies with stderr as the reason, any other exit allows) and subscribed through the plugin's context. Unknown events, non-command hook types and transform events are skipped.

## 5. Events: notify, gate, transform

`events/registry.py` gives every event a kind:

- **notify** — observers; return values are ignored.
- **gate** — may veto (`tool.before`, `turn.stop`).
- **transform** — each rewriter receives `(event, value)` and returns the new value; `None` keeps it, and a rewriter that raises is skipped.

`tool.result` is a transform event. `agent_loop._rewrite_tool_result` joins the result's text blocks, emits the transform, and replaces the text with the rewritten string while keeping images and audio. Applications subscribe to it with `ctx.transform`; shell hooks, and therefore plugins, cannot.

## 6. Web

Plugins carry no UI: the server has no route for plugin Web modules, pages or sidebar rows, and the Web shell has no slots for them. The plugins page lists declarative plugins and their contributions; a `plugins:changed` frame refreshes that list. A screen of its own is an application's `application.json` UI.

## 7. Self-description and the agent tool

`openprogram/extensions/plugins/inspect.py` builds `describe()` from the live registries: the manifest keys a plugin may use, the refused keys, every event with its kind and whether a hook can take it, the Claude Code event map, the exposure tiers, and every registered entry with its owner, tier and approval flag. `guide()` is the same as text. They back `GET /api/plugins/inspect`, `openprogram plugins inspect [--json]` and the `plugin` tool.

The `plugin` tool (`programs/tools/runtime/plugin.py`) lets an agent extend OpenProgram without editing its source: `guide`, `inspect`, `list`, `install` (link, trust as community, enable), `enable`, `disable`, `reload`, `uninstall`. It runs in the worker process (`_run_in_worker`) so registrations land in the live registries, requires approval, and is unavailable on chat channels and in plan mode. A plugin that names code is refused with the same message.

The CLI's `enable`, `disable`, `install`, `uninstall` and `reload` call the running worker's HTTP API first, so the change takes effect at once, and fall back to editing the state files when no worker is running.

## Implementation status

Implemented as described. Not implemented: auto-discovery of Claude Code's default directories (`commands/`, `agents/`, `skills/`, `hooks/hooks.json`) when the manifest does not name them, Claude Code's `prompt` hook type, and `lspServers` / `outputStyles`, which are parsed and ignored.
