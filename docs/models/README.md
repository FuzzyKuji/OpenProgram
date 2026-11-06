# Configure models

OpenProgram needs at least one LLM provider to work. This page covers first-time setup, the provider management commands, and how "enabled models" work.

## First-time setup

```bash
openprogram setup
```

The first-run wizard walks through every configuration section — models, tools, agents, and more. `openprogram setup model` jumps straight to the model section; `openprogram setup menu` opens the interactive picker. The Web UI shows the same wizard on first launch (and Settings → Providers is always available afterwards).

To configure provider credentials only, use the narrower entry point:

```bash
openprogram providers setup      # interactive: scan existing credentials → log in → verify
```

## The providers subcommands

`openprogram providers -h` lists every verb. The common ones:

| Command | What it does |
|---|---|
| `login <provider>` | Log in to a provider. Picks the right method automatically (OAuth or API key); use `--api-key-stdin` in scripts |
| `logout <provider>` | Delete the provider's credentials |
| `status <provider>` | Check whether the current credentials work |
| `list` | List the configured credential pools by account |
| `available [QUERY]` | List every configurable provider catalog entry (including community ones), optionally filtered by keyword |
| `discover` / `adopt` | Scan credentials already on this machine (Codex CLI, environment variables, etc.) and import them — see [Authentication and credentials](auth.md) |
| `use <provider> [account]` | With multiple accounts, choose which one the provider currently runs on |
| `doctor` | Diagnose credentials: expiry, refresh, cooldown, conflicts |
| `aliases` / `accounts` / `migrate` | Short-name aliases, account management, credential format migration |

## Enabled models

Configuring credentials does not by itself make models selectable. Each provider has an "enabled models" list, and only enabled models appear in the chat UI's model picker.

- Mechanism: the registry (`openprogram/models/providers/catalog/enabled_models.py`) reads each provider's model entries from the config file at startup and builds the runtime model list; config changes take effect on reload.
- Config file: `~/.openprogram/config.json` (`~/.openprogram-<name>/config.json` when using `--profile <name>`). Each provider lives under `providers.<id>`: an `enabled` flag and the enabled model entries under `models` (spec rows with context window, pricing, and so on). Models added by hand are stored in the same list, tagged `source: "manual"`.
- How to enable models: tick them in the setup wizard; browse the provider's model list under Settings → Providers in the Web UI and tick them there (the Fetch button re-pulls the official model catalog); subscription providers auto-enable a default model set on login. Editing config.json by hand is normally unnecessary.
- Model for new chats: there is no default model. A new conversation starts on the model you last picked or sent a message with, recorded as the top-level `last_used_model` config key. A fresh install has none, so the first conversation asks you to pick a model. Disabling that model clears the record. Titles, memory writes, MCP sampling and the Auto permission review run on the same model when they have no conversation of their own.

## Other pages in this section

- [Local models](local-models.md) — connect to Ollama, LM Studio, vLLM or another local server
- [Providers](providers.md) — built-in provider catalog, access methods, library usage
- [Authentication and credentials](auth.md) — credential sources, storage location, importing from other CLIs
- [Fast tier](fast-tier.md) — routing requests to a faster service tier
- [Thinking effort](thinking-effort.md) — reasoning depth levels
- [Token tracking](token-tracking.md) — how each provider reports usage

You can disable every model in a provider, including the last enabled model. An empty selection stays empty after reload and restart.

Opening provider settings displays saved models and cached catalogues without waiting for the provider’s remote model endpoint. Use **Fetch models** to update that catalogue.

Provider brand icons are bundled locally, so they remain available without external image services. Custom or unrecognized providers display an initial.
