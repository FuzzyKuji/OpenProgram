# Moving tabs between windows

A desktop tab can leave its window and land in another OpenProgram window, or
in a new window created where it is released. The move is a transaction: the
tab exists in exactly one window when it ends, and a failure anywhere leaves
the source window as it was. A web tab keeps its live page.

Related: [`center-tabs-and-split-layout.html`](../workspace/center-tabs-and-split-layout.html)
(tab strip, groups and split layout inside one window),
[`window-lifecycle.md`](window-lifecycle.md) (main and torn-off windows).
Code: `apps/desktop/main/web-views/transfers.js` (main-process coordinator), the
desktop `tab-transfer-validation.js` and `tab-transfer-store.js` modules,
`apps/web/lib/tabs/transfer/` (renderer drag coordinator and journal) and
`apps/web/lib/tabs/store/transfers.ts` (tab-store insertion and removal).

## What moves

A transfer carries one of three source shapes:

| Source kind | Contents |
|---|---|
| `tab` | exactly one ungrouped tab |
| `segment` | one member of a compound group; the rest of the group stays |
| `group` | a whole compound group with its members, visible members and focused member |

Any center-tab kind can move: session, file, web, new-tab page, application
and built-in page. The payload also carries what the destination needs to
show the tab as it was: the source position (group id, member index, member
order, visible members, focused member, canvas layout), unsaved file drafts,
and per-chat state (composer draft, composer settings, pending project,
channel choice, and whether that chat was active). Page history travels with
each tab.

The main process validates every payload before it accepts it. Strings and
nested values are bounded; the whole payload is at most 20 MiB, and file
drafts are at most 3 per transfer, 2 MiB each and 6 MiB in total. A malformed
payload never yields a token.

## Web pages keep their state

Web tabs are Electron `WebContentsView` objects owned by one window context.
Moving a web tab moves **the same view object**: the coordinator removes it
from the source window's content view and adds it to the destination's. It
never calls `loadURL`, so redirects, sign-in state, form values, scroll
position, in-page memory and the DevTools protocol target survive the move.
The view is hidden until the destination renderer reports its new bounds.

Before reparenting, the coordinator clears the page's agent action cue and
control overlay, records each view's bounds and visibility, and checks that
the source still owns every view. A view that is part of an active transfer
is locked, so a second transfer or an agent command cannot claim it at the
same time.

## Transaction

Each transfer is identified by an opaque single-use token and expires after
15 seconds unless it completes.

```
source renderer          main process                  destination renderer
─────────────────        ────────────────────────      ────────────────────
prepare(payload)  ─────▶ validate, issue token
                         (status: prepared)
                                                ◀────── inspect(token)
                                                        (one window only)
                                                ◀────── accept(placement)
                         lock views, reparent
                         (destination-staged)    ──────▶ insert tab, journal
                                                ◀────── destination-ready
                         (awaiting-source)
remove tab, journal ◀─── remove-source
source-removed    ─────▶ persist "committed"
                         decision, reveal window
                         (committed)
```

- **Prepare.** The source renderer asks for a token synchronously when the
  drag leaves its strip.
- **Inspect and accept.** The window under the pointer inspects the token; the
  source window and any second window cannot. Accepting locks the views and
  reparents them. The destination may instead reject with `duplicate` (it
  already holds that tab and focuses its own copy) or `group-full`; the
  source is told and nothing changes. A payload the destination cannot
  validate at all is not accepted, and its token expires.
- **Destination first.** The destination inserts the tab and reports ready.
  Only then does the source remove its copy, so there is never a moment
  with no live tab.
- **Commit.** The main process writes a `committed` decision to
  `tab-transfers.json` in the application data directory with an atomic
  replace before it reports success. If that write's durability is uncertain,
  the coordinator rewrites the same decision with backoff from 100 ms up to
  5 s; if the decision cannot be written at all, the transfer rolls back.
- **New window.** Releasing outside every OpenProgram window creates a hidden
  torn-off window at the release point. It claims the pending token, accepts
  like any destination, and is shown with a fade only after the tab is
  staged, so it never flashes empty. Concurrent detach requests share one
  window boot.
- **Empty source.** If the source has no tabs left, it closes after its
  journal is finalized.

The target window under the pointer gets hover enter and leave events, so it
can show the drop position only while a drag is over it.

## Journals and recovery

Each renderer writes a journal entry in its own window-keyed local storage
(`openprogram.tabTransferJournal:<windowId>`) before it mutates its tab
store. The entry holds the before and after tab layout, session state, file
drafts and native-view bookkeeping, so the renderer can apply either side
after a reload or crash. The main process records which roles opened a
journal; the durable decision lists them as required roles.

After a reload, a renderer asks for pending terminal decisions and applies
`committed` or `rolled-back` to its journal, then finalizes its role. A
decision is deleted once every required role has finalized. If the window
that owned a role is gone, another live window adopts the orphaned role and
finishes it.

## Rollback

A transfer rolls back on expiry, on a destination or source failure, on an
explicit cancel (Escape or a drag ending without a target), when a
participating window is destroyed or tries to close, and when the commit
decision cannot be written.

- Before any journal is opened, rollback just discards the token and tells the
  source.
- Afterwards, the coordinator writes a `rolled-back` decision, asks the
  destination to undo its insertion (2-second limit), then returns every view
  to the source with its original bounds and visibility. A torn-off window
  created for the transfer is closed and its state discarded.
- If the source window no longer exists, the transferred views are closed
  instead of being left without an owner.
- A committed transfer never rolls back.

Ordinary close rules do not apply to a transfer: removing the source copy
creates no close record, deletes no draft, and does not open a fallback new
tab before the destination has acknowledged receipt.

## Routing after a move

Menu commands and agent web-tab commands go to the focused window only.
Native-view messages are accepted only from the renderer whose window owns
the addressed view, so a moved page answers to its new window immediately.
