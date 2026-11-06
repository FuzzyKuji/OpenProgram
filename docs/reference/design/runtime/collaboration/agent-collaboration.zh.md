# Agent 协作：分支、执行与消息

agent 可以把工作交给子代理。`agent(prompt=...)` 在对话的一条新分支上启动子代理——从空白开始、从调用方的历史开始，或从任意一条更早的消息开始——然后要么等它回复，要么让它在后台运行并返回 `execution_id`。子代理有自己的上下文和工具循环；调用方只拿回它的结果：作为工具结果，或在后台运行结束时作为完成通知，需要更多细节时还附有完整记录的地址。agent 用 `agent(to=...)` 和 `send_message` 按名字寻址已有分支，用 `list_agents` 发现分支，用 `read_conversation` 读取，用 `archive_agent` 归档；每次运行都是一个受跟踪的 Job，有准入限制，可以取消。要改代码的子代理可以用 [worktree 工具](../execution/agent-worktree.zh.md)把改动隔离在一个 Git worktree 里。

本文定义这份协作契约，剩余差距集中列在 §7。保存 Agent 的配置契约见 [Agent 配置](../agent-configuration/agent-configuration-ui.zh.html)，准入、资源计量和取消限制见[资源治理](../reliability/agent-resource-governance.zh.html)。AgentSpec 是可复用配置，运行分支是对话状态，同一分支可以执行多个 Job。创建分支不等于创建一份新的保存 AgentSpec。

## 0. 共享投递机制，分别管理生命周期

协作复用分支寻址、轮次派发和现有事件层。不同操作分别决定是否创建分支，以及立即提交执行还是先进入收件箱，不增加另一套执行引擎。

| 操作 | 分支变化 | 执行变化 |
|---|---|---|
| `agent(prompt=..., start_from=...)` | 一次调用创建分支并执行 prompt | 两种都准入 Job；前台等待并返回结果，后台立即返回 `execution_id` |
| `agent(prompt=..., to=...)` | 继续已有分支 | 先准入受管 Job，再执行或排队，返回 `execution_id` |
| `send_message(message=..., to=...)` | 继续已有分支 | 投递消息；实际异步轮次仍创建 Job。只有收件箱回执不代表执行已获准入 |

目标完成契约是将非空结果回送发起方，不要求收件方再显式调用 `send_message`，同一会话内和跨会话都一样。每条终态路径都把这次回送排成一条完成通知（§2.7）。收件方在最终回复里作答；再用 `send_message` 回发会让答案送达两次，所以回执里写明不要这样做。投递成功不能保证目标模型遵从内容或一定生成回复。

`attach` 是指向新建分支的存储引用与 DAG 展示关系，不是消息或独立执行。

## 1. 四类对象与操作分工

四域区分对象，不要求一次操作只能涉及一类对象。`agent` 可以在同一次调用中创建分支并提交执行；查询或取消该执行属于执行控制，不需要为了分类再新增创建任务工具。

| 域 | 对象 | 公开入口 | 职责 |
|---|---|---|---|
| 计划 | `todo` | `todo_create` / `todo_update` / `todo_list` | 记录计划，清单条目不启动执行 |
| 执行 | `Job` / canonical execution | `list_jobs`、`job_output`；控制动作 `execution.cancel` | 查询或控制已接受的执行，包括排队和终态 |
| 对话 | 运行中的 Agent 分支 | `agent`、`list_agents`、`archive_agent` | 创建、继续、寻址、归档分支，不操作保存 Agent 的配置注册表 |
| 通信 | message | `send_message`、`read_conversation` | 投递内容或读取授权历史；触发的轮次仍有独立执行计量 |

后台 Agent 调用返回 `execution_id`。当前 runner 中 `execution_id == Job.id`，`job_output(job_id=...)` 参数及其 `details.job_id` 字段仍保留这个名称，这是同一身份，不是两份独立任务。公开工具名是 `list_jobs` 和 `job_output`，不是 `list_tasks` 或 `task_output`。当前目录不注册 `job_stop`、`task_stop` 工具。UI/API 取消使用现有 `execution.command`，包含 `action="execution.cancel"`、`command_id`、`execution_id`、`expected_version` 与空 `payload`，仍须通过认证和动作授权，见[执行控制](../execution/control.zh.html)。

分支地址是 `"SID:HEAD"` 或无歧义分支名；保存的 `agent_id` 选择配置，不是分支地址。“任务”可以作为工作内容的自然语言称呼，公开标识符和工具名以以上实际 schema 为准。

### `agent` 模式与一步 fork

| 调用 | 行为 |
|---|---|
| `agent(prompt=...)` | 创建新分支并执行；默认前台返回结果，要求后台时返回执行 ID |
| `agent(prompt=..., start_from="SID:MSG", description="review")` | 从精确历史节点 fork，设置标签，并立即执行 prompt |
| `agent(prompt=..., to="review")` | 向已有分支提交下一次执行，不创建分支或保存配置 |

提供 `to` 时，禁止 `start_from="inherit"` 或 `start_from="SID:MSG"`。API 默认的 `"clean"` 在此模式仅是占位值，不清空目标历史。`description` 为新分支命名，`to` 始终指认已有分支。创建并执行只需一次调用：

```python
agent(prompt="审查这个节点的结果",
      start_from="SID:MSG", description="review",
      run_in_background=True)
```

`job_output` 检查当前 session/job 关系（§5.10）；取消使用 canonical execution 授权，不能仅凭工具别名或知道 ID 就获得控制权。`send_message` 不表达 `agent(to=...)` 的明确工作委派，但它触发的执行同样遵守准入、取消与资源计量。

### 参考实现与命名

其他框架的对照保留在 [Agent 协作对比](agent-collab-comparison.zh.html)。这些资料用于说明设计参考，不保证其他产品具有相同工具名或语义。本仓库注册工具及 canonical execution 接口决定本文使用的公开名称。

## 2. 工具与分支寻址

以下接口复用现有分支、Job 与执行控制。后台 agent 结束后怎样回报见 §2.7，剩余差距列在 §7。

### 2.1 工具

现有 `agent` 接受 `prompt`、可选 `description`、`agent_id`、`start_from="clean"`、`run_in_background=False`、`to=""` 和 `archive_when_done=False`。`agent_id` 选择保存配置，解析契约由配置文档定义。前台创建调用 `run_agent_turn`，通过 `spawn_job(wait=True)` 持久化 Job 并等待结果。后台创建和已有分支派发同样准入 Job。前台工具返回最终文本，不返回后台形式的即时 execution-ID 回执；返回形式不改变资源准入。

`start_from` 分别选择新根（clean）、调用方历史（inherit）或精确 predecessor `SID:MSG`。执行前应检查存在性及历史读取授权；§7 区分已实现的存在性检查与目标共享可见性策略。已归档历史可以作为 fork 来源，因为 fork 创建新分支，不向已归档分支投递。

session S 的节点 A 使用 `start_from="T:M"` 时，新分支在 T 执行。后台 Job 记录 `parent_session_id=T`、`parent_msg_id=M`、`caller_session_id=S`、`caller_msg_id=A`。attach 引用本身存储在 S 的 A 旁，其载荷 `attach.session_id=T` 和终态 `attach.head_id` 指认目标结果。

| 渲染或读取操作 | 使用的身份 |
|---|---|
| 定位引用卡片及发起节点 | 存储消息或 WS 外层的源 `session_id`，以及 pointer ID/caller 元数据 |
| 读取所引用结果 | `extra.attach.session_id` 与 `extra.attach.head_id`，不能在源 DAG 中查目标节点 |
| 绘制同 session 分支关系 | 仅源与目标 session 相同时使用本地 DAG 连线 |
| 展示跨 session 引用 | 使用 external attach card，保留目标 session/head 引用及源卡片位置 |

UI 已区分本地 attach 关系和跨 session 卡片。当前完整 AttachCard 打开 T 但未明确选中 H，execution strip 能选择 (T,H)；目标要求一致的精确 head 跳转，此差异列在 §7。创建或终态化 attach 都不移动 S、T 的选中 HEAD，之后获授权的 follow-up 是独立轮次。源身份属于存储消息/事件外层，不在目标载荷再维护一份可独立修改的字段。投影时验证两端身份，不一致时报错，不能任选其一。见 [DAG attach 渲染](../dag/rendering.zh.md)。

`agent(to=...)` 为已有分支准入一个 Job，目标忙则排队。地址解析到当前 tip，名字歧义时返回候选。它不创建新 attach。`to` 与 `archive_when_done=True` 不能同时使用，只有创建分支的调用才能声明完成归档策略。

`send_message(message, to, agent_id="main", notify_when_idle=False)` 复用已有目标解析。直接异步投递会创建 Job，返回的 `delivery_id` 指认该执行；目标忙时先创建收件箱条目，此时投递回执与稍后执行 ID 分开。它不创建新分支。旧 `to="new"` 形式无效，创建使用 `agent(start_from=..., prompt=...)`。投递与准入限制见 §5.1–5.2。

显式消息包含发件地址，并说明这次投递的最终回复会自动回到发送方（§2.7）。来自另一个会话的消息还会注明这是另一个 agent 的输入，不是收件方自己的用户：它能做什么已由运行时授权限制，这句说明是让模型不要把它当成自己用户的指令。`message` 留空并设 `notify_when_idle=True` 时什么都不投递：目标空闲就立刻返回它的最新回复，否则登记一次空闲观察（§2.7）。目标不存在时不能静默新建。

### 2.2 引用别的分支

message 就是纯文本，跟用户消息一样。要让目标参考别的分支，发送方直接写进
`message`：结论已经通过回送回到发送方手里，直接引用；或者点名分支
（`SID:HEAD` 或分支名），目标自己用 `read_conversation` 去读。读多少由目标
模型自己决定，但仍遵守 §5.6 的输出限制和 §5.9 的读取授权；不增加专门的聚合参数。

### 2.3 `list_agents` — 发现可寻址分支

```
list_agents(scope="session", limit=20, agent_id?, source?) -> str   # db.list_sessions + db.list_branches
```

`scope` 决定查询范围：`"session"`（默认）列当前 session 的分支，也就是在这里
派生出来的 agent；`"all"` 放宽到所有 session，最近活跃优先，不带预览；
`"archived"` 列当前 session 已归档的分支（§2.6），前两种视图会把它们藏起来。

agent 的对话就存在 session DAG 的分支里，所以"能跟谁说话"="有哪些
session、每个有哪些分支"。一次调用全列出，按 session 分组：session 行带
id、标题、agent、busy/idle 状态（`run_control.is_turn_running`，探测失败
就不标）；分支行带名字（若有）、现成的 `to="SID:HEAD"` 地址、轮数与近似字符量
（`— 3 turns, ~2k chars`，不足1000字符显示`<1k chars`）、末端预览。
模型可据此在调用`read_conversation`前选合适的`max_chars`。
这是"两个 agent 互相看见"的入口。

派生出来的 agent 一生都能用 `agent` 调用时给的名字（`description`）找到
（`addressing.agent_tips`，取自会话里的派生 Job）。第二阶段命名（§2.4）可能把
它的分支改名，跑完的 agent 分支也会退出 tip 列表，但 `to="scout"` 仍然送到该分
支当前的 tip，`list_agents` 也照样列出它，分支名不同时标 `(agent «scout»)`。和
Claude Code 一样，跑完的 agent 还能按派生时的名字再发消息。

### 2.4 新建分支要有名字

`agent` 工具每次创建分支，**都必须给分支一个名字**。
否则 web 端只能显示 8 位 hex 短号，一堆分支分不清谁是谁。

- **立刻有名（Stage 1）**：创建时把一个简短 label 传给 `run_agent_turn(... label=…)`
  → `store.set_branch_name`。label 从投递的 prompt 摘一句（截断到 ~24 字），或让
  模型在调用时显式带一个名字（`description`）。这样分支创建时就有可读名，不用等 LLM。
- **后台自动改好名（Stage 2）**：分支正常聊起来后，由 `finalize_turn` 在 `turns`
  命中阈值 `{1,6,16,40}` 时，后台线程用 LLM 依据分支内容生成更贴切的标题，覆盖
  Stage 1 的临时名。规则见 [branch-naming](../operations/branch-naming.zh.md)，那里定义
  了命名的分级、锁、触发点；本节只强调：**agent 工具派生的分支和用户手动
  fork 的分支，走同一套命名（都要 Stage 1 占位名 + Stage 2 自动改名），不能漏。**

### 2.5 回送位置：发起方当前 HEAD，串行处理

异步回送时，`_dispatch_followup` 把一个或多个已结束 job 的通知作为一个
**synthetic user-role turn**（`source="job_followup"`）提交到投递 session，何时提交见 §2.7。**关键规则：回送的 `TurnRequest`
不设 `branch_from`（INHERIT_PARENT），dispatcher 解析为投递 session 当前的
HEAD 并推进它。**每个投递 session 使用独立的回送串行锁
（`JobRunner._followup_lock`），并发完成被串行化：N 个子任务完成形成一条串行链
`… → notice₁ → answer₁ → notice₂ → answer₂`，每条回送读到的 HEAD 已包含上一条的回答。

回送不以发起节点（`caller_msg_id`）为 predecessor：同一轮 fork 出 N 个并行子任务时，
否则每条回送都会成为同一节点的 sibling，触发派生的那一条用户消息会在 N 条并行分支
上被回答 N 次。使用当前 HEAD 让 N 次完成沿同一条会话分支串行处理。

来源关联仍由派生时写入的 **attach 指针**记录，其
`predecessor = caller_msg_id`。DAG 保留每条子分支的发起轮次与每个结果的来源分支。
子分支保持独立，**不合并到发起方分支**。

跨会话派生时，指针仍位于发起方 session，但引用目标
`(session_id, head_id)`。终态化从目标 session 读目标分支及其 ContextCommit，
然后更新发起方 session 里的卡片。源侧发起节点标记 `spawn_out`；目标侧第一个
`agent_spawn` user 节点记录 `caller=<source node>` 与
`metadata.spawned_from_session=<source session>`，并投影为 `spawn_remote`。
因为源 session 里有真实 attach 指针，它的异步 followup 通过 attach 报告（§2.7）获取结果，
不再内联一份重复回复。`send_message` 与 `agent(to=...)` 不创建分支和 attach
指针，因此它们的回复仍内联，也不会得到任何 spawn 标记。

### 2.6 归档：全局分支状态

归档将 `archived: true` 写入目标分支元数据，作用于同一本地状态目录，不是“归档者→目标”的可见关系。A 归档 B 后，C 之后调用 `list_agents(scope="session"/"all")` 同样不再列出 B。`scope="archived"` 明确查看已归档分支记录。历史仍保留，归档不等于删除数据或回收存储空间。

“单向”仅指状态转换：当前工具没有反归档操作，不表示“只对调用方隐藏”。复用归档历史使用 `agent(start_from="SID:MSG", prompt=...)` 创建生命周期独立的新分支。闲置但从未归档的分支仍可出现在列表中；由明确手动操作或完成策略决定归档状态，不按查看者分别过滤。

| 对已归档分支的操作 | 契约 |
|---|---|
| 普通 `list_agents` 视图 | 同一存储内对所有调用方隐藏 |
| `scope="archived"` | 在归档视图显示，也包括已被合并的归档分支记录 |
| 新 `send_message` / `agent(to=...)` | 由共享已有目标解析器拒绝 |
| 已在执行的 Job | 继续运行，归档不执行取消 |
| `read_conversation` / 历史 fork | 仍须满足历史可见范围；归档本身不授予读取权限 |

合并与归档分别存储：已合并分支可以不在活跃 tip 列表中，但不一定带归档标记。归档视图读取分支记录；归档 merged head 时必须指向它自己的分支，而非吸收它的分支。

两个入口最终设置同一个归档状态：

- `archive_agent(to, reason="")` 归档已有分支，重复手动调用幂等。当前实现允许具备该工具能力的本地 session 归档其他分支，没有 creator-only 检查；这是共享本地信任范围，不构成多用户隔离。目标生命周期操作应复用与其他分支操作一致的作用域授权。
- `agent(archive_when_done=True)` 仅为该次调用新建的分支声明终态归档策略，与 `to` 同传报错。同步路径在工具内写标记；异步路径由 §2.7 的终态钩子写。

手动归档先发生时，不取消正在执行的 Job，终态处理也不能重新开放分支。目标共享归档操作保留首次 `archived_at` 和明确手动原因；自动请求只能补未设置字段，不能覆盖。异步终态钩子不动已经归档的分支；同步工具内的写入仍可能刷新时间戳。自动归档保存失败应单独报告，不把已成功的执行结果改成失败。已接受但尚未启动的投递在启动前重查归档状态；拒绝时为 Job/回执记录明确原因，不能静默丢弃。

### 2.7 完成通知、空闲观察与 attach 报告

后台 job（`agent(run_in_background=True)`、`agent(to=...)` 或一次 `send_message`
投递）完成或失败时，会告诉派它出去的会话，做法同 Claude Code 的后台任务通知
（`openprogram/runtime/jobs/notices.py`）：

- **入队。** 每条终态路径都经过 `JobRunner._update_attach_card`：先更新卡片，再执行
  `archive_when_done`，然后在投递 session（`caller_session_id or parent_session_id`）
  的 `notices.json` 里排一条通知。只有完成或出错的 `wait=False` job 才算：等待式
  job 已经把结果交给调用方，被取消的 job 是有意停下的。文件还记住最近 500 个已处理
  的 job id，同一个 job 的第二次终态投影不会再通知一遍。
- **消费。** 对终态 job 调 `job_output` 会把它的通知结清：调用方已经拿到结果，
  通知只会重复。`send_message` 的投递结果写明可以用 `job_output` 在本回合内等回复，
  需要立刻拿到回复的发送方不必去轮询目标。空闲的 `notify_when_idle` watch 直接
  交回目标节点的回复，并结清以该节点结束的已完成 job 的通知（`notices.consume_reply`）。
- **投递。** worker 循环 `run_job_notices`（在服务器 lifespan 里和进程退出通知一起
  启动）每 2 秒扫一次。session 里有任何不是后台 job 的未终态执行时算忙；派发待通知
  job 的那个 agent 还在跑时也算忙（它可能自己去读结果）。同 session 里在跑的后台
  agent 不算忙，所以等三个 agent 的会话会在每个结束时分别收到通知。空闲 session
  里积压的全部通知合成**一个**通知回合。
- **文本。** 通知写明它是自动通知，不是用户的消息。每个 job 给出 agent 名、结果、
  job id 和任务；spawn 的报告已经经 attach 指针进了上下文，投递给已有分支的回复
  则内联（上限 20,000 字符），并附上继续对话用的 `send_message` 地址。
- **空闲观察。** `send_message(to=..., message="", notify_when_idle=True)` 在发送方
  的 `notices.json` 里排一条观察。目标不再忙（`inbox.target_busy`，§5.4）时，观察变成
  一条带目标最新回复的通知并结清。

**attach 报告。** 调用方的上下文不接收子 agent 的完整记录。spawn 写的指针（不是 merge
的 `is_base` / `merge_temp`，也不是用户手动 attach 的 `manual`）由 context commit
generator 生成一条 user 角色 item（`reason="attached_report"`）：任务、最终回复
（指针的 `content`）和完整记录的 `read_conversation(session_id, head_id)` 地址。同步
spawn 已经把回复作为 `agent` 工具结果返回，所以它的指针（`delivery="tool_result"`）
只带地址。merge 和手动 attach 仍按 [上下文总览 §4](../../context/overview.zh.md) 完整展开。

## 3. 协作进行时是什么样

协作跑在框架统一的事件层上，所以过程是实时可见的，不是事后才知道。由此有四
个效果，用户和 agent 需要知道的就是这四条：

- **两边实时更新。** 投给另一个 session 的消息，落地那一刻就出现在那个
  session 的界面上；回复回来时出现在发送方的界面上。两边都不用刷新。
- **agent 之间的往来画成一行，不画成用户气泡。** agent 发出的东西都不会像
  用户自己打的字。发送方聊天里，发送就是工具自己那一行（「已发给 …」）。完成
  通知按每个跑完的 agent 画一行——「scout 已完成，结果交回主 agent」「分支
  「frontend」回复了」「分支「frontend」空闲了」——依据是 `notice_items` 盖在
  通知 user 消息上的 `notice` 条目；点开一行看回复（报告类看当初交给它的任务）。
  收件分支里，送达的消息画成一行，写明发送方（「主对话发来消息」），读自收据头
  `[message|task from SID:HEAD (发送方)]`。发送方是后台 agent 的 job 在发时取该
  agent 的名字，否则是主对话；收件方在另一个对话时用主对话的标题。投递的 job 以
  目标分支命名，所以回复那一行能写出是哪个分支回的。
- **全程留痕。** 投递、分支状态变化、列表查询都写进 session 的事件日志
  （`~/.openprogram/projects/<project-id>/chats/<sid>/events.jsonl`，始终开启），一次协作事后可
  以回放、可以审计。
- **投递可以被拦下确认。** 值守策略拒绝副作用时，`send_message` 在投递前被
  拦住等确认。子 agent 走同一个拦截点，`permission_mode=bypass` 关不掉它。

事件层本身（总线、事件模型、注册表、否决协议）写在
[proactive/event-layer](../../proactive/event-layer.zh.md)。


## 4. 端到端目标流程

1. 从 `list_agents` 或明确地址解析可见且获授权的已有目标。
2. 提交 `send_message` 或 `agent(to=...)`，分别确认收件箱接收和 Job 准入；准入拒绝返回原因，不声称已启动。
3. 目标在自身配置的上下文、资源限制与执行授权下运行。忙目标遵守共享串行/排队策略，发送方无需阻塞。
4. 对已准入的受管执行，先提交终态结果与 attach 状态，再按完成策略向发起方至多提交一次幂等非空 follow-up；失败或空输出不能产生无界回送循环。
5. 委派额度耗尽后，仍可授权读取 `job_output`/执行资源；新派发重新检查拓扑、资源、归档与授权限制。

自动回送接入是必须通过公开入口验收的项目，直接调用 helper 的测试不能证明该行为已完成。

## 5. 健壮性与安全

通信会创建分支、触发别的分支跑、跨 session 写，这些副作用必须有边界。

### 5.1 拓扑限制与精确超限行为

深度、消息计数和扇出限制协作拓扑，不等于 token 预算、session 累计准入或权限。[资源治理](../reliability/agent-resource-governance.zh.html) 单独定义 live/queued/累计数量及 token/cost/runtime/idle 限制。

| 限制 | 当前设置 / 默认值 | 范围与计数 |
|---|---|---|
| 派生深度 | `agent.max_spawn_depth=1` | 一条执行关系路径上的代数，仅新建分支增加 |
| 消息 | `agent.max_messages=8` | 一条执行关系路径上的消息深度；投递把发送方计数 +1 传给目标，不累加发送方同轮的兄弟调用 |
| 扇出 | `agent.max_spawn_fanout=8` | 调用方 `(session, turn)` 内新建分支数量，已有分支派发与消息不消耗 |

拓扑设置为 `0` 表示不执行对应限制检查，传递的上下文计数仍可存在。资源 schema 使用不同语义：`null` 表示未设置/继承，明确数值必须为正。不能将拓扑的 `0=不限` 套用到资源字段。

follow-up 原样绑定已完成 Job 的 `chain_messages`（多个 job 共用一条通知时取最大值），并恢复 `caller_chain_generations`，读取结果不额外加一次消息或代数。因此消息上限不是统计所有分支通信的共享累计额度。兄弟调用及累计工作量分别受扇出与 session 准入限制。

| 达到上限后的操作 | 要求的行为 |
|---|---|
| 新建分支时消息、深度或扇出已耗尽 | 拒绝这次创建并返回原因；被拒绝请求不创建分支或 Job |
| 消息耗尽后 `agent(to=B)` / `send_message(to=B)` | 即使不创建分支也拒绝这次投递；仅深度/扇出耗尽不阻止它们 |
| 已存在 Job、调用方当前轮次、非委派本地工具 | 不因达到拓扑上限就自动取消 |
| `job_output`、执行快照、`execution.cancel` | 在各自授权范围内继续可用；查询和停止不消耗委派额度 |

当前 `agent`/`send_message` 检查新投递限制。消息耗尽后 `job_output` 仍可用，并保留原有会话和祖先任务所有权检查。读取结果不增加消息计数、不创建投递。当前没有注册 `job_stop` 工具；UI/API 取消使用现有 `execution.cancel` 命令。

派生在三项中同时消耗消息深度、代数及调用方轮次扇出；已有分支派发只消耗消息深度，但仍须为新执行通过 §5.2 准入。后续独立用户轮次有新的拓扑上下文，已接受 Job 仍计入 session 累计资源数量。向自身当前分支投递另行拒绝。

默认值的参考对照保留在[协作对比](agent-collab-comparison.zh.html)，当前限制以源码和上述 schema 为准，不依据与其他产品的推定等价关系。

### 5.2 live、queued 与累计执行资源

资源检查在 §5.1 之外同时生效，不是对那三个计数器改名。

| 资源限制 | 计量对象 | 到达限制时 |
|---|---|---|
| `max_live_per_session` 与 `OPENPROGRAM_JOB_WORKERS` | 目标 session 活跃执行 / 全局 worker 容量 | 已准入 Job 无执行容量时保持 queued |
| `max_queued_per_session` | 已接受但等待执行容量的 Job | 队列满拒绝准入，`quota.queue_full` 通常可重试，不虚构 Job |
| `max_jobs_per_session` | 目标 session 成功准入 Job 的累计数，包含后来终态的 Job | `quota.jobs_exhausted` 拒绝；终态完成不归还累计数 |
| token / cost / runtime / idle | 执行及继承的预算范围 | 按资源治理执行预留、取消与计量 |

当前 governor 将 session 计数归属到 `Job.parent_session_id`，也就是实际执行所在 session。S→T 跨 session 调用记在 T；`caller_session_id=S` 表示调用来源，不会把准入账目静默改到 S。调用方轮次扇出和父预算范围仍是独立约束。因此 `max_jobs_per_session` 不是深度或扇出预算的别名。

后台创建、`agent(to=...)` 和 `send_message` 触发的实际异步轮次都会进入 Job 准入。目标忙的 `agent(to=...)` 在等待收件箱前已有准入 Job；普通消息则可能先只有回执，提交轮次时才准入。不能把回执展示成已接受执行，已有排队 Job 启动时也不能重复消耗累计准入数。

前台新建分支同样通过 `run_agent_turn` → `spawn_job(wait=True)` 准入 Job，因此计入 Job 资源限制。普通主聊天及其他直接 runtime 入口需要分别核对，不能仅凭“前台”一词判断是否计量。

拓扑限制设为零不关闭资源治理或取消。“一次派 30 个全部排队”不是通用保证，扇出、队列或累计限制都可能在进入容量队列前拒绝请求。

### 5.3 取消传播

复用 canonical execution 取消路径与 `parent_job_id` 执行关系。取消父执行须阻止尚未启动的后代，向活跃后代发出取消，并在确认实际退出前保持 stopping。撤回排队工作不能发出停止整个 session 的请求而中断其他执行。终态 Job 仍可查询，累计准入数不归还。

界面区分取消已请求与停止已确认。资源释放、worker 丢失、不可抢占操作及恢复以[资源治理](../reliability/agent-resource-governance.zh.html)为准；固定 watchdog 超时不能证明线程或子进程已经退出。session 级 Stop 比取消指定执行范围更大，撤回的收件箱投递必须留下明确结果。

### 5.4 发给"正在跑"的分支（竞态）

A 给 B 发消息时 B 可能正跑一轮。**不打断、不丢弃，排队。**忙判定是
`inbox.target_busy(target_session, head, sender_session)`：

- **跨 session 目标**：`run_control.is_turn_running(target)`。每个并发 turn 入口
  （webui chat、task runner worker）都在 finally 里成对注册/注销 cancel token，
  token 在场就是进程内"正有一轮在跑"的权威信号。条目以 `scope="session"` 入队。
- **同 session 目标**：发送方自己的 turn 总占着这个 session 的 token，所以只看被寻址
  的分支：未结束 job 的 `target_branch_head_id`、`head_id` 或 `parent_msg_id` 是该分支
  tip 时，`inbox.branch_busy` 为真。条目以 `scope="branch"` 入队，之后接在这条分支
  当前的 tip 上，不接 session 主 head。

- **入队**：目标忙时消息持久化到目标 session 的收件箱
  （`<session-repo>/inbox.json`，`openprogram/runtime/conversation/inbox.py`，与 `jobs.json`
  同一放置模式），记录投递全文、发送方 `SID:HEAD`、发送方 agent、发送时的
  链上的消息数、入队时间。发送方立刻得到"目标正忙，消息已排队，对方本轮结束后
  处理"。
- **消费**：`inbox.drain` 把目标此刻已空闲的条目（session 范围：没有在跑的轮次；
  branch 范围：分支不再忙）各经正常异步执行路径提交一轮，回复以完成通知（§2.7）
  回来。它在 turn 收尾时运行（`_process_turn_once` → `_drain_send_message_inbox`，
  成功和 error 两个 return 点都挂），worker 每 2 秒也扫一次，顺带接住没跑 drain 就
  结束的轮次（取消、崩溃、worker 重启）。收尾时还没就绪的条目等扫描。先投递后删除：两步之间崩溃可能重复投递（可接受），
  反过来会丢消息（不可接受）。排队这一跳和直投一样花消息预算（§5.1）。
- **上限**：每个目标最多积压50条，满了丢最旧并在被丢消息的发送方session落一条
  系统提示；同一发送方60秒内与仍在队列中的副本内容完全相同的消息按重复拒收，
  并告知发送方。50取自Claude Code同一结构的数字，它的跨会话信箱就是一个丢最旧的
  50条环，八家里也只有它有信箱可比。60秒这个窗口没有任何一家可对照：Claude Code
  按消息uuid去重，weclaw按收到的消息id去重，两者都只能拦住同一个消息对象被逐字
  重发，拦不住模型第二次写出同样的文字。这个检查只对仍在队列里的条目生效，所以窗口
  只界定一件事：发送方要等多久，同样的文字才算主动重发而不是重试循环。

B 空闲则立即投递（原有行为）。

### 5.5 失败回送

子/目标分支失败（崩溃 / 超时 / 模型报错）：**也回送**，回送内容带 `is_error` + 原因
（"B 失败了：<原因>"），发起方模型读到后自行决定重发/换路/放弃。不据此自动重派任务；新派发仍须满足授权与剩余限制，provider 传输重试沿用自身独立策略。

### 5.6 结果截断与全文存储

当前通用字符串/`ToolReturn` 规范化器默认上限为 30,000 字符，可按上下文容量进一步降低，保留头尾摘要，并可将 UTF-8 全文写入 `<state_dir>/tool_results/`，采用既有归属身份摘要与排他创建后缀组成的不透明独立 `.txt` 文件名。Provider 原始 call ID 可以重复；新保存不会覆盖旧 receipt 引用的文件。已有 receipt 路径保持可读，不改写旧文件。默认 profile 对应 `~/.openprogram/tool_results/...`，它是状态目录文件，不是系统临时文件。只有写入成功才返回路径，写失败不能虚构路径。

这还不是所有 Job 结果的统一保证：`job_output` 返回 `AgentToolResult`，共享规范化器直接传递而不截断；follow-up helper 也可能内联完整 `result_text`。从检查的 helper 无法确认自动 TTL/清理策略，也没有目标 session 文件 ACL。

目标结果契约让 `job_output` 与内联 follow-up 使用同一受限摘要，完整 canonical 结果仍保存在执行/session 存储。全文 artifact 记录执行 ID、所属 session/project、媒体类型、字节数与内容散列；读取使用与结果相同的可见范围检查。不展示路径不等于限制了通用文件系统访问。artifact 保留期跟随所属执行配置，归档本身不删除它。在资源与保留策略接入之前，只报告现有路径和未确认生命周期，不声称会自动过期或已隔离。测试覆盖结构化结果限长、落盘失败、授权后重读及保留文件清理。

### 5.7 配置、上下文与授权

`agent_id` 选择保存的执行配置，与分支身份分别表达。保存/临时配置覆盖和模型选择由 [Agent 配置](../agent-configuration/agent-configuration-ui.zh.html)定义，更换配置不能扩大调用方强制授权。clean 不继承对话消息，inherit 与精确 SID:MSG 只提供经过授权的选中历史；三种方式都不删除系统策略，也不建立文件系统隔离。调用方明确选择历史时，不能再一概声称子分支只看到 prompt。

### 5.8 值守拦截 + 校验

- 值守策略拒绝副作用时，`send_message` 在投递前被拦下等确认（§3）。子分支走同
  一个拦截点，`permission_mode=bypass` 关不掉它。
- `to` 指向不存在的东西就报错，不会静默新建。常规权限门控照常叠加在上面。

### 5.9 历史可见范围与归档授权

目标共享可见性策略覆盖 `read_conversation`、`start_from` 的来源历史、指定上下文、attach 展开及结果 artifact 读取。加载内容前核对调用主体和 project/session 范围。分支地址、保存 `agent_id` 或拥有工具本身不构成目标访问授权；拒绝目标后不能通过降级读取泄漏预览、标题或存在性。归档需相应生命周期权限，并改变全局保存的分支状态（§2.6）。

当前 `read_conversation` 解析 session/head 后读取本地分支，没有目标级 owner/project ACL。工具能力检查因此只是较宽的本地信任范围，不代表逐 Agent 隐私隔离。历史读取和归档工具接入共享授权之前，不能声称不同 Agent 或用户的数据已隔离。“内部”分支标记仅控制 UI 展示，不是授权边界，也不禁止 `agent(to=...)` 寻址其他条件满足的分支。

### 5.10 结果归属与执行控制

当前 `job_output` 使用 `_ownership.check_job_ownership`：session 属于 Job 的执行 session（`parent_session_id`）、caller session 或祖先关系时允许读取。helper 最多检查 64 层祖先并防止循环；没有当前 session 上下文时不返回拒绝，这个 helper 本身不负责用户或 API 身份认证。

Canonical execution 读/控制有独立的已有授权边界：检查 owner 权限、目标 project/session、动作授权和所需 capability，控制要求 `runtime.control`。`execution.cancel` 使用当前执行版本与 command ID，不是 `job_stop` 别名。知道 execution ID 不获得控制权。§5.9 的历史策略复用这套授权框架，不假定能读本地分支就拥有执行控制权。

取消规则由[执行控制](../execution/control.zh.html)与[资源治理](../reliability/agent-resource-governance.zh.html)定义。排队取消阻止该执行启动，不停止同目标上无关的轮次；运行取消进入 stopping，确认退出后才释放资源；终态取消幂等。不能保证任意 Python 线程立即消失，也不能把取消请求被接受当成已停止证明。

### 5.11 明确不做（及理由）

- **parentID 额外字段**：`(session_id, head_id)` + caller/predecessor 已构成树，DAG
  已画，不再加冗余字段。
- **ID 前缀分类**（fork_/msg_）：现有 id + name 足够寻址，不加。
- **重试 / 熔断策略**：失败回送给模型，由模型决定，不内置固定策略（见 §5.5）。
- **内置聚合函数**（投票 / 全部成功等）：综合就是在 `message` 里点名分支、让目标
  模型自己读完综合（§2.2），模型综合比预设聚合灵活，不做固定聚合算子。


## 6. 公开入口验收

下列是必须观察到的行为，不表示所有场景已经验证通过。

| 场景 | 可观察结果 |
|---|---|
| C1 名称与身份 | 注册工具为 `list_jobs`/`job_output`；前后台均准入 Job；取消使用带版本的 execution command |
| C2 fork 并执行 | 一次 `agent(start_from="T:M", prompt=..., description=...)` 在 M 创建分支并执行 prompt；to 不创建缺失目标 |
| C3 全局归档 | A 归档 B 后，C 普通列表也隐藏 B；归档视图保留记录，新投递拒绝；保留历史不代表获得读取权限 |
| C4 完成归档 | 手动先发生、终态先发生及重试均保留首次时间戳/手动原因；归档不取消活跃工作；异步公开完成路径实际执行归档策略 |
| C5 拓扑耗尽 | 消息耗尽拒绝 agent(to=B)，不取消已接受工作；深度/扇出耗尽仅拒绝新建分支；授权查询和取消保持可用 |
| C6 资源交互 | 跨 session 在目标侧计准入；queue-full 与累计满错误不同；排队 Job 不重复计数；同步 Agent 同样受准入约束 |
| C7 attach 位置 | 卡片留在 S，结果按 (T,H) 读取；完整 AttachCard 与 execution strip 都选中精确目标 head，不在 S 查 H |
| C8 历史隐私 | 拒绝 read_conversation、历史 fork、指定上下文和 attach 展开时不泄漏目标内容/元数据；获准场景正常工作 |
| C9 全文结果 | 结构化 Job 结果和内联 follow-up 都限长，全文仅经授权重读；写失败不返回假路径；保留策略只清理有权处理的自有 artifact |
| C10 完成通知 | 从公开异步 Agent/消息入口到 canonical 完成后，预期 follow-up 仅触发一次；空结果、重试、失败、取消不产生无界后续轮次 |

## 7. 实现状态与依据

下表记录源码目前实现了什么，以及还需要通过公开工具入口验收的部分。仅有 helper 测试或函数定义不能证明公开入口已接入；资源验证由关联资源设计负责。

| 范围 | 源码现状 | 剩余验收 |
|---|---|---|
| 命名 / 前台准入 | 注册 list_jobs、job_output；同步 run_agent_turn 与异步 wrapper 都调用 Job 准入 | 工具、UI、文档 schema 保持一致，不恢复已删除 stop 别名 |
| fork / 全局归档 | 已有一步历史 fork 与全局归档字段 | 手动/自动写入保留首次元数据，验证排队投递重查 |
| 异步回送与自动归档 | 每条终态路径都调用 `_update_attach_card`，执行 `archive_when_done`（保留先发生的手动 `archived_at`）并排完成通知；服务器 worker 投递通知和空闲观察（§2.7）。单元测试覆盖入队、消费、合并、忙判定和观察 | 在运行中的 worker 里走公开工具入口做端到端验收 |
| 回合中途投递 | 发给忙 agent 的消息等它这一轮结束，不插进正在跑的轮次的工具调用之间 | 把 agent 消息 steer 进运行中的执行，需要执行命令路径支持非用户 actor |
| 消息耗尽 | 新委派受限，job_output 也被相同 gate 隐藏 | 耗尽委派额度仍保留授权结果读取/控制 |
| 历史可见范围 | read_conversation 读取本地存储，没有目标级 owner/project ACL | 接入共享可见性并验证所有消费历史入口 |
| 跨 session attach | 数据/UI 已区分源位置与目标查找；完整卡片跳转未明确选择 H | 与 execution strip 对齐精确 head 跳转并验证两种入口 |
| 结果截断 | 通用字符串 wrapper 落盘；结构化 Job 输出与内联 follow-up 未统一限长 | 接入统一截断、授权 artifact 和明确保留策略 |

源码依据：

- [Agent tool](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/agent/agent/agent.py)
- [Synchronous and asynchronous admission](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/conversation/sub_agent_run.py)
- [Archive](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/send_message/archive_agent/archive_agent.py)
- [Message delivery](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/send_message/send_message/send_message.py)
- [Job output](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/agents/agent/job_output/job_output.py)
- [History read](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/tools/knowledge/read_conversation.py)
- [Execution authorization](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/execution/authorization.py)
- [Completion helpers](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/jobs/runner/progress.py)
- [Canonical completion](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/jobs/runner/dispatch.py)
- [Borrowed-claim completion](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/jobs/runner/borrowed.py)
- [Result persistence](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/programs/_host/execution.py)
