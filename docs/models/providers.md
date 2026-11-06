# Providers

This page lists the provider implementations built into the repository (one subdirectory each under `openprogram/models/providers/adapters/`), how each one is accessed, and how to use providers directly from Python code. Beyond the built-in implementations, `openprogram providers available` also lists hundreds of community provider catalog entries that speak the OpenAI-compatible protocol; they are configured the same way.

## Built-in providers

Access methods: **API key** = a key stored in the credential store (`providers login <id>`, also importable from environment variables); **OAuth** = browser / device-code login with a subscription account; **CLI credentials** = reads the credential file of an external CLI that is already logged in; **cloud credential chain** = resolved at runtime through the cloud vendor's standard credential chain.

| Provider | Protocol | Access | Notes |
|---|---|---|---|
| `anthropic` | Anthropic Messages | API key (`ANTHROPIC_API_KEY`) | Explicit prompt caching (`cache_control`, 1h TTL supported) |
| `openai` | OpenAI Responses | API key (`OPENAI_API_KEY`) | Automatic caching on the Responses protocol (`prompt_cache_key`) |
| `openai_responses` / `openai_completions` | OpenAI Responses / Chat Completions | — (shared protocol implementations, reused by many providers) | |
| `openai_codex` | ChatGPT backend | OAuth (ChatGPT subscription): browser PKCE sign-in; an existing `codex` CLI login can also be imported via `providers discover` | Model list pulled live from the official endpoint |
| `azure_openai_responses` | Azure OpenAI Responses | API key (`AZURE_OPENAI_API_KEY`) + a base URL you supply | |
| `google` | Google Generative AI | API key (`GEMINI_API_KEY` / `GOOGLE_API_KEY`) | Thinking controlled via a token budget |
| `google_gemini_cli` | Cloud Code Assist | CLI credentials: reads `~/.gemini/oauth_creds.json` directly; the Gemini CLI handles refreshing | |
| `gemini_subscription` | Cloud Code Assist | CLI credentials: imports `~/.gemini/oauth_creds.json` (log in with the Gemini CLI first) | Aliases `gemini`, `gemini-cli` |
| `amazon_bedrock` | Bedrock Converse Stream | Cloud credential chain (`AWS_PROFILE` / access keys / bearer token, etc., detected at runtime) | Explicit prompt caching (`cachePoint`) |
| `github_copilot` | OpenAI Responses and others | GitHub device-code OAuth in the browser, or import a token from `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`; exchanged on demand for a short-lived Copilot token that is never written to disk | No thinking-effort support |
| `deepseek` | OpenAI Completions | API key (`DEEPSEEK_API_KEY`) | Reasoning is not adjustable on reasoner models |
| `openrouter` | OpenAI Completions | API key (`OPENROUTER_API_KEY`) | Aggregation gateway |
| `vercel_ai_gateway` | Anthropic Messages | API key (`AI_GATEWAY_API_KEY`) | Aggregation gateway |
| `groq` | OpenAI Completions | API key (`GROQ_API_KEY`) | |
| `cerebras` | OpenAI Completions | API key (`CEREBRAS_API_KEY`) | |
| `mistral` | OpenAI Completions | API key (`MISTRAL_API_KEY`) | |
| `xai` | OpenAI Completions | API key (`XAI_API_KEY`) | |
| `xai_subscription` | OpenAI Responses | OAuth (SuperGrok / X Premium+): browser PKCE sign-in | Same models as `xai`, via `cli-chat-proxy.grok.com` (not `api.x.ai`) |
| `zai` | OpenAI Completions | API key (`ZAI_API_KEY`) | |
| `huggingface` | OpenAI Completions | API key (`HF_TOKEN`) | |
| `minimax` / `minimax_cn` | Anthropic Messages | API key (`MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY`) | International / China endpoints |
| `minimax_cn_coding_plan` | Anthropic Messages | API key (`MINIMAX_CN_API_KEY` / `MINIMAX_API_KEY` — same account and key as `minimax_cn`) | "MiniMax Token Plan (CN)" coding subscription |
| `kimi_coding` | Anthropic Messages | API key (`KIMI_API_KEY` / `MOONSHOT_API_KEY`) | |
| `alibaba_token_plan_cn` | OpenAI Completions | Plan API key | Alias `bailian` |
| `opencode` | OpenAI Completions and others | API key (`OPENCODE_API_KEY`) | |

Streaming output is supported by every provider (the whole layer is built on the streaming interface). Multimodal input is decided per model rather than per provider, based on each provider's model catalog data; trust what the UI shows for a given model. Prompt caching has been verified in code only where noted in the table above.


## Local model servers

Ollama, LM Studio, vLLM, llama.cpp and a generic local server are available as built-in providers. They support address configuration, optional API keys, discovery and manual model IDs. For multiple servers, mark a custom provider as local. See [Local models](local-models.md) for configuration and deployment-specific token limits.

## Custom providers

Any OpenAI-compatible endpoint the table does not cover can be added from the Web UI under Settings → Providers: a display name and a base URL are the only required fields (an id is derived from the name if you don't give one). A host-only URL such as `https://api.example.com` resolves to the conventional `/v1` API root; an explicit path such as `/compatible-mode/v1` is preserved. The endpoint's `/models` list is then browsable with the same Fetch button as built-in providers, and enabled models use the same resolved base URL at runtime. Custom providers are stored in config as `providers.<id>` with `source: "custom"`.

## Seeing which session uses which model

Settings → Providers opens on **Overview**. The left column lists the sessions that are answering now or called a model in the chosen window (now, 24 hours or 7 days); under each one are its branches, sub-agents and the child sessions a program run started. Model calls that belong to no session, such as titling or memory upkeep, are grouped under **Background calls**. The right column lists the models they use, grouped by provider. A line joins each branch to its model:

- a blue line with a moving dot is a request in flight;
- an orange dashed line points at a model that failed and was switched away from (see [Fallback models](#fallback-models));
- a provider whose key is cooling down after a rate limit, or needs to be fixed, says so next to its name.

Hover a row to pick out its lines. Click a session to open it, or a provider to open its settings. Below the map, **Recent model switches** lists each switch with its reason. Sessions with no model call in the window are only counted. The map needs a wide pane; when the window is too narrow, collapse the sidebars or widen the window.

## Fallback models

When a model is rate limited, overloaded, down or unreachable, OpenProgram can answer with another model instead of showing the error. It is off by default. Turn it on under Settings → System → Models, or from the CLI:

```bash
openprogram config set model_fallback.mode same-provider
```

| `model_fallback.mode` | What happens on such a failure |
|---|---|
| `off` (default) | The error is shown. |
| `same-provider` | Up to two of your other enabled models from the same provider are tried, in the order they appear in your provider settings. No other provider is contacted. |
| `list` | The models in `model_fallback.models` are tried in order. They may come from other providers. |

For `list`, give `provider/model` ids:

```bash
openprogram config set model_fallback.models '["anthropic/claude-sonnet-5-5", "openai/gpt-5.5"]'
```

A switch only happens before the reply has produced any text, so an answer is never stitched together from two models. Authentication errors, invalid requests, a full context window and content-policy refusals are not retried on another model, because they would fail there too. The `OPENPROGRAM_FALLBACK_MODELS` environment variable overrides the setting when set.

## Redacting secrets in requests

Turn on **Redact secrets in requests** under Settings → System → Models (or `openprogram config set privacy.redact_requests true`) to keep credentials and email addresses away from the model provider. Before each request is sent, these are replaced with placeholders such as `[[SECRET_1]]` and `[[EMAIL_2]]`:

- API keys and tokens with a recognisable shape (Anthropic, OpenAI, GitHub, AWS, Google, Slack, JWTs)
- private key blocks
- the value in `password=…`, `api_key: …`, `Authorization: Bearer …` and similar assignments
- email addresses

The reply and the tool calls it makes get the real values back before you or a tool sees them, so a command the model writes with `[[SECRET_1]]` runs with the actual key. The mapping is kept in memory for one request only. Only those shapes are recognised: a password in free text with no `password=` in front of it is sent as is. It is off by default.

## Using providers as a library

To create a runtime in your own Python code, prefer auto-detection:

```python
from openprogram.runtime.agent.runtime.factory import create_runtime

runtime = create_runtime()                                        # picks the first available provider
runtime = create_runtime(provider="anthropic", model="claude-sonnet-4-6")
```

Six providers have bespoke runtime behavior behind `create_runtime` (OAuth / CLI-credential adoption, per-provider conventions):

```python
runtime = create_runtime(provider="anthropic", model="claude-sonnet-4-6")  # Anthropic API key
runtime = create_runtime(provider="openai", model="gpt-4.1")               # OpenAI Responses API
runtime = create_runtime(provider="gemini", model="gemini-2.5-flash")      # Google Generative AI
runtime = create_runtime(provider="anthropic")   # Requires an Anthropic API key
runtime = create_runtime(provider="openai-codex")  # ChatGPT subscription (Codex OAuth)
runtime = create_runtime(provider="gemini-cli")    # reuses the Gemini CLI login state
```

Every other provider in the table above routes automatically by the model's protocol: `create_runtime(provider=..., model=...)` uses the same path as the chat UI.

Grok Subscription preserves the selected model ID in its proxy routing header. Selecting `grok-4.6` requests that model; it does not substitute the `grok-build` alias.
