# Program 模型

Agent 能用的一切都是 **Program**。本文说明 Program 是什么、Program 的两种类型、每个 Program 和插件都经过的那一个注册接口、插件指什么、条目如何暴露给模型、用户的 Program 放在哪里，以及管理它们的 CLI。

## 1. Program 与目录

所有 Program 都在 `openprogram/programs/` 下：

```
openprogram/programs/
  tools/            随核心发布的 Program；始终交给 Agent
  applications/     用户逐个启用的 Program；可以带 UI
  _authoring/       Program 代码导入的东西：错误、JSON 解析、报告、
                    工具辅助、提供方注册表、guides、prechecks 与应用客户端
  _host/            宿主怎样加载和运行 Program：
    runtime.py        `@function` 装饰器与共享工具注册表
    context.py        ProgramContext，注册接口
    services.py       Program 与插件共享的命名服务
    registry.py       加载每个 Program 并保存它的 ProgramContext
    packages.py       Python Program 包：条目注册、用户的包
    sources.py        harness 清单与所有者登记的程序来源
    check.py          `openprogram programs check`
    ui/               应用加载器、目录、UI 与操作运行时
```

Program 通过 `PROGRAM_ENTRIES`（可选 `ENTRY_OPTIONS`）公开可调用的条目；每个条目在共享注册表 `programs/_host/runtime.py` 里成为一个工具。没列出的普通函数不会登记。

## 2. 两种类型：tools 与 applications

类型由 Program 怎样到达 Agent 决定，而不是由它的大小决定。

| | `tools/` | `applications/` |
|---|---|---|
| 来源 | 随核心发布 | 随核心发布，或由用户安装 |
| 交给 Agent | 默认，始终 | 仅在启用时 |
| 能否单独禁用 | 不能 | 能，逐个禁用 |
| UI | 没有 | 可以带，显示在 App 窗口里 |
| `setup(ctx)` | 没有 | 可选 |
| 条目暴露 | 常驻（冷门的延迟） | 延迟；应用在窗口里打开时常驻 |

一个 Program 放进 `tools/` 的条件是：没有它 Agent 就失去一项基本能力（读文件、执行命令、询问用户、规划），并且它不需要自己的界面。工具可以是单个模块，也可以是一个包。其余都是应用：浏览器、用户工作流、已安装应用和外部 harness。

内置 Program 按这条规则摆放：

| 位置 | 内容 |
|---|---|
| `tools/interaction/ask_user.py` | `ask_user`：运行中的 Program 向用户提问并等待回答所用的库 |
| `tools/planning/goal/` | 聊天 Goal：`create_goal` / `get_goal` / `update_goal` 工具和 `goal` Program |
| `applications/browser/` | 浏览器应用（`web_use`） |
| `applications/workflow_recording/` | 演示录制器（没有入口；提供服务 `workflow_recording`） |
| `applications/office_editor/` | Office 编辑器应用（没有 Agent 入口；文档窗口的 Office 路由经 `office_editor` 服务访问它） |
| `_authoring/` | `errors`、`json_parsing` 和 `reports`，内置和用户 Program 都以 `openprogram.programs._authoring.<module>` 导入 |

大多数工具在导入 `openprogram.programs.tools` 时用 `@function` 注册。同时列出 `PROGRAM_ENTRIES` 的工具包登记在 `registry.TOOL_PROGRAMS` 里（目前只有 `goal`），这些条目经它自己的 context 注册。

工具至少有一个 Agent 可调用的条目；没有条目的工具不算工具。应用可以一个条目都没有：只有 UI 的应用也是完整的应用。

### 应用包

应用取下面任一形式，也可以在同一个目录里两者兼有：

- Python 包：`__init__.py`，带 `PROGRAM_ENTRIES`、`ENTRY_OPTIONS` 和可选的 `setup(ctx)`；
- 声明式包：`application.json`、它的 UI（`index.html` 或 `ui/`）和可选的 Python 后端（`backend.py`），后端的操作在清单里声明。

加载器（`programs/_host/ui/loader.py`）用同一个函数 `mount(ctx, root)` 经应用的 context 挂载声明式包，不论它是 `programs/applications/<name>/` 下的内置应用（清单 id 就是目录名），还是用户安装的应用。挂载读取清单，计算目录的内容摘要，并注册三样东西：

- 提供的 UI，按这个摘要从应用自己的目录读取；
- 资源提供者 `application.<id>`；
- 每个标了 `agent: true` 的操作一个条目，名为 `<id>__<operation>`，`[A-Za-z0-9_-]` 以外的字符都换成 `_`（模型 API 的工具名不接受点号）。条目把操作输入作为 `input`（项目级应用另有 `project_id`），经 worker 的应用服务运行操作——每个操作一个进程，按清单做能力检查——并返回结束的运行。条目是延迟加载的，需要审批，也不在 `DEFAULT_TOOLS` 里。标了 `agent: false` 的操作没有条目。

已安装的应用在 `~/.openprogram/programs/catalog.json` 里按源目录登记；不复制任何东西。已安装的应用在 worker 里加载：启动时、安装、启用和禁用之后，以及 Programs watcher 发现源目录变化时。禁用一个应用会释放它的 context，UI、提供者和条目随之移除；源目录变了，就先释放，再用新的摘要重新加载。

内置应用以同样的方式启用和禁用。它的设置是 `catalog.json` 里的一行 `builtin-application`（`{"id": "browser", "enabled": false}`），由 `catalog.builtin_enabled` 读取；`registry.sync_builtin_application` 让应用与设置一致：禁用时释放它的 context（条目、UI、资源提供者、服务、提示词段落），启用时经一个新的 context 重新加载。注册表每次加载 Program 都会同步所有内置应用，所以设置在每个进程里、跨 worker 重启都有效；owner API 的 `PATCH /api/applications/<id>` 把它应用到正在运行的 worker。启用后回来的条目就是原来那个已注册的工具，带着原来的 toolset 和层级。工具不能禁用。

## 3. ProgramContext

`ProgramContext`（`openprogram/programs/_host/context.py`）是宿主唯一的注册接口。每个应用包和每个插件各得到一个 context。经它做的每次注册都记下自己的撤销，`ctx.dispose()` 按从新到旧的顺序执行这些撤销，宿主因此回到这个包加载之前的状态。

context 写进宿主本来就用的各类注册表；没有按包类型另设的注册表：

| 方法 | 注册内容 |
|---|---|
| `ctx.tool(fn)` / `ctx.tools_from(module)` | `PROGRAM_ENTRIES` 作为工具，归属 `ctx.owner` |
| `ctx.on` / `ctx.gate` / `ctx.transform` | 事件总线订阅 |
| `ctx.context(name, build, ...)` | 一个名为 `<owner>:<name>` 的上下文段落：在系统提示词里（`L0`、`L1`），或在一次调用的 prompt 里（`L2`） |
| `ctx.provide` / `ctx.service` | `programs/_host/services.py` 里的命名服务，列出时提供者是 `ctx.owner`；核心用 `services.lookup(name)` 访问应用提供的服务，没有时得到 `None` |
| `ctx.resource(provider)` | 供 `resource` 工具使用的资源提供者；`application.<id>` 只留给应用 `<id>` |
| `ctx.command`、`ctx.skills`、`ctx.mcp_server`、`ctx.provider_root`、`ctx.api_provider` | 斜杠命令、技能根目录、MCP server、provider 目录、模型协议实现 |
| `ctx.effect(dispose)` | 其它任何东西，配上给定的撤销 |

`ctx.owner` 是记在每个工具上的归属（`_program_owner`）：`TOOL_PROGRAMS` 里的工具包是 `tool:<name>`，`programs/applications/` 下的内置应用是 `application:<name>`，用户 Program 是包名，外部 harness 是 `external:<package>`，插件是 `plugin:<name>`。`tool:` 和 `plugin:` 以外的归属都是应用，经它的 context 注册的条目一开始是延迟的（第 5 节）。

注册表（`programs/_host/registry.py`）保存一张 owner → `ProgramContext` 的表。加载一个包时首次用到才创建它的 context；再次加载同一个包会复用它，不会重复登记。卸载或热重载一个包（`programs/_host/watcher.py` 里的 watcher 在 Programs 目录变化时重新发现）调用 `dispose_program(owner)` 释放 context，重载随后经一个新的 context 注册。

示例，作为应用的 `setup`：

```python
def setup(ctx):
    @ctx.tool
    def word_count(text: str) -> int:
        '''Count the words in a text.'''
        return len(text.split())

    ctx.on("tool.after", lambda event: ctx.log.info(event.payload["tool"]))
```

## 4. 插件

**插件**只指 Claude Code、Codex、OpenCode 或 Hermes 格式的声明式包：由 manifest 描述的技能、斜杠命令、agents、hooks、MCP server 和 provider 目录。OpenProgram 兼容读取这些 manifest（`plugins/manifest.py`），并像挂载应用一样经一个 owner 为 `plugin:<name>` 的 `ProgramContext` 挂载它们的内容；hooks 是经 `ctx.gate` / `ctx.on` 订阅的 shell 命令。插件代码不会在 worker 里运行。manifest 里写了代码（`python`、`module`、`setup`、`main`、`tools`、`client`、`web`、`sidebar`、写成 `module:name` 的 hook 映射、Hermes 的 `__init__.py`）的，在安装和加载时都会被拒绝，提示把它打包成应用（带 `application.json`，用 `openprogram programs install <dir>` 安装）。添加工具或 UI 的代码是应用，不是插件。插件的生命周期见 [Plugin Runtime](../integrations/plugin-runtime.zh.md)。

## 5. 暴露层级

每个已注册的条目有一个暴露层级 `programs._host.runtime.Tier`，作为 `_tier` 记在工具上，用 `set_tier` 设置：

- **常驻（resident）**：schema 出现在每个 tools 数组里。
- **延迟（deferred）**：只列出名字；模型需要时用 `tool_search` 加载 schema。
- **隐藏（hidden）**：可从 Python 调用，从不展示给模型（`expose=False`）。

调用是否要等用户批准，是条目的审批策略（`requires_approval`，可以是参数的函数），作用在任何层级之上：`web_use` 是延迟的，也需要审批。

层级按类型分配：

- **工具**在 `RESIDENT_TOOLS` 里时常驻（默认集合去掉其中冷门、schema 大的成员，再加上 `tool_search` 和 `job_output`），否则延迟；工具也可以自己注册为延迟（`defer=True`）。
- **应用条目**是延迟的：内置和已安装的应用、外部 harness 以及用户的包。应用的 context 注册条目时由 `ProgramContext._adopt_tools` 设置层级，所以重载的包和新装的应用同样是延迟的。

应用在某个会话的窗口里打开期间，它的条目对这个会话常驻。信号是会话的应用绑定（`programs/_host/ui/bindings.py` 的 `resource_bindings` 表）：一次指明会话的 `open` 绑定这个应用的一个实例——App 的窗口经带 `session_id` 的 `POST /api/applications/<id>/open`，或 Agent 自己经 `application.<id>` 提供者的调用——`release` 或 `POST /api/applications/<id>/close` 解除它。每轮开始时 `TurnBindings` 读取 `open_application_ids(session_id)` 并安装（`_runtime.install_open_applications`）。`split_tools_for_dispatch` 和 `tool_search` 通过 `resident_now` 读层级：常驻条目、会话用 `tool_search` 加载过的延迟条目、归属 `application:<id>` 且该应用已打开的延迟条目进入 tools 数组。已注册的层级不会变；一次请求用的常驻副本是 `as_resident`。

`_defer` 镜像层级（恰好在延迟时为 `True`），供给 tools 数组计价和持久化的读者使用。`openprogram programs list` 和 `/api/plugins/inspect` 显示每个条目的层级。

## 6. 用户目录

用户的 Program 每个 profile 放在一个目录里：`~/.openprogram/programs/`（命名 profile 为 `~/.openprogram-<profile>/programs/`）。`openprogram/state/program_directory.py` 解析它，不导入注册表：

```
~/.openprogram/programs/
  <name>/          一个 Program 源目录
  catalog.json     按源目录登记的应用及其设置
  .runtime/        应用运行时保存的内容：data/、runs/、environments/、
                   staging/、state.sqlite，以及 versions/（旧安装复制的版本）
  .removed/        `openprogram programs uninstall` 移开的目录
```

Program 源目录是一个 Python 包（带 `PROGRAM_ENTRIES` 的 `__init__.py`）、一个应用目录（`application.json`、UI 和可选的 `backend.py`），或两者兼有。以 `.` 或 `_` 开头的名字、符号链接和普通文件不参与扫描。对该目录的一次扫描（`program_directory.program_dirs`）同时服务两个加载器：

- **包**经 `programs/_host/packages.py` 以目录名加载，目录名必须是 Python 标识符，且不遮蔽其他模块。每个包是独立的 Git 仓库；只有干净、已提交的检出才加载，所以 `openprogram programs check` 通过才让改动可调用。有未提交改动的包继续提供上次加载的版本。它的 context owner 是包名。
- **应用**在 worker 里经 `loader.mount` 加载。放进这里但没有目录记录的应用目录，会在下一次 `loader.sync` 时登记（`catalog.adopt_user_applications`）；需要信任的（Python 后端或 `files.project.write`）除外，它等待 `openprogram programs install <dir> --trust`。已卸载的记录不会被悄悄重新登记。

`catalog.json` 也登记源目录在别处的应用，例如仓库的 `examples/applications/`；它们从那个目录加载，并保留 `enabled`、`hidden` 和 `display_title` 设置。

从 git 安装的 harness 克隆（含 `<package>/agentics/__init__.py` 的仓库）也放在这里，并登记在 `program-sources.json`；它经外部 harness 路径加载，owner 为 `external:<package>`。包目录树里不放任何已安装的东西：旧安装器登记在 `openprogram/programs/packages/` 或 `openprogram/programs/applications/`（运行中的包，或登记为 `catalog_root` 的源码检出）下的克隆，由 `migrate_user_directory` 移到 `programs/<name>`，并改写它在 `program-sources.json` 的行和指向它的 `catalog.json` 行。

Programs watcher（`programs/_host/watcher.py`）对该目录顶层、每个包的文件与 Git 状态，以及目录文件和每个已启用应用的源目录取指纹；有变化就重新发现。

`.runtime/` 和 `.removed/` 下的文件不是 Program 源码：从那里发出的角色调用不带调用位置。

### 从旧布局迁移

早期的 profile 把包放在 `~/.openprogram/workflows/`，把目录文件和应用运行时放在 `~/.openprogram/applications/`。worker 启动时、任何内容加载之前，`program_directory.migrate_user_directory` 为正在启动的 profile 移动：

- `workflows/` 的每一项到 `programs/<项>`；
- `applications/catalog.json`（及其锁文件）到 `programs/`；
- `applications/` 下其他一切（`data/`、`runs/`、`environments/`、`staging/`、`versions/`、`state.sqlite`）到 `programs/.runtime/`。

每一项都是改名，从不复制；目标已存在的项留在原处并记日志。清空后的旧目录被删除。指向旧目录的目录文件记录（复制的版本、包内的应用）改写为新路径。每次移动记一行日志，第二次启动无事可做。没有设置项的键名包含这两个目录，所以设置不变。

## 7. CLI

`openprogram programs` 是管理 Program 的唯一命令组（`openprogram/interfaces/cli/commands/programs.py`）：

| 动词 | 作用 |
|---|---|
| `list [--json]` | 所有 Program：内置工具、内置应用、用户的包和应用、harness；每行带类型、owner、加载状态、目录、启用标志、条目和每个条目的层级 |
| `run NAME [--arg k=v]` | 在本进程调用一个 Program 条目 |
| `run APP OPERATION [--input JSON] [--project ID]` | 在 worker 里启动一个 Agent 可见的应用操作 |
| `status RUN_ID`、`cancel RUN_ID` | 查看或取消一次应用操作 |
| `check DIRECTORY [-m MSG] [--json]` | 校验包、在操作系统沙箱中运行测试并提交；校验应用目录 |
| `install SOURCE [--upgrade] [--replace] [--trust]` | 把本地应用目录登记进目录文件；把本地包仓库、git URL 或 `owner/repo` 克隆到 `~/.openprogram/programs/<name>` |
| `uninstall NAME` | 注销一个应用（保留数据），或把 `~/.openprogram/programs/` 下的目录移到 `.removed/` |
| `enable ID`、`disable ID` | 加载或移除应用（内置或已安装）的 UI、资源、服务和条目；工具会被拒绝 |

改变应用状态的动词经 worker 的 owner API（`/api/applications/*`）；`list` 和 `check` 不需要 worker。REPL 的 `/programs` 列出同样的行。

## 实现状态

1. **ProgramContext 落地。已完成。** `ProgramContext` 和服务注册表位于 `programs/_host/context.py` 与 `programs/_host/services.py`。每个内置 Program 包、每个用户工作流和每个外部 harness 都经自己的 context 注册，context 保存在注册表的 owner 表里；卸载和热重载释放 context。
2. **浏览器成为应用。已完成。** 浏览器位于 `programs/applications/browser/`；它的 `setup` 提供服务 `browser`，核心只经这个服务访问浏览器，没有它也能运行。旧的浏览器工具（`agent_browser`、`browser_agent`、`playwright_browser`）和 CLI 的 `/browser` 命令已删除；`web_use` 是应用唯一的入口。见[操控电脑与浏览器](../integrations/computer-and-browser-use.zh.md#浏览器应用)。
3. **UI 共用一个加载器。已完成。** 应用从自己的目录加载：目录文件记录源目录和设置，摘要在每次加载时计算。每个应用——内置或安装的、Python 或声明式的——都经一个 owner 为 `application:<id>` 的 `ProgramContext` 挂载，由它注册 UI、`application.<id>` 提供者和 `<id>__<operation>` 条目；禁用和重载会释放它。应用新增能力 `files.project.write`。旧安装复制的版本（现位于 `~/.openprogram/programs/.runtime/versions/`）只在应用源目录不存在时读取。
4. **workflow 层解散。已完成。** `programs/workflow/` 和导入路径 `openprogram.programs.workflow` 已不存在。`ask_user` 是 `tools/interaction/ask_user.py`，`goal` 是 `tools/planning/goal/`；编写辅助代码是 `programs/_authoring/errors.py`、`json_parsing.py` 和 `reports/`。工具名、工具集和选项不变，Programs 页面仍把这些 Program 列在 `workflow/` 下。用户工作流包从 `openprogram.programs._authoring.reports` 导入周报辅助代码。
5. **一个用户目录，一个 CLI 命令组。已完成。** 用户的包和应用共用 `~/.openprogram/programs/`（第 6 节），worker 启动时从 `workflows/` 和 `applications/` 迁移；`_workflow_packages.py` 和 `_workflow_check.py` 改为 `_host/packages.py` 和 `_host/check.py`。`openprogram programs` 是唯一的命令组（第 7 节）；`openprogram workflows`、`openprogram apps`、`programs apps`、`programs available` 以及 `gui` / `all` 安装选择器已删除。owner API 保留 `/api/applications/*` 路由，Programs 页面保留 `workflow/<name>` 浏览路径，Web 应用依赖它们。
6. **声明式插件与暴露层级。完成。** 插件只带声明式内容（第 4 节）；manifest 里写了代码的在安装和加载时被拒绝，pip 不再是插件来源，插件的 Web 模块、页面和侧边栏行都已移除。每个条目带一个层级（第 5 节）；应用条目是延迟的，应用在会话的窗口里打开时常驻。内置应用和已安装应用一样可以启用、禁用，`programs list` 显示层级和启用标志。
