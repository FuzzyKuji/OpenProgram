# Web UI

OpenProgram has one workspace UI. It is a React and Next.js app (`apps/web/`), built ahead of time and served by the Python worker on the same port as the API, so the same pages run in a browser tab, in the desktop app, and against a remote server. The desktop app (`apps/desktop/`) is an Electron shell around those pages for macOS and Windows; on Linux and on servers you open the Web UI in a browser.

How the workspace is laid out today:

- **Sidebar and pages.** The main sidebar lists projects and chats and opens Agents, Abilities (Programs, skills, plugins, MCP), Applications, History and Scheduler; Settings sits in the user menu. List pages share one secondary rail.
- **Center tabs.** The center area holds tabs for chats, files, terminals and web pages. A tab can be split into side-by-side panes, and tabs and groups can move between desktop windows.
- **Chat transcript.** A turn shows the model's reply with tool calls folded into summary rows, a file-change summary, sub-agent rows and any requests waiting for you; the transcript follows new output until you scroll away.
- **Composer.** The input box carries attachments, the model and effort pickers, per-folder git pills and the Options menu; local file paths survive into the model context.
- **One visual system.** Colours, sizes and shapes come from design tokens and themes; icons, indicator dots and hover tips each follow one rule set.

The documents below are the design of each of these surfaces:

- [`invariants.md`](invariants.md) — cross-module UI invariants (walk the list before touching related modules)
- [`chat-transcript-follow.html`](chat/chat-transcript-follow.html) — unified transcript follow: one attach/detach policy for send, stream, Jump to latest, session switch, and history windows
- [`chat-turn-visual-spec.html`](chat/chat-turn-visual-spec.html) — chat-turn visual spec (execution timeline, file-change summary surface, manual function runs, and message minimap); file-history semantics live in the [canonical runtime design](../runtime/operations/file-management.html)
- [`tool-group-summary.html`](chat/tool-group-summary.html) — header of a folded run of tool calls: summary grammar, +N −M change badge, running tense, and the turn-level summary decision
- [`activity-panel.md`](chat/activity-panel.md) — the right sidebar's Activity: sub-agents as rows, the concrete issues that need you, and one page per row
- [`sub-agent-row.md`](chat/sub-agent-row.md) — a spawned agent's one step row: its status, its own conversation when opened, `job_id`-stamped frames, and branch transcript load
- [`interaction-feedback.md`](interaction-feedback.md) — the 0ms interaction-feedback rule (optimistic state first, data backfills)
- [`turn-occupancy.md`](turn-lifecycle/turn-occupancy.md) — stop, send-queue, and session-slot occupancy (released on cancel intent)
- [`state-layer.md`](state-layer.md) — web state layer: one store instance per session, with genuinely shared data global
- [`center-tabs-and-split-layout.html`](workspace/center-tabs-and-split-layout.html) — authoritative single-tab and composite split-tab lifecycle, rendering, persistence, and transfer design
- [`built-in-browser.html`](browser/built-in-browser.html) — built-in browser home, browser-profile import, compact History, and the four-entry new-pane launcher
- [`browser-extensions.html`](browser/browser-extensions.html) — product decision not to support Chrome/Edge extension installation or management, retained browser capabilities, and the inert legacy-data boundary
- [`integrated-terminal.html`](workspace/integrated-terminal.html) — real PTY terminal and direct local Claude Code launcher
- [`composer-local-attachment-paths.html`](composer/composer-local-attachment-paths.html) — local attachment path preservation from the composer to model context
- [`composer-responsive-controls.html`](composer/composer-responsive-controls.html) — responsive composer controls and compact-state interaction contract
- [`composer-options-menu.html`](composer/composer-options-menu.html) — Options (+) menu on the shared menu grammar; tools come from the Agent, not the menu
- [`effort-picker.html`](composer/effort-picker.html) — the effort card: lavender level name and `?` help tip in the header, a neutral stepped track with a highest-level animated square field, the thumb's level tip, and the Recommended caption
- [`programs-source-categories.html`](programs/programs-source-categories.html) — Programs grouping and source-category behavior
- [`composer-interaction-modes.md`](composer/composer-interaction-modes.md) — composer interaction modes
- [`attachment-handling.html`](chat/attachment-handling.html) — complete attachment design: storage, admission, delivery, recovery, and acceptance
- [`chat-attachments.html`](chat/chat-attachments.html) — chat attachments both ways: what the transcript shows, how the agent hands a file back, how a readable file opens
- [`resource-preview.html`](resources/resource-preview.html) — Resources list, chat operation preview and human takeover of Agent-operated Pages
- [`agent-control-overlay.html`](browser/agent-control-overlay.html) — status pill and agent pointer drawn over a window or page the agent controls: placement, wording, motion, accent colour, and input safety
- [`indicator-dots.md`](visual-system/indicator-dots.md) — indicator dots
- [`agent-avatars.md`](visual-system/agent-avatars.md) — Agent avatars: the character an Agent wears, how it is stored and derived, where it shows, sources and licences
- [`git-folder-pills.md`](composer/git-folder-pills.md) — per-folder git pill in the composer: branch, change counts, branch switch, worktrees, pull requests
- [`hover-tips.md`](composer/hover-tips.md) — composer hover tips: one `HoverTip` + `TipBody` layout, title with current value, muted detail line
- [`icons.md`](visual-system/icons.md) — icon system: which family goes where (Solar in the composer, animated line icons in the chrome, lucide elsewhere), motion contract, attribution
- [`design-tokens.md`](visual-system/design-tokens.md) — design tokens: every size, shape and ink tier, and which component takes which
- [`surface-system.md`](visual-system/surface-system.md) — surface system
- [`theme-system.html`](visual-system/theme-system.html) — authoritative theme entry, complete token contract, component consumption, and desktop-overlay propagation
- [`secondary-rail.md`](sidebar/secondary-rail.md) — the one list column between the main sidebar and a page's content (History projects, Agents, Programs tree, Settings): shared rows, collapse, button roles
- [`settings-collapsible-columns.html`](settings/settings-collapsible-columns.html) — independent 49px collapse for the app and Settings nav; Providers list stays expanded with a full-width search field
- [`avatar-randomization.html`](settings/avatar-randomization.html) — the user avatar picker: type first, then same-style variants or letter fields
- [`web-styles.md`](visual-system/web-styles.md) — web style organization (one component, one file; directories mirror the component tree)
- [`window-state.md`](desktop/window-state.md) — desktop window bounds, maximize/fullscreen, and titlebar resize hit-testing
- [`window-lifecycle.md`](desktop/window-lifecycle.md) — one main window: launch, Dock activate, and second-instance share a single create
- [`window-tab-transfer.md`](desktop/window-tab-transfer.md) — moving a tab, group segment, or group to another window or a torn-off one: one transaction, the same live web page, journals and rollback
