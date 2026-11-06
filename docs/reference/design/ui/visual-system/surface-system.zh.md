# 表面系统

UI 分为两个**表面上下文**。每个表面有各自的交互语言，眼睛能一眼分清当前停在哪一层：导航层还是内容层。这些规则同时约束**浅色和深色**主题。浅色主题最容易踩坑（浅灰侧栏上铺白底）。

## 两个表面

```
─────────────────────────────────────────────────────────────────
surface        background tone           where it lives
─────────────────────────────────────────────────────────────────
deep           `--bg-secondary`          三栏背后的页面（`.app`）
─────────────────────────────────────────────────────────────────
panel          浮起的卡片：               左右两条侧栏（`--bg-input`，
               `--bg-input`（侧栏）、     和输入框同一种材质）和中间
               `--bg-primary`（中栏）     一栏（`--bg-primary`：聊天
                                         流、设置页和其他所有页面）
─────────────────────────────────────────────────────────────────
```

整个窗口是一张页面上的三张浮起卡片——左右栏用 shadcn Sidebar 的 `floating` 壳（`components/ui/sidebar.tsx`，只取注册表的壳），中栏同时用它 `inset` 的思路。每张卡片用 Nova 浮动 Sidebar 的圆角（`rounded-lg`，12px；分屏格子和画布总览用同一个 `--radius-lg`）、每套主题自己的浮起阴影（`--composer-shadow`），无边框、无描边；侧栏四周各留 7px（`p-2`），中栏上下各离边 7px，左右的缝由侧栏的留白提供。侧栏用白色（`--bg-input`），和输入框、用户气泡同一种材质；中栏保持 `--bg-primary`，这样白色的浮起元素在它上面仍有对比。

分屏时中栏这张卡片消失，每个窗格各自是一张同材质的卡片（`.center-col[data-split]`）：每个窗格离侧栏卡片和窗口边缘 7px，窗格之间相隔 8px。空窗格自己画同样的卡片。

收起时一条侧栏宽 `--rail-collapsed-w`（63px：卡片里 49px 的图标轨加两侧留白），`components/layout/use-resizable-rail.ts` 用同一个数。卡片里的东西——行、分组标题、页脚——不受壳子影响，继续用下面的配方。

## 各表面的交互语言

鼠标点按钮不画外圈焦点环。键盘聚焦普通按钮只轻微提高亮度，不用 outline 或 box-shadow。顶部 `role="tab"` 是唯一例外：用当前主题的 `--focus-ring`，深色更亮，浅色更深。

### Deep 表面（侧边栏）

deep 表面上的组件是**列表行**——会话项、分支、收藏，以及内容区里同一套行（MCP 的 `drawio` / `linear` / `+ Add server`）。它们不应当表现得像按钮：

- 闲置：无边框、无描边、无填充
- 悬停 / 选中：背景换成**看得出的灰色**（``--bg-hover`` / ``--bg-selected``），文字仍是 ``--text-primary`` 或 ``--text-secondary``
- 选中行**禁止**用 ``--bg-input`` 填充。侧栏卡片本身就是这个白，白行铺上去会消失
- 不用品牌色字形，唯一例外是极小的状态点（``.indicator-dot``）

理由：侧栏密、扫得勤。一片品牌色胶囊会吵，还会跟内容列抢视线。悬停变灰让这一层安静，点击目标仍有反馈。

### Panel 表面（聊天内容 + 对话框）

panel 表面上的组件就是按钮 / 胶囊 / 卡片：

- 坐在抬升背景上，"幽灵描边"能干净地呈现
- 闲置：``--bg-surface`` 底，``--text-primary`` 字，主操作用品牌色字
- 悬停：品牌色填充，字切到对比色（``--text-on-accent``）
- 这种反转式悬停让一串操作读起来是同一家人

管理页顶部的 **tab 胶囊**（Abilities / Programs / Plugins / Skills）是唯一的亮底例外：选中态用 ``--bg-input``，跟搜索框一样偏亮，而不是更深。这个填充**只给这些胶囊**。不要抄到侧栏行或 MCP 服务器行上。

## 列表行只有一套尺寸

侧栏导航（`+ New chat`、Agents、Abilities、History、Scheduler）和内容区列表行（MCP 的 `drawio` / `linear` / `+ Add server`）共用**同一只盒子**。不要给右边那列另起一套高度、内边距、圆角或选中底。

```
属性         token / 值
─────────────────────────────────────────────────────────────────
高度         `--ui-list-h` → 30px
内边距       6px 8px
间距         12px
圆角         `--ui-list-radius`（10px）
闲置         透明；需要时用 1px 透明边只为对齐盒模型
悬停         `--bg-hover`
选中         `--bg-hover`（同一灰，绝不用白 / `--bg-input`）
```

`+ Add server` 跟 `+ New chat` 是同一种行：普通列表行，字略淡。不要斜体，不要另做一种"添加"样式。

实现：`apps/web/app/styles/base/list-row.css` 的 `.ui-list-item` 是唯一来源。页面的列表列（历史项目、Agents、Programs 树、设置）通过 `RailItem` 使用它，见 [secondary-rail.zh.md](../sidebar/secondary-rail.zh.md)。MCP 的 `.serverItem` 必须对齐这些数（优先 compose `.ui-list-item`，不要平行再写一套）。

## 按钮

控件高度、字号、圆角、文字颜色和图标尺寸都分档；哪个组件用哪一档，见[设计 token](design-tokens.zh.md)。

按钮是 shadcn/ui 的 `Button`，**radix-nova** 风格，也就是 ui.shadcn.com 文档站自己用的风格。`apps/web/components/ui/button.tsx` 从官方组件仓库复制（`/r/styles/radix-nova/button.json`），本地改了 import、一层给 React 18 用的 `forwardRef`、上面这几档写死成 px 的尺寸，以及应用自己的外观：所有按钮同一个形状——各尺寸都是 `rounded-md`（8px）圆角、无边框、用 composer 阴影对浮起；作用只靠颜色区分（见下文的按钮变体说明）。

不能做成 `<Button>` 的元素（自带 ✕ 的 span、渲染成 span 的 Radix 触发器）在 `className` 上用 `cn(buttonVariants({ variant, size }))` 拿同一套外观——`cn()` 合并不能省：原始类名里同时有 `border-transparent` 和变体自己的边框色。几何不能随 Button 改样式而变的组件（输入框里的语音和发送按钮）尺寸取自己的变量，只从变体取颜色（见"输入框区域的控件"）。

页头那一行（搜索 + tab 胶囊 + 图标按钮）必须同一垂直中线。同一行的控件之间差 1–2px 高度是 bug，不是变体。

## 下拉选择与菜单

所有"从固定列表里选一个"都是 shadcn **radix-nova** 的 `Select`（`apps/web/components/ui/select.tsx`）；应用里没有原生 `<select>`，也没有手写的 listbox。`SimpleSelect` 是一行写法（`value`、`onValueChange`、`options`，可选 `label`、`placeholder`、`size`），覆盖几乎所有调用处；分组选项传 `{label, options}`。

- 触发器：registry 原样的 Nova 触发器——普通的带边框输入框（`rounded-lg`、`border-input`、`bg-transparent`、`dark:bg-input/30`，默认 `h-8` / `sm` 为 `h-7`）。`SimpleSelect` 默认 `w-full max-w-48`；调用处只加宽度或错误边框，不另做外观。
- 弹层：实色 `bg-popover`，外框用菜单的 `--popover-ring` / `--popover-shadow`（见下），registry 原样的 `item-aligned` 定位——直接盖住触发器展开，当前选中项落在原触发器的位置；叠在对话框之上（`z-[130]`）。第一行是弱化色的分组标题，写明在选什么（取 `label`，没有就取 `aria-label`）；分组选项每组一个标题。选中项右侧是普通对勾。
- Radix 把 `""` 留给"未选择"：值为 `""` 的选项在 `SimpleSelect` 内部换成哨兵值传递；没有这种选项时，`""` 显示占位文字。

其余所有菜单弹层——Radix `DropdownMenu`、各种弹出选择器、侧栏底部菜单、标签页右键菜单、函数右键菜单——共用一个外框和一种行，都取自 `apps/web/components/chat/top-bar/menu-styles.ts` 里的 `MENU_PANEL`、`itemCls`、`GROUP_LABEL` 和 `MENU_SEPARATOR`。用 CSS module 写的菜单在 module 里只留位置（定位、层级、宽度），外框和行直接用这些类，不再自己抄一遍数值。

从小按钮或右键打开的操作菜单，每一行都用 `MenuRow`（`apps/web/components/ui/menu-parts.tsx`）搭，页面内和桌面覆盖层一样。一行从左到右：

```
[图标] 标签 ············ [按键] [勾选] [›]
```

- **图标**：Solar Bold Duotone 图标（`MenuIcon`，16px，弱化色），和侧栏文件夹同一系列。文件夹行用 `--folder-color` 画文件夹；危险操作的图标是红色。
- **按键**：价签形状的按键标签（`MenuKey`），按平台写法显示。标签由两块拼成：固定 10px 宽的尖头，取自 Solar `tag-horizontal` 图标圆滑的右端，翻转成朝左；后面接 shadcn 的 `Kbd` 作为底板，高 18px，接尖头的一侧是直角，右侧 5px 圆角，左右内边距 1px / 6px，文字区最小 8px。所以单个字母的标签宽度一致，按键更长时只拉长底板。两块都用 `--menu-key-bg` 上色：平时是 12% 墨色叠在弹层上，比菜单高一级（深色主题里 `--muted` 比菜单还暗，所以不用它）；行点亮时提到 22%，比行的 9% 悬停底色高一级，文字变亮。按键文字由 `formatMenuKeys` 生成：macOS 上是 `⌘T`、`⇧⌘C`，其他系统是 `Ctrl+T`、`Ctrl+Shift+C`。菜单只显示已经能用的按键：真正的快捷键，或菜单打开时响应的单个字母（对话菜单的 R/P/C/A/D）。不为了填标签去新增全局快捷键。
- **勾选**：`MenuCheck` 放在行尾；可勾选分组里没勾的行留空这一列（`CHECK_SLOT_PAD`）。
- **子菜单**：行尾一个右箭头；子菜单可以任意层级嵌套。
- **点亮的行**：鼠标悬停、键盘高亮、子菜单展开或当前行时，整行一起亮起，不只是文字：弱化色的图标、按键标签和箭头变亮，图标像输入框下方的图标一样放大到 1.12。带颜色的图标（文件夹、危险操作）保持原色，只放大。

桌面覆盖层以数据形式拿到同样的字段：`DesktopContextMenuItem` 带 `glyph` 和 `keys`，覆盖层页面用同一套部件渲染。`scripts/ui/check-menu-rows.mjs` 检查每个菜单文件都用这种行。

外框是 `app/globals.css` 里的两个变量，菜单、Select 弹层、`Popover`、命令面板和网页预览小窗共用。浅色主题下它就是文件卡片的外框：`--popover-ring` 透明（不画发丝线），`--popover-shadow` 是卡片平时的阴影 `--composer-shadow`，`--popover-shadow-hover` 是它较深的那档 `--composer-shadow-focus`：鼠标移到弹层上时阴影加深，和卡片一样。深色主题把弹层抬亮一档，保留浅色发丝线和柔和的深阴影，因为那里弹层和下面卡片的底色相同；悬停阴影和平时相同。

```
部分        Nova，文档站尺寸
─────────────────────────────────────────────────────────────────
面板        rounded-lg · p-1 · min-w-32 ·
            实色 bg-popover · --popover-ring · --popover-shadow
行          min-h-7（28px）· rounded-md · px-1.5 py-1 ·
            text-sm（14px）· gap-1.5 · size-4 图标，不左移
悬停        bg-accent（墨色 9%）· text-bright
分组标题    px-1.5 py-1 · text-xs · font-medium · 弱化色
分隔线      -mx-1 my-1 · 1px · --border
快捷键      价签（MenuKey：Solar 尖头 + Kbd）· text-[11px] · 弱化色
选中        强调色对勾（MenuCheck）放在行尾，不铺底色
─────────────────────────────────────────────────────────────────
```

菜单、Select 弹层和对话框是同一种表面：同样的实色弹层、同样的 `--accent` 悬停底色。`app/globals.css` 把 `--accent` 定义为墨色 9%，所以在每套主题里都看得出鼠标停在哪一行。`--popover` 取 `--bg-input`：浅色主题里是白色，深色主题里比页面高一级。只有强调色对勾是应用自己的。

## 输入框与边框

输入框共用**一层 1px** 边（`border: 1px solid var(--border)`，底 `--bg-input`）。

- 不要在这 1px 边上再叠 2px 的 `:focus-visible` 光晕，叠出来就是双层框。
- 悬停必须**保住**这 1px 边。`border-color: transparent` 会让框像消失了一样（MCP catalog 按钮踩过）。
- 不要每个页面另做一套输入框。设置、对话框、插件、MCP 编辑器都用同一套 1px + `--bg-input`。

## 对话框

所有模态框都是 radix-nova 的 `Dialog`（`components/ui/dialog.tsx`）或 `AlertDialog`（`components/ui/alert-dialog.tsx`），从 registry 原样复制。没有手写的遮罩层，也没有浏览器的 `confirm()`。

```
部分        Nova，文档站尺寸
─────────────────────────────────────────────────────────────────
遮罩        bg-black/10 · backdrop-blur-xs · z-[110] ·
            data-native-view-occluder（原生网页视图让开）
内容        rounded-xl · bg-popover · ring-1 ring-foreground/10 ·
            p-4 · gap-4 · max-w-sm · z-[120]
标题        text-base · font-medium
说明        text-sm · 弱化色
底栏        -mx-4 -mb-4 · border-t · bg-muted/50 · p-4 ·
            按钮靠右，取消在前
关闭        ghost icon-sm Button，top-2 right-2（仅 Dialog）
动效        100ms 淡入 + zoom-in-95；不滑动
─────────────────────────────────────────────────────────────────
```

- 所有"确定吗？"都走 `ConfirmDialog`（`components/ui/confirm-dialog.tsx`）：标题、可选说明、`elevated` 的取消，以及确认按钮——一般是 `default`，删除或降低安全保护时（删除聊天、绕过权限）用 `destructive`。按 Esc、点框外、点取消都是取消。命令式调用写 `await confirmAction({...})`，由 `app/providers.tsx` 里唯一的 `<ConfirmDialogHost />` 渲染。
- 表单和多操作的对话框用 `Dialog`，配 `DialogHeader` 和 `DialogFooter`。底栏只放 `Button`：取消 / 关闭用 `elevated`，主操作用 `default`。
- 加在 `DialogContent` 上的 module 类只管尺寸（宽度、`max-width: none`、最大高度、滚动），不重写表面：不写背景、边框、圆角、内边距、阴影。
- 内容铺满边缘的对话框（源码查看、函数运行、Provider 设置）传 `p-0 gap-0`，自己给标题栏和正文加内边距，并给 `DialogFooter` 加 `m-0`。

## 设置行

设置页由 `apps/web/components/settings/settings-ui.tsx` 里的三个积木搭成，只用官方组件（Card、Field）：

- `SettingsPage`——页面标题和说明，下面是可滚动的正文。
- `SettingsSection`——带标题的一组设置，放在一张 `Card` 上，行之间用细线分开。
- `SettingsRow`——一项设置，是横向的 `Field`：左边名称和说明，右边控件（单独一个 Select 宽 12rem）。`stacked` 把宽控件（编辑器、网格、列表）放到名称下面。

里面的控件都是官方组件：`Switch`、`Input`、`Textarea`、`Slider`、`RadioGroup`（选择卡片）、`ToggleGroup`、`Checkbox`、`Button`、`SimpleSelect`。每个设置页不再带自己的行、标签或卡片 CSS。

历史页项目的「设置」「信息」标签也用这三个积木，看起来和设置页一样。项目的四个标签（会话、记忆、设置、信息）用同一套布局：项目标题和标签栏固定，下面的面板铺满剩余空间、左右贴边，每个标签在面板里自己滚动（设置和信息左右留 24px，和会话工具栏对齐）。会话标签按时间分组，每组一张带标题的 `Card`，行之间用细线分隔。每个分组标题都可以折叠：今天、最近 7 天和最新的一组默认展开，更早的月份和年份默认折叠，每组的展开状态记在当前浏览器里。展开的分组先列 8 个会话，再显示"显示全部 N 个"（不超过 10 个的分组直接全部列出）；工具栏有一个按钮可以一次展开或折叠所有分组，搜索时所有分组自动展开。由 `scripts/projects/check-project-tabs.mjs`（`npm run check` 运行）守护。

## 按钮变体指南

所有按钮只有一种外形：各尺寸都是 `rounded-md`（8px）圆角、无边框，用每套主题的 composer 阴影对浮在页面上（`shadow-raised`，悬停加深为 `shadow-raised-hover`，声明在 `app/globals.css` 的 `@theme`）。按钮做什么只靠颜色区分。不提供 Nova 带边框的 `outline` 和平面的 `secondary`：带边框的按钮放在浮起的按钮旁边，看起来像两套组件。

```
变体          外观                                   悬停
─────────────────────────────────────────────────────────────────
default      bg-primary，shadow-raised             primary/90，阴影加深
elevated     --bg-input 底，shadow-raised           阴影加深
destructive  bg-destructive/10，shadow-raised      destructive/20，阴影加深
ghost        透明，无阴影                            bg-muted（深色 /50）
link         primary 色文字                         下划线
─────────────────────────────────────────────────────────────────
```

所有变体按下时下沉 1px，键盘聚焦时显示 3px 的 `ring/50` 光圈，禁用时降到 50% 不透明度。`elevated` 按钮处于按下、勾选或开启状态（`aria-pressed`、`aria-checked`、`data-state=on`）时带一圈 1.5px 的 `primary` 描边，一组浮起的选项里能看出选中的是哪个。`Toggle` / `ToggleGroup` 的 `elevated` 变体是同一种浮起外观。

按位置挑：

- 一块区域的**主操作**（运行、保存、测试、应用、发送、新建…）→ `default`，每块区域一个。
- **其他所有操作**、筛选和选项（取消、关闭、重置、浏览、编辑、重启、输入框下方的模型 / 思考档位 / 权限触发器、环境标签）→ `elevated`。
- **破坏性操作**（删除、移除、停止、清空历史）→ `destructive`。
- 平时应当隐形、悬停才出现的**纯图标工具**（关闭、更多、重命名）→ `ghost`。
- **深层表面——侧栏行**→ 不用 Button 组件，用 `.ui-list-item` / `nav-classes.ts`。

## 输入框区域的控件

聊天输入框用的是同一套零件：

- 输入框上方的**环境标签**（渠道、网页、项目、工作目录、DAG 浮层按钮）→ `elevated` `sm`；添加目录按钮是 `elevated` `icon-sm`。
- **底部控制栏**（权限、聊天模型、Agent、思考档位、加号、工具开关、上下文圆环）→ `elevated`，`sm` / `icon-sm`。输入框的 CSS 用 `revert-layer` 把旧的基础规则让回给 Button，不再自己画一套标签。
  底部控制栏没有固定高度，跟按钮一样高；它离输入框 10px，和上方环境标签离输入框的距离相同。
- **上下两排的图标**统一 16px，和文字间距 5px、上下居中，文字一律 13px。Button 的尺寸会把未指定大小的 svg 压成 12.25px，所以两排各自的模块 CSS 在层外设定尺寸和间距；从控制栏打开的思考力度卡片保留自己的尺寸。
- **发送和语音按钮** → 颜色取 Button 的变体（发送：有内容可发时 `default`，空输入时 `ghost`，停止运行时 `destructive`；语音：`ghost`）。尺寸和位置不取 Button 的尺寸类，而取 `app/styles/design/composer.css` 里输入框自己的变量：`--composer-action-size`（28px），在最后一行 `--composer-line-h`（46px）里居中，离边 `--composer-action-inset`。文字两侧留白、附件列、录音电平条都由同一组变量算出，所以改 Button 样式不会把它们挤歪。语音按钮的悬停底色是 `--composer-action-hover`，因为 ghost 的底色（`--muted`）和输入框本身同色。
- **输入框本体** → 每套主题的 `--composer-*` 变量：`--bg-input` 底色、无边框，平时 `shadow-sm`，鼠标悬停或聚焦时 `shadow-md`（阴影透明度浅色主题 0.1、深色 0.25），不加聚焦光环；圆角 `--radius-lg`，和周围按钮同一种圆角矩形。

## 网页预览与浏览器工具栏

聊天上方的网页预览小窗（`components/center-tabs/pip/web-tab-pip.tsx`）是一张 popover 卡片：`bg-popover`，外框用菜单的 `--popover-ring` / `--popover-shadow`，四角 10px 圆角，标题栏下方的舞台用同样的底部圆角裁切网页。圆角跟原生网页视图的圆角（`apps/desktop/main/web-views/web-views.js`）绑定——原生表面不受 DOM 裁切，外框圆角更大就会在底部两角漏出网页像素，所以两者要一起改，或者都不改。32px 标题栏放标题（`text-sm font-medium text-foreground`）、状态（`text-xs text-muted-foreground`）和 `ghost` `icon-sm` 图标按钮（图标 14px），悬停提示用 `HoverTip` + `TipBody`（见 [hover-tips.zh.md](../composer/hover-tips.zh.md)）；恢复失败的提示是一行 `text-xs text-destructive`，不加框。CSS module 只管几何（位置、尺寸、拖动光标、调整把手），因为不分层的 module 规则会压过工具类。

浏览器工具栏的图标按钮（后退 / 前进 / 重新加载 / 主页 / 书签 / 书签库 / 在浏览器中打开 / 菜单，以及控制条）通过 `webToolbarButton()`（`components/center-tabs/browser/toolbar/toolbar-button.ts`）用同一个 `ghost` Button：取 `icon-sm` 是为了它的 14px 图标规则，由只剩几何的 `.webToolbarBtn` 固定在工具栏自己的 26px，保住 40px 一行的节奏。

## 禁止事项

- 不要每个页面另起一套悬停 / 选中 / 边框。一套配方，反复用。新样子先写进这份文件。
- 不要在未先于此处列出的情况下引入新的胶囊底色。预算内：deep 灰悬停、panel、品牌填充，以及上面的页头 tab `--bg-input` 例外。
- 不要在 deep 表面用品牌色填充。
- 不要用白色 / `--bg-input` 做侧栏或内容区**列表行**的选中底。浅色主题会发白。
- 不要给 MCP 服务器行（或任何内容区列表）另一套高度、内边距或选中底。
- 不要加悬停位移（translate-y、scale-105）。悬停只换背景；唯一的动效是 Button 自带的按下 1px。
- 不要在调用处改 `components/ui/button.tsx` 的样式类，不要给某个按钮单独的圆角、边框或阴影，也不要在 CSS 里再写一份仿 Button 的样式。挑一个 `variant` / `size`；旧规则还压着 Button 时，删掉它或用 `revert-layer` 让回去。
- 不要在 1px 输入/下拉边上再叠 2px 聚焦光晕。
- 不要在悬停时丢掉控件的 1px 边。
- 不要让对话框滑动；只淡入并从 95% 放大。
- 不要让设置说明伸进右侧控件列，也不要把标签堆在控件上面。

## 实现状态

- 已完成：`Button`、`Select`、`Input`、`Textarea`、`Switch`、`Slider`、`Card`、`Badge`、`Label`、`Separator`（radix-nova，包括替换所有原生 `<select>` 和自制下拉），以及 `Checkbox`、`RadioGroup`、`Field`、`Toggle`、`ToggleGroup`；菜单面板和菜单行（Nova 几何和材质）；设置的通用页和桌面提醒一节换成设置积木；输入框上方的环境标签、底部控制栏、发送和语音按钮、输入框本体、网页预览小窗（外框、标题栏、图标按钮）、浏览器工具栏的图标按钮。
- 已完成：所有模态框换成 `Dialog` / `AlertDialog`，所有确认换成 `ConfirmDialog`（原来的 `window.confirm`、删除聊天和绕过权限的确认、插件、频道、分支合并、图标选择、函数和 Provider 设置面板）。附件灯箱保留自己的全屏查看器。
- 已完成：`components/ui` 里的每个部件都是 radix-nova——命令面板（`Command` 放在 Nova `Dialog` 里，选中行和菜单一样用 `bg-accent`）、`Popover`（Nova 表面，外框用菜单的 `--popover-ring` / `--popover-shadow`；`bg-transparent` 的内容自己承载 `MENU_PANEL`）、`Tooltip`（Nova 带箭头的反色小标签；`--surface-tooltip` / `--text-on-tooltip` 指向 `--foreground` / `--background`，手动定位的侧栏提示也一致）、`Tabs`（Agent 编辑页用 `line` 变体）、`Kbd`、`ScrollArea` 和 `Sidebar` 外壳。
- 尚未迁移：其余设置页（仍用 `settings-page.module.css` 的行）。设置页以外的表单输入框在换成 shadcn input 之前继续遵守上面的 1px 边规则。侧栏列表行继续用上面的列表尺寸。
