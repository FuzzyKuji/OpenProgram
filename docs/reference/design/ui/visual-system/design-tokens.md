# Design tokens

Every size, shape and ink in the web app is a tier. A component names a
tier; it never writes a value. The tiers live in
`apps/web/app/styles/design/`, one file per kind of value, and
`npm run check` (`apps/web/scripts/ui/check-design-tokens.mjs`) fails the build on anything written by
hand. This page is the map: which tiers exist, and which component sits
on which.

```
apps/web/app/
  globals.css              entry: tailwindcss → design → themes → styles
  styles/
    design/                the design system
      index.css            imports the token files below
      layout.css           rail widths, chat column, drag surface
      controls.css         control height tiers, list row, button corner
      composer.css         the input box's own geometry
      type.css             type tiers, font stacks
      shape.css            spacing unit, radius tiers
      color.css            accent family, the four text inks, fixed
                           interface colours
      icons.css            icon size tiers
      motion.css           transition durations, the easing
      layers.css           stacking layers (z-index)
      shadcn.css           shadcn's colour names → the app's roles
      tailwind.css         Tailwind's scan paths, variants, utility names
    themes/                colour values, one file per theme (+ fallback)
    base/                  document, focus, list row, shell layout,
                           scrollbar, sidebar, desktop chrome, motion
    chat/ right-dock/ dag/ global styles of those areas
```

Component styles stay next to their component (`*.module.css`); they
read the tokens and add no values of their own.

## Control heights


Every button-like control — Buttons, inputs, selects, toggles, list
rows and the hand-written buttons in stylesheets — takes one of five
heights. The heights are px tokens in `apps/web/app/styles/design/controls.css`:

```
tier       height  token                  Button size      font
─────────────────────────────────────────────────────────────────────────────
inline     20 px   --ui-control-inline    —                —
row        24 px   --ui-button-h-xs       xs · icon-xs     12 px
menu       28 px   --ui-button-h-sm       sm · icon-sm     13 px
standard   30 px   --ui-button-h          default · icon   14 px
composer   32 px   --ui-button-h-lg       lg · icon-lg     14 px
─────────────────────────────────────────────────────────────────────────────
```

`--ui-button-h` is `--ui-list-h`: the standard tier is the sidebar
chat row, and an ordinary button is exactly as tall as that row.

Which component sits in which tier:

| tier | components |
| --- | --- |
| inline 20 | controls drawn inside another control: the center tab's ×, the image annotator's colour swatches, the remove badge on a Launchpad tile, a new-tab shortcut tile and an image chip, the tool switch on a function card, the secret-reveal toggle in a user bubble |
| row 24 | actions that sit on a row, card or message: the sidebar chat row's ⋯, message hover actions (copy, retry …), the find bar's arrows, the address bar's star, the diff hunk and line-comment buttons, queued-message actions, session-resource row actions, branch row actions, bookmark actions, attachment remove and preview close, the project editor's remove, the composer popover's close, the split picker's close, the fast toggle in the effort pill, the Mermaid source toggle, the DAG zoom readout, the Agent catalog's required toggle, settings and avatar colour swatches, the sidebar's project actions (pin, new chat, options) and refresh, the recents filter, the Agents view menu, the skill catalog's install button, the file search's match-mode segment, `ManageIconButton` row actions and `RailAction`, provider account and model rows, an application row's ⋯, an Agent card's menu, the annotate button on an image tile |
| menu 28 | rows in a menu or popover (`itemCls`), and compact controls in toolbars and chip rows: the composer's environment chips (Local, channel, folder) and corner menu buttons, the mic and send buttons, top-bar chips and menu triggers, center tabs and the tab strip's + / overview / menu buttons, the built-in browser toolbar, download and find pills, terminal actions, the PiP title bar buttons, Review's menu and pagination, the DAG tool rail, the transcript's view controls, function-card "Use", Programs' view switch, Memory's view switch, file-panel and settings icon buttons, function-form chips; inputs that sit in a menu or toolbar: the command palette's search, the git menu's input, a bookmark's title, Launchpad's search, the file search options, the DAG selection actions |
| standard 30 | every other Button, input, select, toggle group and search field — page headers, cards, dialogs (the confirm dialog's Cancel / confirm), settings rows, Agents, Applications, Projects, the folder picker; sidebar rows and sidebar icon buttons (`ui-list-item`); the PDF toolbar; the message editor's buttons |
| composer 32 | the composer's corner buttons (`--composer-button-size`), the effort pill, the function form's inputs, and the canvas control tiles |

Not tiered, because they are not buttons of a size: the account
footer row (64px), the Agents settings width handle (20 × 44px), the
center tab's active state (28px + its 6px foot), the drawing of the
tab strip in the effects preview, the browser action cue, label tags,
the Switch (Nova's own 32 × 18.4px track, already in px), switch
knobs and icon glyph sizes. `tests/ui/ui-kit-is-nova.test.mjs`
lists them as its exemptions.

Rules:

- A Button picks its tier through `size`; never a height class
  (`h-7`, `size-8`) at the call site. A control drawn from class
  strings takes `h-(--ui-button-h…)` / `size-(--ui-button-h…)`, never a
  rem height (`h-8`) or a px one (`size-[22px]`); the Nova test scans
  every `.ts` / `.tsx` file for both.
- A hand-written button in a stylesheet sets `height` (and `width`,
  when square) to a tier token, never a px literal. The Nova test
  scans every stylesheet and fails on a literal height in a
  button-like rule.

## Type


Every font size is one of nine tiers, the type counterpart of the
control height tiers above. The sizes are px tokens in
`apps/web/app/styles/design/type.css`:

```
tier      size   line   token          Tailwind
────────────────────────────────────────────────────
2xs       11 px  16 px  --fs-2xs       text-fs-2xs
xs        12 px  16 px  --fs-xs        text-fs-xs
sm        13 px  18 px  --fs-sm        text-fs-sm
base      14 px  20 px  --fs-base      text-fs-base
chat      15 px  24 px  --fs-chat      text-fs-chat
md        16 px  24 px  --fs-md        text-fs-md
title     18 px  28 px  --fs-title     text-fs-title
lg        20 px  28 px  --fs-lg        text-fs-lg
display   30 px  36 px  --fs-display   text-fs-display
────────────────────────────────────────────────────
```

Which text sits on which tier:

| tier | text |
| --- | --- |
| 2xs 11 | counters and dots in a badge, tab counts, kbd hints in the PiP, uppercase group labels on detail pages, DAG node and panel meta, context-commit timeline meta, folder sizes, the attachment strip's size line, the composer chips' small hints, model-list tags |
| xs 12 | secondary meta beside or under a row: timestamps, paths, counts, the account footer's subtitle; menu section labels, menu notes and key hints (`GROUP_LABEL`, `MENU_NOTE`, `SHORTCUT`); field descriptions; xs (24px) Buttons |
| sm 13 | descriptions and helper text, center tabs, page tab pills (`manage-page` tabs, project tabs), Agent card text and pills, sm (28px) Buttons and toggles, settings labels in dialogs |
| base 14 | body text; sidebar and list rows; menu and Select rows (`itemCls`); default (30px) and lg (32px) Buttons, inputs, textareas, selects, toggles; dialog descriptions; card titles in grids |
| chat 15 | transcript copy, the composer's input, embedded conversation cards, the running panel title, the Markdown file preview |
| md 16 | section headings inside a page (Settings card titles, "All chats"), dialog titles, Markdown h3/h4 |
| title 18 | the page title in the header (`manage-page`), the title of a detail pane: Settings detail, Programs entry, Agent editor, Project, Memory editor; Markdown h2 |
| lg 20 | the sidebar wordmark, big figures (usage totals), glyph tiles (project icons), the effects preview, Markdown h1 |
| display 30 | the Launchpad folder title |

Rules:

- CSS writes `font-size: var(--fs-*)`, class strings write
  `text-fs-*`, inline styles `fontSize: "var(--fs-*)"`. Never a px or
  rem literal, never an arbitrary `text-[…]`, and never the stock
  `text-xs` … `text-2xl`: those once meant one size on one page and
  another on the next. `@theme` still maps them to the shadcn docs'
  meaning (`text-sm` = 14px) so pasted registry code renders right,
  but source code names the tier.
- Weights are 400 (body), 500 (labels, controls, row titles), 600
  (titles, emphasis) and 700 (transcript headings only).

## Spacing and radius

Tailwind's spacing unit is 4px (`p-2` = 8px, `gap-3` = 12px) on every
surface. Tailwind's default `0.25rem` landed on half pixels on the
app's 14px root (`p-3` = 10.5px), and a docs-scale container used 4px,
so one class meant two sizes. Hand-written CSS uses whole px multiples
of the unit where it can.

Corners take one of seven radii (`shape.css`), the same names in CSS
(`var(--radius-lg)`) and Tailwind (`rounded-lg`):

```
tier   size   used by
─────────────────────────────────────────────────────────────────────
2xs     2 px  16 px  hairline bars, progress tracks, carets, a tip's arrow
xs      4 px  16 px  tags, kbd, checkboxes, inline code, badges
sm      6 px  18 px  chips and small controls inside a row
md      8 px  24 px  every Button size, inputs, selects, hand-written buttons
lg     10 px  28 px  list rows, menus, popovers, Select popups, cards
xl     12 px  the centre card, split panes, page panels, dialogs
2xl    16 px  user bubbles, large floating surfaces
full          pills, avatars, dots (rounded-full, var(--radius-full))
─────────────────────────────────────────────────────────────────────
```

`--ui-button-radius` is `md` and `--ui-list-radius` is `lg`, so a
hand-written button has the same corner as a `<Button>`. A share of
the box (`50%`, a squircle's `26%`) and a concentric corner written as
`calc()` over a tier are allowed; a radius taken from a surface that
has no tier says so with a `shape:` comment on its line (the Launchpad
folder panel, the editing bubble).

## Text inks

Text takes one of four inks (`color.css`), strongest first:

| ink | text |
| --- | --- |
| `--text-bright` | titles, the hovered or selected row, values |
| `--text-primary` | body text, list rows, controls |
| `--text-secondary` | descriptions, helper text, inactive tabs, counts |
| `--text-muted` | meta (timestamps, paths, placeholders), disabled text |

Tailwind writes `text-text-bright` / `-primary` / `-secondary` /
`-muted`. The shadcn parts in `components/ui` keep the registry's
`text-foreground` / `text-muted-foreground`, which resolve to the same
inks; app code outside it does not use those names. Accents
(`--accent-*`, `--theme-accent`) mark state, never hierarchy.

## Interface colours

Theme colours live in `themes/`; a colour that is the same in every
theme is a named token in `color.css`, on `:root`. Components name the
token, never the literal. Each token keeps the exact value its
component used to write, alpha and format included; one written as
`light-dark(a, b)` follows the color-scheme of the element that uses
it. The groups:

| group | tokens | used by |
| --- | --- | --- |
| session status | `--status-working` `--status-needs-input` `--status-failed` `--status-unread` `--status-refresh-done` | the sidebar's session markers, the refresh flash |
| permission tiers | `--permission-deny` `--permission-ask` `--permission-allow` | the project permissions dots |
| error text | `--error-form` `--error-message-edit` `--error-document` | plugin dialogs, the message editor, the document window |
| catalog pills | `--pill-warn` `--pill-danger` | the skills catalog's hover tints |
| commit timeline | `--commit-state-*` (`-bg` and ink per state), `--commit-error`, `--commit-anchor`, `--commit-refresh-done` | the context commit timeline |
| ANSI | `--ansi-red` `--ansi-green` `--ansi-yellow` `--ansi-blue` `--ansi-magenta` `--ansi-cyan` | a program's progress log |
| ink on fill | `--ink-on-fill`, `--avatar-fallback-bg` | text on a coloured fill (snap label, Save, count badge, active colour well, letter avatar) |
| agent cursor | `--agent-cursor-keyline` `--agent-cursor-shadow` `--agent-light-pulse` | the agent cursor and the controlled-app lights |
| browser | `--browser-control-surface` `--browser-control-ink`, `--browser-pane-active` `--browser-pane-yielding`, `--browser-glyph-*` | the browser-control chip, the browser tab's pane outlines and home glyph |
| canvas controls | `--pane-light-*`, `--pane-divider-*` | a pane's window lights and the split divider |
| scrim | `--scrim-attachment-preview` | an enlarged message attachment |
| PDF preview | `--pdf-viewport-bg` `--pdf-thumb-shadow` `--pdf-thumb-current` | the PDF page well and thumbnails |
| GUI tool | `--gui-tool-rule` | the hairlines of a GUI tool's activity card |
| sidebar | `--nav-toggle-press` `--nav-item-press` `--new-chat-chip` `--new-chat-chip-hover` `--wordmark-from` `--wordmark-to` | pressed nav rows, the New chat chip, the wordmark |
| provider card | `--provider-card-highlight` | a provider's model card |
| theme scenes | `--theme-scene-rain-*` `--theme-scene-gradient-*` | the Code rain and Gradient previews in Settings, the Gradient scene and its glass chrome behind Launchpad |
| Launchpad | `--launchpad-*` | the shadows under app icons and an open folder, the edit-mode remove badge, the label shadow on the Gradient scene |
| running glow | `--running-glow-blue` `--running-glow-violet` `--running-glow-green` | the flowing glow on a running conversation's sidebar row |
| branch lanes | `--lane-0` … `--lane-17` | the conversation graph's lines, nodes and tags, the Activity panel's branch rows, the browser's new-tab tile initials (`lib/format-utils/lane-colors.ts` hands out `var(--lane-N)`) |
| code highlighting | `--hl-keyword` `--hl-string` `--hl-number` `--hl-comment` `--hl-title` `--hl-type` `--hl-attr` | highlight.js tokens in a message's code block |

The step tones in `styles/tool-tones.css` (`--tool-tone-*`,
`--timeline-*`) are the same kind of token; the Running panel's glyphs
read them. Every shadcn role (`--ring`, `--border`, `--muted`, …) is a
full colour, so a module reads it as `var(--ring)`; wrapping it in
`hsl()` resolves invalid and draws nothing. A translucent role is
`color-mix(in srgb, var(--muted) 34%, transparent)`.

A `var(--role, literal)` fallback names a role that is always defined
(the theme roles, `--accent`, `--destructive`, `--muted-foreground`)
without the dead literal; a role that no theme defines (`--danger`,
`--warning`, `--success`, `--red`, `--orange`, `--status-error`,
`--border-color`) was only ever its literal, so it is replaced by the
token holding that literal.

## Icons

An icon is 12, 14, 16, 20 or 24px (`icons.css`):

| size | where |
| --- | --- |
| 12 | inside xs (24px) controls, beside 11–12px text |
| 14 | inside sm (28px) controls, menu rows, chips |
| 16 | default controls, toolbars, page buttons |
| 20 | sidebar navigation, empty states, tiles, page-header glyphs |
| 24 | hero glyphs on empty pages |

A `size` of 28 and up is an illustration (avatar, logo), not an icon.

## Motion

A transition names a duration tier and the one easing (`motion.css`):
`transition: opacity var(--motion-medium) var(--ease-standard)`.

| tier | value | where |
| --- | --- | --- |
| `--motion-fast` | 120ms | hover, press, colour and border changes |
| `--motion-medium` | 160ms | reveals, fades, small movements |
| `--motion-slow` | 240ms | panels, drawers, larger movements |

`--ease-standard` is the one easing. Looping animations (spinners,
pulses) and spring curves written as their own `cubic-bezier` keep their
timing. When script waits for a transition to finish, its timeout is at
least the tier it waits for.

## Shadows

Elevation is one of the theme's shadow tiers, never an `rgba` written in
a component: `--shadow-sm` (cards, small raised parts), `--shadow`
(raised panels), `--shadow-popover` (menus, floating bars, drag
previews), `--shadow-dialog` (dialogs, full-window overlays), and
`--shadow-raised` / `--shadow-raised-hover` for the input box and
elevated buttons. Inset lines and focus rings are borders, not
elevation, and stay where they are drawn.

## Layers

A surface that has to stack above other surfaces names its layer
(`layers.css`); values from 1 to 12 inside one component stay local.

| layer | value | what |
| --- | --- | --- |
| `--z-sticky` | 20 | sticky headers inside a pane |
| `--z-floating` | 50 | panels floating inside a pane |
| `--z-drawer` | 100 | sidebars laid over the content at narrow widths |
| `--z-overlay` | 110 | the dim layer behind a dialog |
| `--z-dialog` | 120 | Dialog, AlertDialog |
| `--z-popover` | 130 | Popover, DropdownMenu, ContextMenu, Select, above dialogs |
| `--z-tooltip` | 140 | Tooltip |
| `--z-toast` | 300 | toasts |
| `--z-fullscreen` | 10000 | full-window editors and lightboxes |
| `--z-drag` | 100000 | drag previews and the drag surface |

Tailwind reads a layer as `z-(--z-popover)`; CSS as
`z-index: var(--z-popover)`, or `calc(var(--z-drag) + 1)` for a part
that sits just above its layer.

## Which layer writes what

Three ways of styling exist side by side; each has one job.

| Layer | Writes | Never |
| --- | --- | --- |
| shadcn parts in `components/ui` | every control: button, input, select, menu, dialog, switch, checkbox | — |
| Tailwind classes in the JSX | layout and spacing (flex, grid, gap, padding, size), simple states | complex selectors |
| `*.module.css` next to the component | what Tailwind cannot say: pseudo-elements (the project guide line), `data-*` and parent selectors, keyframes, layered cascades | a hand-made control, a literal value |

About 280 one-class, layout-only rules remain in the modules. The rest
moved to Tailwind where moving changes nothing on screen. A Tailwind
utility sits in `@layer utilities` and a module rule is unlayered, so a
moved rule loses to every unlayered rule on the same element. A rule
therefore stays in its module when its class appears earlier in the
stylesheet, when the element is a component that merges its own
classes (a `DialogContent` keeps its `sm:max-w-*`), when another module
class on the element sets one of the same properties, or when the
styles object is re-exported or passed whole. These move when their
component is edited, and the guard makes sure the number only goes
down.

## The guard

`apps/web/scripts/ui/check-design-tokens.mjs` (run by `npm run check`)
scans every stylesheet and `.ts` / `.tsx` file and refuses:

- a font size that is not a `--fs-*` tier, an arbitrary `text-[…]` or a
  stock `text-xs` … `text-2xl`; a font named by hand, the `font`
  shorthand, forced `tabular-nums` (Settings owns the typeface and
  digits);
- a weight other than 400 / 500 / 600 / 700;
- a radius in px, an arbitrary `rounded-[…]`, bare `rounded`,
  `rounded-3xl` and up, `--radius`, or a `--radius-*` name that is not
  a tier;
- the retired ink aliases (`--text-tertiary`, `--text-dim`),
  `text-[var(--text-*)]`, and the shadcn ink names outside
  `components/ui`;
- an icon `size` below 28 that is not a tier;
- a colour literal (`#hex`, `rgb()`, `hsl()`) outside the places that
  define colour tokens: `app/styles/themes/`, `app/styles/design/` and
  custom-property lines in `app/styles/`. A component names a token
  (see Interface colours);
- more layout-only rules in a CSS module than
  `apps/web/scripts/ui/module-layout-baseline.json` allows for that file
  (a new module may have none). After moving such rules to Tailwind,
  `node scripts/ui/check-design-tokens.mjs --write-layout-baseline`
  lowers the numbers.

`apps/web/tests/ui/ui-kit-is-nova.test.mjs` refuses a literal control
height in stylesheets and class strings.

Exceptions are named, never silent: APIs that take pixels (xterm,
Mermaid, canvas, Electron views), Framer Motion's numeric radius on the
Agent cards, the input box (hands-off: its radii, weights and icons stay
as drawn), and a line that says `glyph:` or `shape:`. Colour literals
that are data or drawing, not interface colour, are listed in
`COLOUR_DATA`: user-picked palettes and chart series, artwork (Launchpad
app icons and memory icons, the code rain, search-provider glyphs), APIs that
take a colour string (canvas, WebGL, xterm, Mermaid, pdf.js, the web
manifest), and the effort heat scale computed as `hsl()`. A `mask:`
line is exempt too, since its colour only shapes the mask.

A value that fits no tier is a design change: add the tier (or the
component's row in a table above) first, then build it.
