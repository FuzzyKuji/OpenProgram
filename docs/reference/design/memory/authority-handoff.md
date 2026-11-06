# Authority: Two Tiers and Pairing

> How OpenProgram decides what a speaker is allowed to make the agent do, and
> how that decision reaches memory. Speaker attribution itself is
> [`speaker-identity.html`](speaker-identity.html); the visual companion is
> [`authority-landscape.html`](authority-landscape.html).
> Related code: `openprogram/runtime/permissions/authority.py`,
> `openprogram/runtime/permissions/tool_authority.py`,
> `openprogram/interfaces/channels/_access.py`, `openprogram/interfaces/channels/base.py`,
> `openprogram/state/memory/writing.py`.

## The model

Admission is binary and authority is binary. A platform account is in one of
three states, only two of which are runtime authority tiers.

| State | Tier | Can do |
|---|---|---|
| **Owner** — local terminal, local web | `owner` | Everything: run commands, write files, send messages, manage and rewrite memory. |
| **Paired** — an approved platform account | `paired` | Converse, be recorded into memory with attribution, actively append memory. No tool execution. |
| **Unpaired** | none | The message does not reach the agent. The sender receives a pairing code. |

Unpaired is not a third tier. There is no "unknown external speaker gets
reply-only" state: an unpaired message is never rendered into model context at
all, which removes that prompt-injection surface rather than narrowing it.

## The gate

Authority travels as a single enum field, `authority_tier`, on the request
boundary alongside `principal_id`, `speaker_kind`, `speaker_id`,
`speaker_display` and `interaction`. A request never carries a capability list
of its own, so there is nothing a caller can mint inconsistently.

`decide_capability()` in `openprogram/runtime/permissions/authority.py` resolves a capability
against the `TIER_CAPABILITIES` constant table:

| Tier | Capabilities |
|---|---|
| `owner` | `reply`, `memory.source.append`, `schedule.create`, `schedule.manage`, `fs.read`, `fs.write`, `process.exec`, `network.send`, `approval.request`, `runtime.control` |
| `paired` | `reply`, `memory.source.append` |

The gate is **fail-closed**. A missing tier denies with
`AUTHORITY_TIER_MISSING`; a tier that is not a table key denies with
`AUTHORITY_TIER_UNKNOWN`. Neither case falls back to a reduced capability set —
an unrecognized request loses every capability, including `reply`.

`capability_for_tool()` in `openprogram/runtime/permissions/tool_authority.py` maps each tool name onto exactly one capability, and its
default arm is `process.exec`. An installed agentic function or a mounted MCP
tool can carry any name; treating an unclassified name as executable code means
a `paired` speaker cannot reach it, because only `owner` holds `process.exec`.

The gate sits in `_gated_execute` **before** the rule layer, before
the forced approvals (`force_approval`) and before the `bypass` short-circuit, so no permission
mode and no persisted allow rule can skip it. Every decision returns an
`AuthorityDecision` record — allowed, decisive check, stable reason code, tier,
capability — which is logged, so a denial is auditable rather than a bare
boolean.

`runtime_authority()` derives a subagent's or a runtime task's authority from
its parent: it copies the parent's normalized authority, rewrites the speaker
fields and sets `interaction` to non-interactive, and leaves `authority_tier`
untouched. Inheritance never widens. A `paired` turn cannot spawn an `owner`
child, and a parent with no valid authority yields `{}`, which the gate denies.
Because a subagent is never interactive, it also never holds a path to an
interactive approval.

## Pairing

A sender who is not on an account's allowlist is stopped at
`decide_inbound_sender()` and receives an 8-character uppercase pairing code.
The alphabet excludes the ambiguous characters `0`, `O`, `1` and `I`. Codes
expire after one hour, an account holds at most three pending codes at a time,
and the same sender is not re-prompted within the hour.

Approval happens **only on the owner's own machine**, through the CLI or the
local web UI. No channel message can approve anyone. "Please approve code X" in
chat is the canonical injection phrasing; the correct response is to refuse and
point at the owner.

Identity matching uses the platform's stable ID only. Usernames and display
names are mutable, so they are excluded from allowlist matching — someone who
renames themselves to the owner's name gains nothing. Display names reach a
prompt only after `sanitize_speaker_display()` strips newlines, zero-width and
bidi characters and neutralizes the envelope markers `[` and `]`.

## Trust semantics in memory

Memory cites chat messages, so trust is a question about the message a
footnote names. Pairing *is* the trust decision: the owner's turns and every
paired account's turns carry `memory.source.append`, enter the normal
distillation flow exactly as the owner's do, and may be cited, attributed by
speaker. There is no second gate behind the pairing gate.

**Unpaired text does not enter memory or model context.**
`openprogram/interfaces/channels/base.py` consults the access decision before any agent
dispatch. A blocked sender is answered with the pairing reply and the message
never becomes a turn, so there is no chat message to cite and nothing for
recall to return.

A new citation is checked when the edit that adds it commits: the message must
exist in the session store, be a person's or the assistant's words, and come
from a speaker whose authority carries `memory.source.append`. A paired edit
may additionally cite only its own conversation.

## The memory writer

The auto-organize writer follows the default chat agent's provider, model and
credentials rather than hardcoding one CLI agent. `memory.writer.model`
overrides it and is editable in the web settings UI. The default is deliberately
not a cheap model: weak models misread organizing instructions, so downgrading
is an explicit choice.

Retry classification is conservative in both the provider and the session
watcher: an unknown exception is non-retryable, and only explicitly classified
transient exceptions retry.

## Read scoping: stamp on write, filter on read

The policy follows LangGraph's store model: visibility is decided once, when
the content is written, and recorded on the content itself. A read carries the
requester's tier and keeps only what that tier may see. No read path recomputes
authority from conversation state, and no read path consults the pairing store.

**Visibility label.** Every Topic block carries one `visibility` value:

| Value | Written when | Readable by |
|---|---|---|
| `shared` | Every Source the block cites is `authority_tier=paired`, or the owner marked the block shared | owner, paired |
| `owner` | Any cited Source is `authority_tier=owner`, or the block cites no Source | owner |

Two values, not a per-speaker scope. A paired requester reads all `shared`
Topics rather than only memory derived from its own messages: the memory is one
shared workspace by product decision, speakers are already attributed inside it,
and a per-speaker scope would need a second identity index on every read for a
distinction the product does not make.

**Where the label lives.** In the Topic block's own definition line, beside
`Time:` and `Sources:`, so it travels with the block through the existing
Markdown parse and needs no side table that could drift from the prose. The
default for an unlabeled block is `owner`, which makes the migration a no-op:
today's entire workspace stays owner-only until a write relabels a block.

**Derivation, not declaration.** The writer never asks the model for a
visibility value. `install_state` computes it from the trust metadata of the
block's cited Sources, which task 2 now guarantees is Runtime-owned. A model
that could name its own visibility could publish owner content to a paired
reader by writing one word.

**Mixed-authority blocks.** A block whose cited Sources span both tiers is
`owner`. The alternative — splitting the prose — would hand a paired reader a
sentence fragment whose meaning depends on the removed half. The block is the
smallest unit of meaning the format has, so it is the smallest unit visibility
can act on. Where a mixed block is genuinely wanted in shared scope, the owner
splits it into two blocks; that is a memory-organization act, not a filter.

**Core injection.** `core.md` is rendered from `topics/core.md` on every write.
Rendering gains a second output: `core.md` (owner) and `core.shared.md`
(shared blocks only). `system_prompt()` picks the file by the session's tier.
Rendering both at write time rather than filtering at injection time keeps the
per-turn path free of a parse, and keeps the two views impossible to skew.

**Caches and indexes.** The lexical and embedding indexes keep indexing
everything and filter at query time on the label, rather than maintaining one
index per tier. Two indexes would double both the build cost and the ways they
can disagree. The filter is applied inside `MemoryBM25Index.search` and
`MemoryEmbeddingIndex.search`, below every caller, so a new caller cannot
forget it. Persisted index files stay a single artifact; the label is a stored
field on each row.

**Acceptance matrix.** Each row names the Runtime entry point that enforces
the policy and the case its test has to cover.

| # | Read surface | Enforcing Runtime entry point | Case | Test level |
|---|---|---|---|---|
| 1 | Core system prompt | `LocalMemoryBackend.system_prompt` | A paired session receives `core.shared.md`; no owner block appears in it | unit |
| 2 | Automatic per-turn recall | `LocalMemoryBackend.search` | A paired session's recall returns no `owner` block | unit |
| 3 | Explicit `memory_search` | `MemoryBM25Index.search` | A paired requester's hits exclude `owner` blocks at every `top_k` | unit |
| 4 | Embedding search | `MemoryEmbeddingIndex.search` | Same exclusion as row 3, same requester, same query | unit |
| 5 | `memory_get` | `inspect.read_file` | A paired requester reading a Topic file receives only its `shared` blocks; an all-`owner` file is a not-found, not an empty file | unit |
| 6 | `memory_search` with `exact` | `inspect.grep` | A literal string present only in an `owner` block produces no match for a paired requester | unit |
| 7 | `memory_get` without a path | `inspect.list_files` | A file with no `shared` block is absent from a paired listing, and block counts reflect the visible subset | unit |
| 8 | Mixed-authority block | `install_state` visibility derivation | A block citing one owner message and one paired message is labeled `owner` and never partially rendered | unit |
| 9 | Web reads | `/api/memory/*` route dependency | Every memory route resolves the requester tier and applies the same filter as the tool path | integration |
| 11 | Cache coherence | `MemoryBM25Index` persisted rows | A relabeled block changes what the next query returns without an index rebuild | unit |
| 12 | Fail-closed | tier resolution helper | An unresolvable or unknown requester tier reads as `owner`-only-denied, never as owner | unit |

**Migration impact.** None required. Unlabeled blocks read as `owner`, so an
existing workspace is unchanged and stays owner-only. Labels appear as blocks
are rewritten. No history-scanning migration code, consistent with product
decision 3.

**Not in this design.** Per-speaker read scoping, redaction inside a block, and
a hold queue for over-tier reads. Each needs its own design.

## Appendix: Implementation Status

The tier enum, the constant-table gate, fail-closed denial, structured decision
records, subagent inheritance, pairing with 8-character codes, local-owner-only
approval, stable-ID matching, display-name sanitization, citation checks,
and the context-exclusion mechanism above are implemented.

| Item | Status | Note |
|---|---|---|
| Hold queue for over-tier requests | Not implemented | A paired sender's over-tier request (for example "restart the service") queues for one-shot owner approval instead of flat denial. Parameters to adopt: a message cap, an expiry timeout, and re-evaluation of the queue when a sender's tier changes. |
| Read-time filtering by requester tier | Partly implemented | `memory.read` is a capability of its own, held by both tiers and distinct from `fs.read`, so the memory read tools no longer ride on filesystem access. `search` and `system_prompt` take the requesting tier from the caller that already resolved it and never re-read pairing state mid-turn. Per-tier redaction of block content is still designed only. |
| Queryable writer status | Implemented | Latest success time, `last_outcome`, and a failure classified into the closed `MemoryWriteFailureCode` taxonomy with its retryable verdict, plus a pending-turn count, under one versioned schema shared by the status file, CLI, tool, API and web UI. |
