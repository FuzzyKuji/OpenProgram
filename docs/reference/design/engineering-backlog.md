# Engineering improvement backlog

Cross-workstream completion, unmerged implementations and delivery sequencing belong in [Implementation status and handoff](implementation-status.html). This page contains unresolved proposals that need a decision before scheduling. Validate each candidate against current source before implementation; old counts and audit dates are not current evidence. Remove an item when its decision is incorporated into its canonical design.

## Frontend state consolidation

The state-layer proposal retains follow-up work to remove legacy `window.*` state entries, including `W.currentSessionId`, `window.conversations`, `W.isRunning` and `window.__sessionStore`. Audit current usage rather than relying on old occurrence counts. Untyped `window.dispatchEvent` events are part of the same review.

The WebSocket layer in `apps/web/lib/net/ws/use-ws.ts` also rebroadcasts store frames through untyped CustomEvents. Evaluate this together with legacy state retirement, since it creates a second state propagation path alongside the store.

## Repository structure

Findings from a whole-repository structure review, to be discussed one at a time in this order. The intended layering is core (`openprogram/`) at the bottom, with the Server (`openprogram/interfaces/server`) and the CLI (`openprogram/interfaces/cli`) depending on it and never the other way round.

1. **`openprogram/models/providers/` keeps its shared modules in one level.** The provider folders live under `adapters/`, but about 30 shared modules (registry, streaming, types, cache, subscription, configuration) still sit side by side at the top. Proposal: group the shared modules by registry, models and streaming.
2. **Design records lack subfolders.** `docs/reference/design/ui` and `runtime` each hold around a hundred files in one level, and the `site-*` and `repository-*` pages sit loose in `docs/reference/design/`. Proposal: subfolders by area, with `nav.py` routing kept intact.

## Modules with multiple responsibilities

Re-measure module size and responsibility boundaries when scheduling this work. Candidates include `openprogram/programs/tools/computer_use/computer_use_agent/desktop/macos.py` and `windows.py`, `openprogram/state/store/snapshot/checkpoint/store.py`, `openprogram/host/security/safe_http.py`, `apps/desktop/main.js`, `openprogram/runtime/conversation/process_runner.py`, `openprogram/programs/applications/browser/pages.py`, `openprogram/interfaces/server/routes/catalog/programs.py` and `openprogram/programs/_host/runtime.py`. Vendored yoga-layout and ink runtime code under `apps/cli/src/runtime/` is outside this refactoring proposal.

## Regression review checklist

The former repository issue snapshot mixes previously corrected behavior, unverified observations and feature proposals. It is consolidated here as a verification checklist, not a claim that every item is currently broken. Reproduce against current source and the public UI before creating an implementation task; record completion in the relevant canonical design.

| Area | Behavior to verify | Source or entry |
| --- | --- | --- |
| Rewind | Web submits the confirmed apply phase with the plan hash and idempotency key; missing results show an actionable state | `ws_actions/chat/rewind.py`, `_rewind.py`, `message-actions.tsx`, `slash-commands.ts` |
| Command delivery | A closed WebSocket does not count as a successful command or clear the draft | `wsSend`, composer submit |
| Slash commands | Opening `/` does not unexpectedly execute compact; missing `/skill` names and `/task` prompts are rejected with feedback | `slash-commands.ts` |
| Command menu | Closing animation does not consume Return or block history Up/Down; required arguments remain editable | `selectSlashCommand`, composer key handlers |
| Session requirement | Commands without a session give feedback instead of silently clearing input | Composer and slash commands |
| Compaction | Busy, suggested, completed, failed and no-op states are visible; compact precedes snip where required; reactive compact/snip events also receive UI feedback | `loop_runner.py`, `reactive.py`, `chat-handlers.ts` |
| Context history | Compaction retains old turns and the DAG head; snip changes only the next request history; summary expansion needs visible verification | Context details and chat transcript |
| Help and doctor | Help exposes and focuses the command menu; doctor has an intentional result presentation with and without a session | `/help`, `/doctor` |
| Overlapping controls | The jump-to-latest control and slash menu remain usable at their actual positions | Chat UI; overlap must be observed, not inferred only from z-index |
| Attachments | Unsupported or oversized files produce explicit feedback | `image-attach.ts` |
| Desktop startup | The window appears with its intended layout instead of visibly resizing from the corner | Installed desktop App |
| CLI resume | The CLI resume argument reaches the Ink runtime with the intended session | `openprogram/interfaces/cli/ink.py`, `apps/cli/src/index.tsx` |
| SSO, speech and plugin isolation | Documentation distinguishes implemented methods/providers from unimplemented entries; community plugin execution matches its isolation contract | `auth/methods/sso.py`, `speech/tts.py`, `plugins/sandbox.py`, plugin loader |
| Function recovery | Same-frame resume is distinguished from creating a sibling retry; indirect call cycles are addressed by the documented recursion policy | `ws_actions/chat/retry.py`, `agent/call_state.py` |
| Function metadata | Dynamic metadata and literal source declarations follow the documented form contract | Function forms and metadata documentation |
| Distribution | Linux desktop artifacts, upgrade failure recovery, manual workflow publication and sandbox behavior gates match the supported installation documentation | Installation, source upgrades and Workflow publishing |
| Command registry | Duplicate names across registries have a defined lookup order and an unambiguous menu | `runCommand` and command menu |

Idle automatic compaction remains a product decision, not an assumed bug. Environment-variable discovery is not a substitute for the documented AuthStore boundary. External issue counts and earlier snapshot commit IDs are not evidence of current correctness.
