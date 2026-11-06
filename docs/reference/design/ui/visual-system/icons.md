# Icon system

The web app draws from three icon families. Each has a territory, so a
screen never mixes a filled glyph next to a line glyph by accident.

| Family | Territory | Package / source | License |
|---|---|---|---|
| **Solar** (Bold Duotone) | The composer area: environment-row chips, the control row and its plus menu, model / permission badges, the effort pill, the question / approval panel, the send arrow. Also the tiles of the chat execution timeline rows, and the DAG canvas's view controls and the pane's perspective strip (view toggle, session actions) | `apps/web/components/solar-icons` — bodies vendored from the Iconify `solar` set into `bodies.ts` by `apps/web/scripts/icons/fetch-solar.mjs` | CC BY 4.0, Solar Icons by 480 Design |
| **pqoqubbw animated line icons** | App chrome outside the composer: left rail, center tabs, sidebar, settings nav, function cards | `apps/web/components/animated-icons` | MIT |
| **lucide-react** | Everything else that needs no motion: settings bodies, dialogs, the timeline's disclosure chevron | `lucide-react` | ISC |

Provider logos come from LobeHub (`components/settings/providers/icons/lobe-icons.ts`),
the user's avatar from DiceBear, and an Agent's avatar is a character
([Agent avatars](agent-avatars.md)); none of them is part of this contract.

Nobody hand-authors icon SVGs. A new Solar icon is added by extending
`ICONS` in `fetch-solar.mjs` and rerunning it; the generated file is
committed so builds stay offline.

## Solar in the composer

Two-tone glyphs read as designed-for-purpose at the composer's 14–16 px
sizes, where the line sets looked generic. Every Solar icon uses the one
Bold Duotone style: a filled glyph plus a 50 % lighter secondary layer.

| Role | Solar icon |
|---|---|
| `+` options trigger | `tuning-2` |
| Add files | `paperclip` |
| Tools | `case-minimalistic` |
| Tool profile | `settings-minimalistic` |
| Web search | `global` |
| Sandbox | `box-minimalistic` |
| Unattended off / on | `eye` / `eye-closed` |
| Thinking effort | `fire` |
| Chat model badge | the logo of the model's provider (the Settings provider list's logos), drawn at 20/24 of its box like a Solar glyph's live area because the logos run edge to edge; `cpu` for a provider without one |
| Agent badge | the Agent's [avatar](agent-avatars.md), not an icon |
| Fast mode | the effort chip's `fire` turns red |
| Permission badge | `shield-check` |
| Local connection chip | `monitor` |
| Web tab chip | `earth` |
| Picture-in-picture chip | `pip-2` |
| Working folder / add folder | `folder-with-files` / `add-folder` |
| Project chip / missing project | `folder-open` / `danger-triangle` |
| Menu check | `check-circle` |
| Close × | `close-circle` |
| Carets | `alt-arrow-right`, `alt-arrow-down` |
| Send | `plain-2` (paper plane) |
| Copy | `copy` |
| Model capabilities (vision / video / tools / reasoning) | `eye` / `videocamera` / `case-minimalistic` / `lightbulb-bolt`; the briefcase renders at 12px rather than 14px because its artwork fills the box while eye and camera leave a margin, so this is the size at which their edges line up |
| Git pill / its menu: new branch or worktree, worktree, PR, view PR | `git-branch` / `add-circle`, `folder-path-connect`, `git-pull-request`, `square-arrow-right-up` |
| File-change card: title / file rows | `pen-new-square` / `file-text` |
| File-change card: undo / Review buttons | Font Awesome `rotate-left` / `eye` (solid), icon + text label |

Solar's undo glyphs are hairline arrows that disappear at button size,
so the file card's two action buttons use solid Font Awesome glyphs
instead, vendored by the same script into the same table (their
viewBox is recorded in `SOLAR_VIEWBOXES`).

Glyphs that reflect a toggle switch with the state rather than relying
on colour alone: Unattended closes the eye once nobody is watching, the
while-running mode shows a forward arrow for Steer and a queue list for
Queue, the project chip turns into the warning triangle when its folder
is gone.

Two composer glyphs are **not** Solar. The Fast (speed) toggle in the
effort card keeps the gauge from the animated set, with its needle rotated
by the `active` prop; on the effort chip itself, Fast only turns the
`fire` glyph red.
The `?` help button in the effort card
([effort-picker.html](../composer/effort-picker.html)) is lucide `CircleHelp` at 14px: Solar
has no vendored question glyph yet, and the button is static, so it needs
no motion handle. See the implementation status below for both.

## Solar in the execution timeline

Each row of the expanded execution timeline starts with a 24 px tinted
square (20 px when nested) holding a 13 px glyph (11 px nested). The
glyphs are Solar Bold Duotone, so the rows read as flat filled marks in
the tone colour rather than line drawings. `presentTool()` in
`apps/web/components/chat/messages/execution/tool-presentation.ts` picks the glyph
per tool (`ToolPresentation.icon`, a `SolarIconName`); `StepRow` in
`execution-strip.tsx` falls back to a glyph per row kind when no tool
glyph is given. The tile and its tone colours are unchanged by the icon
family.

| Row | Solar icon |
|---|---|
| Command (`bash`, `write_stdin`, `terminal_use`) | `programming` |
| Execute code | `code-square` |
| Edit / write / patch | `pen-new-square` |
| Read file / PDF | `file-text` |
| List folder | `folder-open` |
| Find files (`glob`) | `file-search` |
| Search (`grep`, code search) | `magnifier` |
| Code intelligence (LSP) | `structure` |
| Web search / fetch | `global` |
| Browser control | `cursor` |
| Generate image / analyze image | `gallery-add` / `gallery` |
| Canvas, send file, message an agent | `plain-2` |
| Sub-agent tools | `ghost` |
| Read conversation | `book` |
| Ask the user | `chat-round-question-mark` |
| Plan mode | `map` |
| Scheduled jobs | `calendar` |
| Run program | `box` |
| Use skill | `stars` |
| Resource, memory | `database` |
| Todos | `checklist` |
| Worktree | `git-branch` |
| Self-update | `refresh` |
| MCP | `plug-circle` |
| Any other function | `sledgehammer` |
| Fallbacks by row kind: thinking / LLM / sub-agent / function | `lightbulb-bolt` / `cpu` / `ghost` / `sledgehammer` |

Solar has no wrench, so generic function rows use the sledgehammer as
their tool mark. The thinking fallback reuses `lightbulb-bolt`, the same
glyph the model selector uses for reasoning. A failed row keeps its
small stroked ✗, and the disclosure chevron after the summary stays
lucide `ChevronRight`. Neither is a type glyph.

Timeline glyphs are static (`motionPreset="none"`). The row head is not
a button, and clicking it only expands or collapses the row. The glyphs
carry no tooltip, because transcript content gets no hover tips.

## Motion contract

All three families speak the same imperative handle,
`AnimatedNavIconHandle` (`startAnimation` / `stopAnimation`), so the
container — a button, a menu row, a chip — is the hover target and the
glyph never animates on its own 16 px hit area. A parent attaches a ref
and drives the motion. A Solar icon rendered without a ref follows the
hover of its nearest clickable ancestor (button, link, menu item of any
kind, listbox option, chip), so every button animates the same way whether
or not it wires a ref. The selector, the pop scale and the spring live in
`components/ui/hover-pop.ts`, which Agent characters use too
([Agent avatars](agent-avatars.md)), so a character pops like the icons beside it;
purely decorative glyphs — menu checks, warning triangles, capability
marks — use `none`.

The pqoqubbw icons redraw themselves (a wrench turns, an arrow bobs). A
filled Solar glyph cannot, so `SolarIcon` offers small, uniform presets
instead: `pop` (scale 1.12, the default), `fly` (the send paper plane
moves 1.5 px up-right), `nudge` (a caret slides 1.5 px right), `pulse` (a one-shot
pop-in, used when a menu item becomes checked) and `none`. Everything
collapses to no motion under `prefers-reduced-motion`.

`SolarIcon` renders a `span.inline-flex` wrapper around the `<svg>`, the
same shape as the animated-icon wrapper, so container CSS that sizes or
hides "the element holding the svg" keeps working.

## Attribution

Solar Icons © 480 Design, released under CC BY 4.0
(<https://github.com/480-Design/Solar-Icon-Set>). The two Font Awesome
glyphs are Font Awesome Free, © Fonticons, CC BY 4.0
(<https://fontawesome.com/license/free>). The notice lives in
the header of `bodies.ts` and here; a user-facing credits
entry is still to be added (see below).

## Implementation status

- Composer area on Solar, including the environment-row chips, the plus
  menu, the question / approval panel and the model / permission badges
  shared through `components/chat/top-bar`: **implemented**.
- Execution timeline row tiles on Solar (per-tool glyphs and the
  thinking / LLM / sub-agent / function fallbacks): **implemented**.
- Fast toggle as a state-driven gauge (needle idles low when off, sweeps
  to high and turns accent-red when on): **not implemented** — the
  animated-set gauge with a static `active` rotation remains.
- Effort-card help glyph on a Solar `question-circle` (vendored through
  `fetch-solar.mjs`): **not implemented** — lucide `CircleHelp` stands in.
- User-facing third-party credits entry for Solar (CC BY): **not
  implemented**.
- Rail, tabs, sidebar and settings stay on the animated line set; no
  migration is planned for them.
