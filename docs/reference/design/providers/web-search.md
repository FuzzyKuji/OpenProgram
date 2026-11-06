# Web search: provider-side first, local tool second

## Problem

The chat's Search switch used to do one thing: add the local `web_search`
function tool to the model's tool list. That tool scrapes DuckDuckGo when no
search key is configured, and a scraper gets a bot challenge after a handful
of requests. Meanwhile the model backends people actually run (the ChatGPT
subscription through `openai-codex`, the OpenAI Responses API, Anthropic,
Gemini) each ship a server-side web search: the model decides what to search,
the provider runs the query in its own infrastructure, and the results come
back with citations. Claude Code, Codex and Gemini CLI never scrape anything;
their WebSearch is that provider tool. Ours never turned it on.

## Design

Search is resolved per request from two facts: the session's intent (the
Search switch, stored as `web_search` on the session run config) and the
capability of the API provider the request goes to.

1. **Provider-side search when the provider has it.** The API provider
   registry advertises `supports_web_search` next to `supports_idempotency_key`
   (`_StreamFnProvider`, `ApiProviderSnapshot`). When the session intent is on
   and the resolved model's provider advertises it, the agent runtime sets the
   request option `web_search=True` and removes the local `web_search` tool
   from the request's tool list. The request builder adds the provider's own
   tool:
   - `openai-responses` and `openai-codex`: `{"type": "web_search"}`.
   - `anthropic-messages`: `{"type": "web_search_20250305", "name": "web_search"}`.
   - `google-generative-ai` and `gemini-subscription`: `{"google_search": {}}`,
     but only in a request without function tools. Gemini's `generateContent`
     rejects Google Search grounding next to function declarations (Gemini 3
     combines them only on the Interactions API), and an agent request
     always carries function tools, so these two APIs do not advertise the
     capability and chat keeps the local tool; grounding metadata is still
     parsed when a tool-free request (a plain completion with
     `web_search=True`) uses it.
   A provider that does not advertise the capability (DeepSeek, Kimi, local
   models, every OpenAI-compatible endpoint, Gemini) keeps the local tool,
   exactly as before.
2. **The local tool stays the fallback, and says what to do.** Without a
   provider tool and without a search key the only backend is the DuckDuckGo
   page scraper. When every backend fails, the tool's error tells the model
   that a search key (Settings > Search; Brave and Tavily have free tiers) is
   the fix and that it may open a search page in its browser tools if it has
   them, instead of asking it to "retry later". The unpinned fallback skips
   `arxiv`, which is a paper index, not a web index; it is still available
   when pinned.
3. **A provider search is shown like any other tool call.** The stream
   processors turn the provider's search items into a `ServerToolUse` content
   block and `servertool_start` / `servertool_end` events. The agent loop does
   not execute these (the provider already did); it forwards them, and the
   runtime projects them to the client as the existing `tool_use` /
   `tool_result` events with `tool: "web_search"`, `provider_executed: true`,
   `input` holding `{"query": ...}` and `result` holding the sources the
   provider reported (one `title — url` per line, or `completed` when the
   provider reports none). The same shape is persisted in the reply's blocks,
   so a reloaded transcript shows "Searched the web: …" where it happened.
4. **Citations ride on the text.** URL citations (`url_citation` annotations
   on Responses, `citations` on Anthropic text blocks, `groundingMetadata` on
   Gemini) are collected into `citations: [{url, title, start, end}]` on the
   `TextContent` block, forwarded with `text_end`, persisted with the block,
   and rendered by the client as a compact sources row under the answer.
5. **Replay.** A `ServerToolUse` block is resent to the API that produced it
   in its native shape (`web_search_call` item on Responses; `server_tool_use`
   + the raw `web_search_tool_result` on Anthropic, whose hits carry
   `encrypted_content` that must go back verbatim, so a block without the raw
   result is dropped) so the conversation stays valid; a different API drops
   it, as it drops foreign thinking signatures. Gemini grounding blocks get
   synthetic ids and are never resent.

## Wire contract

Content block (`openprogram/models/providers/types.py`):

```python
class ServerToolUse(BaseModel):
    type: Literal["serverToolUse"] = "serverToolUse"
    id: str                 # provider item id
    name: str               # "web_search"
    input: dict             # {"query": str}
    status: str             # "searching" | "completed" | "failed"
    results: list[dict]     # [{"title": str, "url": str}]
    raw: Any | None = None  # provider item, for replay
```

`TextContent.citations: list[Citation] | None` with
`Citation(url, title, start, end)`.

Assistant message events: `EventServerToolStart(type="servertool_start",
content_index, partial)` and `EventServerToolEnd(type="servertool_end",
content_index, server_tool: ServerToolUse, partial)`.

Client events (`apps/web/lib/net/ws/chat-stream.ts`): `tool_use` and
`tool_result` with `provider_executed: true`; `text_end`-time `citations` on
the text block. Persisted block: `{"type": "tool", "tool": "web_search",
"provider_executed": true, "input": "{\"query\": ...}", "result": ...}`.

## What each framework does well, and what we take

- Claude Code: the search is the provider's `web_search` server tool; results
  carry citations the answer cites. We take: provider tool first, citations on
  the text.
- Codex: `--search` enables the Responses `web_search` tool; the transcript
  shows one "Searched the web: query" line per search. We take: one visible
  step per search, no chat noise.
- Gemini CLI: `google_web_search` is Google Search grounding; the answer ends
  with a numbered sources list. We take: a sources row under the answer.
- OpenProgram keeps what they lack: a local tool with sixteen key-based
  backends for models without a provider search, and a session-level switch
  that follows the model the session uses.

## Implementation status

- Provider capability flag: openai-responses, openai-codex,
  anthropic-messages. Request builders for all five APIs; Google only without
  function tools and without the flag.
- Stream processing to `ServerToolUse` and citations: Responses (shared
  processor), Anthropic, Gemini.
- Runtime: intent to request option, local tool removal, event projection,
  persistence; local tool error text and fallback order.
- Client: provider-executed search cards and citation rows.
