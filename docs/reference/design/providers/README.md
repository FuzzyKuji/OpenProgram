# Providers

The provider layer connects OpenProgram to model vendors: Anthropic, OpenAI, Google Gemini, Amazon Bedrock, Azure OpenAI, xAI, DeepSeek, Mistral, Groq, OpenRouter, GitHub Copilot and more, plus local servers such as Ollama, LM Studio, vLLM and llama.cpp. Each vendor is one adapter directory under `openprogram/models/providers/adapters/` with a `provider.json` that declares its models, wire API and login methods.

How a model call works today:

- **One request format.** The runtime hands the provider layer a ready `Context` (system, messages, tools). The adapter translates it into the vendor's wire request and applies that vendor's prompt-caching mechanism; nothing above this layer knows vendor formats.
- **Several accounts per provider.** Credentials are stored per `(provider, account)` pool, from API keys or subscription OAuth logins. One account is active; rotation and failover across accounts can be switched on, and Settings → Providers shows which session and branch runs on which model.
- **Failures are classified.** Every error is mapped to one taxonomy, retried or failed over according to that class, bounded by timeouts, and carried up to the UI as a structured error.
- **One model catalog.** Models come from the adapters' `provider.json`, subscription catalogs and models.dev; capabilities such as thinking effort and the Fast tier are declared per provider rather than special-cased in code.

Providers are managed with `openprogram providers` (`login`, `list`, `use`, `status`, `doctor`, `accounts`) or in Settings → Providers.

The docs are organized into four groups by responsibility:

## Translation + Caching (core)

How the provider-agnostic unified format is translated into each vendor's wire format, and how prompt caching is implemented per provider — the core mechanism of the providers layer.

- [`request-build`](request-build.md) — **Overall design**: the unified-format Context, per-provider translation, and the caching modes.
- [`cache-control-passthrough`](../plans/cache-control-passthrough.md) (in `plans/`) — per-block passthrough of Anthropic `cache_control`.
- [`routing-overview`](routing-overview.md) — the Overview pane of Settings → Providers: which session and branch uses which model, and the failover switches the ledger keeps.
- [`request-redaction`](request-redaction.md) — replacing secrets and email addresses with placeholders before a request is sent, and restoring them in the streamed reply.
- [`web-search`](web-search.md) — the Search switch: the provider's own server-side search when it has one, the local `web_search` tool otherwise, and how provider searches and citations reach the transcript.
- [`record-replay`](record-replay.md) — recording provider calls to a redacted JSONL recording file and replaying them offline for deterministic tests.
- For upstream (how content is layered and assembled, L0/L1/L2) see [`context/composition.md`](../context/composition.md).

## [auth/](auth/) — Credentials · Authentication · Accounts

Resolution, validation, and storage of API keys and subscription OAuth, plus the multi-account pool and rotation.

- [`credential-validation-unification`](auth/credential-validation-unification.md) — The credential-validation entry point
- [`credential-status-redesign`](auth/credential-status-redesign.md) — Credential status (usable or stopped)
- [`api-key-resolution-unification`](auth/api-key-resolution-unification.md) — The API key resolution chain
- [`unified-auth-storage`](auth/unified-auth-storage.md) — Self-contained auth storage
- [`unified-account-management`](auth/unified-account-management.md) — Account management + pool rotation/fallback

## [reliability/](reliability/) — Fault tolerance · Errors · Retries · Timeouts

Classification, retries, timeouts, and upward propagation of errors when a model call fails.

- [`llm-fault-tolerance`](reliability/llm-fault-tolerance.md) — Overall design for fault tolerance and timeouts
- [`error-retry`](reliability/error-retry.md) — Error handling and retry decisions
- [`error-taxonomy-propagation`](reliability/error-taxonomy-propagation.md) — Structured errors propagated all the way to the UI
- [`error-and-timeout-mechanism.html`](reliability/error-and-timeout-mechanism.html) — Visualization of the error/timeout mechanism

## [models/](models/) — Model catalog · Capabilities

The data layout and configuration structure of the model list, plus the declarative mapping of capabilities like thinking/effort. Every model is bound to the provider it belongs to, so it lives under providers.

- [`models`](models/overview.md) — Model catalog and provider configuration (data layout, fetch, merge)
- [`thinking-effort`](models/thinking-effort.md) — The thinking/effort subsystem (declarative per-provider mapping)
- [`fast-tier`](models/fast-tier.md) — the Fast tier: two-tier detection (hand-written subscription entries / models.dev auto), storage, wires
