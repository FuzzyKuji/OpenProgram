# 运行时

Agent 执行运行时 —— 运行循环、worktree、异步任务、流式传输/恢复、DAG 模型，以及回退层。

API 用法见 [Runtime API](../../api/runtime.zh.md)。以下章节集中说明运行时契约及对应的设计取舍。

## 包结构

`openprogram/runtime/` 按概念划分，每个包回答一个问题：

| 包 | 是什么 |
| --- | --- |
| `agent/` | 一次模型调用。`Agent` 类及其如何使用 `Context`、`agent()` 与 `llm()` 函数、工具循环（`loop/`：`loop.py`、`driver.py` 里的 `LoopDriver`、`AgentSession`、工具与事件类型、重试）以及 `Runtime`。这是 Agentic Programming 的代码。 |
| `conversation/` | 聊天及其轮次，建立在 `Agent` 之上：`turn_runtime/` 运行一轮，`chat.py` 是 `ChatAgent`，`production_driver/` 把一轮作为规范执行来驱动，`run_control/` 跟踪正在运行的轮次，另有会话设置、收件箱、未完成工作、回退和常驻 Agent。 |
| `jobs/` | 后台运行：任务存储、执行池，以及 `resource_governance/`（准入与限额）。 |
| `agent_registry/` | 保存的 Agent 配置：有哪些 Agent、各自的模型、工具和工作区。 |
| `permissions/` | 工具调用能做什么：策略、审批、审计、`authority`（谁在请求）和 `attended` 模式（无人值守时不提问）。 |
| `context/` | `Context` 类（`model.py`）以及决定模型看到什么的一切：渲染、压缩、系统提示词、`session_db.py`。 |
| `execution/` | 暂停、取消与恢复的控制平面：执行存储、修订、等待与检查点。 |
| `events/` | 事件总线。 |
| `scheduler/`、`proactive/`、`commands/` | 定时运行、主动策略与斜杠命令。 |

依赖只朝一个方向：功能包（`conversation`、`jobs`、`agent_registry`、`scheduler`、
`proactive`、`commands`）建立在 `agent` 之上，`agent` 建立在 `context`、`permissions`、
`events` 和 `execution` 之上。`execution`、`context`、`permissions`、`events` 不导入 `agent`。
`tests/contracts/repository/test_runtime_layering.py` 检查这些方向；目前违反方向的导入是一份只能缩小的冻结清单。
`context` 和 `permissions` 已经完全遵守这些方向。下层包需要只有上层知道的信息时，由上层在导入时注册：
`conversation/context_registration.py` 注册 `open_work` 系统提示段落和上下文拆分读取 Agent 配置的方式，
`conversation/permission_registration.py` 提供 `permissions/session_facts.py` 读取的会话与轮次事实。
`Context` 读取的任务局部调用状态（`_call_id`、workflow 调用点）放在 `context/scope.py`，调用核心从那里导入。

`agent` 从不导入功能包。调用核心需要上层引擎提供的东西都经过一个注册端口
`openprogram/runtime/agent/engine_link.py`：运行一次持久轮次或保存的续跑
（`Agent.run_turn` / `resume_turn`）及其起始的 Agent 配置、保存的 Agent 的工具、
为恢复的工具调用绑定预先批准的提问等待、worker 是否正在停止、
正在运行的后台任务的活动与单次操作超时，以及可恢复工具循环写入检查点的运行时契约。
与核心并列或在其下的东西直接导入，有没有注册引擎行为都一样：绑定的会话和执行、
嵌套调用的准入和终态标记（`execution/run_control/`）、审批门
（`permissions.approval.wrap_with_approval`）和预先批准的等待 id（`permissions.session_facts`）。
`conversation/engine_registration.py` 实现这个端口，并在导入
`openprogram.runtime.conversation` 时注册；worker 和 Server 启动时都会导入它。
没有注册时核心按普通库的方式工作：worker 不在停止，没有后台任务，
`Agent.run_turn` 抛出 `EngineUnavailable`。`TurnRequest`
和当前生效的请求（`agent/turn_request.py`）是调用核心的类型，由引擎构造并绑定；
调用方从那里导入。模块只导出自己拥有的名字：执行绑定的名字来自
`openprogram.runtime.execution.run_control`，权限词汇来自 `permissions/modes.py`，
工具契约（`AgentTool`、`AgentToolResult`）来自 `openprogram.models.providers.types`，
调用域 ContextVar 来自 `context/scope.py`；
`tests/contracts/repository/test_no_transitional_reexports.py` 防止这些名字被重新导出。
导入 `openprogram.runtime.conversation` 时也会导入 `conversation/run_control`，
由它接管调用核心的取消检查。在子进程里运行一轮 Agent method 工具的
`process_runner.py` 属于引擎代码，放在 `conversation/` 中。

![按概念划分的运行时包](execution/agent-code-structure.zh.svg)

<div id="runtime-设计理由"></div>

## 1 runtime = 1 session

每个 `Runtime` 实例绑定一个 provider session,生命周期 1:1:

```
create_runtime()      = 开 session
runtime.exec()        = session 里发一次请求
runtime.close()       = 关 session
```

不提供 `reset()` / `new_session()`,要新 session 就再 `create_runtime()`。

**为什么不让一个 Runtime 复用多 session?**

- CLI provider(Claude Code / Codex / Gemini CLI)的 session 状态在子进程里。
  复用就要在 Runtime 上挂"当前哪个 session id"这种可变状态,引入并发竞态。
- API provider 本身无状态,做"多 session"也只是上层 dict,跟"多个 Runtime"
  等价,没新功能。
- ContextVar 自动注入(下条)依赖"runtime 跟当前函数树绑定"这个简单模型;
  多 session 会让注入语义复杂化。

代价:用户想跑两套独立对话要管两个 runtime 对象。可以接受,因为这种场景少。

## ContextVar 自动注入 runtime

`Agent` method 装饰器读 `_current_runtime` ContextVar,如果当前函数
没传 `runtime=` 参数就用它;入口函数也没有,就自动 `create_runtime()`。

**为什么不让函数显式声明 runtime?**

显式声明的话每个 agentic function 都得在签名里加 `runtime: Runtime`,
而且每次嵌套调用都得显式传 `runtime=runtime` 透传——纯粹是 plumbing
样板代码,跟函数逻辑无关。ContextVar 把它隐去:子函数自然继承父函数的
runtime,入口处自动起一个,出口处自动关。

**为什么不用 module-level singleton?**

singleton 跨线程 / 跨协程共享,两个并发 agent 会互相踩 session 状态。
ContextVar 按线程 + 协程隔离,天然并发安全。

## Session-provider vs API-provider 共用一套抽象

无论底层是 Claude Code CLI(有 session)还是 Anthropic API(无 session),
对 `Agent` method 作者都是一样的接口 `llm(...)` / `agent(...)`，两者最终都走 `runtime.exec`。
框架靠 `has_session` 属性区分两类 provider 在内部走不同路径:

| | session provider (CLI) | API provider |
|---|---|---|
| 对话记忆 | 子进程自己管 | 无,每次 exec 独立 |
| 上下文注入 | 跳过 DAG render,只发 docstring + 当次 content | 通过 `render_context` + `render_dag_messages` 从 DAG 拼历史 |
| `render_range.subcalls` | 不生效(session 自己记得对话) | 生效(用来限制注入历史的窗口) |

**为什么不分两套独立的 Runtime 类?**

作者写 `paper_agent` 时不应该关心后端是哪种 provider。强行分开就要每个函数
两份实现,违背"函数描述任务、provider 描述执行通道"的分层。共用抽象的
代价是 `has_session` 这点条件分支,值得。

## Retry 在 runtime 层,不在 provider 层

`exec()` / `async_exec()` 内置 `max_retries` 默认 2,任何 provider 都
享受重试。

**为什么不在每个 provider 类里各自加 retry?**

- 重试策略对所有 provider 一致(网络超时 / 速率限制 / 5xx),没必要重复
- 失败报告统一格式(`Attempt N: ErrorType: msg`),便于排查
- `TypeError` / `NotImplementedError` 这类编程错误统一不重试(只有
  runtime 层知道"这是 provider 实现 bug,重试也没用")

provider 层只关心"把请求发出去、把回复拿回来"。重试 / 节流 / 缓存这种
横切关注点全在 runtime。

## DAG 写入:进出函数都写 code 节点,exec 写 llm 节点

```
进入 Agent method       → 写一个 code 节点 (status=running)
                              → 设 _call_id ContextVar 指向此节点
函数体里 runtime.exec()      → 在当前 _call_id 下写一个 llm 节点
                              → 节点的 caller = _call_id
退出函数(return / except)     → 回填同一 code 节点的 output / status
```

`expose="hidden"` 时跳过 code 节点写入(但 `_call_id` 仍设了一个 phantom
id,以便函数体内 LLM 调用有 frame 可参照)。

**为什么不只在退出时写一个完成态节点?**

- 函数还在跑时 webui visualizer 需要立刻能看到"它在跑"(显示 spinner)
- 异常退出时也要有节点存在(才能记错误信息)

写两次(entry + exit 回填)比写一次(完成时)更适合实时可观察。

## 嵌入接缝

核心可以嵌在不是 OpenProgram 的宿主里运行——别人的服务或 agent 框架把
`Agent` method + 执行 DAG 当作一个组件来用（见
[嵌入到你自己的技术栈](../../../capabilities/agentic-programming/embedding-in-your-own-stack.zh.md)）。
这份契约由 `tests/component/runtime/test_standalone_embed.py` 执行，不只是纸面声明：

- **库面永不 import UI 表面。** `import openprogram` 以及一次完整的
  `Runtime(call=...).exec()` 往返，不得拉起 `webui`、FastAPI、Uvicorn 或 Textual。
- **没有隐式状态路径。** 用 `SessionStore(root_path=...)` +
  `session_scope(store, session_id)` 时，整个运行不查
  `openprogram.state.paths`（`~/.openprogram`）；不绑 store 时照常执行、只是不持久化。

平台需要伸进核心的地方，方向一律倒转成注册钩子，与 `add_pre_invocation_hook`
同款：

| 接缝 | 核心默认值 | 平台注册方 |
|---|---|---|
| `set_cancellation_check`（`openprogram.host.cancellation`） | 空实现——没有任何东西会取消 | `openprogram.runtime.conversation.run_control` 在 import 时注册精确 execution 检查 |
| `set_session_id_provider` | `None`——`runtime.can_ask()` 为 `False` | `openprogram.runtime.conversation.run_control` 提供当前会话 id |
| `session_scope(store, id)` | 未绑定——不持久化 | dispatcher 自己绑定每 turn 的 store |

**为什么用钩子而不是 Web UI 取消模块？** 原来的 session 级模块重复维护取消状态，
并让核心依赖 Web UI。现在由 `run_control` 检查精确 execution token，同时保持依赖
方向为平台 → 核心。

**`exec()` 里的 `ImportError` 按永久错误处理，不算瞬态。** retry 循环把它归为不可
重试：缺失的子系统不会因为重试而出现，烧完整个退避表只是把 0 秒的失败拖成约 52 秒。

## 相关实现文件

- `openprogram/runtime/agent/runtime/` — Runtime 基类、`exec` / `_call` 协议、retry 循环
- `openprogram/runtime/agent/call_state.py` — 装饰器 / `_inject_runtime` / `_call_id` / `_current_runtime` ContextVar
- `openprogram/models/providers/catalog/registry.py` — `detect_provider` 自动检测与内置 `PROVIDERS` 表
- `openprogram/runtime/agent/runtime/factory.py` — `create_runtime`，按检测结果构建 Runtime
- `openprogram/runtime/agent/provider_runtimes/` — 订阅 / CLI 凭据类 provider 的专属 Runtime 子类(`openai_codex.py`、`google_gemini_cli.py`)以及 `create_runtime` 读取的 `PROVIDER_RUNTIMES` 注册表;其他 provider 都跑在基础 Runtime 上。`openprogram/models/providers/adapters/<vendor>/` 下的 provider 包只保留模型、认证和线路代码
- `openprogram/runtime/context/nodes.py` `render_context` — DAG → reads 计算(`render_range` 的实际语义)
- `openprogram/runtime/context/render.py` `render_dag_messages` — reads → provider messages 转换

## 相关设计

- [`dag/overview.md`](dag/overview.zh.md) — **权威**:历史记录数据模型(一整张图 / 三种节点 user·llm·code / caller+predecessor 边 / render_context 上下文检索)
- [`dag/rendering.md`](dag/rendering.zh.md) — **权威渲染规范**：布局/连线/图例/默认可见性，12 场景
- [`dag/branch-collaboration.md`](dag/branch-collaboration.zh.md) — 分支协作（通信 / 派活 / 合并）设计与实现步骤
- [`execution/agent-call-flow.md`](execution/agent-call-flow.zh.md) — 调用流程骨架(turn / loop,跟节点模型正交)
- [`execution/agent-worktree.md`](execution/agent-worktree.zh.md)
- [`execution/async-job-lifecycle.md`](execution/async-job-lifecycle.zh.md)
- [`execution/control.html`](execution/control.zh.html) — **权威设计**：统一暂停、继续、单步、调整、取消、检查点、revision 与恢复合同
- [`execution/dispatcher-split.md`](execution/dispatcher-split.zh.md) — `conversation/turn_runtime/` 如何把一次聊天轮次按职责拆成模块(遵循「单文件不超过 1000 行」规则)
- [`operations/file-management.html`](operations/file-management.zh.html) — 文件归因、Review、Undo、Restore、分支对齐和多 agent 所有权的权威设计
- [`session/`](session/) — Session 子系统：数据模型、存储、命名、列举、生命周期、广播
- [嵌套 `llm()` 流式设计](https://github.com/FuzzyKuji/OpenProgram/blob/main/docs/reference/design/runtime/execution/agentic-llm-streaming.zh.html) — **完整设计**：RuntimeBlock 按节点 token 流（协议、FE 缓冲、落盘、取消/重连、in-process+subprocess）
- [`operations/streaming-resume.md`](operations/streaming-resume.zh.md)
- [`operations/user-input-requests.md`](operations/user-input-requests.zh.md) — 暂停正在运行的函数以向用户提问(`runtime.ask`/`confirm`),问题注册表 + WS/REST 协议 + 子进程桥接
- [`agent-collaboration.md`](collaboration/agent-collaboration.zh.md) — **权威**：agent 协作收敛成一个分支间通信原语 —— 四个域、工具面、三个预算（[工具面图示](collaboration/agent-collab-architecture.zh.html)、[八家参考实现对照](collaboration/agent-collab-comparison.zh.html)）
- [`sandbox-architecture.html`](security/sandbox-architecture.zh.html) — 唯一权威执行安全设计：Authority 权限档、Permission 模式与审批、沙箱执法、框架对照和实现证据。[`permission-model.md`](security/sandbox-architecture.zh.html) 与 [`sandbox.md`](security/sandbox-architecture.zh.html) 只保留为稳定旧链接入口。

- [嵌套 LLM 节点内容（聊天式有序块）](https://github.com/FuzzyKuji/OpenProgram/blob/main/docs/reference/design/runtime/dag/nested-llm-node-content.zh.html)
