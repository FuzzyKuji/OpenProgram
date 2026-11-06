# Open applications from the new tab page

Open **Applications** in the sidebar to see every application, built in and installed, in one list: its icon, title, version and scope, and its one-sentence description. Filter the list with **All**, **Built in** and **Installed**. Each row has **Open** when the application has a window of its own, an enabled switch and a **⋯** menu with **Show in Abilities**, **Hide from new tab** (or **Show in new tab**), **Update from source** (it shows the source directory) and **Uninstall**, which asks first and keeps the application's data. **Install…** opens the install form, which requires explicit trust for Python backends and for the `files.project.write` capability; **Update from source** opens the same form filled with the source, so review the source before submitting. **Abilities → Programs** lists the same applications under **Applications**, together with the built-in ones and the installed programs that have no UI, and lists the built-in tools under **Tools**. Like Tools, Applications is a plain folder view: one folder per application directory, named by that directory (`browser`, `calculator`, `auto_research`) and sorted alphabetically. Expanding a folder shows its real subfolders and source files; an application that lives inside an installed package is that package's subfolder, such as `auto_research/app`. An application's call logic there is the union of the Agent entries it registers, such as `web_use` for `browser`. Selecting an application shows the same icon, title and description as the Applications page, with its directory name, kind and version; **Open** when it has a window and **Use in chat** when it has a single Agent entry; the enabled switch; the entries the Agent can call, each with its one-line description; and details such as its location, window and permissions. A tool lists its parameters instead. An application the Agent cannot call says so in one line: a UI-only application only opens as a window, and a package that only exports Python functions for other Programs is a Python library. The call logic is folded at the bottom; its summary gives a short count, and it expands to the call tree and graph. A source file inside a package shows its call logic directly.

Applications are Programs, managed with `openprogram programs`. An application directory can live in your Programs directory, `~/.openprogram/programs/<name>/`, or anywhere else. Registrations live in `~/.openprogram/programs/catalog.json`: each records the application's source directory and its enabled, hidden and display-title settings; the application loads from its source and nothing is copied. What the runtime keeps for applications (business data, run records, Python environments) is in `~/.openprogram/programs/.runtime/`.

An installed application appears beside Files, New chat, Browser and Terminal.
Click its name to open its own interface in a tab. Opening it again selects the
same instance. Closing the tab does not cancel its operations.

Applications contain standard HTML, CSS and JavaScript, optionally backed by
Python operations. Their interface does not have to use OpenProgram components.
Bundle frontend dependencies locally and use relative asset URLs, including
relative JavaScript module imports. Remote scripts, direct owner API access,
nested frames and form navigation are blocked. Web UI code runs in a sandboxed
iframe with an opaque origin. A resource URL authorizes reads of only that
application's UI directory at the content digest it was opened with; it is not
an owner credential.

## Install and open

With the local OpenProgram worker running:

```bash
openprogram programs install /absolute/path/to/application
openprogram programs list
```

`install` records the directory; the application loads from it, so keep the
directory where it is. `list` reads the catalog and each source directly and
works without a worker; each application row shows its id, its state
(`enabled`, `disabled`, `error`), the directory it loads from and its
Agent entries with their exposure tier (`deferred` for application entries).
`openprogram programs list --json` gives the same rows as JSON, with a `tiers`
map per row.

An application directory placed directly in `~/.openprogram/programs/` needs no
`install`: the worker records it the next time it scans that directory. One
that needs trust (see below) is listed as `needs trust` until you install it
with `--trust`. `openprogram programs check DIRECTORY` validates the manifest,
the package tree and the backend's declared operations without recording
anything.

Python backends execute trusted local code with your operating-system account,
and `files.project.write` lets that code create and replace files in the bound
project. Review the source and dependencies, then pass `--trust` to authorize them:

```bash
openprogram programs install /absolute/path/to/application --trust
```

`openprogram programs disable ID` removes the application's interface, resource,
services and Agent entries and cancels its active operations; `openprogram programs
enable ID` loads it again. Both work for the built-in application `browser` too:
`openprogram programs disable browser` takes away the browser service and
`web_use` until it is enabled again, and `openprogram programs disable workflow_recording`
takes away [workflow recording](workflows/recording.md): the composer's **Record a workflow**
item and the recording routes. The built-in application `office_editor` (**ONLYOFFICE**)
opens Word, Excel and PowerPoint documents in the file window; `openprogram programs disable office_editor`
turns that off, and those files then offer only the original-file download. Both have a window of their own, opened with **Open** on their row or their tile on the new tab page. The ONLYOFFICE window starts a blank document, spreadsheet or presentation at the top of the current project and lists the Office documents already in it; the Workflow Recording window starts a recording without going through the composer. The built-in application `meeting` ([Meetings](meetings.md)) records a call on this computer, transcribes it and summarizes it in a new chat; `openprogram programs disable meeting` turns it off. On the **Applications** page the built-in applications are listed as built in; each one's
enabled switch does what `enable` and `disable` do. The setting is saved in `catalog.json` and
holds across worker restarts. Tools (`bash`, `read`, `goal` …) are always given
to the Agent and cannot be disabled. A git URL or GitHub `owner/repo` that holds an
application is cloned into `~/.openprogram/programs/<name>/` and recorded
the same way (`openprogram programs install owner/repo --trust`).

A plugin cannot carry code: a Claude Code, Codex, OpenCode or Hermes package
that adds tools or a screen of its own is installed as an application instead
(add an `application.json`), see [Plugins](plugins.md).

The new tab page refreshes its application list when focused and every ten
seconds. Project-scoped applications use the current selected project when
opened; changing the conversation project does not rebind an existing instance.
With no current project, a single saved binding is reused. First use or multiple
saved bindings opens a project chooser, which also accepts a new folder.
Global applications share one instance for the current owner. Project instances
have separate business data.

See the [calculator](https://github.com/FuzzyKuji/OpenProgram/tree/main/examples/applications/calculator)
and [PDF editor](https://github.com/FuzzyKuji/OpenProgram/tree/main/examples/applications/pdf_editor)
examples. The PDF editor reads, annotates and reorganizes the PDF files of the
bound project and uses your configured model only when you ask for a summary.

## Application package

Place `application.json` in the package root:

```json
{
  "id": "local.notes",
  "title": "Notes",
  "description": "Keeps notes per project and summarises them on request.",
  "icon": "notebook-pen",
  "version": "1.0.0",
  "scope": "global",
  "dataSchema": 1,
  "ui": {"root": "ui", "entry": "index.html"},
  "capabilities": ["storage.app", "model.invoke"],
  "backend": {"kind": "python", "entry": "backend:operations"},
  "operations": {
    "summarize": {
      "agent": true,
      "input": {"type": "object"},
      "output": {"type": "string"}
    }
  }
}
```

`title` and the optional `description` are what the New tab page, the
Applications page and Abilities → Programs show for the application: write the
description as one plain sentence, on one line, of at most 300 characters. A
Program package without `application.json` is shown by the first `# Heading` of
its `README.md` and the first sentence of the paragraph under it, or by its
directory name when it has no README.

The optional `icon` names the glyph that picks the application's icon on the New
tab page, the Applications page, Abilities and the application's tab. Pick one of `calculator`, `book-open`, `file-search`, `file-text`, `file-pdf`, `telescope`, `notebook-pen`, `table`, `chart-column`, `database`, `image`, `music`, `video`, `map`, `calendar`, `globe`, `code`, `terminal`, `mail`, `message-square`, `list-checks`, `languages`, `pen-tool`, `palette`, `sigma`, `flask-conical`, `briefcase`, `bot`, `sparkles`; any other name, or none, shows the generic application tile in a colour taken from the application's id.

`ui.root` is relative to the package; `ui.entry` is relative to that directory.
Keep Python and private configuration outside `ui.root`. The optional backend
exports a dictionary of callables. Each callable receives `(input, context)` and
returns a JSON value, synchronously or asynchronously. Input and output use JSON
Schema. Only operations with `agent: true` are callable through the Program client.

Supported capabilities:

| Capability | Grants the backend |
|---|---|
| `storage.app` | `context.load()` and `context.save()`: the instance's own saved state |
| `model.invoke` | an ambient Runtime for `llm()` and `agent()` |
| `files.project.read` | `context.read_file(relative_path)` inside the bound project |
| `files.project.write` | `context.write_file(relative_path, content)` inside the bound project; needs a Python backend and `--trust` at install |

They restrict the host bridge, not the operating-system permissions of trusted
Python code. Exact pinned requirements can be listed in
`backend.dependencies`, such as `["package-name==1.2.3"]`. Each application
gets one Python environment per set of pinned dependencies, created on first
use; it also uses the installed host framework and its dependencies. Python
backends are checked in a separate process before registration. Merely listing
applications does not import their code.

## Browser and Python APIs

The host provides `window.openprogramApp` inside the application page:

- `load()` returns `{value, version}`; `save(value, version)` saves only if that
  version is still current. Reload after a concurrent-write error.
- `run(operation, input, requestKey)` returns a durable run record. Reuse the same
  request key when retrying the same submission; different input with that key
  is rejected.
- `runs()` lists recent runs; `status(id, after)` returns status, result, error,
  pending question and events after a sequence cursor.
- `cancel(id)` cancels execution; `answer(id, requestId, answer)` answers its
  current question. Runs from another instance are inaccessible through this bridge.

Python operations receive `context.load()`, `context.save(value,
expected_version=...)`, `context.progress(value)`, `context.ask(question)`, and
`context.read_file(relative_path)` and `context.write_file(relative_path,
content)`. File access requires the declared capability and a bound project.
`write_file` takes text or bytes and a path relative to the project root. It
refuses a path that resolves outside the project, symbolic links included, and
any path into `.git`. It writes a temporary file beside the target and renames
it over the target, so readers never see a partial file, and returns the
written `path` and `bytes`. Model-enabled operations can call the existing `llm()` and
`agent()` APIs with an ambient Runtime; model credentials stay in the backend.
Use `context.ask()` for application questions. Runtime workflow interactions
that require predeclared durable waits retain their existing requirements.

Programs use the same operations:

```python
from openprogram.programs._authoring.application_client import run, status

job = run("local.notes", "summarize", {"text": "..."}, request_key="summary-1")
print(status(job["id"]))
```

Equivalent CLI entry points are `openprogram programs run APP OPERATION
--input JSON` (with `--project ID` for project scope), `openprogram programs
status RUN_ID`, and `openprogram programs cancel RUN_ID`.

## Persistence and lifecycle

An application runs from its source directory. When it loads, the host computes
the content digest of that directory (ignoring `.git`, `node_modules`,
`__pycache__` and `.venv`); the digest identifies the version that pages and
the resource provider were opened with. The worker watches the source: an edit
reloads the application with a new digest, so a reopened page serves the edited
interface and new operations run the edited backend. A page or a resource
`open` from before the edit is refused with its older digest; reopen it.
Already-running operations keep running. An edit that changes `dataSchema` or
`scope`, or adds a Python backend or `files.project.write` to an application
installed without trust, stops the application from loading until you install
it again. Registrations made before applications loaded from their source keep
working: they load from their recorded source directory, and the copied
versions under `~/.openprogram/programs/.runtime/versions/` are used only if
that directory is gone.

Business state is stored separately from code and conversations. Each instance
has its own SQLite state, with a 4 MiB JSON value limit. Events have a 1 MiB limit.
Execution status uses the existing execution store; model call records use the
existing session-node writer under application run storage.

Stopping the worker interrupts an unfinished Python function; a restart reports
it as interrupted. Arbitrary Python stacks are not automatically resumed.
Persist incremental progress and explicitly start another operation after
reviewing the interruption. A schema or scope change is rejected before
activation; automatic data migrations are not supported in this version.

```bash
openprogram programs uninstall local.notes
```

Uninstall removes the menu entry and cancels active operations, retaining saved
data and the registration's schema/scope compatibility identity.
Reinstalling a compatible package restores that data; incompatible reinstallation
is rejected before activation. The owner API also supports `enabled`, `hidden`
and `display_title` through `PATCH /api/applications/{id}`. These are distinct:
hiding an entry does not cancel a task; disabling it does.

Standalone deployment, non-Python backend adapters, MCP Apps compatibility and
embedding native operating-system GUI windows are not implemented.

Project-scoped operations resolve the bound project ID before starting and before
reading a project file. Moving the project keeps the same application instance
and saved data. A missing, replaced, or unverified location blocks new operations;
saved application data remains readable.

## Use an application as a resource

Enabled applications automatically appear as `application.<id>` in
`resource(action="describe")`. Installation, disable, update and uninstall
are reflected without restarting the worker.

Each operation marked `agent: true` is also an Agent entry named
`<id>__<operation>`, with characters other than letters, digits, `_` and `-`
replaced by `_` (`local.notes` and `summarize` give `local_notes__summarize`).
It takes the operation input as `input`, plus `project_id` for a
project-scoped application, waits for the run and returns it. Entries need
approval, like the `resource` tool, and are deferred: the model sees their names
and loads a schema with `tool_search` when it needs one. While the application
is open for a conversation, its entries are resident in that conversation: their
schemas are sent with every request. A run that is still
waiting on a question is returned with its id, for `status`, `answer` or
`cancel` through the resource. Operations marked `agent: false` have no entry. `open` accepts `project_id` for
a project-scoped app and associates the instance with the calling session; that
association is what makes the application open for the conversation. The owner
API does the same for a window: `POST /api/applications/{id}/open` with a
`session_id` associates it, and `POST /api/applications/{id}/close` with
`instance_id` and `session_id` releases it.
`observe` returns instance state and recent runs; `act` accepts a declared
Agent-visible operation and a stable `request_key`. Use the `instance_id` and
`digest` returned by open. Updated packages reject an older digest.

`status`, `cancel` and `answer` require a run belonging to that exact instance.
`save` uses the expected storage version when `storage.app` is declared.
`release` removes the session association, preserving the instance, data and
running operations. Hiding its view also leaves operations running. The
Resources view and top tab open the same instance in the existing sandboxed
application frame. No separate frontend adapter is needed.

Generate a runnable starter package through `POST /api/applications/scaffold`
with `path`, `app_id` and `title`, available through the
[framework tool](framework-control.md). The parent directory must exist and
the target directory must not exist. The package separates `backend/operations.py`,
`ui/index.html` and `application.json`; its UI and Agent both call the declared
read/save operations. Review and install it through `/api/applications/install`
with the source path and `trust: true`. Extend its backend and manifest to expose
additional operations; do not implement business changes only inside UI events.
