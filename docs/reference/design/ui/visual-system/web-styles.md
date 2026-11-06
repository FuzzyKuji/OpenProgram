# Web style organization

The web app's CSS is organized to mirror the component tree: one file per
component (or per tightly-scoped concern), grouped into directories that
match the UI's own structure. Styling a component means opening exactly one
file, named after it.

## Layout

```
apps/web/app/
  globals.css       entry: tailwindcss → design → themes → styles
  styles/
    index.css       imports the global layer in cascade order
    design/         design tokens and Tailwind's names for them
    themes/         colour values, one file per theme (+ fallback.css)
    base/           document, focus, list row, shell layout, scrollbar,
                    sidebar, desktop chrome, motion, canvas drag
    chat/           one file per chat component, by area
      pane/ messages/ cards/ execution/ composer/ welcome/
    dag/            one file per DAG-renderer concern
      graph/ panels/
    right-dock/     right-sidebar panels
```

`app/styles/index.css` imports the tree in cascade order (base → chat →
right-dock → dag). The tokens, and which component takes which tier,
are in [Design tokens](design-tokens.md).

## Rules

- **One component, one file.** A file styles the component it is named
  after, nothing else. Every file opens with a comment naming the
  component and its tsx/ts source path.
- **Placement follows the component tree.** A DAG node style belongs in
  `dag/graph/nodes.css` because the drawer lives in
  `lib/runtime-bridge/dag/render/nodes.ts`; a chat bubble style belongs in
  `chat/bubbles.css`. New components get new files, not appended sections.
- **Genuinely global rules stay global.** Tokens live in `design/`,
  theme values in `themes/`, the shell in `base/`; the chat column skeleton (`.main`,
  `#chatView`) is `chat/layout.css` — the one deliberately cross-component
  file, named for what it is.
- **Module CSS stays module CSS.** Components already using
  `*.module.css` (the composer) keep it; this tree covers the global
  stylesheet layer only.
- Tests that assert on style sources read the per-component file through
  postcss (`tests/tabs/canvas-css-geometry.test.mjs` reads the center-tabs
  modules for the strip sizes).
- **No native scrollbars.** `base/scrollbar.css` hides them on every
  element at zero specificity: macOS Chromium flashes a native bar
  whenever the pointer enters a scrollable box, so a still pane lit up
  under a resting cursor. `lib/runtime-bridge/dom/scrollbar.ts` installs
  a thin floating thumb (vertical, and horizontal when the box overflows
  sideways) on a box the first time it scrolls. The thumb shows only
  while the box scrolls or the thumb is held, fades 900ms later, and
  takes no layout width. Hovering, resizing and content changes move it
  without showing it, and a faded thumb takes no pointer events, so the
  cursor crossing a box's edge never lights it up. A scroller inside a shadow root, where neither the
  stylesheet nor the document's scroll listener reaches, hides its own
  bar and calls `attachOverlayScrollbar`.

## Type

Text looks the same from page to page because every size and face comes
from one place.

- **Sizes are nine tiers.** `design/type.css` defines `--fs-2xs`
  (11px) through `--fs-display` (30px); which text sits on which tier is
  under [Type](design-tokens.md#type). `scripts/ui/check-design-tokens.mjs` (run by `npm run check`)
  refuses any other size.
- **Faces load before the first paint.** Inter's and JetBrains Mono's
  Latin files go through `next/font` (`app/fonts.ts`): preloaded with the
  HTML and `display: block`, so text never paints in a fallback face and
  then reflows. Other scripts use the `@fontsource` faces.
- **The language is right on the first paint.** The exported HTML is
  English. For another locale the head script marks `<html
  data-locale-pending>`, which hides the body; `useTranslation` switches
  the locale in a layout effect, before the browser paints, and removes
  the mark. A page whose script never runs is revealed after 1.5s.
