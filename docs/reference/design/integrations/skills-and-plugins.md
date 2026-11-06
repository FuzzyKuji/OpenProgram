# Skills & Plugins

Skills and plugins extend what an agent knows and can call without changing OpenProgram itself. A **skill** is a directory with a `SKILL.md`: its one-line description is listed in the system prompt, and the model loads the full body with the `skill` tool when a task needs it. A **plugin** is a declarative package — a manifest that contributes skills, slash commands, agents, hooks, MCP servers and provider directories, and carries no code of its own, so enabling one runs nothing inside the worker. Claude Code, Codex, opencode and hermes manifests are all read as they are, plugins install from npm, git or a local path or from a Claude Code-compatible marketplace, and an untrusted plugin is never enabled. Both are managed on the Abilities pages (Skills, Plugins) of the Web UI and with `openprogram skills` / `openprogram plugins`; changes to skill files reload without a restart.

The system covers the capabilities of claude-code, opencode, and hermes, substituting equivalents wherever the stack differs, and adds capabilities that follow from OpenProgram's own host surfaces.

Reference implementations:
- `references/claude-code-leaked/src/{skills,plugins,commands/{skills,plugin}}`
- `references/opencode/packages/opencode/src/{skill,plugin}`, `packages/plugin`, `.opencode/{skills,plugins}`
- `references/hermes-agent/{skills,plugins,optional-skills}`, `web/src/plugins`

---

## 1. Concepts and file conventions

### Skill
Unit: a directory containing `SKILL.md` + optional `references/`, `templates/`, and other resources.

`SKILL.md` frontmatter (claude-code standard + opencode/hermes additions):

```yaml
---
name: my-skill
description: One-line trigger description (LLM reads this to decide invocation)
category: devops              # hermes-style grouping
optional: false               # hermes optional-skills replaces directory-based distinction
allowed-tools: [Read, Edit]   # claude-code: restrict the usable tools
triggers:                     # explicit trigger conditions (our extension; none of the three actually use it)
  keywords: ["deploy", "ci"]
  file_patterns: ["*.yml"]
  slash: "/deploy"
version: 1.0.0
author: ...
---
```

Sources, lowest precedence first (merged for display; on conflict the latter overrides the former):
1. **Remote-pulled** — `~/.openprogram/cache/skills/<name>/` (matching opencode discovery, pulled from a remote index)
2. **Plugin-provided** — contributed by enabled plugins
3. **User** — `~/.openprogram/skills/<name>/`
4. **Project** — `<project>/skills/<name>/`

OpenProgram does not ship default skills. Product workflows belong to Programs;
skills remain an extension mechanism controlled by the user or a plugin.

A skill's name is its directory path relative to the source root, so nesting gives hierarchical names (`anthropic-skills/docx`) and a name collision means the same skill from two sources, not two different skills.

Resource layout (hermes convention): `SKILL.md` + `references/` + `templates/`.

### Plugin
Unit: a declarative package — a manifest naming skills, commands, agents, hooks, MCP servers and provider directories; no code. Every manifest form is parsed uniformly:
- `.claude-plugin/plugin.json` (claude-code), `.codex-plugin/plugin.json` (codex) or `plugin.json` at the root
- `[tool.openprogram.plugin]` inside `pyproject.toml`
- the `openprogram`, `opencode` or `hermes` field inside `package.json`
- `plugin.yaml` / `plugin.yml` (hermes)

A manifest that names code (`python`, `module`, `setup`, `main`, `tools`, `client`, `web`, `sidebar`, a `module:name` hook mapping, a hermes `__init__.py`) is refused; code that adds tools or a UI is an application ([Program Model](../function/program-model.md#4-plugins), [Plugin Runtime](plugin-runtime.md)).

Manifest fields:
```jsonc
{
  "name": "...",
  "version": "...",
  "description": "...",
  "deprecated": false,            // opencode style
  "compatibility": ">=0.1.0",     // opencode-style minVersion check
  "trust": "community",           // community | verified
  "entrypoints": {
    "commands":   "...",
    "skills":     "./skills",
    "agents":     "...",
    "hooks":      "./hooks/hooks.json",  // shell commands on events, claude-code or openprogram shape
    "mcpServers": "...",
    "providers":  "..."           // opencode style: LLM provider injection
  },
  "options": { /* JSON Schema, see PluginOptionsDialog.tsx */ }
}
```

Sources:
1. **Installed via npm** — `~/.openprogram/plugins/node_modules/<name>/` (opencode-style PluginLoader)
2. **Local path or git clone** — `~/.openprogram/plugins/<name>/` (a link for a local path)
3. **Project-pinned** — `<project>/.openprogram/plugins.json` (declares enablement, version, source)

---

## 2. Backend

### Directory
```
openprogram/
  extensions/
    skills/
      loader.py           # four-source merged loading, prompt listing
      tool.py             # the `skill` tool and its invocation trace
      discovery.py        # pull on demand from a remote index (matching opencode discovery.ts)
      watcher.py          # watchdog file watching, hot reload + WS broadcast
    plugins/
      manifest.py         # multi-manifest parsing, code refusal
      loader.py           # discovery, load / unload through a ProgramContext
      installer.py        # npm / git / path install, uninstall
      hooks.py            # manifest hooks as shell commands on bus events
      marketplace.py      # multiple marketplaces, claude-code schema adapter
      trust.py            # trust policy + persistence
      autoupdate.py       # update checks for installed plugins
  interfaces/server/routes/catalog/
    skills.py
    plugins.py
  state/
    frontmatter.py        # SKILL.md frontmatter parsing (shared with output styles and the CLI)
```

### Skills API (`routes/catalog/skills.py`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/skills` | Four-source merged list, including source / enabled / category / optional |
| GET | `/api/skills/_complete`, `/_search`, `/_resolve` | Name completion, search and resolution for the composer and the `skill` tool |
| GET | `/api/skills/{name}` | Full SKILL.md text + frontmatter + resource file tree |
| GET | `/api/skills/{name}/file` | One resource file of a skill |
| POST / PUT | `/api/skills`, `/api/skills/{name}` | Create in project / user; edit |
| DELETE | `/api/skills/{name}` | Delete from project / user / remote-cache only |
| POST | `/api/skills/{name}/toggle` | enable/disable |
| POST | `/api/skills/{name}/invoke-trace` | Return the injection record from the LLM's last invocation of this skill (unique) |
| GET | `/api/skills/discovery/sources` | List registered remote indexes |
| POST | `/api/skills/discovery/sources` | Add a remote index |
| POST | `/api/skills/discovery/pull` | Pull a single skill from an index into the cache |
| GET | `/api/skills/discovery/suggested`, `/browse`, `/diff` | Suggested indexes, browsing an index, comparing a pulled skill with its source |
| POST | `/api/skills/discovery/install` | Install skills from an index |
| WS | `skills:changed` | Triggered by the watcher |

### Plugins API (`routes/catalog/plugins.py`)
| Method | Path | Description |
|---|---|---|
| GET | `/api/plugins` | Installed list + status + errors |
| GET | `/api/plugins/inspect` | Read a plugin source before installing it |
| GET | `/api/plugins/updates` | Available updates for installed plugins |
| GET | `/api/plugins/commands`, `/api/plugins/builtin` | Plugin-contributed slash commands; built-in entries |
| GET | `/api/plugins/{name}` | Details + manifest + entrypoint load status |
| POST | `/api/plugins/install` | `{source: npm|git|path, spec, ref}`; a manifest that names code is refused |
| POST | `/api/plugins/{name}/uninstall` | |
| POST | `/api/plugins/{name}/toggle` | |
| POST | `/api/plugins/{name}/reload` | Matching claude-code `/reload-plugins` |
| POST | `/api/plugins/{name}/validate` | Matching `ValidatePlugin.tsx`, dry-run check |
| GET / POST | `/api/plugins/{name}/options` | Read/write the options JSON Schema |
| POST | `/api/plugins/{name}/trust` | Set the trust level; an `untrusted` plugin is not enabled |
| GET | `/api/plugins/marketplaces` | List marketplaces |
| POST | `/api/plugins/marketplaces` | Add (compatible with the claude-code marketplace schema) |
| DELETE | `/api/plugins/marketplaces/{id}` | Remove a marketplace |
| GET | `/api/plugins/marketplace/{id}/index` | Browse, with search / category / pagination |
| WS | `plugins:changed` | |
| WS | `plugins:error` | Push load failures in real time |

### Junction points for plugin contribution entrypoints
| Entrypoint type | Injected into |
|---|---|
| skills | The skill registry (merged with filesystem skills) |
| commands | `availableFunctions`, tagged with `source=plugin:<name>` |
| mcpServers | The existing `openprogram/extensions/mcp/` registry; no changes to the `/mcp` page |
| providers | The provider registry (corresponding to the openprogram provider system, opencode style) |
| agents | The subagent registry |
| hooks | The event bus, as shell commands (PreToolUse / PostToolUse / UserPromptSubmit / Stop / SessionStart map to `tool.before` / `tool.after` / `chat.before_send` / `turn.stop` / `session.start`) |

### Trust
| trust | Loading |
|---|---|
| `verified`, `community` | The manifest contents mount; hooks and MCP servers run as their own processes |
| `untrusted` | Refused; the UI pops a trust confirmation |

No plugin code runs in the worker, so there is no in-process or RPC loading mode: hooks are subprocesses, MCP servers are separate servers.

---

## 3. Frontend

### Navigation

Skills and plugins live under **Abilities** in the main sidebar, next to Programs and MCP servers; the Abilities entry is active on `/skills`, `/plugins`, `/mcp` and `/programs`.

### Routes
- `/skills` — list (grouped by category, optional collapsed), details with the invocation trace, create, remote index management
- `/plugins` — three tabs: Installed / Marketplace / Errors
  - Installed: `UnifiedInstalledCell`-style rows
  - Marketplace: marketplace selector + card browsing + install (porting `BrowseMarketplace / AddMarketplace / DiscoverPlugins`)
  - Errors: porting `PluginErrors`

### Components
```
apps/web/components/skills/
  skills-page.tsx, skills-list.tsx, skill-detail-page.tsx,
  new-skill-dialog.tsx, discovery/
apps/web/components/plugins/
  plugins-page.tsx,
  views/      installed-list.tsx, marketplace-browser.tsx, plugin-errors.tsx
  dialogs/    plugin-detail.tsx, add-marketplace-dialog.tsx, plugin-options-dialog.tsx,
              plugin-trust-warning.tsx, validate-plugin.tsx
```

Both skill detail views render SKILL.md bodies as untrusted Markdown. Raw HTML and HTML-like math are displayed as text. These views do not add local-resource resolvers or grant filesystem access through skill links.

### Store
`apps/web/lib/abilities/skills-store.ts`, `apps/web/lib/abilities/plugins-store.ts`, subscribing over WS to `skills:changed` / `plugins:changed` / `plugins:error`.

---

## 4. Capabilities beyond the three reference implementations

1. **Declarative plugins**: a plugin carries no code, so enabling one runs nothing in the worker; code ships as an application
2. **Skill invocation trace**: each SkillTool call records `{ skill, injected_md_hash, accessed_refs, ts }`, shown on the skill's detail page
3. **Skill hot reload**: watchdog watches the four sources for changes → re-parse → WS broadcast, no `/reload` needed
4. **Unified across the manifests**: any of `.claude-plugin/plugin.json` / `.codex-plugin/plugin.json` / `plugin.json` / `pyproject.toml` / `package.json` / `plugin.yaml` is recognized, zero migration cost
5. **Cross-ecosystem marketplace interop**: a claude-code marketplace schema adapter layer, able to directly add its official / third-party marketplaces
6. **Package sources**: npm, git and a local path (linked)
7. **Explicit triggers**: `triggers.{keywords, file_patterns, slash}`; a hit on any of conversation/file/command surfaces an activation prompt
8. **Provider as a contribution type**: introduced from opencode, letting LLM providers also be distributed in plugin form
9. **Trust gate**: hooks and MCP servers run commands, so an `untrusted` plugin is not enabled
10. **Validate dry-run**: before install, `POST /validate` checks manifest / entrypoints / dependencies / compatibility, matching `ValidatePlugin.tsx`

---

## 5. Coverage of the three reference implementations

**claude-code**: bundled skills ✓, SKILL.md frontmatter ✓, SkillTool tool invocation ✓, Marketplace / AddMarketplace / BrowseMarketplace / ManageMarketplaces ✓, ManagePlugins / DiscoverPlugins / ValidatePlugin / PluginErrors / PluginOptionsDialog / PluginTrustWarning / UnifiedInstalledCell ✓, ReloadPlugins ✓, the five entrypoints commands/skills/agents/hooks/mcpServers ✓

**opencode**: remote skill discovery (IndexSkill schema) ✓, npm-package-form plugins ✓, Provider plugin ✓, PluginPackage / resolvePluginTarget / compatibility / deprecated fields ✓, Effect-style concurrency and retry (swapped for httpx+tenacity) ✓

**hermes**: domain-grouped skills ✓ (category), optional distinction ✓ (optional field), the `SKILL.md` + `references/` + `templates/` resource layout ✓, `plugin.yaml` manifest ✓ (a Python `plugin_api.py` / `dashboard/dist/` package is an application, not a plugin)

---

## Appendix: Implementation Status

- **Skills** — implemented: the four-source loader, watchdog and WS broadcast, SKILL.md parsing (triggers / category / optional), the `/skills` page, the `skill` tool with its invocation trace, and remote discovery. The package ships no default skills.
- **Plugins, local** — implemented: unified parsing of the manifests with code refusal; installation from npm / git / path; trust; mounting of the commands / skills / mcpServers / providers / hooks / agents entrypoints; the Installed and Errors pages with Validate / Options / Reload; update checks.
- **Marketplace** — implemented: multiple marketplaces with the claude-code schema adapter, plus browsing and installing from them.
- Skills and plugins live under `~/.openprogram/` (`skills/`, `cache/skills/`, `plugins/`). A plugin's `providers` entrypoint adds a provider directory through its `ProgramContext`; the providers in it follow the same `provider.json` contract as the built-in adapters.
