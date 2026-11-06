# 二级侧栏

二级侧栏是页面在主侧栏和内容之间显示的那一列列表：历史页的项目列表、Agent 列表、
能力页 Programs 下的目录树、设置的分类、项目里的记忆列（分区、主题树、时间线），以及会话列表的时间筛选。它们都是同一个组件
`SecondaryRail`，位于
[`apps/web/components/ui/secondary-rail.tsx`](https://github.com/FuzzyKuji/OpenProgram/blob/main/apps/web/components/ui/secondary-rail.tsx)。
页面不自己写侧栏行的样式。

## 结构

```
┌ 页面顶栏（ManagePageHeader，64px）────────────────────────────────┐
│ [⇤] 标题                                       搜索 · 操作        │
├──────────────────────────┬────────────────────────────────────────┤
│ RailSearch               │                                        │
│ RailGroupLabel           │  内容                                  │
│ ▣ RailItem   [标签]   ⚠  │                                        │
│ ▣ RailItem                │                                        │
│   第二行描述              │                                        │
│     ▣ 嵌套 RailItem       │                                        │
│ ───── RailSeparator ───── │                                        │
│ ＋ RailItem（quiet）      │                                        │
└──────────────────────────┴────────────────────────────────────────┘
```

| 部件 | 基于 | 说明 |
|---|---|---|
| `RailSplit` | CSS grid | 侧栏列宽 `--sidebar-width - 1px`，与主侧栏对齐；收起时为 `--rail-collapsed-w`。 |
| `SecondaryRail` | `nav` 或 `aside` | 8px 内边距，行间 1px，右侧细线，自身不设背景。 |
| `RailSearch` | `ui/search-input` | 全站唯一的搜索框。收起时隐藏。可选的 `action` 放在旁边。 |
| `RailGroupLabel` | `menu-styles.ts` 的 `GROUP_LABEL` | 与菜单相同的分组标题。可选的 `action` 放在右端。 |
| `RailAction` | `ui/button` `ghost` `icon-xs` | 放进搜索框或分组标题 `action` 位的图标操作（记忆的刷新），带 `HoverTip`。 |
| `RailItem` | `.ui-list-item` | 主侧栏的行：30px，内边距 6px 8px，间距 12px，文字 `--nav-color`。传 `description` 变成两行（最少 48px，最多两行）。`depth` 每层缩进 16px。传 `href` 渲染 `Link`，否则是 `button`。 |
| `RailBadge` | `ui/badge` outline | 名称后的小标签（“默认”“已隐藏”）。 |
| `RailCount` | 文字 | 尾部的浅色计数。 |
| `RailSeparator` | `ui/separator` | 放在“添加…”行上方。 |

文件夹在所有地方只用一种图标：主侧栏的 Solar `folder` / `folder-open`（双色，颜色取 `--folder-color`：macOS 访达的浅蓝色文件夹，浅色和深色各一个取值），项目栏、记忆主题树、Programs 目录树和文件面板的目录树（Pierre 的图标精灵和根路径）都用它。目录树里展开的文件夹显示为打开状态，项目栏里选中的项目也显示打开的文件夹；页面用 Solar `file-text`，目录缺失用 Solar `danger-triangle`。分区行（记忆的 Topics、Timeline 等）沿用主侧栏的线框导航图标。

状态沿用 [surface-system.zh.md](../visual-system/surface-system.zh.md) 的列表行规则：悬停和键盘焦点用
`--bg-hover`；选中行用 `--bg-hover` 配 `--text-bright`；“添加…”行是 `quiet`（浅色文字）。
所有侧栏只有一种选中色。

## 收起

带 `railKey` 的侧栏可以像主侧栏一样收成图标列。页面顶栏在标题前显示它的 `RailToggle`
（`ManagePageHeader` 的 `railToggle`），按钮图标与下方各行图标在同一条竖线上。收起后，
搜索、分组标题、文字、尾部内容和嵌套行隐藏，每个顶层行变成 32px 方块，名称改由
`HoverTip` 显示。

展开状态按 key 存在 `localStorage["<railKey>NavOpen"]`（设置是 `settingsNavOpen`，另有
`projectsNavOpen`、`agentsNavOpen`）。没有保存过时，窗口窄于 760px 默认收起。窗口缩到
760px 以下会自动收起但不保存；窗口变宽不会自动展开。

| 页面 | 侧栏 | 可收起 |
|---|---|---|
| 历史 | 项目（`PROJECTS_RAIL`） | 是，按钮在历史页顶栏 |
| Agents | 带搜索的 Agent 列表，两行行；随完整编辑区出现（页面先显示卡片） | 是 |
| 设置 | 分类（`Link` 行） | 是 |
| 能力 → Programs | 目录树（`depth`） | 否；能力页顶栏属于四个标签共用 |
| 历史 → 项目 → 记忆 | 分区、主题树（文件夹、与文件夹不同时显示类型标签、日期）、时间线（年 › 月 › 日） | 否；它在项目页内部 |
| 独立的会话列表 | 带计数的时间筛选 | 否 |

没有列表列的页面（调度、应用，以及能力页的 Plugins、Skills、MCP）用页面顶栏的标签和
`ManageSubnav`。

## 按钮

页面外壳只用 Nova `ui/button` 的变体，不在页面里覆盖样式：

| 角色 | 变体 |
|---|---|
| 页面的主操作（新建、添加、安装、打开） | `default` |
| 次要操作（更新、重试、记忆设置） | `outline` |
| 行内图标操作（暂停、删除），经 `ManageIconButton` | `ghost`、`icon-xs`，带 `HoverTip` |
| 移除类操作（卸载） | `destructive` |

纯图标按钮用 `aria-label` 命名并显示 `HoverTip`，不用原生 `title`。页面菜单（Agent
操作菜单）用 `ui/dropdown-menu`，样式来自 `menu-styles.ts`。

## 守护

`apps/web/scripts/ui/check-secondary-rail.mjs`（由 `npm run check` 运行）在以下情况
失败：侧栏页面不再使用 `SecondaryRail`；页面样式表重新定义自己的侧栏行；可收起侧栏与顶栏
按钮使用不同的 key。
