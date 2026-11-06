# CLI / TUI

`openprogram` 在终端里运行的，就是桌面 App 和 Web UI 里的同一个 agent。不带参数运行时打开全屏终端界面里的对话；`openprogram --print "..."` 发一条提示、打印回复后退出；`openprogram --resume <id>` 继续之前的会话。其余能力（模型服务、agent、会话、Programs、技能、插件、MCP 服务器、渠道、设置）各有子命令，按同一条命名规则命名，知道已有的命令就能猜出新的。

目前的组成：

- **一个后端。** 一个常驻的 Python worker 在一个端口上服务所有前端。终端界面是 Node.js 的 Ink 程序（`apps/cli/`），由 `openprogram/interfaces/cli/ink.py` 启动；它通过 `worker.pid` / `worker.port` 找到正在运行的 worker，用 WebSocket 和它通信，所以在终端里开的对话就是 Web UI 里显示的同一个会话。
- **一套设置 schema。** 每个设置只声明一次；`openprogram config`、TUI 设置面板和 Web UI 都经由同一个 schema 读写，所有对 `config.json` 的写入都走同一个带锁的原子入口。
- **一个 slash 命令注册表。** 内置命令、插件命令、MCP prompt 和技能合并进同一个注册表、同一种格式，所以在 TUI 和 Web 输入框里按 `/` 看到的是同一组命令。
- **终端里的对话记录。** 工具调用折叠成一行，`ctrl+o` 打开完整记录，文件修改显示为 diff，运行中输入的内容进入队列。

## 文档

- [`naming.md`](naming.zh.md) —— 每个 `openprogram` 子命令遵守的命名规则。
- [`redesign.md`](redesign.zh.md) —— 配置界面：命令语法、设置 schema、TUI 设置面板和传输。
- [`config-write-safety.md`](config-write-safety.zh.md) —— 写 `config.json` 的唯一原子入口。
- [`drop-run-command.md`](drop-run-command.zh.md) —— `Agent` 方法只有一条执行路径，不论是用户运行还是模型调用。
- [`single-port.md`](single-port.zh.md) —— 一个进程一个端口，Python worker 是唯一来源。
- [`ports.md`](ports.zh.md) —— Web UI 端口的选择、配置和冲突处理。
- [`slash-commands.md`](slash-commands.zh.md) —— 统一的 slash 命令注册表。
- [`slash-commands-references.md`](slash-commands-references.zh.md) —— 另外五个项目如何实现 slash 命令。
- [`tui-upgrade.md`](tui-upgrade.zh.md) —— TUI 对话记录的渲染与交互：工具调用折叠、`ctrl+o` 记录、diff、排队输入、快捷键。
