<div id="session-data-model"></div>

# Data model

## On-Disk Layout

Conversations live in the folder of the project they belong to. Every
project, the home project (id `default`) included, owns one folder:

```
<state>/projects/
├── projects.json                      # project registry
├── <project_id>/                      # one folder per project; `default` is the home project
│   ├── settings.json                  # project defaults
│   ├── memory/                        # the project's memory workspace
│   └── chats/
│       ├── <session_id>/              # session Git repository
│       │   ├── .git/                  # session repository metadata
│       │   ├── meta.json              # session metadata and active DAG head
│       │   ├── history/               # one JSON file per DAG node
│       │   ├── context/               # persisted context artifacts
│       │   └── workdir/attachments/   # uploaded files for this session
│       └── .file-recovery/<session_id>/<turn>/ # per-turn file undo recovery
├── .chats-index.json                  # registry (summary cache)
├── .chats-locations.json              # durable session-id → repository path map
├── .migration/                        # migration journal and staging state
├── .deleted/                          # durable delete intents
└── .locks/ / .session-locks/          # inter-process coordination
```

The store root is `<state>/projects`, where `<state>` is OpenProgram's state
directory. A session is placed at `<project_id>/chats/<session_id>`; a session
bound to no project belongs to the home project and lands under
`default/chats/`. The store's own bookkeeping sits in hidden entries of the
same folder, so a listing shows only the registry and the project folders.
A store opened on any other root (application runs, an embedding host) uses
the same `<project_id>/chats/<session_id>` placement.

Assigning a conversation to another project rebinds it in the registry and
updates `meta.json`; a conversation with no history yet also moves its folder.
A conversation with history keeps its folder, and `.chats-locations.json`
records where it is. `.chats-locations.json` is the durable authority while a
session is being migrated or relocated. A working folder is never used as the
primary conversation repository; the old `<project>/.openprogram/sessions/<id>/`
location is read only as a legacy migration source.

## Persistent Fields (meta.json)

| Field | Type | Registry | Description |
|------|------|--------|------|
| `id` | str | Yes | unique session identifier |
| `agent_id` | str | Yes | the bound agent |
| `title` | str | Yes | display name |
| `created_at` | float | Yes | creation timestamp |
| `updated_at` | float | Yes | last-activity timestamp |
| `project_id` | str? | No | the bound project (supplemented with the `project` name by project_map when listing) |
| `source` | str? | Yes | origin: "tui" / "web" / "wechat" / ... |
| `channel` | str? | Yes | channel type |
| `account_id` | str? | Yes | channel account |
| `peer_display` | str? | Yes | peer display name |
| `peer_id` | str? | Yes | peer ID |
| `pinned` | bool | Yes | pinned |
| `archived` | bool | Yes | archived |
| `group` | str? | Yes | group label |
| `status` | str | Yes | lifecycle status (see below) |
| `unread` | bool | Yes | unread marker |
| `sort_at` | float | Yes | a place in the project list, as the time the session sorts by; 0 = none (see operations.md, "A place in the project list") |
| `sort_since` | float | Yes | the `updated_at` the place was given at; activity past it ends the place |
| `_auto_titled` | bool | No | auto-naming idempotency marker (internal control; not stored in the registry, not returned to the frontend) |

The "Registry" column indicates whether the field is cached in `.chats-index.json`. `_auto_titled` and `project_id` are not stored in the registry: the former is an internal marker, and the latter is supplemented from the project directory mapping when listing.

## Registry-Only Fields

The following fields exist only in the registry, not in meta.json:

| Field | Description |
|------|------|
| `preview` | the first 80 characters of the last user message, maintained by truncation when a message is written |

## status Enum

| Value | Meaning | Frontend Display |
|----|------|----------|
| `idle` | idle, no turn executing | gray dot |
| `running` | a turn is executing | green spinning arc |
| `needs_input` | the agent is waiting for user input | amber dot |
| `done` | background task finished | blue dot shown together with `unread` |
| `failed` | turn execution failed | red dot shown together with `unread`; gray once opened |
| `interrupted` | the worker died mid-turn | gray dot (not run-active) |

`running` is stamped by the dispatcher when a turn starts and cleared
when it ends. A worker killed mid-turn (SIGKILL, crash) never runs that
clear, so the row would stay `running` forever and pin the chat container
at `data-run-active="true"` with no way out short of editing state on
disk. `reconcile_interrupted_runs()` therefore resets any row still at
`running` to `interrupted` on worker startup — a fresh worker has nothing
running by definition. It resets the row independently of the DAG-node
sweep in the same function, because a worker killed between the status
write and the placeholder insert leaves a running *row* with no running
*node*.

## Moving HEAD: `_set_active_head`

`webui/server.py` keeps a per-session mirror in `_sessions[sid]` holding
`head_id` and `messages`, and `_save_session` flushes both straight back
into SessionStore. A path that moves HEAD in the store but leaves the
mirror behind is therefore not merely stale — **the next save actively
reverts the move.**

`_set_active_head(session_id, head_id)` is the single correct way to move
HEAD. It writes SessionStore, re-reads the new branch into the mirror's
`head_id` and `messages`, and drops the message cache, in that order.
Every mutating path routes through it: retry, edit, sibling checkout,
deepest-leaf jump, branch checkout, branch delete, attach, and rewind.

Mutations that move HEAD are refused while a run is in flight
(`_is_run_active`), returning `RUN_ACTIVE_ERROR` with `code:
"run_active"`. Without that guard, an in-flight reply lands with its
predecessor pointing at a branch the user already left; branch delete is
worse still, since the tail being deleted may be the one the turn is
writing into.

## In-Process Cache (`_sessions` dict)

`SessionStore` holds lazy `(GitSession,
SessionMemoryIndex)` pairs. `GitSession` owns file and Git operations; the
memory index is rebuilt from `history/` and `meta.json` and tracks DAG nodes,
edges, and the active head. It is evicted by the bounded LRU cache and can be
invalidated when a subprocess writes the repository.

Uploaded browser attachments are copied into
`<session repository>/workdir/attachments/` before dispatch. Their message
markers retain the saved absolute path, and the copy is committed with the
session repository at turn end. Inbound channel files use the channel
attachment roots under `<state>/channels/*/accounts/*/attachments`; those
roots are separately readable by the attachment path policy. The
`.file-recovery/<session_id>/<turn>/` tree is ordinary per-turn file undo
recovery and is kept outside the session Git repository. During legacy project
migration, session data and any existing recovery tree are staged under
`<state>/projects/.migration/staging/`, verified, then published into the
central destination's sibling `.file-recovery` tree; `.chats-locations.json` is
updated only after publication.

Historical attachment markers retain their original absolute path. The
attachment UI, file reader, and `send_file` path resolution may rebase only the
exact legacy shape `<project>/.openprogram/sessions/<session_id>/workdir/attachments/<relative>`
to the unique current repository for that same session id. The rebased path
must remain under an allowed attachment root and cannot escape through `..` or
a symlink; arbitrary old paths are never remapped.

## Interface

```python
class SessionStore:
    def create_session(session_id, agent_id, *, title="", source=None, **meta) -> None
    def get_session(session_id) -> dict | None
    def update_session(session_id, **fields) -> None
    def delete_session(session_id) -> None
    def list_sessions(*, limit=100, offset=0, **filters) -> list[dict]
    def get_branch(session_id, head_id=None) -> list[dict]
    def append_message(session_id, msg) -> None
    def latest_user_text(session_id) -> str | None
```

See [operations.md](operations.md) for the full behavior of each method.
