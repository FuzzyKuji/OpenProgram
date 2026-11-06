# Built-in tools

See [tool permission modes and live changes](permissions.md) for approval behavior and changes during a task.

OpenProgram ships a set of functions registered as tools that the model calls directly in chat. This page lists them one by one, following the `openprogram/programs/tools/` directory: what each tool does and which keys or local dependencies it needs. Most tools require zero configuration; the ones that need keys cluster in web search and images.

## Files and code

| Tool | What it does | Requires |
|---|---|---|
| `read` | Read file contents | Nothing |
| `write` | Create a file or overwrite one wholesale | Nothing |
| `edit` | String replacement inside a file | Nothing |
| `apply_patch` | Structured multi-file patches in Codex / OpenClaw format | Nothing |
| `list` | List directory contents | Nothing |
| `glob` | Find files by filename pattern | Nothing |
| `grep` | Content search; prefers ripgrep, falls back to Python re without rg | Nothing (`rg` makes it faster) |
| `semble_search` / `semble_find_related` | Semantic + lexical code search returning ranked code blocks | Included in every supported release; source developers install the `search` extra through the locked project environment |
| `lsp_diagnostics` / `lsp_references` / `lsp_definition` | Type-checker errors, real call sites, and true definition sites from a language server — see [Language server tools](lsp.md) | `pyright` for Python, `typescript-language-server` for TypeScript (the tools name the install command when one is missing) |

### Document versions

For Word, PowerPoint, PDF, images, and other binary files, the model can generate a separate temporary result and publish it with `write(file_path="/absolute/final.docx", source_path="/absolute/staged.docx")`. `source_path` and text `content` are mutually exclusive. The source must be a regular local file of at most 64 MiB. Existing targets must first be read; binary reads return metadata and establish the same freshness check as text reads.

Publishing during a conversation records complete before/after bytes in that turn's file history. The record survives reopening the conversation and restarting the application. Undo and reapply use these saved versions and refuse to overwrite conflicting later changes. New files can also be undone. This does not require a Git repository in the project folder.

A failed later history commit preserves the previously published version. If a write is interrupted before its result is recorded, file history reports that the result is unconfirmed and blocks exact recovery; it does not assume the operation succeeded or that no file changed. Corrupt history blocks further recorded writes instead of replacing the history with an empty record. After a failed initial attempt, reread the current file before retrying. Versions are retained with the turn and follow its existing history retention policy. New local document generators use the same `source_path` publication interface; they do not need a separate version store.

Binary versions preserve formatting and embedded media, but the current Review pane does not compare document layout or show Word tracked changes. Ordinary shell commands that overwrite the final file directly are not recorded as exact turn mutations. Previously unrecorded versions cannot be reconstructed from a file card or command output; scripts should write a separate result and use `write` to publish it.

Project files open in Preview. For supported UTF-8 text files, choose Edit to change the file; changes save automatically, and Ctrl/Cmd+S can flush immediately. Switching Preview and Edit preserves the editor's undo history. History shows retained before/after versions and can restore a selected version. If a save fails or the disk file changes elsewhere, the draft remains available for retry, export, or explicit discard. Closing a file waits for its pending changes; a failed save keeps the tab open. Chat attachments use the same preview window in read-only mode.

Manual changes made through the project file editor also retain before/after bytes, independently of conversation history. Each successful write is published immediately. Consecutive changes from the same editor are grouped for at most five minutes; closing a group or detecting an intervening external change starts another version. Restoring a retained version creates a new history entry and checks the current file revision before overwriting it. Project-owned history remains readable while a project's disk is disconnected; writing and restoring require an available project location. It follows the registered project when its location changes. The document API accepts bounded binary content up to 64 MiB; this does not by itself provide an editor for every binary format.


PDF preview provides page navigation, zoom and text search; searches cover the first 500 pages and state that limit for longer documents. PSD preview shows the saved composite and layer names for 8-bit RGB files, and TIFF preview shows the first page. These decoders accept at most 64 MiB and bound the rendered image size. Common images open in preview by default; audio and video use browser playback controls, with codec support depending on the browser. Damaged or unsupported files retain an original-file download. Previewing a retained history version uses its retained bytes. Decoder assets are local and load only when the corresponding format is opened. These preview modes do not edit PDF, PSD, TIFF, audio or video files.

Office support is the built-in application **ONLYOFFICE** (`office_editor`) and an optional local installation shared by presentations, documents and spreadsheets. While the application is disabled on the **Applications** page, an Office file shows that the editor is turned off and offers only the original-file download; nothing is installed or downloaded. The default App and runtime do not bundle it. Opening an Office file without the component displays Install and Cancel; no download starts until you choose Install. The download is about 699 MiB and includes ONLYOFFICE resources, fonts, licenses and source materials. Files are processed locally. Installation verifies the pinned archive and all resource files before selecting a complete version. A failed installation can be retried; existing installations remain available. On success, the current document opens automatically without restarting the App. Cancel leaves the original-file download available, and Installation options lets you choose again. The local Office host is unavailable through remote application access. PDF viewing does not require this component. DOCX, PPTX, XLSX, ODT, ODP and ODS open in the file window ready to edit; there is no separate Preview and Edit switch. A centered status shows resource preparation and document opening. Closing during startup cancels the pending editor; a startup failure offers Retry. Editing starts once the native editor becomes writable; changes save automatically. Switching tabs, split layouts or History retains the current editor and its native undo history. Closing waits for pending input and publication; a failed write retains the document for retry. History previews are read-only and restoring a version creates a new retained version. Legacy DOC, PPT and XLS files can be explicitly converted to a new DOCX, PPTX or XLSX path; the original is preserved and an existing destination is rejected. Attachments remain read-only, and the original-file download remains available when the editor cannot load. These windows do not provide semantic Office redlines.

Static PNG, JPEG and WebP files support Edit with crop, rotation, drawing, shapes and text. Changes save automatically through the document history controller; switching Preview, History, tabs or routes preserves native undo/redo. Failed publication keeps the editable draft available for retry, and closing waits for export. Convert to PNG creates a separate file and rejects an existing destination. Animated PNG/WebP and 16-bit PNG remain read-only. Editing accepts at most 64 MiB, 16 million pixels and 16,384 pixels per side; unsupported or damaged input retains the original download. Image editing exports rendered pixels and does not promise preservation of embedded metadata. Attachments and historical previews remain read-only.

The same History view combines manual edits and confirmed model file changes for the project-relative file. Model entries read the retained before/after bytes from the original session checkpoint; they do not copy the session into a second archive. Restoring one version changes only this file and creates a new manual history entry after checking the current revision. Archived sessions retain their file history; permanently deleting a session makes its model versions unavailable. Manual history remains independent. Older session history is indexed in bounded batches: Continue loading history advances the next batch, and incomplete or unverifiable history is labeled explicitly. Legacy paths are included only when their project ownership can be established. Moving a project does not change the identity of newly recorded file history; offline versions remain readable, while restoration requires an available project location.

## Execution

| Tool | What it does | Requires |
|---|---|---|
| `bash` | Run a shell command and return its output and exit code; a command still running after its wait keeps running as a session | Nothing |
| `write_stdin` | Wait for more output from a session `bash` left running, interrupt it, or type into it | Nothing |
| `execute_code` | Run a Python snippet in an isolated subprocess | Nothing |

`execute_code` returns stdout, stderr and the observed exit code. A nonzero exit or timeout is an error result; partial output remains available to diagnose the failure. Success requires a zero exit code. Each call uses a fresh Python subprocess.

### Commands that keep running

`bash` waits up to `yield_time_ms` (default and maximum 30000 ms, minimum 250 ms) for the command to finish. A command that finishes in time returns its output (stdout and stderr together) and `Process exited with code N`. A command still running then keeps running in the background, and the result says `Process running with session ID <id>`, with the output so far. Servers, watchers and long builds work this way; no separate start step is needed.

`write_stdin(session_id, chars, yield_time_ms)` reaches that session:

| `chars` | Effect | Wait |
|---|---|---|
| empty | Writes nothing and returns new output, or the exit code once the command ends | 5000–300000 ms, default 5000 |
| `"\u0003"` | Interrupts the command, like Ctrl-C | Default 250 ms |
| anything else | Typed into the command as is; end a line with `"\n"` | 250–30000 ms, default 250 |

Typing needs a session started with `bash(..., tty=true)`, which runs the command in a pseudo-terminal (local backend on macOS or Linux). Without `tty` the command's stdin is closed, so a command waiting for input ends instead of hanging, and only the interrupt is accepted. The output of a call is kept up to 1 MiB, its first and last halves when longer.

When a background command ends on its own and no `bash` or `write_stdin` result has shown the agent that exit, the conversation gets a notice turn saying which command ended, its exit code and its last output. A conversation in the middle of a turn gets it once that turn ends; a command you stop yourself sends no notice. Background commands are listed as **Background terminal** under Terminal in Resources, where you can watch their output and stop them, and in Activity. A command's record and output are deleted a day after it ends, or a day after its status became unknown.

A conversation runs at most 64 commands at once. Starting another stops the least recently used one, never one of the eight most recently used, and the result names the command it stopped. Cancelling a turn stops a command that is still in its first wait; commands already in the background keep running.

Polling a session or interrupting it is never asked about, since `bash` already ran the command. Typing into a session follows the permission mode, like `bash`.

### One-shot command directories

`bash` starts a new shell for every call. Use the optional `workdir` argument to select the starting directory for that call, for example `bash(command="npm test", workdir="apps/web")`. This is tool-call notation; the ordinary Python export is an AgentTool, not a direct shell function.

Local relative paths resolve from the currently bound worktree, or the host process directory when no worktree is bound. Absolute paths are also accepted. Paths are literal: `~`, environment variables and shell expressions are not expanded. Omit `workdir` to retain the existing worktree/backend default. A directory change or `export` inside one command does not affect another call. `workdir` does not change the worktree binding or the base used by file tools.

Missing, non-directory or denied workdirs fail without running the requested command; the tool does not create them or fall back to a different location. Selecting a directory does not grant access to it. Under a local sandbox policy, explicit workdirs must already satisfy the original workspace's read/write policy, including symlinks and extra authorized roots. Execution remains inside that original sandbox boundary. An unavailable configured sandbox is not bypassed for an explicit workdir.

SSH and Docker interpret explicit workdirs as POSIX paths in the backend filesystem, not paths on the host. Relative remote paths require an absolute POSIX worktree binding. A guarded directory change prevents the command list from running if that directory is unavailable; Docker does not create the requested directory via `-w`. When a host sandbox policy is active, explicit remote workdirs are refused until backend-native path authorization is available. Omitting `workdir` preserves the existing backend behavior.

Results include the selected local starting `cwd`, or `requested_cwd` for remote paths whose canonical location is not independently observed. This is not an ending-directory report or a promise of persistent shell state. `bash` does not control the Desktop integrated terminal; that is `terminal_use`.

## Web

| Tool | What it does | Requires |
|---|---|---|
| `web_search` | Keywords to a list of relevant URLs, multiple backends | See the backend table below |
| `web_fetch` | Fetch a URL and convert it to readable text | Nothing (`trafilatura` gives cleaner extraction) |

`web_search` backends and keys (arXiv and DuckDuckGo need no key and are always available):

| Backend | Environment variable |
|---|---|
| DuckDuckGo / arXiv | None |
| Brave | `BRAVE_API_KEY` |
| Exa | `EXA_API_KEY` |
| Firecrawl | `FIRECRAWL_API_KEY` |
| Google PSE | `GOOGLE_PSE_API_KEY` + `GOOGLE_PSE_CX` |
| Jina | `JINA_API_KEY` |
| Kagi | `KAGI_API_KEY` |
| MiniMax | `MINIMAX_CODE_PLAN_KEY`, `MINIMAX_CODING_API_KEY`, or `MINIMAX_API_KEY` |
| Moonshot (Kimi) | `KIMI_API_KEY` or `MOONSHOT_API_KEY` |
| Perplexity | `PERPLEXITY_API_KEY` |
| SearXNG | `SEARXNG_URL` (address of a self-hosted instance) |
| Serper | `SERPER_API_KEY` |
| Tavily | `TAVILY_API_KEY` |
| You.com | `YDC_API_KEY` or `YOU_API_KEY` |
| Ollama | Local Ollama (signed in via `ollama signin`), or `OLLAMA_API_KEY` for Ollama Cloud |

The chat Web Search switch controls whether the model can search the web for that message. With a provider that has its own web search (the ChatGPT subscription and the OpenAI Responses API, Anthropic), the model searches through the provider: the provider runs the query, the transcript shows one "Searched the web" step per search with the sources it reported, and the answer carries a sources row with the pages it cites. The local `web_search` tool is not offered in that case. With any other provider, Gemini included (its search grounding cannot be combined with function tools), the switch offers the local `web_search` tool, which uses the backends below. Turning the switch off excludes both even in automatic tool mode. When enabled, the search schema is available immediately, including when Tools is off. Turning it on still respects the Agent's disabled tools and permissions. Tool profile choices belong to each conversation and survive tab changes and refreshes.

Search keys take effect on subsequent calls without restarting. An unavailable saved default falls back to another available provider; an explicitly named unavailable provider reports an error that gives the reason (for example the missing key) and lists the providers usable now. Jina search requires `JINA_API_KEY`. DuckDuckGo reads its no-JavaScript results page and returns the first page of hits (about ten); a bot challenge or an unreadable page is reported as an error, not as an empty search. A search without a pinned provider tries the saved default first and then every other available web backend (arXiv only when named); when all of them fail and no key-based backend is configured, the error says that a search key in Settings > Search is the fix.

`combine="race"` returns the first nonempty successful response. Named `providers` that cannot run are skipped; if none can run, the error lists each one with its reason. `combine="rrf"` retains results completed before the deadline. Total failure is reported as an error, distinct from a successful empty search. Already running requests finish under their transport timeouts.

## Desktop

| Tool | What it does | Requires |
|---|---|---|
| `computer_use_agent` | Operate a screen: application windows in the background (screenshot + Accessibility tree), Pages of the built-in browser, or a configured virtual machine. One step, a batch, Python code, or a new agent working from a brief; one approval per application | Applications: macOS with Accessibility and Screen Recording for the runtime, Linux under X11 with AT-SPI and xdotool, or Windows with UI Automation. Virtual machine: `computer_use.vm_url` |

[Computer use](computer-use.md) lists the targets, actions and approval scopes.

## Images and PDF

| Tool | What it does | Requires |
|---|---|---|
| `image_generate` | Prompt to a PNG saved on disk | Any one backend: OpenAI (`OPENAI_API_KEY`), Gemini (`GEMINI_API_KEY` or `GOOGLE_API_KEY`), fal (`FAL_KEY`) |
| `image_analyze` | Describe an image / answer questions about it (local path or URL) | Any vision-model key: OpenAI / Anthropic / Gemini (reuses configured provider keys) |
| `pdf` | Extract text from a PDF, with offset / limit paging | Bundled with the complete release (`pypdf`) |

Image tools return an error result when the selected provider is unavailable, its request fails, or an image cannot be saved. `mixture_of_agents` also returns an error result for unknown model references, when every reference fails, or when synthesis fails. A successful answer remains successful even when some references fail or its text contains the word Error. Ordinary Python `execute(...)` calls retain their string results.

## Session and collaboration

Collaboration splits into four domains, one word each — see
[agent collaboration](../reference/design/runtime/collaboration/agent-collaboration.md) §1.

| Domain | Tool | What it does | Requires |
|---|---|---|---|
| Open work | `open_work` | What the Agent still owes you in this conversation, shown in its instructions on every turn ([Open work](agents.md#open-work)) | Nothing |
| Planning | `todo_create` / `todo_update` / `todo_list` | The session planning board — a written checklist of intent (create entries, set status / owner / dependencies, list them grouped by status). Writing an entry starts nothing; the Web UI shows the plan as a [task list](../interfaces/web.md#task-list) under the reply of the turn that changed it | Nothing |
| Execution | `list_jobs` / `job_output` | List this session's background tasks and wait for or inspect a result. Result access checks the dispatching session and ancestor ownership | Nothing |
| Entity | `agent` | Spawn a new agent and collect its reply, or with `to=` hand a tracked task to an agent that already exists. `run_in_background=true` returns a task id instead of blocking; `start_from` picks where a new agent begins (`clean` / `inherit` / `SID:MSG_ID`); `archive_when_done=true` archives it once its task ends and the result has come back | Nothing |
| Entity | `list_agents` | The agent list: which agents exist, their names, addresses, sizes and busy state (`scope="archived"` shows the archived ones) | Nothing |
| Entity | `archive_agent` | Archive an agent whose work is finished: it leaves `list_agents` and refuses further `send_message` / `agent(to=)` deliveries, while `read_conversation` still reads its history and `agent(start_from="SID:MSG_ID")` still forks it. Any session may archive any agent, since archiving interrupts nothing and deletes nothing; it is one-way, and there is no unarchive | Nothing |
| Communication | `send_message` | Say something to an existing agent, addressed by `"SID:HEAD"` or by name. No task, no task id, nothing to cancel, which is why anyone may write to anyone. An empty `message` with `notify_when_idle=true` sends nothing and gets one notice with the agent's latest reply when it next goes idle | Nothing |
| Communication | `read_conversation` | Read any agent's history as a plain-text transcript, tool calls included, with turn ranges and a character budget | Nothing |

When a background agent (`run_in_background=true`, `agent(to=)` or `send_message`) finishes or fails, the conversation that sent it gets a notice turn, marked as an automated notice rather than a message from you. A conversation in the middle of a turn gets it once that turn ends, and every agent that finished meanwhile arrives in the same notice. A result already read with `job_output` (which also waits for a `send_message` reply by its `delivery_id`), or handed back by an idle `notify_when_idle` watch, sends no notice, and a cancelled agent sends none. The notice and the caller's context carry the agent's task and final reply, not its whole transcript; the caller reads the transcript with `read_conversation` when it needs the steps. A message to an agent that is still busy waits in its queue and runs once the agent is free.

`job_output` remains available when the collaboration message allowance is exhausted; reading an existing result does not consume that allowance. New Agent deliveries still obey their limits. To cancel a task, use its execution controls; API cancellation uses `execution.command` with `action="execution.cancel"` and the current execution version. This catalog has no `job_stop` tool.

| Tool | What it does | Requires |
|---|---|---|
| `program` | Invoke any registered `Agent` method | Nothing |
| `mixture_of_agents` | Ask N models in parallel, then synthesize; defaults picked from the model registry, one per provider | At least 2 providers in the model registry |
| `ask_user_question` | Ask the user 1-N questions with options | An interactive frontend; missing input infrastructure, invalid question arrays, and noninteractive contexts return tool errors |
| `chat_send` | Post a message into the chat the conversation came from. In an [ambient group](../integrations/channels.md#group-behavior) it is the only way the agent speaks; elsewhere it sends a short note before long work, and the final reply is still posted. At most 5 per turn | A chat-channel conversation (Telegram, Discord, Slack or WeChat); hidden everywhere else |
| `enter_plan_mode` / `exit_plan_mode` | Enter / exit plan mode | Nothing |
| `canvas` | Incrementally write into named blocks of a markdown file; `set` with `content=""` clears a block, while omitted content is an error | Nothing |
| `memory_*` | Read the persistent memory workspace — `memory_search` (by meaning, or an exact string), `memory_get` (what exists; one file, section or block; or the chat message a footnote cites), and `memory_update` to add or correct records. Recording the conversation is not among them: that happens in the background. There is one workspace per instance, shared by every agent and every conversation including chat channels ([Chat Channels](../integrations/channels.md#who-can-talk-to-your-bot)). | Nothing |
| `worktree_*` | Git worktrees: `worktree_create` (also opens a worktree straight from a PR — `pr="123"` / `"#123"` / a GitHub PR URL, via `gh`) / `merge` / `discard` / `list` / `keep` | git |
| `cron` | Register recurring agent tasks | Nothing |
| `list_mcp_resources` / `read_mcp_resource` / `list_mcp_prompts` / `get_mcp_prompt` | Expose MCP resources / prompts primitives to the model (the `mcp_meta` directory) | A configured MCP server (see [MCP](mcp.md)) |
| `tool_search` | Load a deferred tool on demand; its full schema is included in the next model request | Nothing |
| `help` | Read a tool guide by name (`help("self_update.prepare")`), or a tool's overview by tool name | Nothing |
| `self_update` | Install a committed change to OpenProgram itself from an isolated worktree and follow it through build, verification, rollback and repair. Actions: `status` (default), `prepare`, `retry`, `cancel`; `prepare` and `retry` always ask the owner. See [Upgrade](../install/upgrade.md#recovering-a-conversational-self-update) | A macOS source checkout of OpenProgram |

Tools with many rules keep their schema short and hand the model the rest when a call needs it, as *tool guides*. The first result of `computer_use_agent` for a target, or of `self_update`, starts with that tool's guide and lists further guides by name. A call that needs a guide it has not seen, such as the first `self_update(action="prepare")` or the first `computer_use_agent` call with `code`, is refused once and the refusal carries the guide; the next call runs. A guide counts as seen only while it is in the conversation's context, so after compaction it is delivered again when needed.

The registered `canvas` tool marks explicit validation and dependency/process failures as errors. Successful Canvas content remains successful even when the text begins with `Error:`. Plain Python `execute()` calls keep their string return values.
