# 插件运行时

已启用插件的内容怎样在 worker 里挂载，以及它加进来的一切怎样被完整撤掉。manifest 形式、来源、marketplace 和信任级别见 [Skills & Plugins](skills-and-plugins.zh.md)；这份记录讲 enable 到 disable 之间发生的事。

插件是声明式的：一份 Claude Code、Codex、OpenCode 或 Hermes 格式的 manifest，列出技能、斜杠命令、agents、hooks、MCP server 和 provider 目录（见 [Program 模型](../function/program-model.zh.md)）。宿主自己经一个 `ProgramContext` 挂载这些内容；每次注册都是一个带 disposer 的 *effect*，dispose 这个 context 就把插件完整撤掉。不导入任何插件代码。没有单独的"插件专用注册表"：每个 effect 都写进宿主本来就用于这类东西的注册表。

## 1. 生命周期

```
rescan ──► Plugin(manifest, error=代码拒绝信息)   启用集合：~/.openprogram/plugins-enabled.json
load_plugin(name)
  _check：不含代码、trust、compatibility、requires（每个依赖先加载）
  _activate：
     ProgramContext(name, root, options)          owner 为 plugin:<name>
     manifest 键 ──► ctx effects（skills、commands、hooks、mcpServers、providers、agents）
     任何异常   ──► ctx.dispose()，错误留在插件上
  发出 plugin.enable，广播 plugins:changed
unload_plugin(name)
  发出 plugin.disable ──► ctx.dispose()（effects 逆序执行）
reload_plugin(name) = unload + rescan + load   （新文件失败时插件保持启用）
```

- **启动。** `openprogram/interfaces/server/server.py` 在 MCP server 启动之后运行 `_load_plugins`：把事件循环交给 `programs._host.context.set_host_loop`，在线程里调用 `loader.load_enabled()`，按依赖顺序加载启用集合，逐个记录失败，不让一个失败阻断其它。
- **rescan 保留运行中的插件。** rescan 发现已加载插件的 root 没变时保留它的 context；root 变了就先停用。
- **来源。** npm（`~/.openprogram/plugins/node_modules/`）、path（`~/.openprogram/plugins/<name>`）和项目 pin；同名时后者胜出。`install path <dir>` 把 `~/.openprogram/plugins/<name>` 链接到这个目录，改动在 reload 后生效，uninstall 只删链接。

## 2. 代码会被拒绝

`plugins/manifest.py` 把每种形式都解析成一个 `PluginManifest`，并在 `code` 里记下写了代码的键：`python`、`module`、`setup`、`main`、`tools`、`client`、`web`、`sidebar`、形如 `module:name` 的 `hooks` 值，以及 Hermes `plugin.yaml` 旁边的 `__init__.py`。`code_refusal(manifest)` 把它们变成一条信息，列出这些键，并提示加一个 `application.json`、运行 `openprogram programs install <dir>`。每个入口都执行这个拒绝：

- `installer.install` 拒绝 manifest 写了代码的 `path` 安装，删掉 git 克隆，卸载 npm 包；`pip` 不是插件来源。
- `rescan` 把这样的插件和拒绝信息一起列为错误；`_check` 和 `_activate` 抛出 `PluginContainsCode`（一个 `PermissionError`），toggle 路由以 `403` 和 `code: "contains_code"` 回答。

## 3. context

`openprogram/programs/_host/context.py` 定义 `ProgramContext`，即每个 Program 和插件共用的注册接口。插件 loader 用到这些 effect：

| manifest 键 | effect | 宿主注册表 | 撤销 |
|---|---|---|---|
| `skills` | `ctx.skills(dir)` | `skills` 的插件来源 | 注销该来源 |
| `commands` | `ctx.command(name, prompt, description)` | `contrib["_commands"]`，由 commands 注册表的适配器读取 | 随 contributions 清除 |
| `hooks` | 带 shell gate 或 notifier 的 `ctx.gate` / `ctx.on` | `EventBus.subscribe_gate` / `subscribe` | 订阅的 disposer |
| `mcpServers` | `ctx.mcp_server(name, config)` | `mcp` manager 的 `add_server`，名为 `<plugin>_<name>`，调度到宿主 loop；从不写入 `mcp_servers.json` | `remove_server` |
| `providers` | `ctx.provider_root(dir)` | `providers/catalog/plugin_dirs.py`，即 `provider.json` 查找背后的搜索路径 | 移除该 root |
| `agents` | `manager.create` | Agent 注册表 | 无（见下） |

`ctx.dispose()` 逆序执行 disposer，收集错误而不中途停下，并清空 `ctx.contributions`——插件页和 `plugin` 工具显示的按类记录。

manifest 声明的 agents 在缺失时创建为 `<plugin>-<name>`，停用时**不**删除：删 agent 会删掉它的会话。随包发布的 provider 目录与插件的同名时，以随包发布的为准。

## 4. Hooks

`plugins/hooks.py` 读取 `hooks` 的值（内联或来自 JSON 文件），接受 OpenProgram 的形状（`{event: [{command, timeout}]}`，与 `config.json` 的 `hooks` 键相同）和 Claude Code 的形状（`{hooks: {PreToolUse: [{matcher, hooks: [{type: "command", command}]}]}}`）。`CLAUDE_EVENTS` 把 `PreToolUse`、`PostToolUse`、`UserPromptSubmit`、`Stop`、`SessionStart` 映射到 `tool.before`、`tool.after`、`chat.before_send`、`turn.stop`、`session.start`；`${CLAUDE_PLUGIN_ROOT}` 换成插件目录；`matcher` 是对事件 `tool` 的正则表达式。每条命令由 `events/shell_hooks.py` 包装（事件以 JSON 写入 stdin；gate 事件上退出码 2 表示拒绝，stderr 作为理由，其他退出码放行），经插件的 context 订阅。未知事件、非 command 类型的 hook 和 transform 事件会被跳过。

## 5. 事件：notify、gate、transform

`events/registry.py` 给每个事件一个类型：

- **notify**：观察者；返回值被忽略。
- **gate**：可以否决（`tool.before`、`turn.stop`）。
- **transform**：每个改写者收到 `(event, value)` 并返回新值；返回 `None` 保留原值，抛异常的改写者被跳过。

`tool.result` 是 transform 事件。`agent_loop._rewrite_tool_result` 拼接结果的文本块，发出 transform，用改写后的字符串替换文本，图片和音频保持不变。应用用 `ctx.transform` 订阅它；shell hook——因而插件——不能订阅。

## 6. Web

插件不带 UI：服务端没有插件 Web 模块、页面或侧栏条目的路由，Web 外壳也没有给它们的插槽。插件页列出声明式插件及其贡献；`plugins:changed` 帧刷新这个列表。自带界面属于应用的 `application.json` UI。

## 7. 自描述与 agent 工具

`openprogram/extensions/plugins/inspect.py` 从运行中的注册表构建 `describe()`：插件可用的 manifest 键、被拒绝的键、每个事件及其类型和能否挂 hook、Claude Code 事件映射、暴露层级，以及每个已注册条目的 owner、层级和审批标志。`guide()` 是同样内容的文本形式。它们支撑 `GET /api/plugins/inspect`、`openprogram plugins inspect [--json]` 和 `plugin` 工具。

`plugin` 工具（`programs/tools/runtime/plugin.py`）让 agent 不改源码就能扩展 OpenProgram：`guide`、`inspect`、`list`、`install`（链接、信任为 community、启用）、`enable`、`disable`、`reload`、`uninstall`。它在 worker 进程里运行（`_run_in_worker`），注册落进运行中的注册表；需要审批，聊天渠道和 plan 模式里不可用。写了代码的插件会以同样的信息被拒绝。

CLI 的 `enable`、`disable`、`install`、`uninstall` 和 `reload` 先调用运行中 worker 的 HTTP API，变更立即生效；没有 worker 时退回到直接修改状态文件。

## 实现状态

按上文实现。未实现：manifest 没写明时自动发现 Claude Code 的默认目录（`commands/`、`agents/`、`skills/`、`hooks/hooks.json`）、Claude Code 的 `prompt` 类型 hook，以及 `lspServers` / `outputStyles`——它们被解析但忽略。
