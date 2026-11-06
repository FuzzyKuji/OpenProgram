# Tool toggles and toolset management

> The core principle: **the Agent configuration decides which tools a session may call; a session stores only overlay intent, never an expanded list of tool names. The tool array is expanded from the registry at run time, so a newly added tool automatically reaches every historical session.**

---

## 1. How the toolset is determined

### 1.1 Who chooses

| Where | What it sets | Stored in |
|---|---|---|
| Agent configuration (Agents → Capabilities → Programs) | the tool scope: all tools, a selected scope or a named tool profile (Access preset), or none; plus disabled names and a `web_search` default | the Agent profile, `tools: {mode, allowed, preset, disabled, web_search}` |
| Composer Web Search switch | layers `web_search` on or off over the Agent's tool set | session meta, `web_search` |
| `/skill <name>` with `allowed-tools` | narrows the turn to the skill's allowlist | session meta, `tools_override` (`list[str]`) |

The composer has no Tools switch and no per-chat Access preset. A chat that should not call tools uses an Agent whose Programs are set to none. The chat WebSocket action ignores any `tools` / `tools_profile` field; only `web_search` comes from the message.

### 1.2 The priority chain

The tools handed to the model on a turn are computed by `resolve_tools(agent_profile, override, source)` (`openprogram/runtime/conversation/model_tools.py`). `override` is the session's intent, produced by `tools_override_from_config(cfg)` (`openprogram/runtime/conversation/session_config.py`):

| Session intent | Override | Behavior |
|---|---|---|
| nothing set | `None` | the Agent profile's `tools` decide |
| `web_search` set | `{"inherit": True, "web_search": <bool>}` | the profile's tools expanded live, then web_search added or removed |
| `/skill` allowlist | `list[str]` (plus the web_search overlay) | `agent_tools(names=[...])`, by name |

The consumers are the webui chat path (`ws_actions/chat/turn.py`, `context_git_routes.py`), channels (`channels/_conversation.py`) and goal chat (`programs/tools/planning/goal/chat.py`).

### 1.3 Why intent and not a list snapshot

If a session expanded intent into a `list[str]` at write time, its toolset would be frozen at that moment: every later turn would read the old name list back and pass it to `agent_tools(names=[...])`, so a tool added to `DEFAULT_TOOLS` afterwards (list_agents, send_message) would never reach that session. Storing only the overlay (`web_search`) and leaving the tool scope to the Agent profile keeps every session on the live registry. The one stored list is a `/skill` allowlist, which is a deliberate, short selection.

---

## 2. How other projects do it (the consensus)

| Project | What is stored | How staleness is avoided |
|---|---|---|
| **opencode** | per-session `tools: Record<name, boolean>` intent map | the tool table is built fresh from the live registry each turn, then filtered by intent (`config.ts:552`, `session/tools.ts:86`) |
| **claude-code** | `--tools` (a selection, with sentinels `""`=none / `"default"`=all) plus `--allowedTools` / `--disallowedTools` (allow/deny pattern strings) | the builtin set is a constant; only selection / allow / deny intent is stored, and the intersection is taken at run time (`main.tsx:988`) |
| **pi-ai** | builtin toggles and extension tools managed separately | turning builtins off is boolean intent and does not affect live extension loading |
| **hermes** | a named preset (toolset name) | stores the preset **name** and expands at run time (our `TOOLSETS` is ported from it) |

**The consensus, without exception: all of them store toggle intent (booleans, allow/deny, or preset names) and never freeze an expanded tool list.** The real tool array is always expanded from the live registry at request time.

---

## 3. The core principle: store *intent*, not a *list*

All a session stores about tools:

| Field | Meaning | Values |
|---|---|---|
| `web_search` | layered **on top of** the Agent's tool set | `True` / `False` / `None` (follow the Agent) |
| `tools_override` | a `/skill`'s allowed-tools | `list[str]` (short) or absent |

The tool scope itself (all / selected / preset / none, disabled names) lives in the Agent profile and is expanded live through the dict-override channel of `resolve_tools`. As a result: a new tool reaches old sessions on their next turn; deleted tools and preset changes are followed automatically; changing an Agent's configuration changes every conversation that uses it.

---

## 4. Effects on context, cache, and history (checked item by item)

1. **Does the tool array count as tokens**: ContextCommit's `total_tokens` **excludes** the tool array (the commit dataclass has no tools field, `commit/types.py:104-140`), but the provider request **is billed** for the tool array (`anthropic.py:601`, sent with the request). So toolset size is invisible to the compaction budget but visible in the real input cost of every turn.
2. **Caching**: the tool array sits at the **root of the cache prefix** (`cache_policy.py:80-89`; the first breakpoint is placed at the last tool, Anthropic/Bedrock explicit mode only). So **any addition, removal, or reordering of the tool array rewrites the cache prefix and misses the entire prompt cache**. **Hard constraint: expansion must be deterministic** (stable sort plus dedup) so the same intent expands byte-identically every time and the cache hits.
3. **Calls present in history but absent from the current tool array**: historical tool_use / tool_result are rendered from the message (`anthropic.py:328-451`), independent of the current `context.tools`, and replay fine — the model simply cannot issue that call on this turn. So **do not filter or rewrite historical tool_use based on the current tool array** (breaking tool_use↔tool_result pairing causes a 400).
4. **ContextCommit replay is unaffected**: commits do not store the tool array; the toolset is a request-time artifact. Removing the tool snapshot from storage therefore **changes no commit replay semantics**, which keeps the risk of the change low.

---

## 5. Three places that carry the design

**A — the chat action passes intent through** (`openprogram/interfaces/server/ws_actions/chat/turn.py`): it reads only `web_search` from the message. `tools_flag` starts as `None` (follow the Agent); a `/skill` with `allowed-tools` sets it to that list; a new Agent conversation clears both so the Agent's configuration decides. Nothing is expanded here.

**B — session_config stores intent** (`openprogram/runtime/conversation/session_config.py`): `SessionRunConfig` carries `web_search: Optional[bool]` and `tools_override: Optional[list[str]]`. `tools_override_from_config` emits `None`, the `{"inherit": True, "web_search": ...}` dict, or the `/skill` list with the web_search overlay. No snapshot of all tools is ever written.

**C — the dict override layers web_search** (`_model_tools.py`): because web_search is not in `DEFAULT_TOOLS`, the dict branch's `_overlay_web_search` adds it after expansion when the intent asks for it and the result lacks it, and removes it when the intent is `False`, unless the Agent's `disabled` patterns exclude it. A provider's builtin web_search (the `openai_codex.py` kind) is an alternative path whose availability varies by provider (see §8).

---

## 6. Properties that should hold

When the design is correct, all of the following hold at once, and they are also what regression testing looks at:

- **Deterministic expansion**: expanding the same intent twice in a row yields element-wise equal results (stable ordering plus dedup), avoiding the cache thrash of §4.2.
- **Intent round-trip**: storing `web_search=True` reads back True; a session lacking the field reads back None without error.
- **The Agent decides**: with no session intent the override is `None` and the Agent profile's `tools` apply; a `web_search` intent expands the Agent's tools and only adds or removes web_search.
- **Writes do not materialize**: after a session enables web_search, `tools_override` in its meta is absent; only a `/skill` allowlist is ever stored as a list.
- **New tools appear automatically**: expanding the Agent's automatic scope includes the tools most recently added to `DEFAULT_TOOLS` (send_message, list_agents).
- **Cache stability**: a session with unchanged intent sends two turns back to back and provider usage shows a cache hit on the second, with no toolset thrash.
- **No per-chat tool switch**: no client sends `tools` or `tools_profile` with a chat message, and the chat action reads neither.

---

## 7. Deferred loading: availability is not residency

§4.1 established that the tool array is billed on every turn. Toggles decide
which tools are **available**; deferred loading decides which of those pay for
their JSON Schema on every turn. These are separate axes, and conflating them
is what made the resident cost grow with the tool count.

### 7.1 The two states of an available tool

An available tool ships in one of two forms:

- **Resident** — full JSON Schema in the provider's tools array, every turn.
- **Deferred** — one bare `name` line in the system prompt's catalog. The
  model loads the schema on demand by calling `tool_search`, after which it
  is included in the next provider request in the current turn.

The catalog carries names only, not descriptions. A name is enough for the
model to recognise a candidate and ask for it, and it keeps the whole
catalog to a couple of hundred tokens no matter how many tools are deferred.

A deferred tool is **not disabled**. The model can still call it; it just has
to load the schema first. A disabled tool is absent from both the array and
the catalog and cannot be called at all.

### 7.2 The split

`split_tools_for_dispatch(tools)` (`programs/_host/runtime.py`) partitions the
resolved toolset into `(provider_tools, catalog)` by reading each tool's
`_defer` sidecar attribute, minus the session's already-loaded set:

- not deferred → provider array
- deferred and in the session's loaded set → provider array
- deferred and not yet loaded → catalog

The loaded set lives in a ContextVar (`install_loaded_deferred`, seeded per
session by the dispatcher; `mark_deferred_loaded` adds to it from inside
`tool_search`). Which entries of that set actually reach the array is decided
once per turn — see §7.4.

### 7.3 Which tools are deferred

`apply_default_deferral()` runs once at import and marks
`_defer = name not in RESIDENT_TOOLS`. Two groups end up deferred:

1. Everything in the `full` exposure whitelist but outside `DEFAULT_TOOLS` —
   memory, worktree, image, and the other cold tools. These were
   never in the default set, so deferral costs nothing.
2. `DEFERRED_DEFAULT_TOOLS` — tools that stay in `DEFAULT_TOOLS` (available
   by default) but are big and rarely called, so they are not resident:

   | tool | schema | why it is not resident |
   |---|---|---|
   | `enter_plan_mode` | ~1050 tok | Plan mode is normally entered by the user via the tier chip / TUI (`plan_mode.sync_tier`), which does not go through this tool. The model entering plan mode on its own judgement is the rare path. |
   | `exit_plan_mode` | ~640 tok | Only meaningful while plan mode is active, and the plan-mode prompt block names it explicitly, so the model knows to load it. |
   | `send_message` | ~380 tok | Cross-session/branch messaging, only used in multi-branch collaboration. |

`tool_search` itself is never deferred — it is the only way to load anything
else, so deferring it would be a deadlock. This is asserted twice: the
`RESIDENT_TOOLS` union and an explicit guard in `apply_default_deferral`.

Effect: the default resident array drops from ~7.9k to ~4.7k tokens per turn,
a ~41% cut, with no tool becoming unavailable.

### 7.4 Explicit discovery updates the next request

`freeze_turn_tools` captures initial deferred membership at each turn boundary.
`tool_search` explicitly promotes allowed names into both the loaded set and
that turn's shared membership set. The next provider request includes those
tools' real schemas. Returning a schema as tool-result text alone is insufficient
for providers that only permit tools present in the request array.

The membership sets are mutated in place: tool workers inherit ContextVar
values, and replacing a worker's value would not update the provider coroutine.
Promotion uses the turn's resolved, permission-wrapped tools, not a new registry
lookup for execution. Unrelated registry changes do not replace the immutable
runtime contract. Without explicit discovery, the array remains stable; discovery
may change the provider's cached prefix to make the requested tool available.

Each durable safe point records `loaded_deferred_tools` in the checkpoint.
Names must belong to the checkpoint's resolved tool contract. Continuation first
validates the unchanged contract, then restores those names before its next
provider request, without replaying completed searches. Older checkpoints without
this optional field restore an empty set; no tool-result text is interpreted as
authorization or loading state. Provider dispatch also records its current
resident/deferred classification for the context inspector.

Callers assembling tools outside a turn use `release_turn_tools()` to read the
live loaded set.

### 7.5 The catalog is an assembler component

The catalog is not hand-appended by the dispatcher. It is a registered
context component (`deferred_catalog`, L1 order 25, in `context/components.py`)
built by `_build_deferred_catalog`, so the string the engine budgets is the
string that ships. The component reads the tools from a ContextVar and returns
empty when nothing is deferred.

Budget accounting follows the same split. `_estimate_one_tool`
(`context/budget.py`) prices each tool as what that tool actually puts on
the wire:

- **resident** — `description` **and** `parameters` schema, plus a small
  wrapper. Both halves matter: the descriptions are roughly 45% of the
  resident cost, so pricing the schema alone understates the array by
  several thousand tokens.
- **deferred** — its bare name plus a newline, matching
  `deferred_catalog_text`. Pricing a deferred tool by its description
  overstates the catalog by roughly an order of magnitude, because the
  description is precisely what the catalog does not send.

Getting either half wrong is easy to miss, because the two errors point in
opposite directions and a plausible-looking total can hide both.
`tests/unit/context/test_budget.py` therefore checks each half against a real
tokenized wire payload separately, within 15%.

### 7.6 Properties that should hold

Regression coverage lives in `tests/unit/context/test_tool_defer.py`:

- no member of `DEFERRED_DEFAULT_TOOLS` appears in the resident array of a
  fresh session, nor in `RESIDENT_TOOLS`
- every one of them appears in the catalog, and in the assembled system prompt
- `tool_search` moves a deferred tool into the provider array and out of the
  catalog
- `tool_search` is never deferred; `apply_default_deferral` is idempotent
- within a turn, explicit `tool_search` discovery adds the tool to the next
  provider array and removes it from the deferred catalog
- `tool_search` returns the full parameter schema; execution still resolves
  against the original permission-wrapped tools
- checkpoint continuation restores recorded discoveries after validating
  the unchanged runtime contract

---

## 8. Known boundaries

- **Provider builtin web_search vs. web_search in the tool array** (an either/or in change C): codex / OpenAI Responses is confirmed to use the builtin `opts["web_search"]` (`openai_codex.py:376`); Anthropic and other providers need checking one by one. Until that is settled, the safe "web_search layered in as a tool name" path stays.
- **The `allowed` semantics of the dict override**: today `allowed` (`_model_tools.py:406`) filters DEFAULT_TOOLS rather than the full set. This change does not extend that.
- **The exact token count of the tool array** is a server-side figure and cannot be measured statically in this repo; all that is confirmed is that it is billed and sits in the cache prefix.

---

## 9. Implementation status

### 9.1 Carrying files

| File | What it carries |
|---|---|
| `openprogram/runtime/conversation/session_config.py` | the `web_search` and `tools_override` (`/skill` allowlist) fields of `SessionRunConfig`; `save`/`load` for them (stored in git session meta, so no DB schema change — `update_session(**fields)` passes arbitrary keys through); `tools_override_from_config` emits `None`, the web_search dict intent, or the `/skill` list |
| `openprogram/interfaces/server/ws_actions/chat/turn.py` | reads only `web_search` from the message; passes it and a `/skill` allowlist to `save_session_run_config(tools=, web_search=)` |
| `openprogram/runtime/conversation/model_tools.py` | web_search layering in the dict-override branch (`resolve_tools`, ~397-421): `_overlay_web_search` adds web_search after expansion via either the toolset or the names path when the intent asks for it and the result lacks it |
| `openprogram/programs/_host/runtime.py` | the deferred machinery: `_defer` sidecar, the loaded set, `freeze_turn_tools` / `release_turn_tools` (§7.4), `split_tools_for_dispatch`, `tool_search` and the schemas it returns, `deferred_catalog_text` |
| `openprogram/runtime/agent/loop/` | calls `freeze_turn_tools` once per turn at the top of the outer loop; resolves tool calls by name against the full tool list so a mid-turn load is still dispatchable |

### 9.2 Key design points (do not break)

- **Expansion must be deterministic**: the tool array is at the root of the prompt cache prefix, and any ordering wobble misses the whole cache. Today `agent_tools` returns in names/registry order, which is naturally stable, and `tests/unit/programs/tools/test_tool_expansion_deterministic.py` locks that in. **When changing `agent_tools` / `_filter_agent_tools` later, do not introduce `set()` iteration or dict churn that breaks the order** — the cache would fail silently (no error, just quietly more expensive).
- **Never materialize the Agent's tools into a list stored on the session**: the scope is always expanded live from the Agent profile. `list[str]` denotes only a `/skill` allowlist. This is the design's hard line.
- **Do not touch history**: tool toggles govern what can be called next, and never filter or rewrite historical tool_use (that would break tool_use↔tool_result pairing and cause a provider 400).
- **The tools array changes only at turn boundaries** (§7.4). Anything that grows it mid-turn discards the cached prefix for the rest of that turn. When a tool needs to become usable sooner, hand the model its schema in a tool result — do not append to the array.

### 9.3 Tests (regression protection)

- `tests/unit/programs/tools/test_tool_expansion_deterministic.py` — deterministic expansion (stable cache prefix)
- `tests/unit/store/test_session_config_tools_intent.py` — no intent follows the Agent, the web_search overlay (added, removed, respecting the Agent's `disabled`), `/skill` lists passed through, and the cold-provider path for an explicit web_search
- `tests/unit/store/test_session_config.py` — `web_search` and `/skill` allowlist round-trip through session meta
- `tests/unit/context/test_tool_defer.py` — the deferral properties of §7.6, including the turn-boundary freeze
- `tests/unit/context/test_budget.py` — each half of the tool pricing against a real tokenized payload (§7.5)

### 9.4 Extension points

- **Provider builtin web_search** (§8): web_search currently uses the "layer in the tool name" path; once builtin support is confirmed per provider, it can be switched at `_overlay_web_search`.
- **New intent dimensions** (restricting tools per channel, say): add the scope to the Agent profile, or a key to the dict intent handled in the dict branch of `resolve_tools` — do not revert to storing an expanded list.
