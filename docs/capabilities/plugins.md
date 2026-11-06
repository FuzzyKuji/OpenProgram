# Plugins

A plugin is a declarative package: a manifest that names skills, slash commands, agents, hooks, MCP servers and model provider directories, in the format Claude Code, Codex, OpenCode or Hermes already use. OpenProgram reads the manifest and mounts those contents itself; no plugin code runs inside OpenProgram. Code that adds tools or a screen of its own is an [application](applications.md), not a plugin. This page covers installing and managing plugins, and what a plugin may contain.

## Install and manage

```bash
openprogram plugins list                 # installed plugins
openprogram plugins search <query>       # search the configured marketplaces
openprogram plugins install git <url> --ref v1.2   # source is one of npm / git / path
openprogram plugins install npm <package>
openprogram plugins install path /abs/path/to/plugin
openprogram plugins update --all         # reinstall-upgrade npm plugins (or pass one name)
openprogram plugins enable <name>
openprogram plugins disable <name>
openprogram plugins reload <name>         # re-read its manifest and files after editing
openprogram plugins uninstall <name>       # for a linked local plugin, removes only the link
openprogram plugins inspect               # what a plugin may contain, and every entry's exposure tier
```

Git clones land under `~/.openprogram/plugins/`, npm packages under its `node_modules/`, and a local path is linked there so edits apply on `reload`. Trust levels (`verified` / `community` / `untrusted`; unlisted plugins default to `untrusted`, and a local `path` install is trusted as `community`) persist in `~/.openprogram/plugin-trust.json`; hooks and MCP servers run commands, so an `untrusted` plugin is not enabled. The web UI exposes the same management API through the plugin routes.

## What a plugin may contain

A directory carrying one of these manifests, resolved in this order:

1. `.claude-plugin/plugin.json` (Claude Code), `.codex-plugin/plugin.json` (Codex) or `plugin.json` at the root
2. `[tool.openprogram.plugin]` in `pyproject.toml`
3. the `openprogram`, `opencode` or `hermes` field of `package.json`
4. `plugin.yaml` / `plugin.yml` (Hermes)

Manifest fields are `name`, `version`, `description`, `trust`, `entrypoints`, `options` and `requires`; the contribution keys may also sit at the top level, as Claude Code writes them. `requires` declares inter-plugin dependencies: the loader enables plugins in topological order and reports `missing dependencies: ...` when one is absent.

| Key | Contents |
|---|---|
| `skills` | a directory of `SKILL.md` skills |
| `commands` | slash commands: `{name: {description, prompt}}`, or a directory of `.md` files with front matter |
| `agents` | a list of `{name, description, prompt, tools}`, or a directory of `.md` agents; created as `<plugin>-<name>` and kept when the plugin is disabled, because deleting an agent would delete its sessions |
| `hooks` | shell commands run on events, inline or as a `.json` path (below) |
| `mcpServers` | `{name: {command, args, env} \| {url}}` inline, or a `.mcp.json` path; started for as long as the plugin is enabled |
| `providers` | a directory whose children each hold a `provider.json` |

Everything a plugin adds is mounted through one context owned by `plugin:<name>`; `disable` and `reload` remove all of it.

### Hooks

`hooks` takes either OpenProgram's shape, the same as the `hooks` key of `config.json`:

```json
{"tool.before": [{"command": "${CLAUDE_PLUGIN_ROOT}/check.sh", "timeout": 30}]}
```

or Claude Code's `hooks/hooks.json`:

```json
{"hooks": {"PreToolUse": [{"matcher": "bash|write", "hooks": [
  {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/check.sh"}]}]}}
```

Claude Code's events map to OpenProgram's: `PreToolUse` → `tool.before`, `PostToolUse` → `tool.after`, `UserPromptSubmit` → `chat.before_send`, `Stop` → `turn.stop`, `SessionStart` → `session.start`. `matcher` is a regular expression over the tool name. In either shape `${CLAUDE_PLUGIN_ROOT}` is replaced by the plugin directory; commands run in the worker's working directory. The command receives the event as JSON on stdin. On a gate event (`tool.before`, `turn.stop`) exit code 2 denies, with stderr as the reason; any other exit code allows. `openprogram plugins inspect` lists every event.

### What is refused

A manifest that names code installs and enables nowhere: `install` refuses it (a git clone or npm package is removed again), and one placed in the plugins directory by hand is listed with the error and never loads. The refused keys are `python`, `module`, `setup`, `main` and `tools` (Python or JavaScript code), `client`, `web` and `sidebar` (a screen of its own), `hooks` written as `module:name` (a Python handler mapping), and a Hermes `plugin.yaml` beside an `__init__.py`. pip is not a plugin source. The refusal names the keys and says what to do instead: add an `application.json` to the directory and run `openprogram programs install <dir>` — see [Applications](applications.md).

## Write a plugin

```
house-style/
  .claude-plugin/plugin.json
  skills/review/SKILL.md
  commands/summarize.md
  hooks/hooks.json
```

```json
{"name": "house-style", "version": "0.1.0", "skills": "./skills",
 "commands": "./commands", "hooks": "./hooks/hooks.json"}
```

```bash
openprogram plugins install path /abs/path/to/house-style   # links the directory
openprogram plugins enable house-style
openprogram plugins reload house-style                      # after editing its files
```

### Let an agent write it

Agents have a `plugin` tool (approval required, not offered on chat channels or in plan mode). `guide` returns the authoring guide, generated from the running build; after writing the files, `install` with the directory's absolute path links, trusts and enables the plugin in one step, and `reload` applies later edits. A plugin that names code is refused with the same message as the CLI.
