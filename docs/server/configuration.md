<span id="configuration"></span>
# Server configuration

All of OpenProgram's state lives in a single directory, `~/.openprogram/`. This page covers what is in it, how `openprogram config` reads and writes settings, and how to isolate multiple sets of state with profiles.

## What lives in ~/.openprogram/

The main files and subdirectories, grouped by purpose:

| Path | Contents |
|------|------|
| `config.json` | User settings: ports, last used model, provider configuration, disabled tools, etc. — see the [configuration reference](../reference/config.md) |
| `sessions/`, `sessions-git/` | Chat session data and its git archive |
| `agents/`, `agents.json` | Agent definitions (persona, model, skills) |
| `auth/` | Provider credential store |
| `skills/` | Installed skills (SKILL.md directories) |
| `plugins/` | Installed plugins |
| `mcp_servers.json` | MCP server configuration |
| `memory/` | Persistent memory (wiki + journal) |
| `channels/` | Chat channel bot state (Telegram, Discord, WeChat, etc.) |
| `browser-states/`, `chrome-profile/` | Browser tool login state and the sidecar Chrome profile |
| `projects/`, `worktrees/`, `shadow-git/` | Project workspaces and git worktree state |
| `logs/`, `worker.log` | Logs; also worker runtime files such as `worker.pid` / `worker.port` / `worker.lock` |
| `models/`, `cache/`, `tool_results/`, `usage.db` | Model catalog cache, general cache, tool results, usage database |

## openprogram config

```bash
openprogram config list              # list every setting: value, group, when it applies
openprogram config get <key>         # read one setting, e.g. ui.web_port
openprogram config set <key> <value> # change one setting
```

Every setting has an apply mode: `live` (takes effect immediately) or `next start` (takes effect the next time the worker starts; `config list` labels each one). Core keys:

| key | Meaning | Default | Applies |
|-----|------|------|------|
| `ui.web_port` | the single worker port (API + WebSocket + web UI) | 18100 | next start |
| `ui.open_browser` | whether `openprogram web` opens the browser automatically | true | next start |
| `search.default_provider` | default web search provider (`auto` picks the highest-priority configured one) | auto | live |
| `memory.backend` | `local` (on disk) or `none` (no prompt memory, recall, automatic writes, organizer, or memory threads) | local | next start |
| `memory.writer.model` | optional `provider/model` for background writing; empty follows the default chat agent and its credentials | empty | live |
| `tools.disabled.<name>` | per-tool switch (written into the `tools.disabled` list) | all enabled | live |

`config list` also shows read-only `providers.<name>` status rows — they cannot be changed with `config set`; configure them with `openprogram providers login` or the Providers page in the Web UI.

## Prevent idle system sleep

On macOS, optionally keep the system awake while an agent execution is active:

```bash
openprogram config set execution.prevent_idle_sleep true
```

The default is `false`. Each execution reads the setting when its agent loop starts
and holds its own native power assertion until that loop finishes, fails or is
cancelled. Approval waits inside the loop also retain the assertion. Changing the
setting does not affect executions already running. Display sleep and explicit
user-initiated sleep remain available; no permanent system power settings change.
Unsupported platforms or assertion failures log a warning and continue the task
without sleep prevention. This does not cover independent background services or
commands after the agent loop has ended.

## Port shortcut

`openprogram ports` is the dedicated writer for the port preference:

```bash
openprogram ports                    # view
openprogram ports --port 8101        # persist a change
```

## Who can reach the server

Nothing in the API asks the caller to authenticate, so two settings decide
who can talk to it.

`web.host` decides which interface it listens on. The default `127.0.0.1`
accepts connections from this machine only. Setting `0.0.0.0` hands the UI —
and every stored API key, which `/api/providers/…/reveal` returns in
plaintext — to your whole network.

Listening on loopback is not enough on its own, because a browser can reach
loopback from any page you happen to visit. Two attacks do exactly that: a
page can open a WebSocket to `127.0.0.1` (the same-origin policy does not
cover WebSockets) and drive the agent, which owns a `bash` tool; or a
site's own name can re-resolve to `127.0.0.1` after its page loads, so its
requests arrive looking same-origin. So the server checks, before routing:

- the `Host` header names a loopback address, whenever it is bound to one;
- the browser did not label the request `Sec-Fetch-Site: cross-site`;
- `Origin`, when present, matches the request's own `Host` or is loopback.

Anything else gets a 403. A request with no `Origin` at all is not a browser
request — that is the terminal UI, `curl`, and the Python clients — and
passes.

If you front the server with something you run yourself, a reverse proxy on
your own domain, add that origin so its pages are accepted too:

```bash
openprogram config set web.allowed_origins '["https://agent.example.com"]'
```

## Network proxy

The worker follows your ordinary proxy for public destinations: pages read by
`web_fetch`, image and attachment downloads, the built-in web search backends
(including DuckDuckGo), other fixed public services such as update checks, and
model providers whose API or OAuth origin is in the audited provider inventory.
The route comes from:

1. **`OPENPROGRAM_PROXY_URL`** overrides the ordinary proxy route. It accepts
   `http://`, `https://`, and `socks5://` URLs. `NO_PROXY` bypasses still apply.
2. **Standard environment variables** use HTTPX's resolution:
   `http_proxy` / `HTTP_PROXY`, `https_proxy` / `HTTPS_PROXY`,
   `all_proxy` / `ALL_PROXY`, and `no_proxy` / `NO_PROXY`. Python also uses
   macOS and Windows system proxy settings when applicable. Loopback hosts
   never go through the proxy.

The client validates the target first and checks the proxy socket address.
TLS still verifies the service hostname. Proxy authentication stays on the
proxy connection, and a failed proxy request does not fall back to direct access.
An explicit `security.outbound_url.policy_proxy` takes precedence and requires
an owner assertion that it enforces target policy.

When a request goes through the proxy, the proxy resolves the hostname. This is
what makes fake-IP proxies such as Clash work: their local DNS answers come
from `198.18.0.0/15`, which a direct connection would refuse as
`NON_GLOBAL_ADDRESS`. Private, loopback and metadata IP addresses, local names
(`localhost`, single-label hosts, `.local`, `.lan`, `.internal` and similar),
and hostnames whose local DNS answer is a real private address are still
refused. Hosts listed in `NO_PROXY` connect directly with the full address
check. For a strict guarantee that the final resolution is also checked,
configure an enforcing policy proxy.

Custom service origins (a configured provider base URL, SearXNG, a skills or
plugin catalog) do not inherit ordinary proxies. They retain direct address
checks or use an explicit enforcing policy proxy. CLI providers inherit the
worker process environment; the external CLI handles its own routing. SOCKS
support is included.

`openprogram rescue` reports the resolved proxy configuration and flags a
SOCKS proxy whose support package is missing.

## Multiple instances: --profile

`--profile <name>` (or the environment variable `OPENPROGRAM_PROFILE`) reroutes config, sessions, and logs to `~/.openprogram-<name>/`, so parallel workspaces share no state:

```bash
openprogram --profile dev            # run an independent instance on ~/.openprogram-dev/
OPENPROGRAM_PROFILE=dev openprogram status
```

Combined with different `OPENPROGRAM_WEB_PORT` values, several services can run at once. For installation, see [Profiles](../install/profiles.md).
