<div id="dag-rendering-spec-layout-edges-legend-default-visibility"></div>

# Rendering specification

> How the session graph draws: where each node goes, what each edge looks like,
> and what the user sees by default. **This document is the authoritative
> implementation standard** — write the layout code to match it, and when
> something breaks, check against it. For the data semantics (nodes, the two
> edges) see `dag/overview.md`; this document only covers the drawing.
>
> Every rule comes with an example. **The SVG scenario figures in
> `layout.html` are authoritative** (13 scenes: 1–7 base layout, 8 merge,
> 9 cross-branch messaging, 10 spawn dispatch & merge-back, 11 execution-subtree
> aggregation, 12 status & badge legend, 13 badge anchoring & collision). The ASCII
> figures in this file are a text-mode digest, equivalent to the html; on conflict
> the html wins.

---

## Where the graph lives: a center perspective

The graph is one of the chat pane's two **perspectives**, not a side panel. Each
center tab is either on the conversation transcript or on the context graph, and
the pair of controls at the pane's top-right switches between them — a
perspective toggle plus a `…` menu of session actions, following Obsidian's
per-pane controls. The perspective is per tab, so parking one session on the
graph leaves the others on their transcripts.

Giving the graph the full column width is the point: a branchy session needs
lanes, tiers and branch badges that a 288px rail truncates.

| Piece | Where |
|---|---|
| Perspective state | `CenterTab.dagView` (`apps/web/lib/tabs/center-tabs-store.ts`) — not persisted; a reload opens on the transcript |
| Controls | `apps/web/components/chat/pane/view-controls.tsx` |
| Graph host | `apps/web/components/chat/dag/dag-view.tsx` — renders `#historyPanel` + `.history-body`, the elements `apps/web/lib/runtime-bridge/dag/pipeline.ts` and `apps/web/lib/runtime-bridge/dag/render/visibility.ts` select |
| Perspective swap | `.center-pane-chat[data-center-view]` in `apps/web/app/styles/dag/view-host.css` |

Both surfaces stay mounted and swap by `display`: the renderer paints into the
host on every capture regardless of which perspective is showing, so unmounting
would blank the graph until the next one. The host does not re-flow on resize —
it is an infinite canvas, so a wider pane simply shows more of it (see below).

Clicking a node in the graph fills the right sidebar's Details / Context views;
those views stay in the sidebar because they read one selected node, not the
whole session.

### The canvas is infinite

There is no scroll box and no content-sized SVG. The SVG fills the pane, every
drawn thing lives inside one `<g>`, and that group carries a translate + scale
the user drives directly.

| Gesture | Effect |
|---|---|
| mouse wheel, or trackpad pinch | zoom about the cursor, clamped to 25%–300% — the node under the pointer stays under the pointer |
| two fingers on a trackpad | pan |
| right (or middle) drag | pan, from anywhere on the graph |
| left drag on empty canvas | a selection box (§13) |
| left press on a node | the node's — click and double-click still work |

**Wheel** (`apps/web/lib/runtime-bridge/dag/interaction/view/gestures.ts`,
`interaction/view/wheel.ts`): a mouse wheel zooms, the way a map does; two fingers
on a trackpad pan, the way a design canvas does; a pinch zooms. All three are
`wheel` events, so the kind is read from the event: a pinch carries `ctrlKey`
(⌘ + wheel zooms too); a sideways delta is two fingers; and Chromium, which
the App runs on, reports a trackpad's legacy `wheelDeltaY` as exactly
`-3 × deltaY`, while a wheel's notches come as multiples of 120. An earlier
guess read the size of the delta instead and took real mice for trackpads, so
the wheel scrolled when it should have zoomed; the `wheelDeltaY` test does not
look at size. A gesture is judged on its first event and keeps the verdict
until the events pause (180 ms), so a trackpad's inertial tail never flips to
zoom. A pinch zooms at its own, faster rate; line- and page-mode deltas (some
mice) are turned into pixels first. A mouse whose driver sends pixel-smooth
deltas with `wheelDeltaY = -3 × deltaY` reads as a trackpad and pans.

A box sized to its content decides two things it has no business deciding: how
big a graph may get before it needs scrollbars, and where the middle is. A wide
session got a horizontal scrollbar, a deep one got a vertical one, and reading
the whole shape meant scrolling two axes with no way to zoom out.

**The dot lattice is the coordinate system.** The pane's background paints a dot
per grid cell at the layout's own pitch (`COL_W`), transformed with the same pan
and zoom and offset so a dot's centre sits under every node anchor (the layout
pads its origin by `PAD_X` / `PAD_Y`; the lattice backs up half a tile from that
pad). A node visibly sits on a dot — and drifting off one is a bug anyone can
see without reading the layout code. The fit rounds its translation to whole
pixels for exactly this reason. The dot radius rides the zoom too (clamped
1–3px): fixed at 1.2px it vanishes into a zoomed-in tile.

**View state survives re-renders.** The graph repaints on every capture; moving
the camera each time would drag the view around while the user is reading. Pan
and zoom live in `apps/web/lib/runtime-bridge/dag/store/globals.ts` keyed by session, and only arriving at a
different session re-fits. Resizing the pane never re-fits — the user's angle on
the graph is theirs to keep.

**Arriving opens readable; Shift+1 shows everything.** The opening view
is the fit, floored at 80%: a long session fitted whole shrank to a hairline
column of specks (a 40-turn chat opened at 37%). When the graph is larger than
the strip at that floor, the overflowing axis follows HEAD — near the bottom of
the strip, the way a transcript opens on its latest message. Showing the whole graph
(Shift+1) keeps the plain fit down to 25%: asking to see everything is a request
for exactly that (`fitCanvas(opening)` in `apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts`).

**Zoom column.** In the canvas's top-right corner, right under the pane's
perspective strip, so every view control is one column in one corner: one
raised strip holding + · readout · − and, under a hairline, **Find the
working agent** (F); a second strip under it turns
the minimap on and off and, under a hairline, holds the two guides — the
legend (what the marks mean) and the controls sheet (what the canvas answers
to). Each stays open until its button is pressed again, and any of them can
be open together. Left of the zoom column, from the top, is one side column,
the map's width, like the macOS widgets sidebar: the map, the conversation's
floating web preview docked there, the legend, then the controls sheet, 16px
apart and each at its full height. The column ends 16px above the composer and
scrolls as a whole — a wheel over any panel, the map included, scrolls it,
and no panel scrolls on its own. A panel that is off folds its place away.
The conversation perspective has the same dock: left of the pane's view
controls, a side column holding only the preview's place
(`components/chat/pane/view-controls.tsx`), so the preview sits in the
top-right corner in both perspectives and moves between the two docks as
they swap. The preview starts docked (`apps/web/lib/browser/web-tab/web-tab-pip-dock.ts`;
`PipDockSlot` holds its place in the column and the preview floats over that
place, clipped by the column's scroll, with a still frame standing in for
the native page while part of it is scrolled out). Dragging its header
leaves it still until the pointer has gone 36px; then it comes out at its
free size and springs to the pointer, and goes anywhere, keeping that place
in both perspectives. The column keeps its place open until the drop.
Dragged back within 56px of the column's top it springs in — the column
makes room as it nears — and must be taken 88px away to come off again, so
it never flickers on the edge; dropping it there docks it again. Each of
these moves is one spring (framer-motion) from where the preview is drawn
to where it now belongs, which keeps following the pointer meanwhile. An expanded preview always floats. The three
panels come and go like the app's popovers: a fade, a 95% scale and an 8px
slide in from the column's side over 100ms, played back on the way out
(`PANEL_MOTION` in `components/chat/dag/dag-key-sheet.tsx`; the minimap's
`.is-hidden` in `app/styles/dag/panels/tools.css`). Entering the graph view, the map is
put away without motion first (`stowMinimap`) — the last visit may have
left it shown, and the first frames draw the emptied cache — so it comes in
once, with the first paint that has a graph, instead of shrinking away and
popping back. The column's strips slide in top to bottom with the same fade
and 8px slide, 150ms each and 40ms apart; leaving the view is instant.
**Full screen** belongs to the session pane, not to the graph: its button sits
in the perspective strip above the column (focus mode in the conversation's
view controls), so switching perspectives keeps it. It gives the window to
the session pane: the center body — the canvas or the conversation, with the
composer — lifts out of the layout and grows over the app's left sidebar,
right sidebar and center tab strip, which stay where they are underneath,
until it sits `--canvas-fullscreen-inset` (8px) inside the window, the
sidebar cards' gap to the window's edges, and the tab strip fades out under
it, its tinted row turning to the page colour the other gaps show; the canvas's other panes step aside while it lasts. The
growth moves the body's real edges, as the canvas moves its panes and as
macOS zooms a window: each of the four edges travels from the session pane's
own box to the window's inset, and the content lays out at the box's size on
every frame — nothing snaps to the end size first and then scales. It runs
on the Web Animations API, whose clock starts on the first painted frame,
for 400ms on a symmetric ease-in-out curve (the content stops growing at the
chat column's max width, early on the way in, so a front-loaded curve jumped
it there); leaving takes the edges back onto the pane's box in 320ms before
the body drops into the layout there. The content is never laid out at the
full-screen size ahead of the glide: the transcript's scroll would be clamped
to that shorter text and jump, so the end box is the named inset, not a
measurement, and the start box is also held in the body's own style, since
Chromium lays a new animation's first frame out at the element's style.
While it runs the canvas counts as moving (`lib/tabs/canvas/canvas-motion.ts`):
the transcript re-wraps only the rows in view, keeps its first visible line
with the browser's scroll anchoring, and re-renders its rows once at rest.
The shell does not re-render for the body's size meanwhile. A toggle
mid-glide turns it around where it is, and Reduce Motion skips it. It is a
mode of the app, not the browser's full screen — the window keeps its size —
and native web views hide while it covers them. Pressed again, Esc (once
nothing is selected), another kind of tab coming to the front or a reload
ends it (`lib/tabs/canvas/canvas-fullscreen.ts` holds the state, Esc and the
glide; the look is `html[data-canvas-fullscreen]` in
`app/styles/chat/pane/center-pane.css`).
Showing the whole graph used to hold this spot; it was a fit that, on a small
graph, looked just like the readout's 100%, so it is Shift+1 alone now.
A toggle that is on holds the hover grey, never an accent colour. Every glyph
in the column and in the pane's perspective strip is Solar Bold Duotone with
the composer's hover pop (`docs/reference/design/ui/visual-system/icons.md`). The buttons step by exactly one wheel notch (`ZOOM_STEP`), and
clicking the readout resets to 100% — both anchored on the pane's centre,
since a button has no cursor to anchor on. A press, like the + / − and
Shift+0 keys, glides there in 0.22s, the scale moving evenly in log space so
in and out feel alike; a press during a glide steps on from where it is
headed. The wheel and pinch stay immediate — a gesture already moves
continuously — and a wheel or a pan takes over a glide in flight
(`glideZoom` in `canvas.ts`). The readout is written
imperatively by `apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts` on
every view change, because routing a gesture's every wheel event through
React state would repaint the tree sixty times a second. The controls used to
sit in the composer's env-chip row and on a left rail as well; one column
on one edge replaced both.

The strips share one material and button style
(`apps/web/app/styles/dag/panels/tools.css`). The legend panel and the controls sheet take
their padding from `MENU_PANEL`
(`components/chat/top-bar/menu-styles`) but wear the minimap's frame — fill,
raised shadow, 10px corners, no outer ring — since the three stack as one
280px column and a ring would draw them a pixel wider than the map;
`apps/web/app/styles/dag/panels/legend.css` keeps only the legend's anchoring
and rows.

| Piece | Where |
|---|---|
| Pan / zoom / fit | `apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts` (`zoomStep` / `resetZoom` for the zoom column) |
| View state | `_viewTx` / `_viewTy` / `_viewScale` / `_viewSession` in `apps/web/lib/runtime-bridge/dag/store/globals.ts` |
| Surface + lattice | `.history-body` in `apps/web/app/styles/dag/graph/canvas.css` |
| Zoom column | `DagZoomColumn` in `apps/web/components/chat/dag/dag-view.tsx`; strips in `apps/web/app/styles/dag/panels/tools.css`, legend and sheet padding from `MENU_PANEL`, frame shared with the minimap, legend rows in `apps/web/app/styles/dag/panels/legend.css` |

### The composer belongs to the pane, not to the transcript

**The perspective swap hides `#chatArea`, the transcript scroll box — never
`#chatView`.** The composer is a singleton portalled into `#composer-mount`
inside `#chatView` and anchored `bottom: 0` against it, so hiding that ancestor
would take the composer down with the transcript, and mounting a second one
would fork the draft, the run state and the model row into two copies of what
the user reads as one input box. Both perspectives therefore share the one
composer instance, and the graph replaces only the scroll area above it.

You can send a message from the graph, and the node it produces appears on the
next capture — the send path is the transcript's send path, unchanged, so
nothing about the graph perspective has to know it is showing.

The graph takes the transcript's place by **covering the pane**, not by taking
its slot in the column: `#chatView` keeps its `flex: 1` and its full height, so
the composer's `bottom: 0` still lands on the pane's bottom edge, and stacking
order does the rest — the graph sits under the composer's `z-index: 5`. Shrinking
`#chatView` instead would drag the input box up the pane.

The canvas runs edge to edge under the composer — panning past it is one
gesture, and the fit centres the graph in the strip above it
(`apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts::fitCanvas`), so nothing needs a reserved padding band.

### Branch switching lives in the graph

There is no branch strip above the canvas. Each branch's name is a button drawn
in the graph itself, anchored below the branch's last conversation-layer node
(`apps/web/lib/runtime-bridge/dag/render/labels/badges.ts`, §5): the active branch's tag is a flat block tinted in its
lane colour, and clicking any other tag checks that branch out. The graph
already draws the branch structure; a strip above it would repeat that
information and cut a line across the pane's floating view controls. Rename,
delete, merge and attach stay in the right sidebar's branch list, which has the
vertical room those flows need.

---

## 0. First, "what to draw": two granularities, only the conversation layer by default

A session graph has two kinds of node, an order of magnitude apart in count:

| Layer | Nodes | Question it answers | Magnitude |
|---|---|---|---|
| **Conversation layer** | ROOT, user, llm replies, spawn branch roots, merge, **manually-invoked top-level function nodes** (the user's explicit action — the code node behind a fn-form/run card) | What shape the session has: how many turns, how many branches, who spawned whom | single digits ~ dozens |
| **Execution layer** | code (tool call) and its internal sub-calls | What one turn did internally | can reach dozens in a single turn |

**Default visibility rule: the Viewport lays out only the conversation layer.**
Everything a turn *did* — every function call, every agent it spawned — is that
turn's **call thread** (§12): folded into a count on the node's shoulder by
default, opened by clicking the node into a column of real nodes beside it.

Two merges keep the chain at user-visible granularity — **one triangle = one
reply and everything the model did until the next user message**:

* a runtime-notice reply is not a chain node: the turn an agent's return
  triggers (`source="job_followup"`) or a background command ending triggers
  (`source="process_exit"`). A function's return gets no new node when the
  model keeps talking, and these returns are the same event at a different
  scale — the reply merges into its **anchor**, found by climbing
  `predecessor` past every followup. The notice's synthetic user message is
  `display=runtime` and never painted; `graph_layout/filter.py` re-parents the
  reply onto the notice's predecessor first, so the reply never points at a
  node missing from the payload (that is what drew it as a floating orphan,
  with every later turn restarting one column to the right). The same pass
  (`bridge_hidden`) covers every stripped `display=runtime` row, not just
  notices: restarting an interrupted run writes a synthetic "continue the
  interrupted task" user turn, and its reply re-parents onto the reply the
  restart cut off, so the branch carries on in its column instead of floating
  below the graph, cut off from it. That reply is stamped `resumed`: it is the
  rest of the cut-off reply — the chat already draws the two as one — so it
  merges into the same anchor as a notice reply, one glyph whose thread holds
  both halves' calls.
  A side effect worth naming: legacy data whose followup predecessors an old
  rollback bug scarred resolves to the same anchor, so the scar stops
  rendering as a phantom fork.
* a spawned agent's internal turns are not chain nodes either. The spawn head
  IS the agent (§12); everything in the agent's lane merges into it.

```
Default (conversation layer):    Click the reply to open its thread:
◇ROOT                          ◇ROOT
├ ○Hello                        ├ ○Hello
│ └ △Reply                      │ └ △Reply
├ ○Weather                      ├ ○Weather
│ └ △Reply ⁹                    │ └ △Reply┄┐
                               │        ■ bash
                               │        ■ web_fetch
                               │        ■ sub-agent ⁵
                               │        ■ …(9 rows)
```

Rationale: execution-layer information already has a better presentation in the chat
stream (each turn's execution-tree card, the Executions page). The Viewport's job is
to let you see the session structure at a glance; 50 tool squares laid out flat would
drown the 8 structural nodes — a real weather session with 66 nodes, 50+ of them code,
looked exactly like that.

> The other two views — chat stream and call tree — are unaffected: the chat stream
> lays out top-level turns by seq with function nesting folded; the Executions /
> execution-tree card expands fully along caller. Same data, three projections.

---

## 1. A node's position = (column, row)

- **Column (horizontal) = lane start column + tier indent**
- **Row (vertical) = depth**

Both axes step in the same unit (`COL_W == ROW_H`, `apps/web/lib/runtime-bridge/dag/types.ts`), offset from
the origin by `PAD_X` / `PAD_Y` — the square lattice the canvas paints its dots
on.

### lane — which branch it belongs to

**Count the branches and hand out column numbers 0, 1, 2… in order of appearance; no
gaps, no judging which is "the trunk."**

A branch = one conversation chain (user → llm → user → …). Three events produce a new
branch:

| Event | New branch's root | Attachment |
|---|---|---|
| retry / rewrite a turn | the forked-off user / llm node | shares predecessor with the replaced node |
| spawn (agent / send_message dispatch) | the `source=agent_spawn` user node | caller = the initiating node, predecessor empty |
| the new mainline from a merge | the merge node itself | lands in the base branch lane (see scenario 8), no new lane opened |

**Branches are packed by actual column occupancy**: the columns a branch occupies = from
its start column to the deepest column of its visible CHAIN nodes; the next branch
starts at the previous branch's actually-occupied rightmost column +1, with no
overlap. A lane that begins with a fork root keeps **one extra gap column** from
the lane it forked off — the branch is a parallel version, and the two grid units
of air are what say so. Tiers are zeroed per lane (the backend hands a fork root
the tier of its old in-lane position; without zeroing a one-node branch arrives
columns adrift). **A fork lane mirrors the trunk internally**: the lane's
first column is an empty SPINE — the dashed bridge lands on it, its line
starts at the fork root's row and runs down, and every turn (the fork root
included) steps one column right and stubs off it, exactly as trunk turns
stub off ROOT's line. The branch starts as a line, not as a node. Only
capsules and superseded relics — lanes with no user turns of their own —
take the bridge straight to the glyph. Thread items
(§12) reserve no lane width: their column is chosen after the lanes are down,
in the nearest column right of their anchor that no line runs down across
at the insertion row (something above it and something at or below it in
that column). Everything wholly above stays clear and everything below is
pushed down past the thread, so threads on different rows share a column —
two open threads still never share a cell, and a stub never runs long past
lanes that do not reach its row.

### tier — how many columns to indent within a branch

**The conversation layer is fixed by role.** The execution layer does not indent
by caller depth any more — an open thread is one flat, time-ordered column (§12),
because "what did this turn do, in what order" is the question the graph answers;
per-call nesting is the transcript's and the Executions page's job.

| Node | Layer | column |
|---|---|---|
| ROOT | conversation | tier 0 |
| user | conversation | tier 1 |
| llm reply, merge | conversation | tier 2 |
| any thread item (call square, spawn head) | execution | its anchor's column +1; a nested open agent's thread +1 more |

### depth — which row

Chain rows are allocated by a **preorder walk of the structural parent tree**:
every visible chain node takes its own row, and a subtree pushes the siblings
below it down by however many rows it occupies. Rows are not "hops to root" —
that would stack all children of one parent on a single row.

One exception grows sideways instead of down: a fork root sits on the **same
row** as the chain sibling it runs parallel to (scene 3), and every branch off
one fork point shares that one row — the alternatives they are. Each branch
bridges to the branch immediately to its left, not back across everything to
the trunk, so the dashed bridge is a straight horizontal two grid units long.

Thread rows are allocated **recursively** (§12): an anchor's items run from its
next row (past any fork rows hanging off it) down one row per event; an open
spawn's own thread continues from its row, and its rows push the parent's later
items down. After a chain-anchor thread is seated, later conversation-layer
nodes (and already-placed thread rows below the insertion) shift down by the
occupied span — expansion is insertion, never overlay. Cross-session spawns land
as the target session's own conversation chain (lane 0), not a side branch
(scene 12).

---

## 2. Three global layout rules

**① Square grid**: `COL_W == ROW_H`, child nodes strictly at the parent's lower-right
corner (45°). The canvas's dot background paints the same lattice (see "The canvas
is infinite" above), so this is a property the eye checks, not a promise the code
makes.

**② Strict alignment + compaction**: nodes land on grid intersections; **empty rows shift
up to fill, empty columns shift left to fill, no empty rows or columns are kept.** This
applies to every visibility change: execution subtree collapse/expand, branch folding,
visibility filtering — once collapsed, the rows and columns it occupied must be freed
immediately. **Corollary: any "placeholder box" violates this rule** — the running state
is expressed by the node's own block (see the legend), not by drawing a dashed
placeholder node.

**③ Glyphs are cells; text is a caption.** A node occupies its grid point;
counts hang beside it in annotation grey, never inside a shape sized to its own
text. A glyph that grows with its label is a glyph every neighbour has to be
measured against — that negotiation is what §12's earlier pill got wrong.
Every glyph is the same rounded tile (§4), the §9 compaction capsule
included, and occupies exactly one cell; the grid leaves a gap of one tile
between neighbours so the belt between them stays visible.
A call or a message of yours carries a caption in annotation grey to the
right of its icon ("Ran npm test", "Read a.ts", the start of what you wrote;
`render/labels/captions.ts`). A caption only takes room nobody uses: it runs along
its row up to the next tile, branch tag or line crossing it, steps past a
fork line that runs down right where it would start, and is dropped when
there is too little room, so it never pushes the layout. The tile an agent stands on shows
the agent's bubble instead, and zoomed far out captions are hidden.

---

## 3. Edges: color = branch, line style = type (orthogonal)

Each lane has one color (`LANE_COLORS`, `var(--lane-N)` references to the `--lane-*` tokens in `apps/web/app/styles/design/color.css`; the minimap resolves them through computed style). Any edge uses the lane color of
the branch it belongs to / points at; **never give a category of edge a fixed color.** Type
is conveyed only by line style:

**The road to HEAD wears HEAD's colour.** Turns shared by several branches —
ROOT down to the fork — belong to whichever branch you are on, so they, the
calls they made and their lines take HEAD's lane colour
(`layout/assign-lanes.ts` `_stampPathLanes` stamps `_pathLane`, which
`_branchColor` reads first). Check out another branch and the shared stretch
repaints in that branch's colour; the branch you left keeps its own colour from
the fork on. Each turn's line runs down the trunk from ROOT, so lines overlap:
`render/edges.ts` draws the road last, else a later branch would lie over it.

| Edge type | Line style | Color | Default |
|---|---|---|---|
| same-branch parent→child | solid | this branch's color | shown |
| retry fork bridge (origin → the branch lane's spine top, shared row) | dashed `6 4` horizontal; an elbow only when rows diverged | branch's color | shown |
| call thread (anchor → its items, §12) | solid, 1.4px — the trunk pattern one level down: a vertical in the anchor's column, a horizontal stub per item (down first, then right, like every chain edge) | anchor's branch color | shown while open |
| merge convergence (peer tip → merge node) | thick solid 2.4px | peer branch's color | shown |
| attach merge-back (source tip → embed position) | long dashes `4 4` | source branch's color | shown when both ends are visible — an agent-internal tip merged into its triangle draws no line; the spawn head's position ON the thread is the return relationship |
| inter-branch communication (send_message) | dotted `1 5` | target branch's color | **shown only on hover** (numerous; always-on would smear) |

**Chain and thread edges are conveyor belts**: an 8px neutral track
(`.dag-belt`, its own layer under every line, opaque so tracks that share a
trunk or meet at a junction never darken where they stack) with the 2px
branch-coloured line on it. A belt that leads to work carries goods: beads in
the branch colour ride the track towards the working node, under the solid
line, so a running belt never reads as a dashed ghost line. A chain belt runs
into a node that is itself running; a thread belt runs while anything down
the item it leads to is running — the call being made, or a sub-agent's turn
behind its spawn — and the thread trunk runs down to that item only.
`paintBelts` sets this from the graph through each belt's `data-to`, so the
in-place status patch repaints it. Ghost lines keep their dashes and get no
track: they are not what the next request carries.

**Every line is drawn centre to centre**, and the tiles' background fill paints
over the ends, so a line joins every tile seamlessly without a measured
stand-off.

---

## 4. Node legend: icon tile = role, tone = kind, state = CSS

**Every node is the same round chip** (`apps/web/lib/runtime-bridge/dag/render/tiles.ts`):
a 28px circle tinted with the node's own colour (18% of the tone mixed into the
canvas, so it stays opaque and buries the belt ends under it) and its icon in
full colour. Your message, a reply and a call are one family; an earlier version
mixed a grey raised button for your messages with black square plates and icons
at 38% for everything else, and the graph read as grey parts that did not
belong together. Every state restyles the chip itself, the way a game button
lights up when pressed — nothing is drawn around it:

| State | The chip |
|---|---|
| normal | 18% tint, icon in full colour |
| hover | 30% tint |
| selected (§13) | filled solid in its colour, the icon in the canvas colour, 8% larger |
| HEAD | 24% tint and a slow breathing glow in its colour |
| not in the next request (§8) | 10% tint, icon at 60% |
| error | the red `!` badge on its upper-right edge |

A 
call takes the icon and tone `presentTool` gives it in the transcript, so "ran
npm test" looks alike in both places; tones are shared CSS variables
(`apps/web/app/styles/tool-tones.css`). Conversation nodes get their own:

| Node | Icon | Tone |
|---|---|---|
| ROOT | house | secondary ink |
| user | person | its branch colour, so a branch reads by its messages as well as its line |
| agent reply | the agent's character: the conversation Agent's for the main agent, the sub-agent's in a sub-agent's run | its branch colour |
| call | per tool (`presentTool`) | per tool (shell, edit, read, search, web, …) |
| sub-agent spawn | the sub-agent's character | its branch colour — dispatching an agent IS a call; it expands into the agent's activity (§12) |
| compaction summary | archive | memory (§9) |
| merge / attach | pull request / link | plan |

An agent's character is the shape of its avatar ([Agent avatars](../../ui/visual-system/agent-avatars.md)),
drawn flat like an icon: the body in the chip's colour, the eyes cut through
so the chip shows behind them (`components/avatar/bot/glyph.ts`). The colour
is the branch's, not the character's own, so a branch still reads by colour
and every chip state (faint, HEAD, selected, far) applies unchanged. The main
agent wears the character of the Agent the conversation runs with: the graph's
nodes carry no Agent id, so `components/chat/dag/dag-view.tsx` reports it to
`render/agent-look.ts`, and a change repaints the graph. A sub-agent wears the
character its name gives (the name its tag shows), by the rule that pictures
an Agent without an avatar, so two sub-agents look different and one looks
the same wherever it shows. The legend and the Activity panel's agent rows
draw the same glyphs.

**Agents stand on their step** (`render/agents.ts`). Every agent that is
working puts a status dot of its branch colour on the upper-left corner of
the tile it is on — the Activity panel's `indicator-dot`, breathing the same
way while it works; a second agent on the same tile sits beside it — and
a bubble beside the tile says "name · what it is doing" (the tile's activity text in the present tense:
"Thinking…", "Running npm test"). Agents are read from the whole graph: a
node belongs to the sub-agent whose spawn root its chain leads back to, else
to the main agent, and each agent shows its latest running node. When that
node is folded into a count, the dot sits on the nearest drawn tile and
the bubble still names the call; agents sharing a tile stack their bubbles.

An earlier version put a round token with the agent's initial ("M") on the
tile's corner; nobody could tell what the letter meant, and the bubble already
names the agent; a ring round the tile came next and was too loud. Now the
dot marks *where* and the bubble says *who*.

**Semantic zoom.** Zoomed out, dots and bubbles keep their on-screen size,
like unit markers on a map (`--dag-marker-scale`, set by
`interaction/view/canvas.ts`; the marker is pinned to its tile in world units and
only its body scales). The agent's dot is pinned to the tile's corner itself,
not to the screen offset that corner had at 100%, so it rides the shrinking
tile instead of drifting off it. Below 55% an icon is a few pixels of noise, so every
tile becomes a solid block of its tone (`is-far`): the map reads by colour,
and covered tiles stay brighter than the rest. A tile that is itself a 7px dot
cannot carry a status dot beside it without reading as two nodes, so the
corner dot hides with the icons; the bubble's own dot still marks the
working agent.

Zoomed that far out the canvas reads like a map, which keeps its place names
readable and shows fewer of them as you pull back; before this, every label
shrank with the graph into specks of grey. So below 55%:

- a dot is a steady 7px on screen, so neighbours 14px apart never touch,
  and a line keeps 1.5px; the press target stays about 10px;
- **a selected node stays obvious**: with something selected, the rest of
  the graph (dots, lines, labels) fades to 25% and the selected dots keep
  their full colour (`has-selection` on the canvas, set by
  `interaction/selection/selection.ts`). Nothing grows or gains an outline: a larger
  dot merged with its neighbours, and the ink colour, black in the light
  theme, turned a selection into a blot. The minimap draws selected nodes
  larger in the accent colour, so a selection off screen still shows there;
- branch names and the opening words of your messages (`is-turn` captions,
  `render/labels/captions.ts`) stay readable. Every label — captions, branch
  names, fold counts — follows one gentle curve at any zoom below 100%
  (`--dag-label-scale`): 12px at 100%, about 8.5px at the least zoom. A
  label that shrank with the graph and jumped back to full size at 55%
  read as a glitch; one held at 12px all the way down read as a wall of
  text. From 100% down, `interaction/view/far-labels.ts` hides any label that
  would come within 8px of one already shown — branch names first, the
  current branch before the rest, then your messages nearest HEAD, then
  calls;
- call captions, fold counts and corner marks are detail and hide; zoom back
  in for them.

With nothing
running, the main agent's dot rests on HEAD, steady, without a bubble. The layer is
rebuilt from the node DOM, so the in-place status patch repaints it.

**HEAD is a breathing glow on its own chip**: a `drop-shadow` in the chip's
colour that swells and settles on a slow cycle (2.4s), stamped on the shape
itself (`data-head`). The light hugs the chip's outline at every zoom —
unlike a drawn halo ring, which reads as a second, blurrier node beside the
first — and unlike a solid fill, it leaves the shape vocabulary intact: HEAD
stays visibly the same tile as its neighbours, just lit. Under
`prefers-reduced-motion` the pulse freezes to a steady glow. HEAD carries no
coverage mark of its own: it is the one node that cannot leave the context
window — the next request lands on it.

**status mapping** — status is drawn on the node itself, never as a separate dashed
placeholder box:

| status | Drawing |
|---|---|
| success | the plain block |
| running | `is-running`: the icon breathes, and its agent's dot and bubble appear |
| error | `is-error`: the Activity panel's red badge, `!` in place of a count, on the upper-right corner; the tone stays, so an agent reply that failed is still its character in its own colour |
| cancelled | `is-faded`: the tone turns ghost grey |

**Badges** (attached to the node, no grid cell of their own):

| Badge | Meaning |
|---|---|
| fold count (upper-right shoulder, annotation grey) | the size of the node's folded call thread — §12, written `+N` ("N more inside"). Glued to the glyph, no enclosing shape: anything shaped would read as a node. Open, it disappears — the calls are on screen and countable |
| `↗` (top-right corner) | marked on **both sides** of a cross-session spawn: `spawn_remote` on the first target-session user node and `spawn_out` on the initiating source-session node. The target projection places the external caller at ROOT; the source attach card stores the target session and branch head. A cross-session attach does not create an in-graph `attach_returns` edge because its endpoint belongs to another graph. The glyph currently indicates the cross-session relation only; clicking it does not navigate. **Cross-session only**: a same-session spawn has both ends in one graph and keeps the ordinary return edge, so it has no ↗ |

---

## 5. Branch-name badge

- **Anchoring**: **on the row of the branch's deepest currently visible node**, just
  right of its tile, the way a message's caption sits beside it. In the default (folded) view that is the last conversation-layer node; when a
  call thread is open the badge follows the bottom-most thread item and moves back up
  on fold. It follows only the branch's own descendants: a sibling branch sharing the
  lane (a scheduled job's reply threaded off a turn) keeps its own tip. Under the
  tile the name landed on the next row's line, and centred, a long name reached over
  the neighbouring lane until the collision below pushed it under another branch's
  tip. An agent's bubble on the tile hides the name, as it hides a caption.
- **No badge for a spawned agent's branch**: the agent is its triangle on the
  thread (§12); a branch pill for the same fact would be a second drawing of it.
  The climb from a branch row's head that passes a spawn root stops without
  placing anything.
- **Edge avoidance**: beside the tile the name is clear of the column's descending line;
  a line running right along the row breaks around the letters (canvas-colour halo).
- **Collision**: judged on **measured pixel boxes** (badge backing width = measured text
  width + padding, not grid cells). Short names almost never collide across the grid
  spacing; long names (branches auto-named from a message or task description) on
  same-row anchors do overlap — the later one (by branch order) slides down one row
  until there's no collision.
- **Source**: badges come ONLY from `list_branches` — **active** branches (bright,
  clickable to checkout). **Merging erases the name** (git semantics): a merged-in
  branch no longer draws a badge; its name moves into the ◉ merge node's tooltip
  (like a merge commit message recording provenance). The name data in session meta
  is kept on disk.
- Styling follows the HEAD label (`--bg-hover` rounded background, 9px text, backing sized
  to the measured text width).

---

## 6. Scenarios (SVG authority in spec.html, 13 scenes)

| # | Scene | Key points |
|---|---|---|
| 1–7 | Base layout (single turn / multi-turn / retry / tool indent / manual function / composite / collapse shift-left) | Scenario 4's tool calls show as the shoulder count in the default view (scene 11); the thread squares appear only after opening |
| 8 | merge (multi-parent convergence) | ◉ solid circle with a hole, lands on the base branch lane, peer merge-in thick solid lines (peer lane color); attach pointer nodes are not drawn, only the lines |
| 9 | cross-branch messaging (send_message) | dotted `1 5`, target branch color, hidden by default / shown on hover; a from_branch user node lands at the target branch tail |
| 10 | spawn dispatch → return | the sub-agent's head is an item ON its caller's thread (§12): it sits in the sequence position the spawn actually happened at, between the calls before and after it. Its return needs no extra line — the followup reply it triggers merges into the same anchor (§0), so dispatch, work and return are one column read top to bottom (the chat stream still renders the Spawned card, display order moved ahead — see `ui/invariants.md` rule 9) |
| 11 | call-thread default aggregation | see §0/§12: folded to a shoulder count by default, click to open into layout, fold reclaims rows/cols per rule ②; open state is per-node independent and recursive |
| 12 | status & badge legend | see §4: status drawn on the node's own block, no placeholder boxes; both sides of a cross-session spawn carry the ↗ corner mark |
| 13 | badge anchoring · avoidance · collision · merged | see §5: name on the row of the branch's own last visible node, just right of the tile, collision shifts down one row, merging erases the badge (provenance moves into the merge node's tooltip) |

**Send-back nodes and the switcher (semantic note, no dedicated layout scene)**: a
send_message send-back (the child branch's answer returning to the initiator's lane
as a user node with `predecessor = the initiating node`) forms a fork whenever the user
also sent a message while waiting — **send-back nodes participate in the `< N/M >`
switcher** (they are genuine alternative continuations of the initiator's dialogue;
`source=from_branch` gets no agent_spawn-style isolation — see `ui/invariants.md`
rule 7). A send-back is a turn of the receiving chain, whatever its `caller`
says: its `caller` only records the sender's turn, so it takes the user tier
(1) with its reply one column right, and it is never one of the sender's
internal nodes. Its label is the sender's name and the words: the graph row
drops the `[message from …]` receipt line from `preview` and carries the
sender as `message_from`.

**A sub-agent spawning again**: forbidden at the data layer at the default
spawn budget (`agent.max_spawn_depth=1` — only the main agent may agent(); a
spawned agent does the work itself, see `ui/invariants.md` rule 6, and a
larger budget allows further generations). The renderer recurses
anyway (§12 — a spawn on an agent's thread is a triangle like any other), so
historical multi-generation delegation chains remain drawable.

## 7. Render pipeline (code map)

```
apps/web/lib/runtime-bridge/dag/
  pipeline.ts        orchestration: passes → layout → edges → nodes → badges → canvas
  interaction/view/canvas.ts    the infinite canvas: the view (pan / zoom / fit), and
                           the dot lattice that makes the grid visible
  interaction/view/gestures.ts  wheel, pinch and drags, which move the view
  render/seat.ts           reads a drawn group's translate(x,y) back, for the
                           passes that run after drawing
  passes/            data transforms, applied in order:
    merge-runs.ts               merge consecutive runs of the same node
    collapse-runtime-pairs.ts   fold a legacy display=runtime user/assistant
                                wrapper pair into a single row (pre-`caller`-edge
                                schema left the wrapper with no chat content of
                                its own, so it duplicated the column)
    demote-decoration-cards.ts  re-stamp LLM-triggered runtime cards so a reply
                                with both a card child and a follow-up user turn
                                isn't mistaken for a fork (which would split the
                                figure into two lanes)
    fold-summaries.ts           fold a compaction capsule's covered range (§9)
    thread.ts                   the call-thread model (§0/§12): merge followup
                                and agent-internal turns into their anchors,
                                attribute every call and spawn to an anchor's
                                time-ordered thread, decide visibility from the
                                open set
  apps/web/lib/runtime-bridge/dag/layout/geometry.ts the implementation of section 1. Packs the backend's
                     lane / tier / depth into lattice `(col, row)` positions for
                     CHAIN nodes (fork lanes one gap column out, fork roots on
                     their sibling's row), then places every open thread
                     recursively beside its anchor, shifts later chain rows by
                     the insertion, and reserves each thread column.
                     **tier and lane are NOT computed here** — the backend
                     computes them in `openprogram/state/store/session/graph/layout/` and ships
                     them on the node; the front end only consumes the values.
  apps/web/lib/runtime-bridge/dag/render/edges.ts    the line-style table of section 3
  apps/web/lib/runtime-bridge/dag/render/nodes.ts    the tiles + status states + badges of section 4
  apps/web/lib/runtime-bridge/dag/render/labels/badges.ts   the branch-name badge of section 5
  apps/web/lib/runtime-bridge/dag/store/globals.ts   expansion state, lastGraph, signatures
```

**What a paint costs.** A capture redraws the whole SVG, so the drawers keep
what does not change between captures: each icon is parsed once and cloned
into its tiles, a tool's presentation is kept per name, arguments and
language, and text widths per font and string. Attaching the new SVG sets
its transform at once and leaves everything that needs the pane's size to
the next frame, so a capture never forces a layout of its own. Gestures only
move the view in the store; `applyView` paints it once a frame. A pan
rewrites the two translations and the lattice offset; the work bound to the
scale — the semantic-zoom variables, label culling, the lattice pitch — runs
only when the scale or the drawn graph changes. On a 150-node session one
repaint takes about 5ms of main-thread time.

The backend `openprogram/state/store/session/graph/builder.py` produces the node array (including the
`branch_name` stamp, caller/predecessor), and `graph_layout/` does the lane/tier/depth
annotation — **tier specifically in `graph_layout/tier.py`**. Verification tool: `python scripts/dag_dump.py <session_id>` prints
lane/tier/depth + an ASCII grid.

## 8. The fill means context coverage

A node's fill marks it as **part of what the next LLM call will carry**. A
covered tile (`is-covered`, set in
`apps/web/lib/runtime-bridge/dag/render/visibility.ts`) shows its icon at full
ink on its tinted chip; an uncovered one steps back — the tint drops to 10%
and the icon to 60% — and an aged one a step back (icon 75%). Both stay
legible: an icon at 38% turned most of a long session grey. Bubbles, captions and branch
tags are words with no chip behind them, each with a canvas-colour halo so a
line passing behind breaks around the letters. The same rule holds in both themes, and the
legend swatch is a covered tile.
"White fill" below means this fill.
There is no mode to choose and no switch to find: whenever the graph is
showing, it owns its pane. A lone session tab gets the chat shell plus this
graph; two session tabs split into two `PeerSessionPane`s where the shell — and
therefore the graph — is not rendered at all. So there is never a transcript
beside the graph, "which bubbles are on screen" has no reading to give, and
coverage is simply what the fill means.

The covered set is served by `GET /api/sessions/{id}/context-range`: the active
branch walked back from head, stopping at the most recent compaction summary,
plus the calls each covered turn made. The predecessor walk sees turns only —
a call hangs off its reply by `caller` — so the route adds the code nodes
`render_context` reads whose conversation owner is in the set, each listed
right after its owner (`_with_code_nodes` in
`openprogram/interfaces/server/routes/files/tree.py`). Without them every
opened call drew as outside the next request, and `aged`, a code-node fact,
could never be set.
Nodes outside it draw dimmed. `enterExclusiveCoverageMode`
(`apps/web/lib/runtime-bridge/dag/index.ts`) is what the host calls to fetch and
apply it.

### Coverage data shape

The same response carries, per node, the two degradations the context pipeline
applies to content it is still carrying:

```json
{
  "session_id": "…",
  "node_ids": ["…"],
  "count": 12,
  "nodes": [
    { "node_id": "…", "in_context": true, "aged": false, "spilled": true }
  ]
}
```

| Field | Meaning | Backend source |
|---|---|---|
| `in_context` | the node is in the covered set — always true for a row, since the list IS that set | `get_branch` |
| `aged` | a code node old enough that its result renders as a one-line stub | `openprogram/runtime/context/render.py::_aged_code_ids`, boundary from `context/aging.py` |
| `spilled` | the result was written to `large_nodes/` and the render only cites it | `metadata.spilled`, written by `state/store/session/spill.py::spill_if_large` |

Both flags come from the functions the real render pass calls, not from a
parallel reimplementation — **the graph never derives context semantics
itself**; it asks the backend and draws the answer.

### Drawing the two degradations

| State | Drawing |
|---|---|
| in context | white fill (the baseline) |
| `aged` | a covered block a step fainter (20% tone) — reads as "still here, but only the gist" |
| `spilled` | `▤` at the node's upper LEFT |

`aged` lowers **the block's tone, never `opacity`**: the fill is the
coverage signal, and fading the whole node would fade the icon and badges too,
collapsing two independent facts into one. The `▤` mark takes the upper left because the upper
right is spoken for (`!` error, `↗` cross-session spawn) and the lower right
holds the fold badge; it is drawn as `<text>` so `_applyVisibility`'s
"first shape child" scan cannot mistake it for the node body.

Compaction covers a range of nodes with a summary; those covered nodes simply
fall out of `node_ids`, so the white fill lands on the summary and nowhere in
the range behind it. §9 is what the graph then does with that range.

Refreshing: coverage is re-fetched whenever `context_stats` or
`compaction_finished` arrives (`chat-handlers.ts`), so the fill tracks the real
context without the frontend ever recomputing it. Note that `aged` and
`spilled` are **not** part of the render signature, so applying new coverage
busts it (`setLastSignature(null)`) — otherwise the repaint silently no-ops and
the graph keeps painting the previous answer.

Compaction interaction:

- `insert_summary_node` clones nothing (dag/overview.md §8): the summary is an
  ordinary `role=llm` chain member carrying `metadata.covers`, and the kept
  tail keeps its own ids and predecessors. The branch ids therefore ARE the
  ids the graph draws, so `/context-range` returns them directly — no
  translation layer, no second id space.
- The summary node is drawn like any other conversation node in every respect
  the data cares about; only genuinely synthetic bridges are filtered
  (`graph_layout/filter.py`). Its capsule is a shape, not a role — §9.
- After compaction the covered prefix falls out of the set, so the fill lands
  on the summary and the kept tail.
- `compaction_finished` must refresh the context range
  (`chat-handlers.ts`); coverage is event-driven like everything else — the
  frontend never computes context membership itself.
- Context ids that have no drawn node (e.g. `display=runtime`
  task-followup rows) are silently ignored: they are context, but not
  graph.

## 9. Compaction reads as one capsule, not fourteen dimmed turns

Dimming a covered range says the right thing about each node and the wrong
thing about the session: fourteen faint circles still cost fourteen rows, and
the eye still has to walk them to reach the live conversation. The summary is
one node that stands for all of them, so the graph draws it that way.

**The capsule.** A summary node is a double circle on the trunk: the
reference circle with a thin concentric inner ring. Same footprint as every
other glyph, one grid slot — the ring is what says "a turn that holds more
than it shows". The ring follows the outer stroke's colour states (grey when
inert or superseded). It is still an ordinary `role=llm` chain member
(dag/overview.md §8): the shape is a shape, not a fourth role.

**The count.** A folded capsule wears the covered-node count as digits on its
right shoulder — the same fold vocabulary as a turn's call-thread count (§12),
and it disappears when the capsule opens, because then the stack is drawn.
No text caption: the glyph (double circle) says what it is, the count says
how much, the ghosts say it is open, and the tooltip/inspector carry the
details.

**The fold is per-branch.** A summary belongs to the branch whose context
carries it — the branch whose active chain contains the whole covered segment
(context/compaction.md §3). Only on that branch does the capsule fold: the
covered range is elided by default, clicking the capsule brings it back as
ghosts, clicking again folds it away (view-only state, never persisted; a
fresh session starts folded). Expansion is sticky across branch switches:
viewing a branch where the covered turns render raw marks the summary
expanded, so returning to the carrying branch finds the range open instead
of snapped shut — seen is seen. On any other branch — a fork from inside the
covered range, a sibling of the same era — those turns ARE the live context:
they render raw, in full branch colour, and the capsule stays on screen but
inert: its own colour, no fold affordance, no count, no white fill — the
node set is identical on every branch, only its reading changes. Switching
branches flips both readings; nothing about the stored graph changes.

**The ghosts.** An expanded range keeps its branch colour; "not part of the
next request" is said by the dashed incoming edge and by the missing white
fill (the white fill lands only on nodes in the context set), never by
draining the colour to grey — grey is reserved for dead history (archived
failure lines, superseded summaries), which no branch can ever carry again.
Readable, clickable, visibly not live: "did the summary actually capture
what I said" is answerable without the answer ever being confused for
context.

**Rolling summaries.** Compaction chains: a second compact feeds the first
summary's text back into the summariser and `extra_meta._last_summary_id`
moves to the replacement — the next request carries exactly one summary,
never a stack. The graph says the same thing: only the active summary gets
`covers_ids` (capsule + fold); a superseded summary keeps its row and its
capsule silhouette but arrives flagged `superseded_summary`, draws in ghost
grey, and folds nothing.

**Where the capsule sits.** One slot, identical in every state and on every
branch: the covered segment's end. Expanded, it follows its ghosts
(ghosts → capsule → tail); on a non-carrying branch it follows the same
turns in the raw (filled turns → hollow capsule → the rest); folded is the
same slot with the segment collapsed, which puts the capsule first on the
trunk. Position never changes when the user switches branches or toggles the
fold — only colour and folding do. All placements are view-only clone
rewrites in `fold-summaries.ts`; the stored row keeps its real `predecessor`
(the range's start — ROOT) in every state.

The white fill never lands on a covered node, in either state, because
`/context-range` does not list it. One fact, one source (§8).

### Where the coverage comes from

The persister writes `metadata.covers_ids` — the exact chain nodes the summary
replaces (context/persistence.py). Ids, not a seq interval: seq intervals span
sibling branches in a DAG, so a dead fork whose seqs fall inside
`[first_seq, last_seq]` would fold behind a capsule that never summarised it,
and the answer would change whenever HEAD moved. `openprogram/state/store/session/graph/builder.py`
passes the list through, adds the caller subtrees hanging off covered turns (a
covered turn folds with its calls), drops ids that no longer exist, and puts
the result on the summary row as `covers_ids`.

One field drives everything: the capsule shape, the fold, the pleat count, the
ghost marking, and the inspector's coverage row. The frontend does no seq
arithmetic and calls no second endpoint.

## 10. A failed turn stays visible as an archive, never as an alarm

A turn that ends in `status = error` is a terminal node; the retry forks off its
predecessor and the conversation continues on the new line (dag/overview.md).
The failed line is kept — that is the point of forking rather than rewinding —
but it can never re-enter context.

So once such a node is **off the HEAD chain**, it draws in the same grey as a
covered turn, and the inspector labels it `Failed turn · Recorded`. The two states look
alike because on the only axis the graph is about they *are* alike: on disk,
readable, and never in the next request.

The grey deliberately replaces the tile's tone. The red `!` on a live
error means "this needs you now", and an archived line does not — the retry already
happened. The `!` glyph itself stays, so why the line ended is still legible.

Both halves of the test matter. `status` alone would grey the error you are
currently looking at, before you have retried it. Off-HEAD alone would grey
every sibling branch. The node has to be a failure *and* abandoned.

`status` is the store's own terminal marker, written by the turn machinery
([Unified execution control](../execution/control.html) for the cancel case, which stays
`cancelled` and keeps its own 50% grey). The graph reads it; it never decides
it.

## 11. Hover, click, right-click, double-click

One surface per question. There used to be three info windows — a hover
tooltip, a second-stage dwell expansion of it, and a click-opened inspector
popover — which gave the click two jobs at once: open a window AND toggle the
node's thread, with the popover landing on top of the very expansion it had
just triggered.

**Hover → the brief card.** The quick cut: role (a spawn head titles itself
`Subagent · <name>` — this is where the name lives, §12), model/tokens, a
short content preview, folded call count, and a status row when the node is
running, cancelled or failed (a finished node's status is the default and gets
no row). The token figure is
`llm.output_tokens` when the node carries a measurement and `chars/4` when it
does not; the card says which (`tokens` vs `tokens (estimated)`), and a node
with no text gets no estimate at all. Keys share one fixed column, so the
values line up. Appears after a short hover delay, gone when the cursor leaves.
The expanded card shows the node's whole id: derived ids (`<reply>_t_<call>`)
share their first dozen characters.

**Click → the node's own action.** Fold or unfold its call thread (§12).
Nothing else — no window competes with the expansion. The right rail's
Details view still fills quietly for whenever the user opens it.

**Right-click → the SAME card expands in place.** Not a second window: the
one card element deepens where it stands (`apps/web/lib/runtime-bridge/dag/interaction/node/tooltip.ts expandTooltip`) — every
field, longer previews, coverage state, context standing, id — and the verbs
join at its bottom: checkout to this branch · fork from this node · fork and
edit this message (user turns only) · copy node id · view raw JSON. One row
builder (`renderNodeInfo`) feeds both states, so they cannot disagree; the
coverage rows read off the DOM flags the node drawer already stamped
(`data-ghost`, `data-failed`, `.out-of-context`), so the card and the picture
beside it cannot disagree either. Expanded, the card turns interactive and
stays — mouse-off no longer dismisses it, hover cannot repaint it, and a
click anywhere else (or running a verb) collapses it. Raw JSON opens in the
inspector shell rather than a modal — a modal would take the graph away to
show you one node from it.

**Double-click a user turn → fork and edit.** The message text lands in the
composer with HEAD already back at its fork point. Other nodes keep the
checkout behaviour — there is nothing to edit on a reply or a tool result.

### Every action is an existing operation

Nothing here adds a verb to the protocol:

| Action | Route | Why that is the whole implementation |
|---|---|---|
| checkout | `POST /api/chat/checkout` | a pure HEAD move, exactly what the transcript's sibling navigator sends |
| fork from node | `POST /api/chat/checkout` | fork *is* checkout plus intent — a turn sent from a HEAD that already has children is by definition a sibling of them, which is how the transcript's "branch from here" button works too |
| fork and edit | `POST /api/chat/checkout` to the node's **predecessor**, then the text into the composer | the user edits and sends; that send is an ordinary send against the new HEAD, so it forks with no protocol change and no "send from node X" concept to keep alive. The predecessor is the fork point precisely because the edited message has to stand *beside* the original, not after it — the same shape `POST /api/chat/edit` produces |

The inspector and menu are built imperatively (`apps/web/lib/runtime-bridge/dag/interaction/node/inspector.ts`) because
the graph is: they float over an SVG the renderer owns, keyed to node geometry,
outside React's tree.

**Legend.** A card names the shapes and the two greys, switched on and off by
the zoom column's legend button (`apps/web/components/chat/dag/dag-view.tsx`); a
click on the canvas leaves it open. It starts
closed — the vocabulary is small and learnable, so the legend is for the
first few sessions rather than a permanent fixture on the canvas.

## 12. The call thread: what a turn did is one sequence, folded into one count

Everything a turn did — every function call, every agent it spawned — is one
time-ordered sequence of events, the turn's **thread**. Calls and spawns are
the same kind of event at different scales, so they share one line, one
ordering, and one fold. A session whose one reply made 41 calls and spawned two
agents is, by default, three chain nodes and the digits `43`; open, it is 43
real nodes in the order they happened.

**Folded is folded.** The only mark is the count on the node's upper-right
shoulder: digits in annotation grey, glued to the glyph. Not a badge shape, not
a pill, not a square on a line — anything with an outline reads as a node, and
a phantom node is exactly the misreading the fold must not invite. No thread
line, no items, nothing else.

**Open is open.** Clicking the node inserts the thread into the layout: a
solid line in the anchor's branch colour drops the anchor's own column and every event
hangs off it on a horizontal stub — down first, then right, the trunk
pattern one level down. Every event is a real node on that line — a square per call
in the anchor's lane colour — spawned agents included — one row
per event, top to bottom in call order. Later user / assistant nodes on the
figure move down by those inserted rows, so the thread vertical in the
anchor's column ends before the next triangle. Each open thread reserves its
column. Fold reclaims the rows (rule ②).

**The head IS the agent, and the spawn IS a call.** A spawn root draws as a
SQUARE — dispatching an agent is a function call, and the square is the call
vocabulary. The dispatch call node (`agent` / `send_message`) folds into it:
one spawn, one glyph (a dispatch that opened no spawn keeps its own square —
that failure is worth seeing). The agent's internal turns are not chain
nodes — they merge into it (§0), replies drawing as triangles and calls as
squares once opened — and its own thread sits one column further right,
opened by clicking the square. While the spawn square is on
screen (its owner's thread is open — the opt-in that keeps the default
canvas clean), a badge pill (the same pill as branch badges,
apps/web/lib/runtime-bridge/dag/render/labels/badges.ts) sits at its RIGHT as the square's name tag; clicking it
checks the agent chain's tip out as the active branch — taking over the
agent's conversation. Badges never cover a node: every visible glyph seeds the
badge collision boxes, so a badge that would land on one steps down a row. The model is recursive and so is the picture: every level reads
by the same two rules, count-on-shoulder folded, column-of-nodes open. A
nested open thread pushes the parent's later items down; a chain-anchor
thread likewise inserts later conversation-layer turns. Expansion is
insertion, never overlay.

**No captions.** The agent's name lives in the tooltip and the inspector
(which titles the node `Subagent · <name>` rather than the `user` its role
field claims); the canvas carries only the glyph and its count. The name on
the wire comes from the label the runner stamps (`spawned_from.label`), with
the recorded branch name as a fallback.

**No return line.** The agent's return triggers a followup reply, and that
reply merges into the same anchor whose thread carries the agent (§0) —
dispatch, work and return are one column read top to bottom. The old dashed
attach-return curve only draws when both of its ends are chain-visible, which
an agent-internal tip never is any more.

**View state.** `_threadOpen` in `apps/web/lib/runtime-bridge/dag/store/globals.ts`, keyed by anchor id (chain
turn or spawn head — one vocabulary). Never persisted, reset on session
switch, exactly as in §9. A spawn head is visible only while every thread
above it is open; its items likewise — visibility is the whole ancestor
chain's, not the node's own flag.

## 13. The mouse, the controls sheet, selection and deleting nodes

The canvas has one mouse and no tools to switch between. Splitting browsing,
box-selecting and lasso-selecting into three tools made every first drag a
question of which tool was in hand. One mouse does all of it, the left
button selecting and the right one moving the camera:

| Gesture | What it does |
|---|---|
| Click a node | select it, then the node's own action (§11, §12) |
| Drag on empty canvas | a box; every node it touches is selected |
| Shift/⌘ + click or drag | add to the selection, or take a node out |
| Click on empty canvas | clear the selection |
| Right drag | pan, from anywhere on the graph (the middle button pans too) |
| Right click a node | its menu (§11) |
| Wheel, or pinch | zoom about the cursor |
| Two fingers on a trackpad | pan |
| Double-click a node | fork & edit (§11) |

The mouse wheel zooms like a map's; two fingers on a trackpad pan; a pinch
zooms at its own, faster rate. macOS fires the right-click menu on the press, before a
drag can start, so the canvas holds it and opens it on release when the
pointer did not move. These are fixed by design, not settings: touching
selects (no enclose-only mode) (`apps/web/lib/runtime-bridge/dag/interaction/view/gestures.ts`,
`interaction/node/nodes.ts`, `interaction/selection/selection.ts`).

Every canvas control is one raised strip of the app's button material (the
input box's fill and the composer's shadow, which deepens under the pointer as
the composer's buttons do): the zoom column, the action bar, the minimap and
the pane's top-right controls. There is no left rail. **Find the working
agent** (F, in the zoom column) glides the view to the tile a working
agent stands on, keeping the zoom. Pressed again it moves to the next working
agent, and with none at work it goes to HEAD (`focusAgent` in
`interaction/view/canvas.ts`). Zoom is the zoom column on the
right edge (see "The canvas is infinite"). The column's last button (a notes
glyph, since half the sheet is mouse gestures, not keys) opens the **controls
sheet**: every gesture and key the canvas answers to, grouped as mouse, camera
and selection, in a panel left of the column, from the top
(`components/chat/dag/dag-key-sheet.tsx`). `?` opens it
too. It is a guide like the legend and behaves like it: it stays open until
its button or `?` is pressed again, or the legend takes its spot — clicks on
the canvas and Esc leave it be. Esc runs down one thing at a time: the
selection, then full screen. The view keys follow design
tools: Shift+1 fits the graph, Shift+0 returns to 100%, and + / − step the
zoom, the same steps as the zoom column's buttons (`interaction/selection/keys.ts`).

**Selection.** View state of the current session's canvas. Each selected node
lights up in place (`is-selected`): its chip fills solid in its own colour and
its icon turns to the canvas colour, a pressed button. Nothing is drawn around
it — dashed rings, rings round square tiles and a grey disc behind the tile were
all tried and all made the edge harder to see. The box that selects is an
accent outline over an 8% accent fill. The set is re-applied after
every repaint and pruned to the nodes the canvas still draws, so a node that is
deleted or folded away leaves the selection. A session switch drops it.
Selecting on the canvas takes keyboard focus from the composer, so Delete and
Esc reach the selection rather than the draft.

**The action bar.** While something is selected, a bar at the canvas's top
left reads `N selected | ⌖ · Copy ID · Delete · ✕`, with Delete in the danger
colour. ⌖ fits the view to the selection, as Shift+2 does in design tools
(`frameSelection` in `interaction/view/canvas.ts`). After a delete it reads `Deleted N nodes | Undo` for a few seconds.
It sits at the top left rather than at the top right, which belongs to
the pane's perspective controls. It is the same raised material as the column.

**Deleting.** Delete or ⌫ deletes the selection at once, with no
confirmation, and ⌘Z undoes it. The store
(`openprogram/state/store/session/session_store/node_deletion.py`) applies these
rules:

- Only the selected nodes go, plus what they own through `caller`: a reply's
  tool calls, a call's sub-calls, the agent branch a call spawned. What merely
  followed in the conversation stays. Each surviving node whose predecessor was
  deleted is re-pointed at the nearest surviving predecessor, so deleting a
  node closes the gap the way deleting a box in a diagram does.
- A glyph stands for every row it shows. A followup reply merged into its
  anchor (§12) is deleted with the anchor, and selecting a spawn square deletes
  the dispatch call that opened it, which takes the agent branch with it.
- Structure cannot be deleted: the root, a spawn-branch root on its own, a
  compaction summary, attach/merge machinery. The canvas leaves these out of
  the request and the store refuses them.
- If HEAD was deleted it moves to the nearest surviving predecessor. A branch
  name on a deleted tip moves there too.
- Nothing is unlinked. The node files move to
  `<sessions root>/.deleted-nodes/<session>/<op_id>/`, outside the session's
  git repository, together with a journal of every edge, HEAD and branch-name
  change. Trash older than 24 hours is purged on the next delete.
- Undo replays the journal backwards. An edge or a HEAD that something else
  has moved since keeps its newer value.
- Both actions are refused while a turn runs. The in-flight turn may be
  writing under the nodes being removed.

The wire format is `delete_nodes {session_id, node_ids}` → `nodes_deleted
{ok, op_id, deleted, error}` and `restore_deleted_nodes {session_id, op_id}` →
`nodes_restored` (`openprogram/interfaces/server/ws_actions/dag_nodes.py`).
A success also broadcasts `session_reload`, so the transcript and the graph
both redraw. The undo stack is per session and lasts as long as the page.

### The minimap

A long session runs off the screen, so the canvas has a minimap in its
top-right corner, left of the zoom column, in the column's raised material. Each node is a
dot of its tone on the graph's own lines (thin, faint, in their branch colours, so the
trunk and its branches read at a glance), and the part on screen is a frame in the accent colour. A
press or a drag on the map moves the camera there at the same zoom. The map
frames the graph and the view together, so the frame is never cut off, and it
holds still while you drag. HEAD is a larger dot ringed in the accent colour,
the "you are here" of the map, and a wheel over the map zooms the canvas about
its middle. It starts hidden; the column's map button or M shows it and hides
it again, and the choice is kept in the browser. Once shown it stays on
screen whatever the view: a map that faded out whenever the whole graph fitted
came and went with the zoom and read as a glitch
(`apps/web/lib/runtime-bridge/dag/interaction/view/minimap.ts`, repainted with the
view, once a frame; the dots, lines and colours are read once per drawn graph).

## Appendix: Implementation Status

The whole spec is implemented. Where each part lives:

| Spec item | Implementation |
|---|---|
| Infinite canvas (pan / zoom / fit / dot lattice) | `apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts` + `.history-body` in `apps/web/app/styles/dag/graph/canvas.css`; view state in `apps/web/lib/runtime-bridge/dag/store/globals.ts`; zoom column in `apps/web/components/chat/dag/dag-view.tsx` |
| §1 lane / tier / depth layout | `apps/web/lib/runtime-bridge/dag/layout/geometry.ts::computeGeometry` (tier-packed chain lanes with per-lane tier zeroing, preorder rows, scene-3 fork rows + gap column, recursive thread placement that inserts later chain rows and reserves thread columns); lattice, no-overlap, thread columns/rows and fork geometry all executed and asserted by `apps/web/tests/dag/dag-subagent-thread.test.mjs` |
| §2 rule ③ glyphs are cells | no shape is sized from text; captions take only free cells and never move the layout (`render/labels/captions.ts`) |
| §4 HEAD breathing glow | `apps/web/lib/runtime-bridge/dag/render/nodes.ts` stamps `data-head` + the branch colour as `color`; `dag-head-glow` keyframes in `apps/web/app/styles/dag/graph/nodes.css` (reduced-motion → steady glow); every glyph stays hollow (`apps/web/lib/runtime-bridge/dag/render/shapes.ts`); HEAD pointing at a merged reply re-seats on its anchor (`apps/web/lib/runtime-bridge/dag/pipeline.ts` via `threadModel.anchorOf`) |
| §0/§12 call-thread aggregation | `apps/web/lib/runtime-bridge/dag/passes/thread.ts` (`buildThreadModel`: anchor merge, event attribution, recursive visibility); `apps/web/lib/runtime-bridge/dag/render/nodes.ts` draws the shoulder count (`history-thread-count`); `_threadOpen` in `apps/web/lib/runtime-bridge/dag/store/globals.ts` |
| Rule ② corollary (no placeholder box) | `apps/web/lib/runtime-bridge/dag/render/shapes.ts`: no `square_outline`; task renders as a plain square |
| §4 status on the block | `graph_builder` emits status; `nodes.ts` sets it as a CSS state of the tile (running breathing / error `!` / cancelled grayed) |
| §5 badge anchoring | `apps/web/lib/runtime-bridge/dag/render/labels/badges.ts`: anchor at last conversation-layer node, half-column left shift when a line crosses the anchor cell, measured-pixel-box collision slides down one row |
| Scene 8 merge shape and lines | `apps/web/lib/runtime-bridge/dag/render/shapes.ts` `merge_dot` (◉); `edges.ts` merge-in line peer-colored 2.4px solid |
| Scenes 8/10 attach pointer | backend filters it (display=runtime) + `graph_builder` stamps the ref onto the embed host (`attach_returns`); `edges.ts` draws the long-dash return line |
| §4 cross-session ↗ | `graph_builder` stamps `spawn_remote` from target-root provenance and `spawn_out` from the source attach's target session; `nodes.ts` draws ↗ on both sides. Cross-session badge navigation is not implemented |
| §1 spawn root tier | `graph_layout`: tier=1 / same-row depth / new lane; `job_followup` / `process_exit` replies re-parent onto the receiving turn (`filter.py` fallback) |
| Composer shared by both perspectives | `apps/web/app/styles/chat/pane/center-pane.css` hides `#chatArea`, not `#chatView`; asserted by `apps/web/tests/tabs/center-perspective.test.mjs` |
| In-graph branch tags (checkout buttons) | `apps/web/lib/runtime-bridge/dag/render/labels/badges.ts`; hover styles on `.history-branch-tag` in `apps/web/app/styles/dag/graph/badges.css` |
| §8 coverage query | `routes/tree.py::_coverage_nodes` fills `/context-range`'s `nodes`; tested in `tests/unit/context/test_context_range_coverage.py` |
| §8 aged / spilled drawing | `apps/web/lib/runtime-bridge/dag/render/nodes.ts` (fainter block + `▤`), fed by `_coverageSet` in `apps/web/lib/runtime-bridge/dag/store/globals.ts` |
| §9 `covers_ids` on the wire | `openprogram/state/store/session/graph/builder.py` resolves `metadata.covers` to ids; tested in `tests/unit/dag/test_graph_builder_covers.py` |
| §9 capsule shape | `apps/web/lib/runtime-bridge/dag/render/shapes.ts` `capsule` (keyed on `covers_ids`, tagged `data-shape` so `_applyShapeSize` leaves its geometry alone) |
| §9 fold + pleats + ghosts | `apps/web/lib/runtime-bridge/dag/passes/fold-summaries.ts` (fold), `apps/web/lib/runtime-bridge/dag/render/nodes.ts` (pleats, `Compacted · N turns` caption, ghost stroke), `apps/web/lib/runtime-bridge/dag/render/edges.ts` (dashed ghost edge), `_summaryExpanded` in `apps/web/lib/runtime-bridge/dag/store/globals.ts`; executed by `apps/web/tests/dag/fold-summaries.test.mjs` |
| §10 archived failure | `apps/web/lib/runtime-bridge/dag/render/nodes.ts::_isArchivedFailure` — `status=error` AND off the HEAD chain; grey overrides the tone, the `!` stays |
| §11 one card, two states / fork & edit | `apps/web/lib/runtime-bridge/dag/interaction/node/tooltip.ts`: `renderNodeInfo` feeds both states, `expandTooltip` deepens the card in place; `apps/web/lib/runtime-bridge/dag/interaction/node/inspector.ts` builds only the verb list (+ raw JSON layer), wired in `apps/web/lib/runtime-bridge/dag/interaction/node/nodes.ts`; the actions go through `POST /api/chat/checkout` |
| §11 legend | `DagLegend` in `apps/web/components/chat/dag/dag-view.tsx` (in the zoom column), `.dag-legend` in `apps/web/app/styles/dag/panels/legend.css` |
| §12 call thread + agent spawn | `apps/web/lib/runtime-bridge/dag/render/shapes.ts` (spawn → square), `apps/web/lib/runtime-bridge/dag/passes/thread.ts` (model), `apps/web/lib/runtime-bridge/dag/layout/geometry.ts` (recursive placement), `apps/web/lib/runtime-bridge/dag/render/edges.ts` (dotted thread line, centre-to-centre chain edges, scene-3 bridge), `apps/web/lib/runtime-bridge/dag/render/nodes.ts` (`data-thread*`, shoulder count), `apps/web/lib/runtime-bridge/dag/interaction/node/nodes.ts` (`toggleThreadOpen`); executed by `apps/web/tests/dag/dag-subagent-thread.test.mjs` |
| §12 the name on the wire | `task/runner.py::_update_attach_card` stamps `attach.label` from the task; `ws_actions/session/transcript.py::_annotate_spawn_origin` carries it to the spawn root as `spawned_from.label`; tested in `tests/unit/test_task_attach_integration.py` |
| §13 mouse, controls sheet, selection, delete / undo | selection state, hit-testing and the selection box in `apps/web/lib/runtime-bridge/dag/interaction/selection/selection.ts`; drags in `gestures.ts`, clicks in `nodes.ts`, keys in `keys.ts`; widening and the undo stack in `node-delete.ts`; action bar in `apps/web/components/chat/dag/dag-tools.tsx`, zoom column in `dag-view.tsx`, controls sheet in `dag-key-sheet.tsx`, minimap in `interaction/view/minimap.ts`, + `apps/web/app/styles/dag/panels/tools.css`; store splice and journal in `openprogram/state/store/session/session_store/node_deletion.py`; tested in `tests/component/store/test_node_deletion.py` and `apps/web/tests/dag/dag-selection.test.mjs` |
