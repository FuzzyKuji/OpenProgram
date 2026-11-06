# 图标体系

Web 端用三族图标。每一族有自己的地盘，一个界面里不会无意间把实心图标和线性图标并排放在一起。

| 族 | 地盘 | 包 / 来源 | 许可 |
|---|---|---|---|
| **Solar**（Bold Duotone） | 输入框区域：环境条 chip、控制行及其 + 菜单、模型 / 权限徽章、思考力度 pill、提问 / 审批面板、发送箭头；以及聊天执行时间线每一行左侧的图标方块；还有 DAG 画布的看图控件和窗格右上角那一条（视图切换、会话操作） | `apps/web/components/solar-icons`——图标主体由 `apps/web/scripts/icons/fetch-solar.mjs` 从 Iconify 的 `solar` 集合取回，落在 `bodies.ts` | CC BY 4.0，Solar Icons by 480 Design |
| **pqoqubbw 动效线性图标** | 输入框以外的外壳：左侧 rail、中央标签页、侧栏、设置导航、功能卡片 | `apps/web/components/animated-icons` | MIT |
| **lucide-react** | 其余不需要动效的地方：设置正文、对话框、时间线行尾的展开箭头 | `lucide-react` | ISC |

供应商 logo 来自 LobeHub（`components/settings/providers/icons/lobe-icons.ts`），用户头像来自 DiceBear，Agent 的头像是一个角色（见 [Agent 头像](agent-avatars.zh.md)）；它们都不在本约定之内。

没有人手画图标 SVG。要加一个 Solar 图标，就在 `fetch-solar.mjs` 的 `ICONS` 里加一项再跑一遍；生成文件提交进仓库，构建不依赖网络。

## 输入框区域用 Solar

在输入框 14–16px 的尺寸下，双色图标看起来像是为这个功能专门设计的，线性图标则显得通用。所有 Solar 图标统一用 Bold Duotone 一种样式：实心主体 + 浅一档（50% 透明）的副层。

| 位置 | Solar 图标 |
|---|---|
| `+` 选项触发 | `tuning-2` |
| 添加文件 | `paperclip` |
| 工具 | `case-minimalistic` |
| 工具配置 | `settings-minimalistic` |
| 网页搜索 | `global` |
| 沙箱 | `box-minimalistic` |
| 无人值守 关 / 开 | `eye` / `eye-closed` |
| 思考力度 | `fire` |
| Chat 模型徽章 | 模型所用厂商的 logo（与设置里厂商列表同一套），因为 logo 满版绘制，按 Solar 图标的有效区画到盒子的 20/24；没有 logo 的厂商用 `cpu` |
| Agent 徽章 | Agent 的[头像](agent-avatars.zh.md)，不是图标 |
| 高速模式 | 思考力度按钮的 `fire` 变红 |
| 权限徽章 | `shield-check` |
| Local 连接 chip | `monitor` |
| 网页标签 chip | `earth` |
| 画中画 chip | `pip-2` |
| 工作目录 / 添加目录 | `folder-with-files` / `add-folder` |
| 项目 chip / 项目目录丢失 | `folder-open` / `danger-triangle` |
| 菜单勾选 | `check-circle` |
| 关闭 × | `close-circle` |
| 展开箭头 | `alt-arrow-right`、`alt-arrow-down` |
| 发送 | `plain-2`（纸飞机） |
| 复制 | `copy` |
| 模型能力（视觉 / 视频 / 工具 / 推理） | `eye` / `videocamera` / `case-minimalistic` / `lightbulb-bolt`；公文包用 12px 而不是 14px，因为它的图形占满整格、眼睛和摄像机留有边距，12px 时三者上下边才对齐 |
| Git 胶囊 / 其菜单：新建分支或 worktree、worktree、PR、查看 PR | `git-branch` / `add-circle`、`folder-path-connect`、`git-pull-request`、`square-arrow-right-up` |
| 文件修改卡片：标题 / 文件行 | `pen-new-square` / `file-text` |
| 文件修改卡片：撤回 / Review 按钮 | Font Awesome `rotate-left` / `eye`（实心），图标 + 文字 |

Solar 的撤回图标都是细线箭头，在按钮尺寸下几乎看不见，所以文件卡片的两个操作按钮改用 Font Awesome 的实心图标，由同一个脚本取回、放进同一张表（viewBox 记在 `SOLAR_VIEWBOXES`）。

反映开关的图标随状态换形，而不只靠颜色：无人值守开启后眼睛闭上；运行中模式"注入"是前进箭头、"排队"是队列列表；项目目录丢失时项目 chip 变成警告三角。

输入框区域有两个**不是** Solar 的图标。思考力度卡片里的高速（Fast）开关保留动效集里的仪表盘，由 `active` 属性转动指针；思考力度按钮本身只把 `fire` 图标变红来表示高速。思考力度卡片里的 `?` 帮助按钮（[effort-picker.zh.html](../composer/effort-picker.zh.html)）是 14px 的 lucide `CircleHelp`：Solar 尚未取回问号图标，而且这个按钮是静态的，不需要动效句柄。二者均见文末实现状态。

## 执行时间线用 Solar

展开后的执行时间线，每一行以一个 24px 的着色方块开头（嵌套时 20px），里面是 13px 的图标（嵌套时 11px）。图标用 Solar Bold Duotone，所以各行显示为色调色的扁平实心标记，而不是线稿。`apps/web/components/chat/messages/execution/tool-presentation.ts` 里的 `presentTool()` 按工具选图（`ToolPresentation.icon`，类型为 `SolarIconName`）；没有工具图标时，`execution-strip.tsx` 的 `StepRow` 按行类别兜底。方块本身和色调配色不随图标族改变。

| 行 | Solar 图标 |
|---|---|
| 命令（`bash`、`write_stdin`、`terminal_use`） | `programming` |
| 执行代码 | `code-square` |
| 修改 / 写入 / 补丁 | `pen-new-square` |
| 读取文件 / PDF | `file-text` |
| 列出目录 | `folder-open` |
| 查找文件（`glob`） | `file-search` |
| 搜索（`grep`、代码搜索） | `magnifier` |
| 代码分析（LSP） | `structure` |
| 网页搜索 / 抓取 | `global` |
| 浏览器操作 | `cursor` |
| 生成图片 / 分析图片 | `gallery-add` / `gallery` |
| 画布、发送文件、给代理发消息 | `plain-2` |
| 子代理类工具 | `ghost` |
| 读取对话 | `book` |
| 向用户提问 | `chat-round-question-mark` |
| 规划模式 | `map` |
| 定时任务 | `calendar` |
| 运行程序 | `box` |
| 使用技能 | `stars` |
| 资源、记忆 | `database` |
| 待办 | `checklist` |
| 工作树 | `git-branch` |
| 自我更新 | `refresh` |
| MCP | `plug-circle` |
| 其他函数 | `sledgehammer` |
| 按行类别兜底：思考 / LLM / 子代理 / 函数 | `lightbulb-bolt` / `cpu` / `ghost` / `sledgehammer` |

Solar 没有扳手，通用函数行用锤子（sledgehammer）作为工具标记；思考行兜底复用 `lightbulb-bolt`，与模型选择器里表示推理能力的图标相同。失败行保留小号描边 ✗，摘要后的展开箭头仍是 lucide `ChevronRight`，二者都不是类型图标。

时间线图标是静态的（`motionPreset="none"`）：行头不是按钮，点击只负责展开 / 收起。图标不带任何悬停提示，因为对话内容不加 tooltip。

## 动效约定

三族图标都讲同一套命令式句柄 `AnimatedNavIconHandle`（`startAnimation` / `stopAnimation`）：容器——按钮、菜单行、chip——才是悬停目标，图标自己 16px 的命中区从不单独动。父级挂上 ref 就接管驱动；没有 ref 的 Solar 图标跟随最近的可点击祖先（按钮、链接、各类菜单项、列表选项、chip）的悬停，所以不论有没有接 ref，每个按钮的表现都一样。选择器、放大倍数和弹簧参数在 `components/ui/hover-pop.ts`，Agent 角色也用它（见 [Agent 头像](agent-avatars.zh.md)），所以角色和旁边的图标一样放大；纯展示的图标——菜单勾、警告三角、模型能力标记——用 `none`。

pqoqubbw 图标会自己重绘（扳手转一下、箭头跳一下）。实心的 Solar 图标做不到，所以 `SolarIcon` 提供几种克制而统一的预设：`pop`（放大到 1.12，默认）、`fly`（发送纸飞机向右上飞 1.5px）、`nudge`（箭头右移 1.5px）、`pulse`（一次性弹入，用于菜单项变为勾选时）和 `none`。`prefers-reduced-motion` 下全部不动。

`SolarIcon` 在 `<svg>` 外包一层 `span.inline-flex`，与动效图标的包裹层同构，容器里按"装着 svg 的那个元素"去定尺寸或隐藏的 CSS 继续有效。

## 署名

Solar Icons © 480 Design，CC BY 4.0（<https://github.com/480-Design/Solar-Icon-Set>）。两个 Font Awesome 图标来自 Font Awesome Free，© Fonticons，CC BY 4.0（<https://fontawesome.com/license/free>）。声明放在 `bodies.ts` 文件头和本页；面向用户的致谢条目尚未添加（见下）。

## 实现状态

- 输入框区域换成 Solar，含环境条 chip、+ 菜单、提问 / 审批面板，以及经 `components/chat/top-bar` 共用的模型 / 权限徽章：**已实现**。
- 执行时间线行图标换成 Solar（按工具选图，以及思考 / LLM / 子代理 / 函数兜底）：**已实现**。
- 高速开关改为状态驱动的仪表盘（关时指针停在低速区，开时甩到高速区并变成强调红）：**未实现**——目前仍是动效集的仪表盘加静态 `active` 旋转。
- 思考力度卡片的帮助图标换成 Solar `question-circle`（经 `fetch-solar.mjs` 取回）：**未实现**——暂用 lucide `CircleHelp`。
- 面向用户的 Solar 第三方致谢（CC BY）：**未实现**。
- rail、标签页、侧栏、设置仍用动效线性集，不计划迁移。
