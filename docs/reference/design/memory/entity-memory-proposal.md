# Entity memory on Git — deferred proposal

> **Implementation status:** This is a proposed entity-memory design. The
> Session-Git and Project-Git lifecycle described below is not implemented in
> the current Memory runtime. The active implementation is the
> Source/Topic/Core workspace documented in [`overview.md`](overview.md).

This page consolidates the proposed lifecycle, replay and consistency contracts. All paths, hooks and UI entries below belong to the deferred proposal, not an installation guide. The proposed history/ and context/ layout is used consistently here; older messages/ and SQLite-specific sketches are not the current storage contract. See [session storage](../runtime/session/storage.md) for current persistence. Project auto-commit requires identifying agent-owned changes; a clean starting tree alone cannot establish ownership when the user edits concurrently.

<span id="1-concept"></span>
<span id="entity-memory"></span>
<span id="entity-memory-on-git-session-git-project-git"></span>
<span id="mental-model"></span>
<span id="1-relationship-to-the-existing-dag"></span>
<span id="2-session-git"></span>
<span id="21-file-layout"></span>
<span id="23-branch-retry"></span>
<span id="3-project-git"></span>
<span id="31-concept"></span>
<span id="33-agent-file-edits-trigger-auto-commit"></span>
<span id="34-user-manual-edits-vs-agent-edits"></span>
<span id="35-sessions-not-bound-to-a-project"></span>
<span id="4-ui-entry-points"></span>
<span id="41-session-history-replay"></span>
<span id="7-comparison-with-claude-code"></span>
## Concept

Entity memory is an immutable, factual historical record backed by git storage. An "entity" is something that actually happened and can be traced back step by step.

There are two kinds of entities:

| Type | Granularity | Storage location |
|------|------|----------|
| **Session-Git** | Per conversation, one commit per turn | `<state>/projects/<project_id>/chats/<id>/` or `<project>/.openprogram/sessions/<id>/` |
| **Project-Git** | The bound user working directory | `<user-workdir>/.git/` (reuses the existing one) |

Session-Git records the conversation process (the user → LLM → tool call chain). Project-Git records the agent's actual modifications to the user's code/documents. The two are complementary: session stores "what was said", project stores "what was changed".

<span id="2-storage-layout"></span>
## Storage Layout

```
~/.openprogram/                              ← get_state_dir()
├── sessions/
│   ├── <session_id>/                        ← one Session-Git repo
│   │   ├── .git/
│   │   ├── meta.json                        title, agent_id, project_id, created_at, ...
│   │   ├── history/                         DAG node files
│   │   │   ├── 000001-u-<id>.json           user message
│   │   │   ├── 000002-a-<id>.json           assistant message
│   │   │   ├── 000003-t-<id>.json           tool result (called_by = assistant)
│   │   │   └── ...
│   │   ├── context/                         per-turn LLM context materialized view
│   │   │   └── commits/<commit_id>.json
│   │   └── workdir/                         temporary working directory for this session
│   │
│   └── locations.json                       ← index: in-project session → real path
│
├── projects/
│   └── projects.json                        project registry
│
└── memory/                                  ← abstract memory layer (see virtual-memory.md)

<user working directory>/
├── .git/                                    ← Project-Git (reuses the existing one, or auto-init)
└── .openprogram/sessions/<id>/              ← session repo bound to this project
```

<span id="3-session-git-lifecycle"></span>
## Session-Git Lifecycle

<span id="31-create"></span>
### Create

**Trigger**: lazy-init when the first message is written (`SessionStore._open(id, create_if_missing=True)`).

**Artifacts created**:
- `git init` → `.git/`
- Write `meta.json` (title, agent_id, project_id, created_at)
- Create the `history/`, `context/`, `workdir/` directories

**Attribution**: each session is bound to a project at creation time:
- A working directory was specified → bind to the real Project-Git, and the session repo lands in `<project>/.openprogram/sessions/<id>/`
- Not specified → bind to the default project (a purely logical label `project_id="default"`), and the session repo lands at the home root

<span id="32-validity"></span>
### Validity

A directory is treated as a valid session if and only if:

1. The directory exists
2. A `meta.json` file exists in the directory
3. `meta.json` parses as valid JSON

Directories that do not meet the above conditions are **skipped: not listed, no error raised**. This covers:
- Test leftovers (only a `steering/` subdirectory, no meta.json)
- Manually created unrelated directories
- Corrupted sessions (meta.json cannot be parsed)

<span id="33-title-rules"></span>
### Title Rules

The session title is the primary identifier by which a user recognizes a conversation in the list.

#### Generation strategy (highest to lowest priority)

1. **User-set name**: a title set by the user via `/rename` or UI right-click rename always takes precedence and is never overwritten.

2. **LLM-generated summary (the preferred automatic method)**: after the first round of conversation ends (the assistant reply is complete), a background thread calls the LLM to generate a descriptive 3-7 word title.
   - **Trigger**: after `finalize_turn` of the first turn, executed asynchronously
   - **Input**: the first 500 characters of the user message + the first 500 characters of the assistant response
   - **Prompt**: "Generate a short, descriptive title (3-7 words) for this conversation. Return ONLY the title, no quotes, no prefix."
   - **Model selection**: the model used by the current session (connection already established, no extra overhead); if unavailable, the cheapest available model in the system
   - **Parameters**: `max_tokens=50`, `temperature=0.3` (highly deterministic)
   - **Post-processing**: strip quotes, strip the "Title:" prefix, truncate to 80 characters
   - **Non-blocking**: executed by a background daemon thread; failures are only logged and do not affect the user
   - **Idempotent**: the `_titled=True` flag in `meta.json`; once generated, it is not triggered again

3. **Fallback — first-message excerpt**: when the LLM is unavailable or the call fails, take the first line of the first user message, truncated to 50 characters + "…".

4. **Presentation-layer fallback**: if none of the above was triggered (the session was created through a non-dispatcher entry point, such as the harness), and the title at listing time is still empty/"New conversation"/"Untitled" → display the preview (first 80 characters of the first user message) instead.

5. **No filtering of empty placeholders**: all valid sessions are shown in the sidebar, including freshly created conversations whose title/preview is not yet ready. "New chat" does not create a session — the conversation is created lazily by the backend only when the first message is sent, so a listed session always has content and there is nothing for such a filter to hide.

#### Sequence

```
User sends the first message
  → dispatcher processes the turn
  → finalize_turn:
      1. Immediately set title = first 50 characters of the first line (Fallback, ensures the sidebar is not empty)
      2. Start a background thread → LLM generates a summary → on success, overwrite title + set _titled
  → User immediately sees the excerpted title in the sidebar
  → A few seconds later the LLM title is ready → broadcast session_updated → the sidebar updates to the summary title
```

#### Design decisions

- **Why not wait for the LLM before displaying?** An LLM call takes 1-5 seconds, and the sidebar cannot be empty when the user switches to another session. Use the excerpt as a placeholder first, then update asynchronously.
- **Why use the current model?** To avoid extra API key / connection overhead. The title-generation prompt is very short (< 1200 tokens), a negligible cost for any model.
- **Why trigger only once?** To avoid the title flipping back and forth as the conversation goes deeper. The first round best represents the user's intent.
- **Why temperature=0.3?** Slightly creative but mostly deterministic. Re-running on the same conversation opener will not produce a completely different title.

<span id="34-discovery"></span>
### Discovery

When listing all sessions, there are two sources:

1. **Global directory scan**: traverse every `<state>/projects/<project_id>/chats/` folder and run validity checks one by one
2. **locations.json index**: records the paths of sessions that land inside project directories, validated one by one

The two sources are merged, deduplicated, and sorted by `updated_at` in descending order.

Display rules:
- Validity check passes → shown (including freshly created conversations whose title/preview is not yet ready; there is no empty-placeholder filter)
- Validity check fails → skipped

The sidebar and the Chats page use the same set of display rules.

<span id="35-readwrite"></span>
### Read/Write

**Write**:
- `append_message(session_id, msg)` → synchronously write `history/NNNN-<role>-<id>.json` + update the in-memory index
- `commit_turn(session_id, message)` → one git commit when the turn ends (not one per message)

**Read**:
- `get_branch(session_id, head_id)` → traverse the DAG along parent_id edges and return the rendered message list
- `get_nodes(session_id)` → raw `Call` objects (including tool-call details)
- `session_commits(session_id)` → git log (turn granularity)

**Branch/retry**:
- DAG retry → git branch (`retry-<assistant_id>`)
- Switching the DAG head ↔ git checkout

<span id="36-management"></span>
### Management

**Metadata update**: `update_session(session_id, title=..., project_id=..., ...)` → write `meta.json` + update the in-memory index

**Cache**:
- Maintain an `OrderedDict[session_id → (GitSession, SessionMemoryIndex)]` in memory
- LRU, cap=256 (configurable via env `OPENPROGRAM_SESSION_CACHE_CAP`)
- Eviction is lossless: rebuilt from disk on the next access
- Thread-safe: per-session lock + global store lock

**Project binding**:
- The `project_id` field of `meta.json`
- Sessions bound to a real project land inside the project directory (`locations.json` records the path)

<span id="37-deletion"></span>
### Deletion

**Manual deletion**: `delete_session(session_id)` →
1. Remove from the in-memory cache
2. Close the associated runtime (if any)
3. `shutil.rmtree()` the entire session directory (including `.git/`)
4. If there is an entry in `locations.json`, remove it

**Cascading effects**:
- Provenance pointers in abstract memory that reference this session become dangling
- They are automatically skipped on query via the validity check (session directory does not exist → returns None)
- No explicit cleanup of virtual-layer records is needed

**Frontend entry points**:
- Sidebar right-click menu → Delete
- Chats page (to be added: right-click delete)

<span id="38-garbage-collection"></span>
### Garbage Collection

| Scenario | Handling |
|------|------|
| Directory without `meta.json` | Skipped when listing (§3.2 validity check) |
| Has meta.json but history is empty and title is the default value | Listed; title/preview fallback applies, without filtering valid sessions |
| Long-inactive session | **Not deleted automatically** (user data, the user decides) |

Design decision: no automatic TTL. Rationale: a session is the user's conversation history, it belongs to the user as user data, and should not be cleaned up automatically by the system. If space reclamation is needed in the future, it is decided by the policy layer (user configuration), not implemented at the store layer.

<span id="4-project-git-lifecycle"></span>
## Project-Git Lifecycle

<span id="41-create"></span>
### Create

**Trigger**: `resolve_project(path, name)` — when the user binds a working directory in the UI, or when a session specifies a workdir.

**Behavior**:
- The directory already has `.git/` → reuse it
- The directory has no `.git/` → `git init`
- Register it in `projects.json`

<span id="42-write-auto-commit"></span>
### Write (Auto-commit)

At the end of a turn, if the session is bound to a real project and the agent has modified files:

```
if working_tree_clean_before_agent:
    git add -A
    git commit -c user.name="agent (<model> via OpenProgram)"
              -m "[agent <session_id>] turn <N>: <user msg first 60 chars>"
else:
    skip + UI warning (do not pollute the user's uncommitted changes)
```

Agent commits are identified by an overridden user.name/email to distinguish them from the user's manual commits.

<span id="43-read"></span>
### Read

- `ProjectGit.log(limit)` → agent-attributed commits
- `project_commits(project_id)` → the read primitive of the provenance layer

<span id="44-deletion"></span>
### Deletion

Unbinding a project ≠ deleting the git history. The user's `.git/` contains the user's own commits and must not be deleted by OpenProgram.

When unbinding:
- Remove the registration from `projects.json`
- The `project_id` of the associated session is unchanged (historical pointer)
- The session repo stays inside the project directory (it is not moved back to the home root)

<span id="5-relationship-to-abstract-memory"></span>
## Relationship to Abstract Memory

Entity memory is the **single data source** for abstract memory. The distillation pipeline reads the DAG nodes of session-git + the commit history of project-git, extracts events and relationships from them, and writes them into the timeline/graph of abstract memory.

Each abstract memory carries a `Provenance` pointer back to the entity layer:
```python
@dataclass
class Provenance:
    project_id: str
    session_id: str
    node_ids: tuple[str, ...]
    commit: str | None
    event_time: float
    ingestion_time: float
```

See [`virtual-memory.md`](virtual-memory.md) for details.


## Turn commits, replay and consistency

<span id="22-commit-timing"></span>
### Commit Timing

One commit at the end of **each turn**, not one per message — per-message commits
are too fine-grained to be useful. End of turn = when
`dispatcher.process_user_turn()` returns a TurnResult.

A turn contains:
- 1 user message
- 1 assistant placeholder → eventually filled with content
- N tool results (caller = assistant)

commit message:

```
turn <N>: <first 60 chars of user msg>

assistant: <first 80 chars of reply>
tools: read, grep × 3, list

[meta: turn took 12.3s, 18 tools, 4521 tokens]
```

<span id="24-replay-ui"></span>
### Replay UI

prev / next controls at the top of chat / on the right of the history area:

```
[← prev turn]  Turn 7 / 12  [next turn →]    [view full history]
```

- prev: `git checkout HEAD~1` + replay the UI to that state
- next: walk the reflog backward
- view full history: pop a timeline (one line per commit, click to view the message content)

At the implementation level: WS action `git_history(session_id)` returns the
commit log, `git_checkout(session_id, commit_sha)` switches to a given state, and
the dispatcher continues the next user message on top of that commit.

<span id="25-dual-write-consistency"></span>
### Dual-Write Consistency

**Main path**: the dispatcher writes the DAG.
**Mirror**: after a turn completes, all of that turn's nodes are asynchronously
serialized to the session repo and committed.

It is async because a git commit takes ~100-500ms and shouldn't block the user.
It runs in the background with `threading.Thread`; on failure it logs and does
not block.

Conflict probability is very low (one repo per session, serial commits), with a
file lock as a fallback.

<span id="26-migrating-old-sessions"></span>
### Migrating Old Sessions

On startup, the existing session store is scanned and sessions without a repo get a
one-time backfill: walk the nodes by seq and commit them out turn by turn. It
runs once, then stays incremental.



## Project metadata and presentation

<span id="32-association"></span>
### Association

```python
class Project:
    id: str
    name: str
    workdir: str               # absolute path, a directory in the user's filesystem
    sessions: list[str]        # list of session ids (who is working in this project)
    status: "active" | "paused" | "done"
    created_at: float

# Reverse association:
Session.metadata["project_id"] = "proj_xxx"   # proposed session metadata
```

A session can exist standalone (no project). When there is a project, the commits
triggered by the agent's file edits land in the project repo.

<span id="42-projects-panel"></span>
### Projects Panel

A "Projects" section in the left sidebar:

```
─ Projects ─────────
  ● Wiki Agent Refactor   2 sessions  ●  active
  ○ DAG Visualization    1 session   done
  ○ ...
  + New Project
```

Clicking a project opens the project detail page: name / workdir / associated
sessions / commit history / abstract-memory entry point.

New project flow: pick a directory → name it → create / reuse a git repo →
associate the current session (optional).

<span id="43-project-indicator-at-the-top-of-chat"></span>
### Project Indicator at the Top of Chat

If the current session is associated with a project, the top status area shows
the project name + an abbreviated workdir; clicking it goes to the project page.



<span id="5-key-invariants"></span>
## Key Invariants

1. **The DAG is the current source of truth, Git is the mirror.** A git failure
   doesn't affect the DAG. Not the other way around — git landed but the DAG not
   written is dirty data.
2. **Session-git is one commit per turn**, not subdivided by message.
3. **Project-git favors cleanliness**: the user's working tree must not be
   polluted by the agent. When there are uncommitted changes the agent skips the
   commit.
4. **Replay doesn't break the DAG**: a checkout is a read-only view; when the
   user sends a new message it forks a new branch on the DAG based on that
   commit.
5. **Abstract memory builds on entity memory**, not the other way around.
6. **The project registry is never lost to a failed read or a race.** The
   worker, the CLI and agent subprocesses all read-modify-write
   `projects.json`, so each change holds a cross-process file lock
   (`<state>/projects/.locks/.projects-registry.lock`) for the whole
   read-modify-write. A write goes to a unique temporary file and is published
   by rename, so a reader sees either the old or the new file whole. A read
   error raises instead of returning an empty registry, because the next write
   would erase every project and session binding. A file that is not a JSON
   object is moved aside as `projects.json.unreadable-<time>-<id>` for
   recovery, and the registry starts over from empty.



<span id="6-risks"></span>
## Risks

- **Async git commit failure**: invisible to the user, silently dropping data.
  Mitigation: background-thread retry on failure + validate DAG seq vs git commit
  count on startup, trigger a backfill on mismatch.
- **Project workdir is not a git repo**: auto `git init` on the agent's first
  commit. A repo the user already has under git: reuse directly.
- **Multiple sessions concurrently editing the same project**: a file lock
  serializes project commits. In the extreme case it degenerates to a queue.
- **Semantics of replay + continuing to chat**: after the user goes back to turn
  5 and sends a new message, the result is a fork rather than an overwrite of what
  came after (the DAG already has this concept via retry), which maps naturally to
  a git branch.



<span id="8-relationship-with-the-existing-commit-chain"></span>
## Relationship with the Existing commit chain

No conflict. The commit chain is "the context view the LLM sees", while git is
"the history that actually happened" — two layers:

- DAG nodes (the raw source of truth) → git commits (persisted mirror)
- the ContextCommit chain (the LLM's view) → not in git (derived, recomputable)

A commit can be selectively exported to git (e.g. the user wants to see "what the
LLM saw back then"), but it's not mandatory.



## External comparison boundary

The earlier proposal compared replay with Claude Code. No verified implementation evidence accompanies that comparison, so it does not establish how Claude Code stores or restores sessions. This proposal specifically exposes Git log/diff history; any external feature comparison must be verified before it informs implementation.


## Appendix: Proposed Build Order

The work splits into five independently verifiable pieces:

1. **Session-git infrastructure** — module `openprogram/state/memory/session_git/`
   (init / commit / log / checkout wrappers); hook at the end of
   `dispatcher.process_user_turn` running the commit on a background thread;
   backfill script turning old sessions into git repos; WS actions
   `git_session_log`, `git_session_checkout`.
2. **Project schema + UI** — Project registry `projects` (id, name, workdir, status, …);
   `project_id` in session metadata; WS `list_projects`, `create_project`,
   `add_session_to_project`; Projects section in the left sidebar.
3. **Project-git auto-commit** — project commit hook after a turn for sessions
   with a bound `project_id`; commit when clean, warn when dirty; UI warning
   banner.
4. **Replay UI** — prev/next at the top of chat + timeline view; WS action
   calling git_checkout to replay history.
5. **Data migration** — backfill over all existing sessions; existing git
   projects imported as Projects.
