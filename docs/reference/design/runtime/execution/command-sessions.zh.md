# 命令会话

Agent 怎样运行 shell 命令：`bash` 和 `write_stdin`，以及它们和 `terminal_use` 的关系。整体照搬 Codex 的 unified exec（`exec_command` / `write_stdin`）和 Claude Code 的后台任务通知，建在 OpenProgram 现有的受管进程 supervisor 之上。

## 两组工具，按进程归谁来分

| 分组 | 工具 | 进程归谁 |
|---|---|---|
| Agent 命令 | `bash`、`write_stdin` | Agent。结果只回到 agent。 |
| 终端面板 | `terminal_use` | 终端标签页：agent 自己开的（id 以 `terminal-resource:` 开头），或用户开的。 |

Codex 和 Claude Code 也是这样分：Codex 用 `exec_command`/`write_stdin` 管自己的进程，对用户终端只有只读的 `read_thread_terminal`；Claude Code 用 `Bash` 管自己的进程，终端面板另有一组工具。这样分是因为风险不同：agent 命令只影响 agent 要求的事，而用户的标签页里有用户的登录状态和正在做的事。

## bash

`bash(command, workdir, yield_time_ms, tty, description)`：

1. `prepare_command` 照旧解析 `workdir`（worktree、沙箱检查、远端 `cd` 保护）。
2. `session.run` 检查 64 个会话上限，然后 `processes.start(command, cwd, tty=..., run_command=...)` 在独立 supervisor 下启动命令。
3. `collect` 每 50 毫秒把未读输出读进首尾缓冲（1 MiB，保留开头一半和结尾一半），直到命令结束或过了 `yield_time_ms`（默认 30000；范围 250–30000，同 Codex 的 exec_command）。
4. 已结束：回复 `Process exited with code N` 加输出，并删除记录，因为输出已经全在回复里。仍在运行：记录设 `background=True`，回复 `Process running with session ID <id>`。

回复头照搬 Codex（`Wall time`、`Process exited with code` / `Process running with session ID`、`Output:`），另加 `cwd=` 和非本地时的 `backend=`。stdout 和 stderr 合成一路。退出码非零或 supervisor 失败是错误结果；仍在运行的会话不是错误。沙箱下运行的命令，如果合并输出命中 `is_sandbox_denial`，会附上沙箱说明。

首次等待期间取消这一轮会停止命令（保留原来前台命令的约定，由 collect 循环里的 `check_cancelled` 检查）。已经在后台的会话不受之后的取消影响。

没有可信对话的调用（脚本或测试直接调用工具）通过 `backend.run` 跑一次，限时十分钟，沿用原来的 `exit_code=` 格式。

## write_stdin

`write_stdin(session_id, chars, yield_time_ms)` 先在对话里找到会话（同一 `session_id`，或其范围内的某个 execution），然后：

| `chars` | tty 会话 | 管道会话 |
|---|---|---|
| 空 | 轮询 | 轮询 |
| `"\x03"` | 写入终端（行规程发出 SIGINT） | `interrupt` 命令：向进程组发 SIGINT |
| 其他 | `write` 命令，原样字节，等 100 毫秒再读 | 拒绝：stdin 已关闭 |

等待时间：写入默认 250 毫秒，范围 250–30000；空轮询范围 5000–300000（Codex 的取值）。显示了退出的回复会把记录标为 `reported`。

## 进程层

- `group_guard` 以 `/dev/null` 作为管道命令的 stdin（Codex 对非 tty 也关闭 stdin）。tty 时打开一个 pty，把它设为自身会话的控制终端（它本来就是会话首进程），把自己的进程组设为前台，设 30×120，并在 master 和 supervisor 管道之间转发。它像忽略 SIGTERM 一样忽略 SIGINT，因此中断到达命令，而不是 guard。
- supervisor 的 `write` 命令发送原样字节（不追加换行）；`interrupt` 向进程组发 SIGINT（Windows：终止进程树）。
- `ProcessStore` 记录 `tty`、`sandboxed`、`background`、`reported`、`last_used`；`take()` 返回未读输出和来不及读就被丢弃的字节数；`live_count()` 和 `unreported_exits()` 各是一条 SQL 查询。
- tty 需要 macOS 或 Linux 上的本地 backend。

## 会话上限

每个对话最多 64 个运行中的会话（Codex `MAX_UNIFIED_EXEC_PROCESSES`）。先用 `live_count` 快速判断；到达上限时，停止最近用过的 8 个（`PROTECTED_RECENT`，同 Codex）之外最久没用的那个，标为 `reported`，并在新命令的回复里写明。没有空闲超时，也没有一次性超时模式。

## 结束通知

`runtime.conversation.process_notices.run_exit_notices` 在 worker 的 lifespan 里运行，每 2 秒扫描一次：

1. `unreported_exits()`：`background` 为真、未 `reported`、状态 `exited` 或 `failed`。`stopped` 的命令（用户点停止，或被上限停掉）不发通知。
2. 对话有正在运行的回合或未结束的 execution 时跳过，这一轮结束后再试。
3. 复制该对话最新的一次 chat 请求（沿用它的可信身份和配置快照，同 Goal 续跑），设 `source="process_exit"`、新的用户消息 id 和通知文字（命令、退出码、耗时、最后 2000 个字符的输出），以键 `process_exit:<id>` 提交。没有 chat execution 的对话直接标为 reported，不发通知。
4. `process_exit` 是运行时来源：这一轮的用户节点 `display="runtime"`，记忆写入会跳过它。

## 审批

- `write_stdin` 的 chars 为空或 `"\x03"` 时不询问直接放行（`SESSION_POLL`），因为 `bash` 已经批准过这条命令。其他输入按模式处理，和 `bash` 一样。
- `terminal_use` 的 `input`、`interrupt` 或 `close` 按权限模式处理，用户开的标签页和 agent 开的一样。需要询问时，卡片（`TerminalApproval`）写明标签页、shell 集成报告的当前目录、有没有命令在运行、有没有用户没输完的内容，并把要输入的内容连同控制字符原样显示出来。
- 原来 `process` 所在的风险名单里都换成了 `write_stdin`（Auto 风险集、MCP/委派硬约束、危险允许规则）。

## 界面

- Activity 只列后台会话（`background` 为真，或没有这个字段的旧记录）；还在首次等待的命令显示为进行中的工具调用。
- Resources 在 Terminal 分组里把运行中的后台会话列为“后台终端”（`backgroundTerminalRows`），`BackgroundTerminalView` 用 xterm 只读显示保留的输出，带“停止”。输出随受管进程轮询（3 秒）刷新。
- 工具行：`write_stdin` 显示“等待输出”“中断命令”或“输入”；`terminal_use` 的 input 显示“在终端输入”。

## 实现状态

已按上文实现。未从 Codex 采用：zsh fork、Shell 快照、`shell` / `login` / `max_output_tokens` 参数，以及策略变化时的 stdin 审批。后台终端的输出靠轮询刷新，不是流式推送。
