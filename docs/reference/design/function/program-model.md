# Program Model

Everything the Agent can use is a **Program**. This record states what a Program is, the two kinds of Program, the one interface every Program and plugin registers through, what a plugin is, how entries are exposed to the model, where user Programs live and which CLI manages them.

## 1. Programs and their directory

All Programs live under `openprogram/programs/`:

```
openprogram/programs/
  tools/            Programs shipped with the core; always given to the Agent
  applications/     Programs the user enables one by one; may carry a UI
  _authoring/       what Program code imports: errors, JSON parsing, reports,
                    tool helpers, provider registries, guides, prechecks and
                    the application client
  _host/            how the host loads and runs Programs:
    runtime.py        the `@function` decorator and the shared tool registry
    context.py        ProgramContext, the registration interface
    services.py       named services shared between Programs and plugins
    registry.py       loads every Program and keeps its ProgramContext
    packages.py       Python Program packages: entry registration, the user's packages
    sources.py        the harness catalogue and the owner-recorded program sources
    check.py          `openprogram programs check`
    ui/               the application loader, catalog, UI and operation runtime
```

A Program exposes its callable entries through `PROGRAM_ENTRIES` (with optional `ENTRY_OPTIONS`); each entry becomes one tool in the shared registry, `programs/_host/runtime.py`. Plain functions that are not listed are not recorded.

## 2. Two kinds: tools and applications

The kind is decided by how the Program reaches the Agent, not by its size.

| | `tools/` | `applications/` |
|---|---|---|
| Ships with | the core | the core, or installed by the user |
| Given to the Agent | by default, always | only while enabled |
| Can be disabled on its own | no | yes, one by one |
| UI | none | may carry one, shown in an App window |
| `setup(ctx)` | no | optional |
| Entry exposure | resident (the cold ones deferred) | deferred; resident while the application is open in a window |

A Program belongs in `tools/` when the Agent loses a basic ability without it (reading files, running commands, asking the user, planning) and it needs no screen of its own. A tool may be a single module or a package. Everything else is an application: the browser, user workflows, installed applications and external harnesses.

The built-in Programs are laid out by that rule:

| Location | Holds |
|---|---|
| `tools/interaction/ask_user.py` | `ask_user`, the library a running Program uses to ask the user and wait for the answer |
| `tools/planning/goal/` | chat Goals: the `create_goal` / `get_goal` / `update_goal` tools and the `goal` Program |
| `applications/browser/` | the browser application (`web_use`) |
| `applications/workflow_recording/` | the demonstration recorder (no entries; provides the service `workflow_recording`) |
| `applications/office_editor/` | the Office editor application (no Agent entry; the `office_editor` service behind the document window's Office routes) |
| `_authoring/` | `errors`, `json_parsing` and `reports`, imported by built-in and user Programs as `openprogram.programs._authoring.<module>` |

Most tools register with `@function` when `openprogram.programs.tools` is imported. A tool package that also lists `PROGRAM_ENTRIES` is named in `registry.TOOL_PROGRAMS` (today only `goal`) and registers those entries through its own context.

A tool always has at least one entry the Agent can call; a tool without one is not a tool. An application may have none: an application that is only a UI is complete.

### Application packages

An application takes either form, or both in one directory:

- a Python package: `__init__.py` with `PROGRAM_ENTRIES`, `ENTRY_OPTIONS` and an optional `setup(ctx)`;
- a declarative package: `application.json`, its UI (`index.html` or `ui/`) and an optional Python backend (`backend.py`) whose operations the manifest declares.

The loader (`programs/_host/ui/loader.py`) mounts a declarative package through the application's context with one function, `mount(ctx, root)`, whether the package is built in under `programs/applications/<name>/` (its manifest id is the directory name) or installed by the user. Mounting reads the manifest, computes the content digest of the directory, and registers three things:

- the served UI, read from the application's own directory under that digest;
- the resource provider `application.<id>`;
- one entry per operation marked `agent: true`, named `<id>__<operation>` with every character outside `[A-Za-z0-9_-]` replaced by `_` (model APIs accept no dots in tool names). The entry takes the operation input as `input` (and `project_id` for a project-scoped application), runs the operation through the worker's application service, one process per operation with the manifest's capability checks, and returns the finished run. Entries are deferred, need approval and are not in `DEFAULT_TOOLS`. Operations marked `agent: false` get no entry.

An installed application is recorded in `~/.openprogram/programs/catalog.json` by its source directory; nothing is copied. Installed applications load in the worker: at start, after install, enable and disable, and when the Programs watcher sees their source change. Disabling one disposes its context, which removes the UI, the provider and the entries; a changed source is disposed and loaded again with a new digest.

A built-in application is enabled and disabled the same way. Its setting is a `builtin-application` row of `catalog.json` (`{"id": "browser", "enabled": false}`), read by `catalog.builtin_enabled`; `registry.sync_builtin_application` makes the application match it, disposing its context when disabled (entries, UI, resource provider, services, prompt sections) and loading it through a fresh context when enabled. The registry syncs every built-in application each time it loads Programs, so the setting holds in every process and across worker restarts, and the owner API's `PATCH /api/applications/<id>` applies it to the running worker. An entry that comes back on enable is the same registered tool with its toolsets and tier. A tool cannot be disabled.

## 3. ProgramContext

`ProgramContext` (`openprogram/programs/_host/context.py`) is the host's single registration interface. Every application package and every plugin gets one context. Each registration made through it records its own undo, and `ctx.dispose()` runs those undos newest first, so the host returns to exactly the state it had before the package loaded.

The context writes into the registries the host already uses for each kind of thing; there is no separate registry per kind of package:

| Method | Registers |
|---|---|
| `ctx.tool(fn)` / `ctx.tools_from(module)` | `PROGRAM_ENTRIES` as tools, owned by `ctx.owner` |
| `ctx.on` / `ctx.gate` / `ctx.transform` | event-bus subscriptions |
| `ctx.context(name, build, ...)` | a context section named `<owner>:<name>`: in the system prompt (`L0`, `L1`), or in one call's prompt (`L2`) |
| `ctx.provide` / `ctx.service` | a named service in `programs/_host/services.py`, listed with its provider `ctx.owner`; the core reaches a service an application provides with `services.lookup(name)`, which is `None` without it |
| `ctx.resource(provider)` | a resource provider for the `resource` tool; `application.<id>` is reserved to the application `<id>` |
| `ctx.command`, `ctx.skills`, `ctx.mcp_server`, `ctx.provider_root`, `ctx.api_provider` | slash commands, skill roots, MCP servers, provider directories, model wire implementations |
| `ctx.effect(dispose)` | anything else, with the given undo |

`ctx.owner` is the owner recorded on each tool (`_program_owner`): `tool:<name>` for a tool package in `TOOL_PROGRAMS`, `application:<name>` for a built-in application under `programs/applications/`, the package name for a user Program, `external:<package>` for an external harness, `plugin:<name>` for a plugin. Every owner other than `tool:` and `plugin:` is an application, and an entry registered through its context starts deferred (section 5).

The registry (`programs/_host/registry.py`) keeps a table owner → `ProgramContext`. Loading a package creates its context on first use; loading the same package again reuses it and records nothing twice. Unloading or hot-reloading a package (the watcher in `programs/_host/watcher.py` re-runs discovery when the Programs directory changes) calls `dispose_program(owner)`, which disposes the context, and a reload then registers through a fresh one.

Example, as an application's `setup`:

```python
def setup(ctx):
    @ctx.tool
    def word_count(text: str) -> int:
        '''Count the words in a text.'''
        return len(text.split())

    ctx.on("tool.after", lambda event: ctx.log.info(event.payload["tool"]))
```

## 4. Plugins

**Plugin** means only a declarative package in the Claude Code, Codex, OpenCode or Hermes format: skills, slash commands, agents, hooks, MCP servers and provider directories described by a manifest. OpenProgram reads those manifests compatibly (`plugins/manifest.py`) and mounts their contents through a `ProgramContext` owned by `plugin:<name>`, exactly as it mounts an application; hooks are shell commands subscribed through `ctx.gate` / `ctx.on`. No plugin code runs in the worker. A manifest that names code (`python`, `module`, `setup`, `main`, `tools`, `client`, `web`, `sidebar`, a `module:name` hook mapping, a Hermes `__init__.py`) is refused at install and at load with the message to package it as an application (`openprogram programs install <dir>` with an `application.json`). Code that adds tools or a UI is an application, not a plugin. The plugin lifecycle is described in [Plugin Runtime](../integrations/plugin-runtime.md).

## 5. Exposure tiers

Every registered entry has one exposure tier, `programs._host.runtime.Tier`, kept on the tool as `_tier` and set with `set_tier`:

- **resident**: its schema is in every tools array.
- **deferred**: only its name is listed; the model loads the schema with `tool_search` when it needs the entry.
- **hidden**: callable from Python, never shown to the model (`expose=False`).

Whether a call waits for the user's approval is the entry's approval policy (`requires_approval`, possibly a function of the arguments), which applies on top of any tier: `web_use` is deferred and needs approval.

Tiers are assigned by kind:

- **Tools** are resident when they are in `RESIDENT_TOOLS` (the default set minus its cold, large-schema members, plus `tool_search` and `job_output`) and deferred otherwise; a tool may also register itself deferred (`defer=True`).
- **Application entries** are deferred: built-in and installed applications, external harnesses and the user's packages. `ProgramContext._adopt_tools` sets the tier when an application's context registers an entry, so a reloaded package or a newly installed application is deferred too.

An application's entries become resident for a session while the application is open in a window of that session. The signal is the session's application bindings (`programs/_host/ui/bindings.py`, the `resource_bindings` table): an `open` that names the session binds one of the application's instances — the App's window through `POST /api/applications/<id>/open` with `session_id`, or the Agent's own call through the `application.<id>` provider — and `release` or `POST /api/applications/<id>/close` removes it. At the start of each turn `TurnBindings` reads `open_application_ids(session_id)` and installs it (`_runtime.install_open_applications`). `split_tools_for_dispatch` and `tool_search` read the tier through `resident_now`: a resident entry, a deferred entry the session loaded with `tool_search`, or a deferred entry whose owner `application:<id>` is open goes into the tools array. The registered tier never changes; a resident copy for one request is `as_resident`.

`_defer` mirrors the tier (`True` exactly for deferred) for the readers that price and persist the tools array. `openprogram programs list` and `/api/plugins/inspect` show every entry's tier.

## 6. User directory

The user's Programs live in one directory per profile, `~/.openprogram/programs/` (`~/.openprogram-<profile>/programs/` for a named profile). `openprogram/state/program_directory.py` resolves it without importing the registry:

```
~/.openprogram/programs/
  <name>/          a program source directory
  catalog.json     applications recorded by source directory, with their settings
  .runtime/        what the application runtime keeps: data/, runs/, environments/,
                   staging/, state.sqlite, and versions/ (copies made by older installs)
  .removed/        directories set aside by `openprogram programs uninstall`
```

A program source directory is a Python package (`__init__.py` with `PROGRAM_ENTRIES`), an application directory (`application.json`, its UI and an optional `backend.py`), or both. Names starting with `.` or `_`, symbolic links and plain files are not scanned. One scan of the directory (`program_directory.program_dirs`) serves both loaders:

- A **package** loads through `programs/_host/packages.py` under its directory name, which must be a Python identifier that shadows no other module. Each package is its own Git repository; only a clean, committed checkout loads, so a passing `openprogram programs check` is what makes a change callable. A package with uncommitted edits keeps serving the version that loaded last. Its context owner is the package name.
- An **application** loads through `loader.mount` in the worker. A directory placed here without a catalog row is recorded on the next `loader.sync` (`catalog.adopt_user_applications`), unless it needs trust (a Python backend or `files.project.write`): that one waits for `openprogram programs install <dir> --trust`. An uninstalled row is never re-recorded behind the owner's back.

`catalog.json` also records applications whose source lives elsewhere, such as the repository's `examples/applications/`; they load from that directory and keep their `enabled`, `hidden` and `display_title` settings.

A harness clone (a repository with `<package>/agentics/__init__.py`) installed from git lands here as well and is recorded in `program-sources.json`; it loads through the external-harness path, owned by `external:<package>`. Nothing installed lives inside the package tree: `migrate_user_directory` moves a clone that an older installer recorded under `openprogram/programs/packages/` or `openprogram/programs/applications/` (of the running package or of the source checkout recorded as `catalog_root`) into `programs/<name>`, and rewrites its `program-sources.json` row and any `catalog.json` row that pointed into it.

The Programs watcher (`programs/_host/watcher.py`) fingerprints the top level of this directory, the files and Git state of every package and the catalog with each enabled application's source; a change re-runs discovery.

Files under `.runtime/` and `.removed/` are not Program source: role calls made from them carry no call site.

### Migration from the older layout

Earlier profiles kept packages in `~/.openprogram/workflows/` and the catalog and application runtime in `~/.openprogram/applications/`. At worker start, before anything loads, `program_directory.migrate_user_directory` moves, for the profile being started:

- every entry of `workflows/` to `programs/<entry>`;
- `applications/catalog.json` (and its lock file) to `programs/`;
- everything else under `applications/` (`data/`, `runs/`, `environments/`, `staging/`, `versions/`, `state.sqlite`) to `programs/.runtime/`.

Each item is renamed, never copied; one whose destination already exists stays in place and is logged. The emptied old directories are removed. Catalog rows that pointed into the old directories (copied versions, an application inside a package) are rewritten to the new paths. Every move is logged as one line, and a second start finds nothing to do. No settings key names either directory, so no settings change.

## 7. CLI

`openprogram programs` is the one command group for Programs (`openprogram/interfaces/cli/commands/programs.py`):

| Verb | Does |
|---|---|
| `list [--json]` | every Program: built-in tools, built-in applications, the user's packages and applications, harnesses; each with kind, owner, load state, directory, enabled flag, entries and each entry's tier |
| `run NAME [--arg k=v]` | calls a Program entry in this process |
| `run APP OPERATION [--input JSON] [--project ID]` | starts an Agent-visible application operation in the worker |
| `status RUN_ID`, `cancel RUN_ID` | inspect or cancel an application operation run |
| `check DIRECTORY [-m MSG] [--json]` | validates a package, runs its tests in the OS sandbox and commits it; validates an application directory |
| `install SOURCE [--upgrade] [--replace] [--trust]` | records a local application directory in the catalog; clones a local package repository, a git URL or `owner/repo` into `~/.openprogram/programs/<name>` |
| `uninstall NAME` | unregisters an application (its data is kept), or moves a directory of `~/.openprogram/programs/` into `.removed/` |
| `enable ID`, `disable ID` | load or remove an application's UI, resource, services and entries, built in or installed; a tool is refused |

Application verbs that change state go through the worker's owner API (`/api/applications/*`); `list` and `check` work without a worker. The REPL's `/programs` lists the same rows.

## Implementation status

1. **ProgramContext lands. Done.** `ProgramContext` and the services registry live in `programs/_host/context.py` and `programs/_host/services.py`. Every built-in Program package, every user workflow and every external harness registers through its own context, kept in the registry's owner table; unloading and hot reload dispose the context.
2. **Browser becomes an application. Done.** The browser lives in `programs/applications/browser/`; its `setup` provides the service `browser`, and the core reaches the browser only through that service and runs without it. The legacy browser tools (`agent_browser`, `browser_agent`, `playwright_browser`) and the CLI `/browser` command are gone; `web_use` is the application's one entry. See [Computer and browser use](../integrations/computer-and-browser-use.md#the-browser-application).
3. **One loader for UIs. Done.** Applications load from their own directory: the catalog records the source directory and the settings, and the digest is computed at each load. Every application, built in or installed, Python or declarative, mounts through one `ProgramContext` owned by `application:<id>`, which registers its UI, its `application.<id>` provider and its `<id>__<operation>` entries; disable and reload dispose it. Applications gained the capability `files.project.write`. Copies made by older installs (now under `~/.openprogram/programs/.runtime/versions/`) are read only when an application's source is gone.
4. **The workflow layer dissolves. Done.** `programs/workflow/` and the import path `openprogram.programs.workflow` are gone. `ask_user` is `tools/interaction/ask_user.py` and `goal` is `tools/planning/goal/`; the authoring helpers are `programs/_authoring/errors.py`, `json_parsing.py` and `reports/`. Tool names, toolsets and options are unchanged, and the Programs page still lists these Programs under `workflow/`. User workflow packages import the report helpers from `openprogram.programs._authoring.reports`.
5. **One user directory, one CLI group. Done.** The user's packages and applications share `~/.openprogram/programs/` (section 6), migrated at worker start from `workflows/` and `applications/`; `_workflow_packages.py` and `_workflow_check.py` are `_host/packages.py` and `_host/check.py`. `openprogram programs` is the only command group (section 7); `openprogram workflows`, `openprogram apps`, `programs apps`, `programs available` and the `gui` / `all` install selectors are gone. The owner API keeps its `/api/applications/*` routes and the Programs page keeps its `workflow/<name>` explorer paths, which the Web app uses.
6. **Declarative plugins and exposure tiers. Done.** Plugins carry only declarative content (section 4); a manifest that names code is refused at install and load, pip is no longer a plugin source, and plugin Web modules, pages and sidebar rows are gone. Every entry carries a tier (section 5); application entries are deferred and resident while their application is open in a window of the session. Built-in applications are enabled and disabled like installed ones, and `programs list` shows tiers and the enabled flag.
