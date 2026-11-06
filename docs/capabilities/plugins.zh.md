<div id="plugins"></div>

# 插件

插件是声明式的包：一份 manifest，列出 skills、斜杠命令、agents、hooks、MCP server 和模型 provider 目录，格式就是 Claude Code、Codex、OpenCode 或 Hermes 已经在用的那几种。OpenProgram 读取 manifest，自己把这些内容挂上去；插件代码不会在 OpenProgram 里运行。添加工具或自带界面的代码是[应用](applications.zh.md)，不是插件。这一页讲插件怎么装、怎么管，以及插件里可以放什么。

## 安装与管理

```bash
openprogram plugins list                 # 已安装插件
openprogram plugins search <query>       # 在配置的 marketplace 里搜索
openprogram plugins install git <url> --ref v1.2   # 来源三选一：npm / git / path
openprogram plugins install npm <package>
openprogram plugins install path /abs/path/to/plugin
openprogram plugins update --all         # 重装升级 npm 来源的插件（也可以只传一个名字）
openprogram plugins enable <name>
openprogram plugins disable <name>
openprogram plugins reload <name>         # 改完文件后重新读取 manifest 和文件
openprogram plugins uninstall <name>       # 链接进来的本地插件只删链接
openprogram plugins inspect               # 插件可以包含什么，以及每个条目的暴露层级
```

git 克隆落在 `~/.openprogram/plugins/` 下，npm 包在其 `node_modules/` 里，本地路径以链接形式放在这里，改动在 `reload` 后生效。信任等级（`verified` / `community` / `untrusted`，未登记的插件默认 `untrusted`，本地 `path` 安装记为 `community`）持久化在 `~/.openprogram/plugin-trust.json`；hooks 和 MCP server 会执行命令，所以 `untrusted` 的插件不会被启用。Web UI 通过插件路由暴露同一套管理 API。

## 插件可以包含什么

一个目录，带下面某一种 manifest，按顺序解析：

1. `.claude-plugin/plugin.json`（Claude Code）、`.codex-plugin/plugin.json`（Codex）或根目录的 `plugin.json`
2. `pyproject.toml` 里的 `[tool.openprogram.plugin]`
3. `package.json` 的 `openprogram`、`opencode` 或 `hermes` 字段
4. `plugin.yaml` / `plugin.yml`（Hermes）

manifest 字段有 `name`、`version`、`description`、`trust`、`entrypoints`、`options` 和 `requires`；各贡献键也可以像 Claude Code 那样写在顶层。`requires` 声明插件之间的依赖：loader 按拓扑顺序启用，缺依赖时报 `missing dependencies: ...`。

| 键 | 内容 |
|---|---|
| `skills` | 一个放 `SKILL.md` skills 的目录 |
| `commands` | 斜杠命令：`{name: {description, prompt}}`，或一个放带 front matter 的 `.md` 文件的目录 |
| `agents` | `{name, description, prompt, tools}` 列表，或一个放 `.md` agent 的目录；创建为 `<plugin>-<name>`，停用插件时保留，因为删除 agent 会删掉它的会话 |
| `hooks` | 在事件上运行的 shell 命令，内联或写成 `.json` 路径（见下） |
| `mcpServers` | 内联 `{name: {command, args, env} \| {url}}`，或一个 `.mcp.json` 路径；插件启用期间一直运行 |
| `providers` | 一个目录，每个子目录放一个 `provider.json` |

插件添加的一切都经由一个 owner 为 `plugin:<name>` 的 context 挂载；`disable` 和 `reload` 会把它们全部移除。

### Hooks

`hooks` 接受两种形状。一种是 OpenProgram 自己的，与 `config.json` 的 `hooks` 键相同：

```json
{"tool.before": [{"command": "${CLAUDE_PLUGIN_ROOT}/check.sh", "timeout": 30}]}
```

另一种是 Claude Code 的 `hooks/hooks.json`：

```json
{"hooks": {"PreToolUse": [{"matcher": "bash|write", "hooks": [
  {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/check.sh"}]}]}}
```

Claude Code 的事件映射到 OpenProgram 的事件：`PreToolUse` → `tool.before`、`PostToolUse` → `tool.after`、`UserPromptSubmit` → `chat.before_send`、`Stop` → `turn.stop`、`SessionStart` → `session.start`。`matcher` 是对工具名的正则表达式。两种形状里 `${CLAUDE_PLUGIN_ROOT}` 都会替换成插件目录；命令在 worker 的工作目录里运行。命令从 stdin 收到 JSON 形式的事件。在 gate 事件（`tool.before`、`turn.stop`）上，退出码 2 表示拒绝，stderr 作为理由；其他退出码都放行。`openprogram plugins inspect` 列出所有事件。

### 会被拒绝的内容

manifest 里写了代码的插件在哪里都装不上、启用不了：`install` 会拒绝它（git 克隆或 npm 包会被删掉），手动放进插件目录的会带着错误列出来，永远不会加载。被拒绝的键有 `python`、`module`、`setup`、`main` 和 `tools`（Python 或 JavaScript 代码），`client`、`web` 和 `sidebar`（自带界面），写成 `module:name` 的 `hooks`（Python 处理函数映射），以及旁边有 `__init__.py` 的 Hermes `plugin.yaml`。pip 不是插件来源。拒绝信息会列出这些键并说明该怎么做：在目录里加一个 `application.json`，运行 `openprogram programs install <dir>`——见[应用](applications.zh.md)。

## 写一个插件

```
house-style/
  .claude-plugin/plugin.json
  skills/review/SKILL.md
  commands/summarize.md
  hooks/hooks.json
```

```json
{"name": "house-style", "version": "0.1.0", "skills": "./skills",
 "commands": "./commands", "hooks": "./hooks/hooks.json"}
```

```bash
openprogram plugins install path /abs/path/to/house-style   # 链接这个目录
openprogram plugins enable house-style
openprogram plugins reload house-style                      # 改完文件后
```

### 让 agent 来写

Agent 有一个 `plugin` 工具（需要审批，不在聊天渠道和 plan 模式里提供）。`guide` 返回由当前构建生成的编写指南；写好文件后，用目录的绝对路径调用 `install`，一步完成链接、信任和启用，之后的修改用 `reload` 生效。写了代码的插件会被拒绝，提示与 CLI 相同。
