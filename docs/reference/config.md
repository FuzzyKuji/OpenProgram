<span id="configuration"></span>
# Configuration reference

The keys in `~/.openprogram/config.json`, what `openprogram config` can read and write, and the environment variable roundup. For the everyday entry point to changing settings, see [Configuration and data directory](../server/configuration.md).

## What openprogram config can read and write

```bash
openprogram config list              # every setting: value, group, apply mode
openprogram config get ui.web_port
openprogram config set ui.web_port 8101
```

The settings registry is defined in `openprogram/state/settings.py` (the single source of truth; the setup wizard, the TUI settings page, and the Web settings page all render from it). Every setting is labeled with an apply mode: `live` takes effect immediately, `next_start` takes effect the next time the worker starts.

| key | Group | Meaning | Default | Applies |
|-----|------|------|------|------|
| `ui.web_port` | Ports | the single worker port for the API, WebSocket, and Web UI | 18100 | next start |
| `ui.open_browser` | Ports | whether `openprogram web` opens the browser automatically | true | next start |
| `search.default_provider` | Search | default web search provider; `auto` picks the highest-priority configured one | auto | live |
| `memory.backend` | Memory | `local` (on-disk memory) or `none` (no prompt memory, recall, automatic writes, organizer, or memory threads) | local | next start |
| `memory.writer.model` | Memory | optional `provider/model` override for background writing; empty uses the default chat agent's provider, model, and credentials | empty | live |
| `sandbox.mode` | Sandbox | `danger-full-access`, or `workspace-write` to apply the host-native sandbox to local model-driven commands: writes are limited to the working directory/configured roots, deny-read paths are blocked, and network is disabled | workspace-write | live |
| `sandbox.writable_roots` | Sandbox | extra directories a sandboxed command may write, as a JSON list | [] | live |
| `sandbox.deny_read` | Sandbox | globs a sandboxed command cannot read; defaults include credential paths. Linux cannot enforce middle-wildcard patterns such as `**/.env`: use an exact path or a concrete directory deny such as `/absolute/path/to/secrets/**` for sensitive content | see `openprogram config get sandbox.deny_read` | live |
| `sandbox.deny_write` | Sandbox | globs a sandboxed command cannot write, on top of the always-blocked function-watcher directory | [] | live |
| `sandbox.network` | Sandbox | whether a sandboxed command has network access | false | live |
| `sandbox.pass_env` | Sandbox | environment variable names to pass through besides the built-in allowlist | [] | live |
| `sandbox.unavailable_policy` | Sandbox | `refuse` fails the command when the platform backend is missing or cannot create its required isolation; `warn` runs it unsandboxed | refuse | live |
| `tools.disabled.<name>` | Tools | per-tool switch; written as members of the `tools.disabled` list | all enabled | live |
| `agent.output_style` | Agent | how replies are written; appends a block to the system prompt. See [Output styles](output-styles.md) | default | live |
| `providers.<name>` | Providers | read-only status row (configured or not); configure with `openprogram providers login` or the Web UI | — | — |

The local sandbox uses Seatbelt on macOS, bubblewrap on Linux, and bubblewrap delegated through the default WSL2 distribution on Windows. If that backend is unavailable, commands are refused while the sandbox is enabled unless the owner explicitly selects the unsafe `sandbox.unavailable_policy=warn` or sets `sandbox.mode=danger-full-access`. Docker is not an automatic fallback.

## Top-level keys in config.json

The top-level keys actually written to `~/.openprogram/config.json` (do not edit by hand — go through `openprogram config set`, the setup wizard, or the Web UI):

| Key | Meaning | Code |
|----|------|------|
| `ui` | `{web_port, open_browser}`, see the table above | `openprogram/state/settings.py` |
| `search` | `{default_provider}` | `openprogram/state/preferences.py` |
| `memory` | `{backend, writer: {model}}`, see the table above | `openprogram/state/settings.py`, `openprogram/state/memory/` |
| `tools` | `{disabled: [tool name, ...]}` | `openprogram/operations/setup.py`, `openprogram/state/settings.py` |
| `sandbox` | `{mode, writable_roots, deny_read, deny_write, network, pass_env, unavailable_policy}`, see the table above | `openprogram/host/sandbox/__init__.py`, `openprogram/state/settings.py` |
| `last_used_model` | `{provider, model}` a new conversation starts on: the model last picked or sent with. Empty on a fresh install | `openprogram/models/providers/catalog/last_used.py` |
| `default_workdir` | Default working directory for agents | `openprogram/state/paths.py` |
| `providers` | Per-provider settings subtree (enabled models, custom models, etc.), managed by the Web UI model listing | `openprogram/models/providers/settings/config_read.py`, `openprogram/models/providers/settings/storage.py` |
| `api_keys` | Environment variable name → API key mapping, written by the setup wizard and exported into the environment at worker startup. Used for web-search / TTS keys; LLM provider keys live in the credential store (`openprogram providers login`), not here | `openprogram/interfaces/cli/setup_sections/sections.py`, `openprogram/interfaces/server/server.py` |
| `spec_migration_version` | One-time marker for the model-spec migration; see the code for its meaning | `openprogram/models/providers/settings/storage.py` |

## Environment variables

Set these in the shell that launches `openprogram` (or the worker). Every one has been verified against the code; each row names where it is defined.

### Paths and instances

| Variable | Purpose | Code |
|------|------|------|
| `OPENPROGRAM_PROFILE` | State-directory profile, equivalent to `--profile`, reroutes to `~/.openprogram-<name>/` | `openprogram/state/paths.py` |
| `OPENPROGRAM_HOME` | Alternative base directory for auth accounts | `openprogram/models/auth/account/accounts.py` |
| `OPENPROGRAM_WORKDIR` | Default agent working directory (takes precedence over the config's `default_workdir`) | `openprogram/state/paths.py` |

### Ports and web

| Variable | Purpose | Code |
|------|------|------|
| `OPENPROGRAM_WEB_PORT` | the single worker port (default 18100); below explicit flags, above the persisted preference | `openprogram/operations/worker/lifecycle.py`, `openprogram/interfaces/cli/commands/web.py` |
| `OPENPROGRAM_NO_WEB` | `1` = the worker skips the frontend build gate and does not serve the web UI | `openprogram/operations/worker/runner.py` |
| `OPENPROGRAM_WEB_NO_FRONTEND` | `1` = `openprogram web` skips the frontend and starts only the backend | `openprogram/interfaces/cli/commands/web.py` |
| `OPENPROGRAM_DOCS_BASE` | Mount path of the docs site (default `/docs/`; must start and end with `/`) | `scripts/docs_site/build.py` |

### Behavior switches

| Variable | Purpose | Code |
|------|------|------|
| `OPENPROGRAM_NO_AUTO_WORKER` | `1` = the TUI does not auto-launch a worker; connects only to an existing one | `openprogram/interfaces/cli/ink.py` |
| `OPENPROGRAM_NO_SLEEP` | `1` = disable the memory sleep-consolidation scheduler | `openprogram/state/memory/scheduler.py` |
| `OPENPROGRAM_NO_PROGRAMS_WATCH` | `1` = disable the file watcher on the programs directory | `openprogram/programs/_host/watcher.py` |
| `OPENPROGRAM_PROJECT_AUTOCOMMIT` | `0` = turn off project auto-commit | `openprogram/state/store/project/project_commit.py` |
| `OPENPROGRAM_WEBSEARCH_DISABLE` | Disable a web search provider by name (e.g. `ollama`) | `openprogram/programs/tools/web/web_search/providers/ollama.py` |

### LLM calls

| Variable | Purpose | Code |
|------|------|------|
| `AGENTIC_PROVIDER` / `AGENTIC_MODEL` | Provider / model that `detect_provider()` (and thus `create_runtime()`) picks first, before config-file and CLI detection | `openprogram/models/providers/catalog/registry.py` |
| `OPENPROGRAM_MAX_RETRIES` | Runtime retry count for transient API failures (default 6) | `openprogram/runtime/agent/runtime.py` |
| `OPENPROGRAM_RETRY_BACKOFF_BASE` | Base seconds for the exponential retry backoff (default 1.5) | `openprogram/runtime/agent/runtime.py` |
| `OPENPROGRAM_EXEC_TIMEOUT_S` | Default wall-clock budget in seconds for every `runtime.exec` when the caller passes no `timeout_s` (unset or `0` = unbounded) | `openprogram/runtime/agent/runtime.py` |
| `OPENPROGRAM_FALLBACK_MODELS` | Failover chain used when the main model fails before any output. Unset = the other enabled models of the same provider (max 2); a comma-separated `provider/model` list overrides it and may cross providers; `off` disables failover | `openprogram/models/providers/utils/failover.py` |
| `OPENPROGRAM_PROVIDER_STREAM_RETRIES` | Attempts per streaming request, including the first (default 5). Connection retries draw on their own allowance of this minus one, separate from output repairs | `openprogram/models/providers/utils/stream_retry.py` |
| `OPENPROGRAM_NETWORK_WAIT_MAX_S` | How long a request whose endpoint cannot be reached (no network, DNS failure, stopped local proxy) keeps waiting for the network after its retries are spent, checking every 5 to 30 seconds, before the turn fails (default 1800; `0` = fail at once). Cancelling the turn ends the wait | `openprogram/models/providers/utils/stream_retry.py` |
| `OPENPROGRAM_STRICT_TOOLS` | `0` = turn off strict tool schemas (on by default) | `openprogram/models/providers/schema/__init__.py` |
| `OPENPROGRAM_FORCE_IPV4` | `1` = force an IPv4 source address (for broken IPv6 networks) | `openprogram/models/providers/utils/http_client.py` |

### Debugging

| Variable | Purpose | Code |
|------|------|------|
| `OPENPROGRAM_LOG_LEVEL` | Log level for the process (`DEBUG`, `INFO`, `WARNING`, `ERROR`; any case). Overrides the default: `INFO` for the worker, the scheduler and the foreground Server, `WARNING` for the CLI. An invalid value is ignored | `openprogram/host/process_logging.py` |
| `OPENPROGRAM_DEBUG_RUNTIME` | `1` = mirror runtime logs to stderr | `openprogram/interfaces/server/server.py` |
| `OPENPROGRAM_DEBUG_REGISTRY` | `1` = add the traceback to function-registry import failures | `openprogram/programs/_host/registry.py` |
| `OPENPROGRAM_DEBUG_DISPATCHER` | `1` = dispatcher debug logs (at `INFO`, in the worker log) | `openprogram/runtime/conversation/turn_runtime/runtime_attach.py` |
| `OPENPROGRAM_DEBUG_PROVIDER` | `1` = provider-layer debug logs (at `INFO`, in the worker log) | `openprogram/models/providers/adapters/openai_codex/openai_codex.py` |

### Others

The code holds a further batch of more internal variables (HTTP/SSE timeout tuning `OPENPROGRAM_HTTPX_*` / `OPENPROGRAM_SSE_*`, TCP keepalive `OPENPROGRAM_TCP_*`, per-provider retry counts `OPENPROGRAM_<PROVIDER>_MAX_RETRIES`, `OPENPROGRAM_JOB_WORKERS`, `OPENPROGRAM_IMAGE_DIR`, `OPENPROGRAM_BROWSER_CDP_URL`, etc.). `grep -rn "OPENPROGRAM_" openprogram/` lists the full set; every variable is commented where it is defined.
