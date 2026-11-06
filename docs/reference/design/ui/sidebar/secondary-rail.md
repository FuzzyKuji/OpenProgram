# Secondary rail

A secondary rail is the list column a page shows between the main sidebar and
its content: the project list on History, the Agent list, the Programs tree under
Abilities, the Settings categories, the Memory column of a project (sections, topics tree,
timeline), and the recency filters of the chat list.
All of them are one component, `SecondaryRail`, in
[`apps/web/components/ui/secondary-rail.tsx`](https://github.com/FuzzyKuji/OpenProgram/blob/main/apps/web/components/ui/secondary-rail.tsx).
No page styles its own rail rows.

## Anatomy

```
┌ page header (ManagePageHeader, 64px) ─────────────────────────────┐
│ [⇤] Title                                   search · actions      │
├──────────────────────────┬────────────────────────────────────────┤
│ RailSearch               │                                        │
│ RailGroupLabel           │  content                               │
│ ▣ RailItem   [badge]  ⚠  │                                        │
│ ▣ RailItem                │                                        │
│   second-line description │                                        │
│     ▣ nested RailItem     │                                        │
│ ───── RailSeparator ───── │                                        │
│ ＋ RailItem (quiet)       │                                        │
└──────────────────────────┴────────────────────────────────────────┘
```

| Part | Built from | Notes |
|---|---|---|
| `RailSplit` | CSS grid | Rail column is `--sidebar-width - 1px`, so it lines up with the main sidebar; `--rail-collapsed-w` when collapsed. |
| `SecondaryRail` | `nav` or `aside` | 8px padding, 1px rows gap, right hairline, no background of its own. |
| `RailSearch` | `ui/search-input` | The one search box. Hidden when collapsed. An optional `action` sits beside it. |
| `RailGroupLabel` | `GROUP_LABEL` from `menu-styles.ts` | Same section label as menus. An optional `action` sits at its right end. |
| `RailAction` | `ui/button` `ghost` `icon-xs` | Icon action in a search or label `action` slot (Memory's refresh), with a `HoverTip`. |
| `RailItem` | `.ui-list-item` | The main sidebar's row: 30px, 6px 8px padding, 12px gap, `--nav-color` text. A `description` makes it a two-line row (min 48px, clamped to two lines). `depth` indents a tree level by 16px. `href` renders a `Link`, otherwise a `button`. |
| `RailBadge` | `ui/badge` outline | Small tag after the name ("Default", "Hidden"). |
| `RailCount` | text | Quiet trailing count. |
| `RailSeparator` | `ui/separator` | Above an "Add …" row. |

Folders are one glyph everywhere: the main sidebar's Solar `folder` /
`folder-open` (duotone, in `--folder-color`: macOS Finder's light folder
blue, one value per light/dark scheme), in the project rail, the
Memory topics tree, the Programs tree and the Files panel tree (its Pierre
sprite and root path). A tree folder is open while
expanded, and the selected project in the rail shows the open folder; pages are Solar `file-text`, and a
missing folder shows Solar `danger-triangle`. Section rows (Memory's Topics,
Timeline, …) keep the main sidebar's line nav icons.

States follow the list-row recipe in [surface-system.md](../visual-system/surface-system.md):
hover and keyboard focus use `--bg-hover`; the selected row uses `--bg-hover`
with `--text-bright`; an "Add …" row is `quiet` (muted text). There is one
selected colour for every rail.

## Collapse

A rail with a `railKey` collapses to an icon column, like the main sidebar. The
page header shows its `RailToggle` before the title (`ManagePageHeader`
`railToggle`), and the toggle's icon sits on the same vertical axis as the row
icons below it. Collapsed, search, group labels, text, trailing slots and nested
rows are hidden, each top-level row becomes a 32px square, and its name moves
into a `HoverTip`.

The open state is stored per key as `localStorage["<railKey>NavOpen"]`
(`settingsNavOpen` for Settings, `projectsNavOpen`, `agentsNavOpen`). With no
stored choice a rail starts collapsed below 760px. Narrowing the window below
760px collapses it without saving that; widening never expands it.

| Page | Rail | Collapsible |
|---|---|---|
| History | Projects (`PROJECTS_RAIL`) | yes, toggle in the History header |
| Agents | Agent list with search, two-line rows, shown with the full editor (the page opens on cards) | yes |
| Settings | Categories (`Link` rows) | yes |
| Abilities → Programs | Catalog tree (`depth`) | no; the Abilities header belongs to all four tabs |
| History → project → Memory | Sections, topics tree (folders, a type badge when it differs from the folder, date), timeline (year › month › day) | no; it sits inside the project page |
| Chat list (stand-alone) | Recency filters with counts | no |

Pages without a list column (Scheduler, Applications, Abilities' Plugins,
Skills and MCP) use the page header's tabs and `ManageSubnav` instead.

## Buttons

Page chrome uses the Nova `ui/button` variants only, without per-page overrides:

| Role | Variant |
|---|---|
| The page's main action (New, Add, Install, Open) | `default` |
| Secondary actions (Update, Retry, Memory settings) | `outline` |
| Row icon actions (pause, delete) via `ManageIconButton` | `ghost`, `icon-xs`, with a `HoverTip` |
| Removing something (Uninstall) | `destructive` |

Icon-only buttons name themselves with `aria-label` and show a `HoverTip`, never
a native `title`. Page menus (the Agent actions menu) are `ui/dropdown-menu`
styled with `menu-styles.ts`.

## Guard

`apps/web/scripts/ui/check-secondary-rail.mjs` (run by `npm run check`)
fails when a rail page stops using `SecondaryRail`, when its stylesheet defines
its own rail rows again, or when a collapsible rail and its header toggle use
different keys.
