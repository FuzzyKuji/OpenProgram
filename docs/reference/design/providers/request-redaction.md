# Request redaction

Request redaction keeps credentials and email addresses out of what a model provider receives, while the agent keeps working with the real values. It is off by default; the `privacy.redact_requests` setting turns it on. The product-side description is in [Providers](../../../models/providers.md#redacting-secrets-in-requests).

## Where it sits

`openprogram/models/providers/utils/redaction.py` wraps the agent loop's `stream_fn` (`(model, context, options) -> EventStream`). The wrapper is the outermost layer, outside [model failover](reliability/llm-fault-tolerance.md), so one vault covers every fallback candidate and the reply is restored once.

```
agent_loop ─ redacting_stream_fn ─ failover_stream_fn ─ snapshot_stream ─ provider
              redact Context  ──────────────────────────────────────────▶
              restore events  ◀──────────────────────────────────────────
```

## Redacting the request

`Vault.redact` runs over every model-visible string of the `Context`: the system prompt, user text, assistant text and thinking, tool-call arguments, tool results and tool definitions. Model fields that are not text the model reads (`data` of images and media, `thought_signature`, `thinking_signature`, ids, `cache_control`) are left alone. The caller's `Context` is never mutated; unchanged parts are shared with the redacted copy.

Only high-precision shapes are recognised, because a false positive breaks the request it hides:

| Kind | Shapes | Placeholder |
|---|---|---|
| Whole-token secrets | private key blocks, `sk-ant-…`, `sk-…`/`sk-proj-…`, `ghp_…` family, `github_pat_…`, AWS `AKIA`/`ASIA` ids, Google `AIza…`, Slack `xox?-…`, JWTs | `[[SECRET_n]]` |
| Assigned values | the value after `Bearer`, and after `password`, `api_key`, `secret`, `access_token`, `auth_token`, `client_secret` and similar keys followed by `:` or `=` | `[[SECRET_n]]` |
| Email addresses | `local@domain.tld` | `[[EMAIL_n]]` |

Numbers are assigned in order of first appearance and one value always maps to one placeholder. The same history therefore redacts to the same request text on every call, which keeps provider prompt caches valid and makes a reasoning block the model wrote with a placeholder identical when it is sent back.

A request with nothing to redact is passed to the inner `stream_fn` unchanged, so turning the setting on costs nothing for such requests.

## Restoring the reply

Every event is copied with placeholders replaced by the vault's values: the `partial` message, `text_end`/`thinking_end` content, `toolcall_end.tool_call`, and the `done`/`error` message. Tool calls therefore run with real values, and the transcript stores real values.

Deltas need more care, because a placeholder can be split across them (`"[["`, `"SECRET_"`, `"1]]"`). `_DeltaRestorer` keeps, per content block, a tail that may be the start of a placeholder (`[` within `len("[[SECRET_99999]]")` of the end, with no closing `]]`) and prepends it to the next delta. The matching `*_end` event flushes whatever is held as one last delta before the end event, so no text is lost. The `partial` of a delta event is cut before such a tail too, so a half placeholder is never displayed.

## Lifetime

The vault exists for one provider call and only in memory. Nothing is written to disk, and the next call builds a new vault from the (real-valued) history.

## Limits

- A secret in free text with no recognisable shape or key name is sent as is.
- A model that rewrites a placeholder (for example `[[SECRET 1]]`) gets that text back unchanged.
- Values that only a provider-side tool sees (for example a hosted web search) are not covered, because they never pass through the `Context`.
