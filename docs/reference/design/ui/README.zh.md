<div id="web-ui"></div>

# 网页界面

OpenProgram 只有一套工作区界面。它是 React + Next.js 应用（`apps/web/`），预先构建好，由 Python worker 在和 API 同一个端口上提供，所以同一套页面可以在浏览器标签页、桌面 App 和远程服务器上运行。桌面 App（`apps/desktop/`）是包着这些页面的 Electron 外壳，支持 macOS 和 Windows；在 Linux 和服务器上，用浏览器打开 Web UI。

目前工作区的布局：

- **侧栏与页面。** 主侧栏列出项目和对话，并打开 Agents、能力（Programs、技能、插件、MCP）、应用、历史和定时任务；设置在用户菜单里。各列表页共用一列次级栏。
- **中间标签页。** 中间区域放对话、文件、终端和网页的标签页。一个标签页可以分成并排的窗格，标签页和分组可以在桌面窗口之间移动。
- **对话记录。** 一轮对话显示模型的回复，工具调用折叠成摘要行，另有文件修改摘要、子代理行和等你处理的请求；在你向上滚动之前，记录会跟随新输出。
- **输入框。** 输入框承载附件、模型与思考力度选择、每个目录的 git 胶囊和选项菜单；本地文件路径会原样进入模型上下文。
- **一套视觉体系。** 颜色、尺寸和形状来自设计 token 与主题；图标、指示点和悬停提示各自遵守一套规则。

下面的文档是这些界面各自的设计：

- [`invariants.md`](invariants.zh.md) — 跨模块 UI 不变量清单（改相关模块前先过一遍）
- [`chat-transcript-follow.html`](chat/chat-transcript-follow.zh.html) — 统一的转录跟随：发送、流式、跳到最新、会话切换与历史窗口共用一套附着/脱离策略
- [`chat-turn-visual-spec.html`](chat/chat-turn-visual-spec.zh.html) — 聊天轮次视觉规范（执行时间线、文件修改摘要表面、手动函数运行和消息导航）；文件历史语义见[运行时权威设计](../runtime/operations/file-management.zh.html)
- [`tool-group-summary.html`](chat/tool-group-summary.zh.html) — 折叠工具调用行的标题：摘要语法、+N −M 改动徽标、进行时文案，以及整轮摘要的取舍
- [`activity-panel.md`](chat/activity-panel.zh.md) — 右侧栏 Activity：以子代理为行、列出具体待处理事项、每行一个页面
- [`sub-agent-row.md`](chat/sub-agent-row.zh.md) — 派生子代理唯一的步骤行：状态、展开后它自己的对话、带 `job_id` 的帧和分支记录加载
- [`interaction-feedback.md`](interaction-feedback.zh.md) — 交互反馈 0ms 规则（乐观状态先行，数据后补）
- [`turn-occupancy.md`](turn-lifecycle/turn-occupancy.zh.md) — 停止、发送队列与 session 槽位占用（在取消意图上释放）
- [`state-layer.md`](state-layer.zh.md) — Web 状态层：每个会话一个 store 实例，真正共享的数据留全局
- [`center-tabs-and-split-layout.html`](workspace/center-tabs-and-split-layout.zh.html) — 普通 tab 与复合分屏 tab 的生命周期、显示、持久化和跨窗口转移权威设计
- [`built-in-browser.html`](browser/built-in-browser.zh.html) — 内置浏览器主页、浏览器 profile 导入、紧凑 History 与四入口新建 pane
- [`browser-extensions.html`](browser/browser-extensions.zh.html) — 不支持 Chrome/Edge 扩展安装与管理的产品决策、保留的浏览器能力，以及旧扩展数据不执行也不自动删除的边界
- [`integrated-terminal.html`](workspace/integrated-terminal.zh.html) — 真实 PTY 终端与本机 Claude Code 直接启动入口
- [`composer-local-attachment-paths.html`](composer/composer-local-attachment-paths.zh.html) — Composer 到模型上下文的本地附件路径保留规则
- [`composer-responsive-controls.html`](composer/composer-responsive-controls.zh.html) — Composer 响应式控件及紧凑状态交互契约
- [`composer-options-menu.html`](composer/composer-options-menu.zh.html) — 共享菜单文法上的选项（+）菜单；工具由 Agent 决定，不在菜单里开关
- [`effort-picker.html`](composer/effort-picker.zh.html) — 思考力度卡片：标题行的淡紫档位名与 `?` 帮助提示、中性刻度滑轨与最高档动态方格、滑块上的档位提示、"推荐"标注
- [`programs-source-categories.html`](programs/programs-source-categories.zh.html) — Programs 分组与来源分类行为
- [`composer-interaction-modes.md`](composer/composer-interaction-modes.zh.md) — Composer 交互模式
- [`attachment-handling.zh.html`](chat/attachment-handling.zh.html) — 完整附件设计：存储、执行准入、内容交付、恢复与验收
- [`chat-attachments.html`](chat/chat-attachments.zh.html) — 聊天附件双向流转：聊天流里显示成什么、agent 怎么把文件交回来、可读文件怎么点开
- [`resource-preview.html`](resources/resource-preview.zh.html) — Resources 列表、聊天操作预览与人类接管 Agent 操作的 Page
- [`agent-control-overlay.html`](browser/agent-control-overlay.zh.html) — agent 控制窗口或网页时画在上方的状态胶囊和指针：位置、文案、动效、强调色与输入安全
- [`indicator-dots.md`](visual-system/indicator-dots.zh.md) — 指示点
- [`agent-avatars.md`](visual-system/agent-avatars.zh.md) — Agent 头像：Agent 的角色形象、存储与推导、出现的位置、来源与许可
- [`git-folder-pills.md`](composer/git-folder-pills.zh.md) — 输入框里每个目录的 git 胶囊：分支、修改计数、切分支、worktree、PR
- [`hover-tips.md`](composer/hover-tips.zh.md) — 输入框区域悬停提示：统一的 `HoverTip` + `TipBody`，标题带当前值，浅色细节行
- [`icons.md`](visual-system/icons.zh.md) — 图标体系：哪一族用在哪里（输入框区域 Solar、外壳动效线性图标、其余 lucide）、动效约定、署名
- [`design-tokens.md`](visual-system/design-tokens.zh.md) — 设计 token：所有尺寸、形状和颜色的档位，以及各组件用哪一档
- [`surface-system.md`](visual-system/surface-system.zh.md) — Surface 系统
- [`theme-system.html`](visual-system/theme-system.zh.html) — 主题入口、完整 token 契约、组件消费与桌面浮层传播的权威设计
- [`secondary-rail.md`](sidebar/secondary-rail.zh.md) — 主侧栏与页面内容之间的那一列列表（历史项目、Agents、Programs 树、设置）：统一的行、收起、按钮分级
- [`settings-collapsible-columns.html`](settings/settings-collapsible-columns.zh.html) — 应用主侧栏与 Settings 分类栏的独立 49px 折叠；Provider 列表始终展开，搜索框通栏
- [`avatar-randomization.html`](settings/avatar-randomization.zh.html) — 用户头像选择器：先选类型，再进入同风格变体或字母字段
- [`web-styles.md`](visual-system/web-styles.zh.md) — Web 样式组织（一个组件一个文件，目录对齐组件树）
- [`window-state.md`](desktop/window-state.zh.md) — 桌面窗口普通尺寸、最大化/全屏与标题栏缩放命中
- [`window-lifecycle.md`](desktop/window-lifecycle.zh.md) — 一个主窗口：启动、Dock、二次启动共用同一次创建
- [`window-tab-transfer.md`](desktop/window-tab-transfer.zh.md) — 把标签页、分组成员或整个分组移到另一个窗口或拖出的新窗口：一次事务、同一个活网页、日志与回滚
