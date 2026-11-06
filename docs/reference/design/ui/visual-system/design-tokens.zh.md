# 设计 token

Web 应用里所有的尺寸、形状和文字颜色都分档。组件只写档位名，不写具体数值。档位定义在 `apps/web/app/styles/design/`，每类数值一个文件；`npm run check`（`apps/web/scripts/ui/check-design-tokens.mjs`）遇到手写数值就让构建失败。这一页是地图：有哪些档位，哪个组件在哪一档。

```
apps/web/app/
  globals.css              入口：tailwindcss → design → themes → styles
  styles/
    design/                设计系统
      index.css            引入下面这些 token 文件
      layout.css           侧栏宽度、聊天列、拖拽表面
      controls.css         控件高度档位、列表行、按钮圆角
      composer.css         输入框自己的几何
      type.css             字号档位、字体栈
      shape.css            间距单位、圆角档位
      color.css            主色家族、四种文字颜色、固定界面颜色
      icons.css            图标尺寸档位
      motion.css           过渡时长档位、统一缓动
      layers.css           层级（z-index）
      shadcn.css           shadcn 的颜色名 → 应用的颜色角色
      tailwind.css         Tailwind 的扫描路径、变体和工具类名
    themes/                各主题的颜色取值，一个主题一个文件（含兜底）
    base/                  文档、焦点、列表行、外壳布局、滚动条、侧栏、
                           桌面窗口外框、动效
    chat/ right-dock/ dag/ 这些区域的全局样式
```

组件样式放在组件旁边（`*.module.css`），只读 token，不自带数值。

## 控件高度

所有像按钮的控件——按钮、输入框、下拉框、分段切换、列表行，以及样式表里手写的按钮——只用五档高度。高度是 `apps/web/app/styles/design/controls.css` 里的 px 变量：

```
档位       高度    变量                   Button 尺寸      字号
─────────────────────────────────────────────────────────────────────────────
内嵌       20 px   --ui-control-inline    —                —
行内       24 px   --ui-button-h-xs       xs · icon-xs     12 px
菜单       28 px   --ui-button-h-sm       sm · icon-sm     13 px
标准       30 px   --ui-button-h          default · icon   14 px
输入框     32 px   --ui-button-h-lg       lg · icon-lg     14 px
─────────────────────────────────────────────────────────────────────────────
```

`--ui-button-h` 就是 `--ui-list-h`：标准档等于侧栏会话行，普通按钮和那一行一样高。

各组件所在档位：

| 档位 | 组件 |
| --- | --- |
| 内嵌 20 | 画在别的控件里面的控件：中间标签页的 ×、图片标注的颜色块、Launchpad 卡片和新标签页快捷方式上的删除角标、图片小标签的移除、函数卡片的工具开关、用户气泡里的密文显示开关 |
| 行内 24 | 落在一行、一张卡片或一条消息上的操作：侧栏会话行的 ⋯、消息悬停操作（复制、重试……）、查找栏的上下箭头、地址栏的星标、diff 的整块操作和逐行评论、排队消息的操作、会话资源行操作、分支行操作、书签操作、附件移除和预览关闭、项目编辑里的移除、输入框上方小窗的关闭、分屏选择的关闭、思考强度里的快速开关、Mermaid 源码切换、DAG 缩放读数、Agent 目录的必填开关、设置和头像的颜色块、侧栏项目操作（置顶、新对话、选项）和刷新、最近会话筛选、Agents 视图菜单、技能目录的安装按钮、文件搜索的匹配方式切换、`ManageIconButton` 行操作和 `RailAction`、服务商账号行和模型行、应用行的 ⋯、Agent 卡片的菜单、图片附件上的标注按钮 |
| 菜单 28 | 菜单和弹层里的行（`itemCls`），以及工具栏、标签行里的紧凑控件：输入框下方的环境标签（Local、渠道、文件夹）和角落菜单按钮、麦克风和发送、顶栏标签和菜单触发器、中间标签页及标签栏的 + / 总览 / 菜单按钮、内置浏览器工具栏、下载和查找胶囊、终端操作、画中画标题栏按钮、Review 的菜单和翻页、DAG 工具栏、对话视图控制、函数卡片"使用"、Programs 和 Memory 的视图切换、文件面板和设置里的图标按钮、函数表单的标签；放在菜单或工具栏里的输入框：命令面板搜索、git 菜单输入框、书签标题、Launchpad 搜索、文件搜索选项、DAG 选择操作 |
| 标准 30 | 其余所有按钮、输入框、下拉框、分段切换和搜索框——页头、卡片、对话框（确认框的取消 / 确认）、设置行、Agents、Applications、Projects、文件夹选择器；侧栏行和侧栏图标按钮（`ui-list-item`）；PDF 工具栏；编辑消息的按钮 |
| 输入框 32 | 输入框四角按钮（`--composer-button-size`）、思考强度胶囊、函数表单的输入框，以及画布控件方块 |

不分档的，因为它们不是某一档的按钮：左下角账号行（64px）、Agents 设置宽度把手（20 × 44px）、中间标签页的选中态（28px 加 6px 底脚）、效果预览里画出来的标签栏、浏览器操作提示、文字标签、Switch 开关（Nova 原样的 32 × 18.4px 滑轨，本来就是 px）、开关的圆钮、图标本身的尺寸。`tests/ui/ui-kit-is-nova.test.mjs` 把它们列为豁免。

规则：

- Button 用 `size` 选档位，调用处不写高度类（`h-7`、`size-8`）。用样式类拼出来的控件写 `h-(--ui-button-h…)` / `size-(--ui-button-h…)`，不写 rem 高度（`h-8`）也不写 px 高度（`size-[22px]`）；Nova 测试会扫描所有 `.ts` / `.tsx` 文件。
- 样式表里手写的按钮，`height`（正方形时连同 `width`）写档位变量，不写 px 数字。Nova 测试会扫描所有样式表，像按钮的规则里出现 px 高度就失败。

## 字号

所有字号只用九档，相当于上面控件高度档位在文字上的对应。字号是
`apps/web/app/styles/design/type.css` 里的 px 变量：

```
档位      字号   行高   变量            Tailwind
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

各处文字在哪一档：

| 档位 | 文字 |
| --- | --- |
| 2xs 11 | 徽标里的计数和圆点、标签计数、PiP 里的按键提示、详情页的大写分组标题、DAG 节点和面板的元信息、上下文提交时间线的元信息、文件夹大小、附件条的大小行、输入框芯片的小提示、模型列表标签 |
| xs 12 | 行旁或行下的次要信息：时间、路径、计数、账号栏副标题；菜单分组标题、菜单说明和快捷键提示（`GROUP_LABEL`、`MENU_NOTE`、`SHORTCUT`）；表单项说明；xs（24px）按钮 |
| sm 13 | 描述和辅助说明、中间标签页、页面标签（`manage-page` 标签、项目标签）、Agent 卡片的文字和胶囊、sm（28px）按钮和分段切换、对话框里的设置标签 |
| base 14 | 正文；侧边栏和列表的行；菜单和 Select 的行（`itemCls`）；默认（30px）和 lg（32px）按钮、输入框、多行输入框、下拉框、分段切换；对话框描述；网格里的卡片标题 |
| chat 15 | 对话正文、输入框、嵌入的对话卡片、运行面板标题、Markdown 文件预览 |
| md 16 | 页面内的分区标题（设置卡片标题、"All chats"）、对话框标题、Markdown h3/h4 |
| title 18 | 页头的页面标题（`manage-page`）、详情面板的标题：设置详情、Programs 条目、Agent 编辑器、项目、记忆编辑器；Markdown h2 |
| lg 20 | 侧边栏字标、大数字（用量合计）、图形方块（项目图标）、效果预览、Markdown h1 |
| display 30 | Launchpad 文件夹标题 |

规则：

- CSS 写 `font-size: var(--fs-*)`，类名写 `text-fs-*`，内联样式写 `fontSize: "var(--fs-*)"`。不写 px 或 rem 字面值，不写任意值 `text-[…]`，也不写自带的 `text-xs` … `text-2xl`：它们曾经在这页是一个大小、下一页是另一个大小。`@theme` 仍把它们映射到 shadcn 文档站的含义（`text-sm` = 14px），让粘贴进来的 registry 代码显示正确，但源码里写档位名。
- 字重只有 400（正文）、500（标签、控件、行标题）、600（标题、强调）和 700（只用于对话正文里的标题）。

## 间距与圆角

Tailwind 的间距单位在所有页面上都是 4px（`p-2` = 8px，`gap-3` = 12px）。Tailwind 默认的 `0.25rem` 在应用 14px 的根字号下会落在半像素上（`p-3` = 10.5px），而文档站缩放的容器里又是 4px，同一个类名有两个大小。手写 CSS 尽量用这个单位的整数倍。

圆角只用七档（`shape.css`），CSS（`var(--radius-lg)`）和 Tailwind（`rounded-lg`）名字一样：

```
档位   大小   用在
─────────────────────────────────────────────────────────────────────
2xs     2 px  16 px  细条、进度轨道、光标、提示框的小箭头
xs      4 px  16 px  标签、键位、复选框、行内代码、徽标
sm      6 px  18 px  行内的芯片和小控件
md      8 px  24 px  所有尺寸的 Button、输入框、下拉框、手写按钮
lg     10 px  28 px  列表行、菜单、弹层、Select 弹层、卡片
xl     12 px  中间大卡片、分屏面板、页面面板、对话框
2xl    16 px  用户气泡、大块浮层
full          胶囊、头像、圆点（rounded-full、var(--radius-full)）
─────────────────────────────────────────────────────────────────────
```

`--ui-button-radius` 是 `md`，`--ui-list-radius` 是 `lg`，所以手写按钮和 `<Button>` 圆角一样。按盒子比例写的圆角（`50%`、圆角方块的 `26%`）和在档位上用 `calc()` 算出的同心圆角可以用；取自某个没有档位的表面的圆角，要在同一行用 `shape:` 注释说明（Launchpad 文件夹面板、编辑中的气泡）。

## 文字颜色

文字只用四种颜色（`color.css`），从强到弱：

| 颜色 | 文字 |
| --- | --- |
| `--text-bright` | 标题、悬停或选中的行、数值 |
| `--text-primary` | 正文、列表行、控件 |
| `--text-secondary` | 描述、辅助说明、未选中的标签、计数 |
| `--text-muted` | 元信息（时间、路径、占位符）、禁用文字 |

Tailwind 写 `text-text-bright` / `-primary` / `-secondary` / `-muted`。`components/ui` 里的 shadcn 组件保留 registry 的 `text-foreground` / `text-muted-foreground`，它们解析成同样的颜色；这个目录以外的应用代码不用这两个名字。主色（`--accent-*`、`--theme-accent`）只表示状态，不表示层级。

## 界面颜色

随主题变化的颜色在 `themes/`；所有主题都一样的颜色是 `color.css` 里 `:root` 上的具名 token。组件写 token 名，不写字面量。每个 token 保留组件原来写的确切取值，透明度和写法都不变；写成 `light-dark(a, b)` 的，跟随使用它的元素的 color-scheme。分组：

| 分组 | token | 使用者 |
| --- | --- | --- |
| 会话状态 | `--status-working` `--status-needs-input` `--status-failed` `--status-unread` `--status-refresh-done` | 侧栏的会话标记、刷新完成的闪色 |
| 权限档 | `--permission-deny` `--permission-ask` `--permission-allow` | 项目权限的圆点 |
| 错误文字 | `--error-form` `--error-message-edit` `--error-document` | 插件对话框、消息编辑器、文档窗口 |
| 目录按钮 | `--pill-warn` `--pill-danger` | 技能目录按钮的悬停色 |
| 提交时间线 | `--commit-state-*`（每种状态的 `-bg` 和文字色）、`--commit-error`、`--commit-anchor`、`--commit-refresh-done` | 上下文提交时间线 |
| ANSI | `--ansi-red` `--ansi-green` `--ansi-yellow` `--ansi-blue` `--ansi-magenta` `--ansi-cyan` | 程序的进度日志 |
| 色块上的文字 | `--ink-on-fill`、`--avatar-fallback-bg` | 彩色底上的文字（吸附标签、保存按钮、计数徽标、选中的自定义色井、字母头像） |
| Agent 光标 | `--agent-cursor-keyline` `--agent-cursor-shadow` `--agent-light-pulse` | Agent 光标和被控应用的窗口灯 |
| 浏览器 | `--browser-control-surface` `--browser-control-ink`、`--browser-pane-active` `--browser-pane-yielding`、`--browser-glyph-*` | 浏览器控制浮块、浏览器标签页的窗格描边和首页图标 |
| 画布控件 | `--pane-light-*`、`--pane-divider-*` | 窗格的窗口灯和分隔条 |
| 遮罩 | `--scrim-attachment-preview` | 放大的消息附件 |
| PDF 预览 | `--pdf-viewport-bg` `--pdf-thumb-shadow` `--pdf-thumb-current` | PDF 页面底色和缩略图 |
| GUI 工具 | `--gui-tool-rule` | GUI 工具活动卡片的发丝线 |
| 侧栏 | `--nav-toggle-press` `--nav-item-press` `--new-chat-chip` `--new-chat-chip-hover` `--wordmark-from` `--wordmark-to` | 按下的导航行、新对话圆钮、字标 |
| 服务商卡片 | `--provider-card-highlight` | 服务商的模型卡片 |
| 主题场景 | `--theme-scene-rain-*` `--theme-scene-gradient-*` | 设置里 Code rain 和 Gradient 的预览，Launchpad 背后的 Gradient 场景和它上面的玻璃控件 |
| Launchpad | `--launchpad-*` | 应用图标和打开的文件夹下的阴影、编辑模式的删除角标、Gradient 场景上的标签阴影 |
| 运行中光晕 | `--running-glow-blue` `--running-glow-violet` `--running-glow-green` | 侧栏里运行中对话那一行流动的光晕 |
| 分支泳道 | `--lane-0` … `--lane-17` | 对话图的线、节点和标签，Activity 面板的分支行，浏览器新标签页磁贴的首字母（`lib/format-utils/lane-colors.ts` 给出 `var(--lane-N)`） |
| 代码高亮 | `--hl-keyword` `--hl-string` `--hl-number` `--hl-comment` `--hl-title` `--hl-type` `--hl-attr` | 消息代码块里的 highlight.js 记号 |

`styles/tool-tones.css` 里的步骤色（`--tool-tone-*`、`--timeline-*`）是同一类 token，Running 面板的图标读它们。shadcn 的每个角色（`--ring`、`--border`、`--muted` 等）都是完整颜色，模块里直接写 `var(--ring)`；再包一层 `hsl()` 会解析无效、什么也不画。半透明写成 `color-mix(in srgb, var(--muted) 34%, transparent)`。

`var(--role, 字面量)` 的兜底：角色总有定义的（主题角色、`--accent`、`--destructive`、`--muted-foreground`），去掉用不到的字面量；没有任何主题定义的角色（`--danger`、`--warning`、`--success`、`--red`、`--orange`、`--status-error`、`--border-color`）一直画的就是字面量，整个换成存着这个字面量的 token。

## 图标

图标只有 12、14、16、20、24px 五档（`icons.css`）：

| 大小 | 用在 |
| --- | --- |
| 12 | xs（24px）控件里、11–12px 文字旁边 |
| 14 | sm（28px）控件里、菜单行、芯片 |
| 16 | 默认控件、工具栏、页面按钮 |
| 20 | 侧栏导航、空状态、方块、页头图形 |
| 24 | 空页面的主图形 |

`size` 为 28 及以上的是插图（头像、标志），不算图标。

## 动效

过渡写时长档位和统一缓动（`motion.css`）：
`transition: opacity var(--motion-medium) var(--ease-standard)`。

| 档位 | 值 | 用在 |
| --- | --- | --- |
| `--motion-fast` | 120ms | 悬停、按下、颜色和边框变化 |
| `--motion-medium` | 160ms | 展开、淡入淡出、小幅移动 |
| `--motion-slow` | 240ms | 面板、抽屉、大幅移动 |

`--ease-standard` 是唯一的缓动。循环动画（转圈、脉冲）和自己写 `cubic-bezier` 的弹性曲线保留原有时长。脚本等过渡结束时，等待时间不短于它等的那一档。

## 阴影

层次感用主题的阴影档位，组件里不写 `rgba`：`--shadow-sm`（卡片、小的凸起部件）、`--shadow`（凸起面板）、`--shadow-popover`（菜单、浮条、拖拽预览）、`--shadow-dialog`（对话框、整窗浮层），输入框和 elevated 按钮用 `--shadow-raised` / `--shadow-raised-hover`。内描边和焦点环属于边框，不算阴影，留在原处。

## 层级

需要叠在其他表面之上的元素写层级名（`layers.css`）；组件内部 1–12 的值保持局部。

| 层级 | 值 | 内容 |
| --- | --- | --- |
| `--z-sticky` | 20 | 面板内的吸顶标题 |
| `--z-floating` | 50 | 面板内浮动的小面板 |
| `--z-drawer` | 100 | 窄屏时盖在内容上的侧栏 |
| `--z-overlay` | 110 | 对话框背后的遮罩 |
| `--z-dialog` | 120 | Dialog、AlertDialog |
| `--z-popover` | 130 | Popover、DropdownMenu、ContextMenu、Select，高于对话框 |
| `--z-tooltip` | 140 | Tooltip |
| `--z-toast` | 300 | toast |
| `--z-fullscreen` | 10000 | 整窗编辑器和灯箱 |
| `--z-drag` | 100000 | 拖拽预览和拖拽表面 |

Tailwind 写 `z-(--z-popover)`；CSS 写 `z-index: var(--z-popover)`，紧贴某层之上的部件写 `calc(var(--z-drag) + 1)`。

## 三种写法各管什么

三种样式写法并存，各自只负责一件事。

| 写法 | 负责 | 不做 |
| --- | --- | --- |
| `components/ui` 里的 shadcn 部件 | 所有控件：按钮、输入框、选择器、菜单、弹窗、开关、复选框 | — |
| JSX 里的 Tailwind 类 | 布局和间距（flex、grid、gap、padding、尺寸）、简单状态 | 复杂选择器 |
| 组件旁边的 `*.module.css` | Tailwind 表达不了的：伪元素（项目引导线）、`data-*` 和父级选择器、关键帧、分层层叠 | 手搓控件、写死数值 |

模块里还剩大约 280 条只含布局属性的单类规则；其余的已经搬到 Tailwind，前提是搬动后界面上什么都不变。Tailwind 工具类在 `@layer utilities` 里，模块规则不在任何 layer 里，所以搬走的规则会输给同一元素上所有未分层的规则。因此以下几种情况规则留在模块里：类名在样式表前面已经出现过；元素是会合并自身类名的组件（`DialogContent` 会保留它的 `sm:max-w-*`）；元素上另一个模块类设置了相同属性；样式对象被重新导出或整体传递。它们在所属组件被修改时再迁移，检查保证这个数只减不增。

## 检查

`apps/web/scripts/ui/check-design-tokens.mjs`（`npm run check` 运行）扫描所有样式表和 `.ts` / `.tsx` 文件，拒绝：

- 不是 `--fs-*` 档位的字号、任意值 `text-[…]`、自带的 `text-xs` … `text-2xl`；手写的字体名、`font` 简写、强制 `tabular-nums`（字体和等宽数字归设置管）；
- 400 / 500 / 600 / 700 以外的字重；
- px 圆角、任意值 `rounded-[…]`、不带档位的 `rounded`、`rounded-3xl` 及以上、`--radius`，或不是档位的 `--radius-*` 名字；
- 已退役的颜色别名（`--text-tertiary`、`--text-dim`）、`text-[var(--text-*)]`，以及 `components/ui` 以外的 shadcn 颜色名；
- 小于 28 且不在档位里的图标 `size`；
- 定义颜色 token 的地方以外的颜色字面量（`#hex`、`rgb()`、`hsl()`）：只有 `app/styles/themes/`、`app/styles/design/` 和 `app/styles/` 里的自定义属性行可以写。组件写 token 名（见“界面颜色”）；
- CSS 模块里只含布局属性的规则多于 `apps/web/scripts/ui/module-layout-baseline.json` 给这个文件的数（新模块一条都不能有）。把这类规则搬到 Tailwind 之后，运行 `node scripts/ui/check-design-tokens.mjs --write-layout-baseline` 调低数字。

`apps/web/tests/ui/ui-kit-is-nova.test.mjs` 拒绝样式表和类名里写死的控件高度。

例外都点名，不会悄悄放过：只收像素的接口（xterm、Mermaid、canvas、Electron 视图）、Agent 卡片上 Framer Motion 需要的数字圆角、输入框（不动：它的圆角、字重和图标保持原样），以及注明了 `glyph:` 或 `shape:` 的行。属于数据或绘图、不是界面颜色的颜色字面量列在 `COLOUR_DATA` 里：用户挑的调色板和图表序列色、插画（Launchpad 应用图标和记忆图标、代码雨、搜索服务商图标）、收颜色字符串的接口（canvas、WebGL、xterm、Mermaid、pdf.js、web manifest），以及按 `hsl()` 计算的思考强度色阶。`mask:` 行也不查，它的颜色只决定遮罩形状。

哪一档都放不下的数值属于设计改动：先加档位（或在上面的表里加上这个组件），再去做。
