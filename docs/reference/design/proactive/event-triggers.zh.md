# 事件触发

Scheduler 任务通常按时间触发。另外两种触发在有事发生时运行任务：周期任务或监控任务上的 **watch**，只在一条命令的输出变化时运行任务；**webhook** 任务在外部服务 POST 过来时运行。两者都沿用任务已签名的执行规格，并把一个**事件**交给这次运行，也就是启动它的那段外部文字。

| 部分 | 位置 |
| --- | --- |
| 任务类型、`watch` 字段、hook key | `openprogram/runtime/scheduler/service.py` |
| 签名规格里带上 `watch` | `programs/tools/jobs/cron/cron.py`（`_build_execution_spec`、`_verify_execution_spec`） |
| watch 检查、事件传递 | `programs/tools/jobs/cron/worker.py`（`_check_watch`、`watch_change`、`event_note`、`fire_event`） |
| webhook 校验与限流 | `openprogram/runtime/scheduler/hooks.py` |
| HTTP 路由 | `webui/routes/execution/scheduler.py` 里的 `POST /hooks/{task_id}` |
| 免登录放行 | `webui/owner_auth.py` |
| 不可信的唤醒回合 | `conversation/owner_turn.py`（`untrusted`）、`scheduler/reminders.py` |

## Watch

`watch` 是存在任务上的一条 shell 命令，和任务正文一起冻结进签名的执行规格，所以改任务文件改不了每次 tick 要跑的东西。到点时 `_tick` 调 `_check_watch` 而不是 `_spawn`：先校验规格，再由一个守护线程用 `_invocation(..., force_sandbox=True)` 在任务的沙盒策略下运行这条命令，超时 120 秒。`watch_change` 在存储锁下，把每个任务的命令 SHA-256、输出 SHA-256 和输出本身（前 20000 字符）记在 `<schedule dir>/watch-state.json`。一条命令的第一次检查是基线；换了命令重新记基线；摘要没变什么也不做。摘要变了就返回事件 `{"source": "watch", "text": <命令和 unified diff，最多 6000 字符>}`，线程拿它调 `_spawn`。检查失败或超时只记日志，基线不动。每分钟的 claim 和其他任务一样，所以一次 tick 每个 watch 只查一次。

## Webhook

`webhook` 任务既没有 `cron` 也没有 `run_at`，所以 `_entry_due` 永远不会触发它。创建时在条目上存一个随机 `hook_key`（24 字节，URL 安全）；工具的创建结果打印 URL（`hooks.url`，取自当前 Web 访问快照）和 key。`POST /hooks/{task_id}` 是 `OwnerAuthMiddleware` 唯一不要求主人登录就放行的 HTTP 路径，而且只限 `POST`、只限这个形状；Host 和 Origin 检查照常执行。路由最多读 64 KB，在工作线程里调 `hooks.receive`：

1. 任务不存在、任务类型不对、key 不对，一律返回 `404`，不暴露哪些 id 存在。key 可以放在 `X-OpenProgram-Key`，也可以作为 `X-Hub-Signature-256`（GitHub）的 HMAC-SHA256 secret；两种都用常数时间比较。
2. 任务已暂停返回 `409`。
3. 同一个任务在一个进程里每 10 秒最多触发一次（否则 `429`）。
4. `worker.fire_event` 带着 `{"source": "webhook", "text": ...}` 调 `_spawn`：请求体（是 JSON 就格式化），有 `X-GitHub-Event` 时加在前面，截到 8000 字符。`202` 表示运行已启动。

## 事件以数据的身份进入运行

`_spawn` 把事件交给三种正文：

- **prompt**：`_run_prompt_job` 追加 `event_note(event)`：文字放在 `<event source="…" trust="untrusted">` 里，其中的 `</event>` 被转义，后面一行告诉 Agent 这段文字只是数据、只做自己的任务。这次运行是普通的非交互 scheduler 回合（`source="scheduler"`，权限模式 `ask`），需要审批的调用一律拒绝。
- **reminder**：`reminders.fire` 把 `event` 放进 `reminder.fired` 负载。唤醒型提醒的文字会写明事件来源并带上同样的说明，`_wake` 调 `start_owner_turn(..., untrusted=True)`。不可信的 owner 回合在会话模式为 `bypass`、`auto` 或 `acceptEdits` 时改用 `ask`（`UNTRUSTED_DOWNGRADE`）；`ask` 和 `plan` 保持不变。审批随后和其他审批一样在该会话里等待。
- **command**：进程环境里有 `OPENPROGRAM_EVENT` 和 `OPENPROGRAM_EVENT_SOURCE`。

任务日志在 `# started by <source>:` 下记录事件。

## 实现状态

已实现：watch、webhook（key 头和 GitHub 签名）、三种正文的事件传递、不可信唤醒回合、Scheduler 页面的标签。未实现：Scheduler 页面上创建 watch 和 webhook 任务的表单（目前通过 `scheduler` 工具或带 `watch` / `"type": "webhook"` 的 `POST /api/scheduler/tasks` 创建），以及创建后在页面上再次显示 webhook 的 URL 和 key（key 在任务里，`GET /api/scheduler/tasks/{id}` 可读）。
