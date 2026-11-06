# Surface system

The UI splits into two **surface contexts**. Each surface has its
own interaction language so the eye can tell at a glance which
"layer" of the app it is hovering: navigation vs content. These
rules apply in **light and dark** themes. Light-theme tokens are
the ones that usually go wrong (white fill on a pale rail).

## The two surfaces

```
─────────────────────────────────────────────────────────────────
surface        background tone           where it lives
─────────────────────────────────────────────────────────────────
deep           `--bg-secondary`          the page behind the
                                         three columns (`.app`)
─────────────────────────────────────────────────────────────────
panel          raised cards:             the left and right rails
               `--bg-input` (rails),     (`--bg-input`, same
               `--bg-primary` (centre)   material as the input
                                         box) and the centre
                                         column (`--bg-primary`:
                                         chat stream, settings
                                         and every other page)
─────────────────────────────────────────────────────────────────
```

The window is three floating cards on one page — the shadcn
Sidebar `floating` shell for both rails (`components/ui/sidebar.tsx`,
the registry's shell only) and its `inset` idea for the centre
column at once. Each card has Nova's floating-Sidebar corner
(`rounded-lg`, 12px; split panes and the canvas overview use the
same `--radius-lg`) and the
per-theme raised shadow (`--composer-shadow`), no border and no
ring; the rails keep a 7px gutter on every side (`p-2`), the
centre card sits 7px off the top and bottom edges and takes its
side gaps from the rails' gutters. The rails are white
(`--bg-input`) so they share a material with the input box and
the user bubble; the centre card stays `--bg-primary` so those
white raised elements keep their contrast on it.

In a split layout the centre card dissolves and every pane is its
own card of the same material (`.center-col[data-split]`): each
pane keeps 7px to the rail cards and the window edges, and the
panes sit 8px apart. Empty panes draw the same card themselves.

Collapsed, a rail is `--rail-collapsed-w` (63px: the 49px icon
rail inside the card plus the two gutters);
`components/layout/use-resizable-rail.ts` carries the same number.
Everything inside the cards — rows, section headers, the footer —
is unchanged by the shell and keeps the recipes below.

## Interaction language per surface

Mouse interaction never draws an outer focus ring on buttons. Keyboard focus
on buttons uses a small brightness change without an outline or box-shadow.
The top tab strip is the exception: its `role="tab"` targets use each theme's
own `--focus-ring`, which is lighter in dark themes and darker in light themes.

### Deep surface (sidebars)

Components on the deep surface are **list rows** — conversation
items, branch entries, function favourites, and the same row used
in a content-pane rail (MCP `drawio` / `linear` / `+ Add server`).
They should NOT behave like buttons:

- no border, no outline, no fill in the idle state
- hover / selected → switch background to a **visible grey**
  (``--bg-hover`` / ``--bg-selected``), text stays in
  ``--text-primary`` or ``--text-secondary``
- never fill selected rows with ``--bg-input``. The rail card is
  already that white; a white row on it disappears
- avoid the brand-coloured glyph treatment except for the very
  small status / activity indicators (``.indicator-dot``)

Rationale: the sidebar is dense and frequently scanned. A field
of brand-coloured pills makes it loud and visually competes with
the content column. Greying-on-hover keeps the layer calm and
still gives the click target enough feedback.

### Panel surface (chat content + dialogs)

Components on the panel surface ARE buttons / pills / cards:

- they sit on a lifted background, so a "ghost outline" pattern
  reads cleanly
- idle state — ``--bg-surface`` background, ``--text-primary``
  text or brand-coloured text for primary actions
- hover — fill with the brand colour, swap text to its contrast
  pair (``--text-on-accent``)
- the inverted hover is what makes the chain of "actions" feel
  like one design family — the user knows that the colour
  shift is universally the "this is going to do something"
  affordance

Header **tab pills** on a manage page (Abilities / Programs /
Plugins / Skills) are the one bright exception: the selected tab
uses ``--bg-input`` so it reads like the search box (lighter, not
darker). That fill is **only** for those pills. Do not copy it
onto sidebar rows or MCP server rows.

## One list-row recipe

Sidebar nav (`+ New chat`, Agents, Abilities, History, Scheduler)
and content-pane list rows (MCP `drawio` / `linear` / `+ Add server`)
share **one** box. Do not invent a second height, padding, radius,
or selected fill for the rail on the right.

```
property     token / value
─────────────────────────────────────────────────────────────────
height       `--ui-list-h` → 30px
padding      6px 8px
gap          12px
radius       `--ui-list-radius` (10px)
idle         transparent, 1px transparent border if needed for
             box-sizing only
hover        `--bg-hover`
selected     `--bg-hover`  (same grey, never white / `--bg-input`)
```

`+ Add server` is the same row as `+ New chat`: a normal list
row, slightly muted text. Not italic, not a different add-style.

Implementation: `.ui-list-item` in `apps/web/app/styles/base/list-row.css`
is the source. A page's list column (History projects, Agents, the
Programs tree, Settings) renders it through `RailItem`; see
[secondary-rail.md](../sidebar/secondary-rail.md). MCP `.serverItem` must match those metrics (prefer
composing `.ui-list-item` over a parallel recipe).

## Buttons

Control heights, type sizes, radii, inks and icon sizes are tiers; the
tables of which component takes which are in
[Design tokens](design-tokens.md).

Buttons are the shadcn/ui `Button` in the **radix-nova** style, the
style ui.shadcn.com's own docs use.
`apps/web/components/ui/button.tsx` is copied from the official
registry (`/r/styles/radix-nova/button.json`); the local changes are
its imports, a `forwardRef` wrapper for React 18, the px-pinned sizes
above, and the app's own looks: every Button has one shape,
`rounded-md` (8px) at every size, no border, lifted by the composer
shadow pair; colour alone marks the role (see Button variant
guidance).

Elements that cannot be a `<Button>` (a span that hosts its own
✕, a Radix trigger rendered as a span) take the same look through
`cn(buttonVariants({ variant, size }))` on their `className` — the
`cn()` merge matters: the raw class list carries both
`border-transparent` and the variant's border colour. A component
whose geometry must not move when the Button is restyled (the
composer's mic and send) takes its size from its own tokens and only
its colours from the variant (see Composer controls).

A header row (search + tab pills + icon buttons) shares one vertical
center. A 1–2 px height mismatch between controls in one row is a
bug, not a variant.

## Selects and menus

Every choice from a fixed list is the shadcn **radix-nova**
`Select` (`apps/web/components/ui/select.tsx`); the app has no
native `<select>` and no hand-rolled listbox. `SimpleSelect` is the
one-line form (`value`, `onValueChange`, `options`, optional
`label`, `placeholder`, `size`) and covers almost every call site;
grouped options pass `{label, options}` entries.

- Trigger: the registry's Nova trigger — a plain bordered field
  (`rounded-lg`, `border-input`, `bg-transparent`,
  `dark:bg-input/30`, `h-8` default / `h-7` `sm`). `SimpleSelect`
  defaults to `w-full max-w-48`; call sites only add width or an
  error border, never their own chrome.
- Popup: solid `bg-popover` in the menus' frame (`--popover-ring` /
  `--popover-shadow`, below), in the registry's `item-aligned` position — it opens
  over the trigger with the chosen row where the trigger was — above
  dialogs (`z-[130]`). Its
  first line is a muted group heading naming the choice (the
  `label`, else the `aria-label`); grouped options get one heading
  per group. The chosen row shows a plain check.
- Radix reserves `""` for "nothing chosen": an option whose value
  is `""` travels under a sentinel inside `SimpleSelect`; without
  such an option, `""` shows the placeholder.

All other menu popups — Radix `DropdownMenu`, the popover pickers,
the sidebar footer menu, the tab context menu and the function
context menu — share one frame and one row, taken from
`MENU_PANEL`, `itemCls`, `GROUP_LABEL` and `MENU_SEPARATOR` in
`apps/web/components/chat/top-bar/menu-styles.ts`. A CSS-module
menu keeps only its placement (position, z-index, width) in the
module and takes the frame and rows from those classes; it never
restates their values.

Every action menu opened from a small button or by right-click
builds its rows with `MenuRow` (`apps/web/components/ui/menu-parts.tsx`),
in the page and in the desktop overlay alike. A row reads, left to
right:

```
[icon] label ············ [key] [check] [›]
```

- **icon**: a Solar Bold Duotone glyph (`MenuIcon`, 16px, muted),
  the family the sidebar folder uses. Folder rows draw the folder in
  `--folder-color`; destructive rows draw it red.
- **key**: a price tag (`MenuKey`) in the platform's notation. The
  tag is a fixed 10px tip, the rounded right end of Solar's
  `tag-horizontal` outline mirrored to point left, joined to the
  shadcn `Kbd` as its plate: 18px tall, square where it meets the tip,
  5px round on the right, 1px / 6px padding around at least 8px of
  text, so every single-letter tag is the same width and a longer key
  only lengthens the plate. Both parts paint `--menu-key-bg`: the ink at
  12% over the popover at rest, one step above the menu (`--muted` sits
  below the menu in dark themes). The key text comes
  from `formatMenuKeys`: `⌘T`, `⇧⌘C` on macOS, `Ctrl+T`,
  `Ctrl+Shift+C` elsewhere. A menu shows only keys that already work:
  real shortcuts, or single letters the open menu answers (the chat
  menus' R/P/C/A/D). No global shortcut exists just to fill a tag.
  A lit row lifts `--menu-key-bg` to the ink at 22%, a step above
  the row's 9% hover fill, and turns the text bright.
- **check**: `MenuCheck` at the row end; an uncheckable row in a
  checkable group keeps the column empty (`CHECK_SLOT_PAD`).
- **submenu**: a trailing chevron; submenus nest to any depth.
- **lit row**: hover, keyboard highlight, an open submenu or the
  active row light the whole row, not only the label: the muted icon,
  key tag and chevron turn bright and the icon pops to 1.12, as the
  composer's icons do. A tinted icon (folder, destructive) keeps its
  colour and only pops.

The desktop overlay receives the same fields as data:
`DesktopContextMenuItem` carries `glyph` and `keys`, and the overlay
page renders them with the same parts. `scripts/ui/check-menu-rows.mjs`
holds every menu file to this row.

The frame is two tokens in `app/globals.css`, shared by menus, the
Select popup, `Popover`, the command palette and the page preview. In
the light themes it is the files card's frame: `--popover-ring` is
transparent (no hairline), `--popover-shadow` is the card's resting
shadow (`--composer-shadow`) and `--popover-shadow-hover` its deeper
one (`--composer-shadow-focus`): the frame deepens while the pointer is
over it, like the card. The dark themes lift the popup a step and
keep a light hairline with a soft deep shadow, because there a popup
sits on the same colour as the cards under it; their hover shadow is
the resting one.

```
part        Nova, at the docs' scale
─────────────────────────────────────────────────────────────────
panel       rounded-lg · p-1 · min-w-32 ·
            solid bg-popover · --popover-ring · --popover-shadow
row         min-h-7 (28px) · rounded-md · px-1.5 py-1 ·
            text-fs-base (14px) · gap-1.5 · size-4 icons, not shifted
hover       bg-accent (the ink at 9%) · text-bright
label       px-1.5 py-1 · text-fs-xs · font-medium · muted
separator   -mx-1 my-1 · 1px · --border
shortcut    price tag (MenuKey: Solar tip + Kbd) · text-[11px] · muted
chosen      accent check (MenuCheck) at the row end, never a fill
─────────────────────────────────────────────────────────────────
```

Menus, the Select popup and dialogs are one surface: the same solid
popover and the same `--accent` highlight, which `app/globals.css`
defines as the ink at 9% so a hovered row reads in every theme.
`--popover` is `--bg-input`: white in the light themes, one step
above the page in the dark ones. Only the accent check is the app's
own.

## Inputs and borders

Inputs share **one single-layer 1px** edge
(`border: 1px solid var(--border)`, fill `--bg-input`).

- Do not stack a 2px `:focus-visible` halo on that 1px edge; the
  stacked ring reads as a double frame.
- Hover must **keep** the 1px border. Setting `border-color:
  transparent` on hover makes the box look like it vanished
  (MCP catalog buttons had this).
- Do not invent a second input chrome per page. Settings,
  dialogs, plugins, and MCP editors use the same 1px +
  `--bg-input` treatment.

## Dialogs

Every modal is the radix-nova `Dialog` (`components/ui/dialog.tsx`)
or `AlertDialog` (`components/ui/alert-dialog.tsx`), copied from the
registry. There are no hand-rolled backdrops and no browser
`confirm()`.

```
part        Nova, at the docs' scale
─────────────────────────────────────────────────────────────────
overlay     bg-black/10 · backdrop-blur-xs · z-[110] ·
            data-native-view-occluder (native web views hide)
content     rounded-xl · bg-popover · ring-1 ring-foreground/10 ·
            p-4 · gap-4 · max-w-sm · z-[120]
title       text-fs-md · font-medium
description text-fs-base · muted
footer      -mx-4 -mb-4 · border-t · bg-muted/50 · p-4 ·
            buttons right-aligned, Cancel first
close       ghost icon-sm Button, top-2 right-2 (Dialog only)
motion      100ms fade + zoom-in-95; no slide
─────────────────────────────────────────────────────────────────
```

- Every "are you sure?" goes through `ConfirmDialog`
  (`components/ui/confirm-dialog.tsx`): title, optional description,
  an `elevated` Cancel and a confirm button that is `default`, or
  `destructive` when the action deletes or lowers a safeguard
  (delete chat, Bypass Permissions). Escape, a click outside and
  Cancel all cancel it. Imperative callers use
  `await confirmAction({...})`, served by the one
  `<ConfirmDialogHost />` in `app/providers.tsx`.
- Forms and multi-action dialogs use `Dialog` with `DialogHeader` and
  `DialogFooter`. The footer holds `Button`s only: `elevated` for
  Cancel / Close, `default` for the main action.
- A module class on `DialogContent` only sizes the dialog (width,
  `max-width: none`, max-height, overflow). It never restates the
  surface: no background, border, radius, padding or shadow.
- Dialogs that run edge to edge (source viewer, function runner,
  provider setup) pass `p-0 gap-0`, pad their own header and body,
  and give `DialogFooter` `m-0`.

## Settings rows

Settings pages are built from three blocks in
`apps/web/components/settings/settings-ui.tsx`, composed only from
the official components (Card, Field):

- `SettingsPage` — the page title and description, then a
  scrolling body.
- `SettingsSection` — a titled group of rows on one `Card`, rows
  divided by hairlines.
- `SettingsRow` — one setting as a horizontal `Field`: name and
  description on the left, the control on the right (a lone Select
  is 12rem wide). `stacked` puts a wide control (editor, grid, list)
  under the name instead.

Controls inside are the official components: `Switch`, `Input`,
`Textarea`, `Slider`, `RadioGroup` (choice cards), `ToggleGroup`,
`Checkbox`, `Button`, `SimpleSelect`. A tab carries no row, label or
card CSS of its own.

The Settings and Info tabs of a History project use the same blocks, so
they read like a Settings page. All four project tabs
(Chats, Memory, Settings, Info) share one layout: the project head and tab
bar stay put, the panel fills the rest edge to edge, and each tab scrolls
inside it (Settings and Info with a 24px edge, like the Chats toolbar).
The Chats tab groups chats by recency, one titled `Card` per group with
hairline-divided rows. Each group title is a disclosure: Today, Last 7 days
and the newest group start open, older months and years start folded, and
the viewer's choice per group is remembered in this browser. An open group
lists 8 chats, then "Show all N" (a group of 10 or fewer lists them all); a toolbar button expands or folds every
group, and a search opens them all. `scripts/projects/check-project-tabs.mjs` (run by `npm run check`) guards
this.

## Button variant guidance

Every Button wears one face: `rounded-md` (8px) corners at every
size, no border, lifted off the page by the per-theme composer shadow
pair (`shadow-raised`, a step deeper on hover with
`shadow-raised-hover`, declared in `app/globals.css` `@theme`). Colour
alone says what the button does. Nova's bordered `outline` and flat
`secondary` are not offered: a bordered button next to a raised one
read as two different kits.

```
variant      face                                  hover
─────────────────────────────────────────────────────────────────
default      bg-primary, shadow-raised             primary/90, deeper shadow
elevated     --bg-input, shadow-raised             deeper shadow
destructive  bg-destructive/10, shadow-raised      destructive/20, deeper shadow
ghost        transparent, no shadow                bg-muted (/50 dark)
link         primary text                          underline
─────────────────────────────────────────────────────────────────
```

All variants press down 1px while active, show a 3px `ring/50`
halo on keyboard focus, and drop to 50% opacity when disabled. An
`elevated` Button that is pressed, checked or on (`aria-pressed`,
`aria-checked`, `data-state=on`) wears a 1.5px `primary` ring, so a
choice among raised options shows which one is picked. `Toggle` /
`ToggleGroup` offer the same raised face as their `elevated`
variant.

Pick per surface:

- **Main action** of an area (Run, Save, Test, Apply, Send, New …)
  → `default`, one per area.
- **Every other action**, filter or choice (Cancel, Close, Reset,
  Browse, Edit, Restart, the composer's model / effort / permission
  triggers, environment chips) → `elevated`.
- **Destructive** (Delete, Remove, Stop, Clear history) →
  `destructive`.
- **Icon-only tools** that should vanish until hovered (close,
  more, rename) → `ghost`.
- **Deep surface — sidebar rows** → don't use the Button
  primitive. Use `.ui-list-item` / `nav-classes.ts`.

## Composer controls

The chat composer is built from the same parts:

- **Environment chips** above the box (channel, web surface,
  project, working folders, DAG HUD) → `elevated` `sm`; the
  add-folder chip is `elevated` `icon-sm`.
- **Bottom row** (permission, chat model, Agent, effort, plus,
  tool toggles, context ring) → `elevated`, `sm` / `icon-sm`. The
  composer CSS hands its older base rules back to the Button with
  `revert-layer` rather than drawing its own chip.
  The control row has no fixed height: it is as tall as its chips,
  10px under the box, the same distance the environment chips keep
  above it.
- **Glyphs in both rows** are 16px with a 5px gap to the label and
  centred on it, and every label is 13px. The Button sizes would
  shrink an unsized svg to 12.25px, so the two rows' module CSS sets
  the size and gap unlayered; the effort card opened from the row keeps
  its own sizes.
- **Send and voice mic** → colours from the Button variants (send:
  `default` when there is something to send, `ghost` when empty,
  `destructive` while it stops a run; mic: `ghost`). Their size and
  place do not come from the Button size classes but from the
  composer tokens in `app/styles/design/composer.css`: `--composer-action-size`
  (28px) centred in the last `--composer-line-h` (46px) text line,
  `--composer-action-inset` from the box edge. The text gutters, the
  attachment column and the voice level strip are computed from the
  same tokens, so a Button restyle cannot move them. The mic's hover
  fill is `--composer-action-hover`, because the ghost fill
  (`--muted`) is the box's own colour.
- **Input box** → the per-theme `--composer-*` tokens: `--bg-input`
  surface with no border, `shadow-sm` at rest and `shadow-md` on
  hover or focus (shadow alpha 0.1 on light themes, 0.25 on dark),
  no focus ring; `--radius-lg` corners, the same rounded-rectangle
  family as the chips around it.

## Web page preview and browser toolbar

The floating page preview over chat
(`components/center-tabs/pip/web-tab-pip.tsx`) is a popover card:
`bg-popover` in the menus' frame (`--popover-ring` /
`--popover-shadow`), 10px corners on all four sides, and the stage below the
header clips the page at the same bottom radius. The radius is pinned
to the native page view's corner radius
(`apps/desktop/main/web-views/web-views.js`), which the DOM cannot clip: a
larger frame radius would let page pixels show past the bottom
corners, so the two change together or not at all. The 32px header
holds the title (`text-fs-base font-medium text-text-primary`), the status
(`text-fs-xs text-text-muted`), and `ghost` `icon-sm` icon buttons
with 14px icons whose hover tips are `HoverTip` + `TipBody`
([hover-tips.md](../composer/hover-tips.md)); a resume error is one line of
`text-fs-xs text-destructive`, no box. The CSS module keeps geometry only
(position, size, drag cursor, resize handles), because unlayered
module rules would beat the utilities.

The browser toolbar's icon buttons (back / forward / reload / home /
bookmark / library / open in browser / menu, and the control bar) are
the same `ghost` Button through `webToolbarButton()`
(`components/center-tabs/browser/toolbar/toolbar-button.ts`): `icon-sm` for its 14px
icon rule, held at the toolbar's 26px by `.webToolbarBtn`, which
carries geometry only, so the 40px row keeps its rhythm.

## Don'ts

- Don't invent a new hover / selected / border treatment per
  page. One recipe, then reuse it. A new look needs a line in
  this file first.
- Don't introduce a new pill background colour without listing it
  here first. Flavours in budget: deep grey hover, panel, brand
  fill, and the header-tab `--bg-input` exception above.
- Don't put brand-coloured fills on the deep surface — the
  contrast against the rail makes a brand pill look like an
  alert, not a click target.
- Don't use white / `--bg-input` as the selected fill on sidebar
  or content-pane **list rows**. Light theme washes out.
- Don't give MCP server rows (or any other content-pane list) a
  different height, padding, or selected fill than sidebar nav.
- Don't add hover motion (translate-y, scale-105) on either
  surface. Hover swaps the background; the only motion is the
  Button's own 1px press while active.
- Don't edit the classes in `components/ui/button.tsx` at a call
  site, give one Button its own radius, border or shadow, or restate
  a Button lookalike in CSS. Pick a `variant` / `size`; if a legacy rule still overrides a Button, remove it or
  hand it back with `revert-layer`.
- Don't stack a 2px focus glow on a 1px input/select edge.
- Don't drop a control's 1px border on hover.
- Don't slide dialogs; they fade and zoom in from 95%.
- Don't let a settings description overflow into the right-hand
  control column, or stack label above control.

## Implementation status

- Done: `Button`, `Select`, `Input`, `Textarea`, `Switch`,
  `Slider`, `Card`, `Badge`, `Label`, `Separator` (radix-nova, every
  former `<select>` and custom dropdown included), plus `Checkbox`,
  `RadioGroup`, `Field`, `Toggle` and `ToggleGroup`; menu panels and
  rows in Nova geometry and material; the Settings General
  page and desktop attention section on the Settings blocks; the
  composer environment chips, bottom-row controls, send and mic
  buttons, input box, the web page preview (frame, header, icon
  buttons), and the browser toolbar's icon buttons.
- Done: every modal on `Dialog` / `AlertDialog`, every confirmation
  on `ConfirmDialog` (the former `window.confirm` calls, the
  delete-chat and Bypass Permissions prompts, the plugin, channel,
  branch-merge, icon-picker, function and provider-setup panels).
  The attachment lightbox keeps its own full-screen viewer.
- Done: every part in `components/ui` is radix-nova — the command
  palette (`Command` in the Nova `Dialog`, selected row on
  `bg-accent` like the menus), `Popover` (Nova surface with the
  menus' `--popover-ring` / `--popover-shadow` frame; a
  `bg-transparent` content hosts its own `MENU_PANEL`), `Tooltip`
  (Nova's inverted badge with an arrow; `--surface-tooltip` /
  `--text-on-tooltip` alias `--foreground` / `--background` so the
  hand-placed rail tips match), `Tabs` (the Agent editor uses the
  `line` variant), `Kbd`, `ScrollArea` and the `Sidebar` shell.
- Not yet migrated: the other Settings pages (still on
  `settings-page.module.css` rows). Form inputs outside
  Settings keep the 1px-edge rule above until they move to the
  shadcn input. Sidebar list rows stay on the list set above.
