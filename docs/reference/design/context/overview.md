<div id="context-the-context-layer"></div>

# Overview

**The context layer decides what the model reads on each call.** Every user message, model call and tool call is a node in the session's execution DAG. Instead of replaying a growing transcript, each call renders a selection of those nodes: the branch it continues, with old tool output shortened and, once the window fills up, the oldest turns replaced by one summary. The result is a `Context` (system / messages / tools) that the [provider layer](../providers/README.md) translates into each vendor's wire request; this layer decides **what to feed and how to layer it**, providers decide **how to send it**.

> For how each call is layered by stability and how the model is told its situation, see
> [`composition.md`](composition.md). The data model and rendering rule are specified in
> [`../runtime/dag/overview.md`](../runtime/dag/overview.md); compaction in [`compaction.md`](compaction.md).
> This document is the overview that ties them together.

---

## 1. Assembly Pipeline

The main chat path has one context-assembly engine (`openprogram/runtime/context/engine.py`):

```
process_user_turn  (openprogram/runtime/conversation/turn_runtime/)
  → engine.prepare()            ← produces TurnPrep
      1. reference scan (tool_use ids cited later)
      2. render history from the DAG: resolve the head → render_context → render_dag_messages
      3. take the system prompt the caller assembled (identity + AGENTS.md chain + skills + tools)
      4. compute the token budget (system / history / tools / output reserve)
      5. reconcile usage (last provider measurement + local estimate of what was added since)
      6. return TurnPrep
  → budget ≥ 80%? → engine.compact()  (inline, LLM-written summary)
  → agent loop → Context(system, messages, tools) → provider
       └ provider reports context overflow → reactive compaction, one retry
```

The DAG render is the only pipeline: there is no fallback assembly. A render failure fails the turn visibly instead of silently sending a differently shaped prompt.

**Main path vs. auxiliary paths**: outside the main path, several features each make their own single LLM call (summarization, memory sleep, branch summary, mixture-of-agents). They bypass `engine.prepare` and build a minimal `Context` (essentially a system prompt and one user message, no tools). This is intentional layering — these calls don't need the full chat context.

---

## 2. Storage Model: DAG

Conversation history is the session DAG, stored in a git-backed session store (`openprogram/state/store/session/`). It is append-only: no rule ever rewrites a node.

### Nodes

```python
@dataclass
class Call:
    id: str
    seq: int                      # monotonically increasing within a session; the sole ordering key (≠ wall-clock)
    created_at: float
    role: str                     # "user" | "llm" | "code"
    name: str                     # model id / function name / user name; context/* names are pipeline nodes
    input: Any                    # prompt blocks / arguments
    output: Any                   # reply text / return value / user content (permanent original text)
    caller: str                   # call edge: who invoked me (top-level turns use "ROOT")
    predecessor: Optional[str]    # conversation edge: the turn this one continues
    reads: list[str]              # which nodes went into this call's prompt
    metadata: dict
```

`output` is permanent original text; aging and compaction never touch it. Two pipeline node kinds join the chain like any other node: `context/system_prompt` records the exact system prompt whenever it changes, and `context/summary` stands in for the turns a compaction replaced.

### The git metaphor: retry / edit / fork are the same operation

Each turn is a "commit", and `predecessor` is the object it responds to. retry / edit / fork
are essentially identical — hanging a divergent sibling under some node's parent, differing only in how they're triggered:

| Operation | Meaning |
|---|---|
| Send a new message | append a node under the current HEAD, HEAD advances |
| retry | a same-content sibling (assistant re-sampling / function re-run) |
| edit | a different-content sibling (forks under the same parent) |
| switch version `< N/M >` | checkout to a sibling, **display-only, no re-run** |
| copy conversation | new Session holding the history up to HEAD, diverges going forward |

Key points: **checkout never triggers a re-run** (switching HEAD only re-renders); **edit/retry/checkout are forbidden while an agent is running**
(to avoid hanging the active execution tree on a node that's about to "go stale"); **workdir does not roll back with checkout**
(side effects belong to the user, just as `git checkout` won't re-run your tests).

---

## 3. Rendering, Aging and Compaction

### Which nodes are read

`render_context(graph, head_id, frame)` walks the predecessor chain from the head back to the start of the branch and, for each turn on it, admits the turn's call subtree through the frame and `expose` rules. Sibling branches are never read, and a spawned sub-agent's internals stay in its own branch. The walk is pure: it writes nothing. `render_dag_messages` then translates the selected nodes into provider messages: a tool call becomes a real ToolCall/ToolResult pair inside its assistant message, a direct function call a text pair.

### Aging

The last `TAIL_TURNS` (default 3) assistant turns keep their tool output in full; older tool results render as a short `[aged]` stub. The aging boundary advances only when a turn commits, never inside one, so two requests in the same turn share a cache prefix. Each model call records a `render_manifest` (policy version, aging boundary, spilled nodes), so a historical call can be re-rendered byte for byte. Nodes larger than the spill threshold are spilled to disk when they are written, never when they are read.

### Compaction

When the budget reaches 80% before a turn (or the user runs `/compact`, or the provider rejects a request as too long), `engine.compact` summarizes the oldest whole turns into one `context/summary` node whose `covers_ids` lists the turns it replaces. A branch that contains the whole covered segment renders `[summary, kept tail…]`; any other branch renders raw. There is at most one active summary per session: the next compaction absorbs the previous one. The summary is validated before it is written (it must be non-empty and strictly smaller than what it replaces), and HEAD and the original history stay unchanged. Full specification: [`compaction.md`](compaction.md).

---

## 4. Attach / Merge (Cross-Branch References and Aggregation)

Both reuse one mechanism: an **attach pointer**, a node with `function="attach"` that hangs off a user turn as a side child and carries another branch's content. Because it sits in that turn's call subtree, the normal render admits it; it renders as delimited `[Attached from "label"]` … `[End of attached content]` text.

- **Attach** is passive: the pointer is staged and the content is read on the next model call.
- **Sub-agent report**: when a spawned sub-agent finishes, its result returns to the caller as an attach pointer holding the task, the final reply and the `read_conversation(session_id, head_id)` address of the full transcript. A synchronous spawn returns the reply in its `agent` tool result instead. The caller sees what the sub-agent concluded, not every step it took.
- **Merge** is active: `process_merge_turn()` writes one attach pointer per peer branch after the target head, plus a merge instruction, and runs a normal turn on the target session. One peer can be marked as the base; its content is kept verbatim while the others may be summarized. After the turn, the merged peers' heads are marked merged and a multi-parent context commit records which branches the result drew from, so the Context timeline can show the lineage.

---

## 5. Cross-Turn Tool Context

**Problem**: if tool calls in history are dropped, the model can't see across turns which tools it called,
with what arguments, and what they returned — leading to repeated calls and hallucinating files it "already checked". This is distinct from summarizing the whole history (per-item
tool aging vs. whole-segment semantic compaction).

**Strategy** (tool aging from §3, in detail):

- **tail-window full text**: the tool_use / tool_result of the most recent `TAIL_TURNS=3` assistant turns is
  retained in full.
- **old-turn aging**: for earlier turns, the tool_use head is kept (args truncated to `MAX_TOOL_ARGS_CHARS=200`),
  and the tool_result is swapped for a one-line semantic stub.
- **per-item cap**: any tool_result over `MAX_TOOL_RESULT_CHARS=4000` is truncated at head and tail (truncated even within the tail,
  to prevent a single turn from blowing up).
- **critical-tool protection**: `PRUNE_PROTECTED_TOOLS={todo_create, todo_update, todo_list, open_work, web_search}`
  do not participate in aging.

Data flow: `render_context` selects the branch's turns with their tool calls → the aging pre-pass marks code nodes before the boundary (full in tail
/ stub for old ones) → per-item truncation → `render_dag_messages` emits ToolUse +
ToolResult content blocks; whole-segment summarization happens separately, in compaction. Code: `openprogram/runtime/context/tool_aging/`, `aging.py`, `render.py`.

Thresholds are taken from reference frameworks: tail-window (OpenCode), per-item stub (Hermes), per-item truncation + critical-tool
protection (OpenCode).

---

## 6. Invariants

1. The DAG is append-only; aging and compaction never change node content.
2. The read path is pure: rendering writes nothing; spill happens on write.
3. The aging boundary only advances, and only at turn commit.
4. A historical call re-renders from its recorded `render_manifest`, not from today's policy.
5. A session has at most one active summary; a summary never moves HEAD or rewrites edges.
6. A branch never reads a sibling branch or a spawned sub-agent's internals; other branches arrive only through attach pointers.
7. checkout is display-only, does not re-run, does not roll back the workdir.

---

## 7. UI

- **History view**: the full DAG, with one node shape per role, showing all tool calls /
  retry branches / merge confluences.
- **Context timeline** (right sidebar): `apps/web/components/right-sidebar/context-commit-timeline/`
  + `ws_actions/context_commits.py`. Lists the session's recorded context commits, grouping
  sibling attempts at the same fork point, with each commit's items, state badges and token counts.

### Occupancy: one number, two readers

Two widgets report how full the window is — the progress ring in the composer
(`apps/web/components/chat/badges/context-badge.tsx`) and the `/context` breakdown panel it
opens (`apps/web/components/chat/badges/context-breakdown-panel.tsx`). Both render the same
server-computed record, so they agree at every moment:

```python
{"window": int, "total_used": int, "basis": "measured" | "estimated",
 "estimated": int, "calibration": float}   # calibration only when measured
```

`openprogram/runtime/context/session_stats.py` builds it; `server.session_context_stats`
serves it to `/context` and `server._broadcast_context_stats` pushes it over the
`context_stats` WS frame. The ring reads `total_used / window` from the store; the
panel reads the same fields for its headline and derives `Free space` from them,
so its per-category rows never contradict the total.

The panel has two levels. The overview shows four parts (system prompt, tools,
memory, conversation); clicking one, or its bar segment, opens its detail. The
system prompt detail lists components (base prompt, output style, the agent's own
prompt, environment, AGENTS.md, skills index, workflows and tool notes, date, plan
mode) with their text; tools are grouped loaded / on demand / MCP; memory lists the
`MEMORY.md` of each layer; the conversation is split by kind
(`messages_detail.groups`) with its largest messages (`messages_detail.top`), each
linking to its transcript row. Detail rows are scaled with their category, so they
add up to it. A chat with no session yet reads `GET /api/context/draft?provider=&model=`
(`session_stats.compute_draft_breakdown`): the agent's prompt and full toolset
against that model's window. When a turn records its `context/system_prompt` node, the node's
metadata carries `sections: [{name, chars}]`, the length of each component's block,
so `session_stats` cuts the recorded text back into components exactly. A node
recorded before that is split by locating the blocks of a fresh build in it; what
cannot be located shows as Other.

The canonical WebSocket chat runner records each provider request's prompt size
as it finishes, so the ring and panel update between tool calls. At turn end it
refreshes the active branch head and persists the final measurement. Session
loading can recover a newer provider usage
record when an older chat turn finished before this broadcast was implemented;
it only does so when no later session edit has superseded that usage.

**The number always describes now.** Two bases produce it:

| Basis | When | `total_used` |
|---|---|---|
| `measured` | a real request just completed | what the provider billed for that call's prompt (`input_tokens + cache_read`) |
| `estimated` | the graph moved since that request | recomputed from the current branch with the local tokenizer |

A measured reading also records `calibration` — measured ÷ estimated for the same
graph — which says how far the local estimate drifts from what the provider charges.

**Graph-change triggers.** Anything that changes what the next request will carry
re-estimates and re-broadcasts through `server.refresh_context_stats`, so the ring
follows the graph instead of lagging one request behind:

| Change | Site |
|---|---|
| compaction lands mid-turn | `openprogram/interfaces/server/ws_actions/chat/context_usage.py` (the measured request after compaction) |
| model switch | `openprogram/interfaces/server/routes/execution/runtime.py`, `openprogram/interfaces/server/ws_actions/runtime.py` |
| branch checkout / delete | `openprogram/interfaces/server/ws_actions/branch.py` |
| sibling checkout | `openprogram/interfaces/server/context_git_routes.py` |

A measurement belongs to the branch it was taken on: `session_context_stats`
keeps the `measured` basis only while HEAD has not moved, and re-estimates for
any other head.

**Window resolution.** One path only — `get_model(provider, model)` +
`real_context_window()`, splitting `"provider:model"` on the colon
(`server._resolve_context_window`). The session's picker override wins over its
persisted model, so a switch takes effect before the next save.

---

## 8. Relationship to the Three-Layer Composition

[`composition.md`](composition.md) layers each LLM call into three tiers by how often
the content changes, which serves the cache (stable content up front) and also tells the model its
situation. This document's mechanism supplies the material for those tiers:

| Tier | Content | Change frequency | Where it comes from |
|---|---|---|---|
| **L0 constant** | identity / global instructions / tool list | unchanged for the whole session | assembled by the engine's system-prompt step (§1) |
| **L1 situation** | which function I'm a part of / who called me / which step of the program / where the output goes | changes on each new frame | the call tree, rendered from the DAG (§2) |
| **L2 task** | progress within the frame / inherited upstream results / current input / output format | changes each step | history selection + compaction (§1, §3) |

---

## Appendix: Implementation Status

- The DAG render described in §1–§3 is the only chat context pipeline; `openprogram/runtime/context/engine.py`, `nodes.py`, `render.py`, `aging.py` and `compaction_view.py` are authoritative.
- The context-commit generator and its rule pipeline (`openprogram/runtime/context/commit/`, `rules/`) are no longer on the chat path. Context commits are now written only by merge turns, so the Context timeline shows merge commits and commits recorded by sessions from before the DAG render; it does not yet show the rendered view of an ordinary turn.
- The auxiliary paths' system prompt does not follow the agent. Summarization and branch summary use a
  fixed summarizer prompt (`openprogram/runtime/context/prompts.py`) that does not track the user's AGENTS.md, identity, or
  skills.
- User-driven manual pin/unpin of individual context items is not available.

Current context occupancy uses the last measured request, never the sum of requests in a turn. Empty terminal events preserve the last measurement. If no measurement exists, the UI uses a local estimate. Persisted usage and calibration from the older cumulative accounting format are invalidated; cumulative billing totals remain unchanged.
