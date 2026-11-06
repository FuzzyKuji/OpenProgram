# 常驻 Agent

常驻助手在用户不在场时持续工作：持有一个常驻目标，按计划唤醒，没有任务时做只读调研，并报告发现。参考产品是 OpenAI 的 dots 和 xAI 的 Grok Bot：两者都给一个 agent 持久目标、独立的工作场所、随反馈改进的记忆，以及“哪些事可以自己做”的规则。

OpenProgram 用现有部件构建它，并沿用产品其他部分的分工：Agent 是配置，会话是工作发生的地方。常驻是已保存 Agent（`AgentSpec`）的 `always_on` 分区。使用该 Agent 的每个会话就是一个常驻助手：它自己唤醒，有自己的目标、巡检、[未完成事项](../../../capabilities/agents.zh.md#未完成事项)和报告，使用该 Agent 的模型、指令、工具、记忆空间和会话的权限规则。会话之外没有单独的助手对象，Agent 之外也没有单独的设置。常驻相关代码（`openprogram/runtime/conversation/always_on/`）只负责决定哪些会话何时唤醒、每次唤醒做什么、报告送到哪里。

## 组成

| 部件 | 位置 | 复用 |
| --- | --- | --- |
| 配置 | `agent.json` 中的 `AgentSpec.always_on` | Agent 管理与带 revision 的保存 |
| 助手本身 | 使用该 Agent 的每个用户会话 | 会话存储与聊天界面 |
| 常驻目标 | 会话里的一个聊天目标 | 目标续跑、验证与预算 |
| 唤醒调度 | `openprogram/runtime/conversation/always_on/ticker.py`，worker 线程 | worker 服务启动 |
| 安静时段与唤醒的日子 | `openprogram/runtime/conversation/always_on/schedule.py` | 本地时钟 |
| 巡检轮次 | 只带只读工具列表的普通一轮 | `owner_turn.start_owner_turn`、`TurnRequest.tools_override` |
| 报告 | `always_on_report` 工具、会话的报告文件、`always_on_report` 帧 | 桌面通知桥 |
| 渠道投递 | `openprogram/runtime/conversation/always_on/delivery.py` | `channels.outbound.send_full`、绑定、渠道会话 |
| 团队交接 | `handoff` 工具、`openprogram/runtime/conversation/always_on/handoff.py` | 唤醒型提醒的路径：`owner_turn.start_owner_turn_when_free` |
| 学习 | Agent 自己的记忆空间 | 记忆策略与会话结束时的提取 |
| 规则 | 会话的权限模式与规则 | 权限规则、授权卡片 |
| 状态与立即唤醒 | 会话的运行记录面板 | 运行记录的条目和页面 |

## 配置

`always_on` 是 Agent 配置的一部分，因此通过 Agent 编辑器的同一份草稿和 revision 检查保存：

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | 使用此 Agent 的会话按计划唤醒 |
| `goal` | 字符串，最多 4000 字符 | `""` | 常驻目标；为空表示只巡检 |
| `wake_minutes` | 整数，5–10080 | `60` | 两次计划唤醒的间隔 |
| `research` | bool | `true` | 没有未结束的目标时进行巡检 |
| `autonomy` | `"report"` 或 `"act"` | `"report"` | 巡检能否自行开始目标 |
| `channels` | `{channel, account_id, peer_id, label}` 列表，最多 10 个 | `[]` | 同时收到每条报告的渠道会话 |
| `quiet_hours` | `{start, end}`，两个不同的本地 `"HH:MM"` 时间，或 `null` | `null` | 每天不做计划唤醒的时段；结束早于开始表示跨过午夜 |
| `wake_days` | 非空的星期列表，周一 `0` 到周日 `6` | 全部七天 | 允许计划唤醒的日子 |

`agent_registry/manager.py` 中的 `validate_always_on()` 像 `validate_memory_config()` 规范化记忆配置那样规范化这个分区。没有这个分区的旧 `agent.json` 按关闭加载。复制 Agent 时会复制这个分区，但强制关闭 `enabled`，副本不会自己开始唤醒。

## 运行状态

运行状态与配置分开存放，唤醒不会增加配置 revision，也不会和编辑器中打开的草稿冲突。

每个会话在自己的会话目录里、消息旁边保存自己的状态：

- `always_on.json`：`joined_at`、`applied_goal`（最近一次按配置启动的目标文本和目标 id）、`last_check_in_at`、`last_wake`（`at`、`reason`、`outcome`）和 `next_wake_at`。
- `always_on_reports.jsonl`：每行一条报告（`id`、`at`、`title`、`body`、`links`、`session_id`，选了渠道时还有 `deliveries`），只保留最新 200 条。

Agent 只保存一件事：`<agent dir>/always_on/state.json` 中的 `enabled_at`，即调度器第一次看到常驻开启的时间。常驻关闭时清除。

交接链跨越多个会话，所以 worker 把它们存在同一个文件 `<state dir>/always_on/handoffs.json` 中（见[交接](#交接)）。

所有文件都在每个会话一把的锁下原子写入（`enabled_at` 是每个 Agent 一把，交接文件单独一把）。删除会话时，它的状态和报告随之删除。

## 哪些会话会唤醒

一个会话满足下面两点就会唤醒：它是常驻 Agent 的用户会话，并且已经加入。

- **用户会话**：未归档，并且是网页聊天（source 为空或 `web`）、渠道会话，或旧版本留下的常驻会话（source `always_on`）。子代理会话（`agent`）和导入的会话不会唤醒。
- **已加入**：已有唤醒状态，或在 `enabled_at` 之后有过更新，或刚被换成这个 Agent。`POST /api/sessions/{id}/agent` 调用 `join()`，把第一次唤醒排在切换后一个间隔。调度器记录 `joined_at`，并把第一次唤醒排在一个间隔之后，所以刚打开的对话不会被打断；开启常驻后没人用过的会话保持安静。因此给 Main 开启常驻也不会唤醒所有旧对话。

归档会话就是停止它的方式，不需要单独的设置。重新开启常驻时，`next_wake_at` 早于新 `enabled_at` 的会话从那一刻起重新计算间隔，而不是立刻唤醒。

旧版本每个 Agent 只有一个常驻会话，状态存在 `<agent dir>/always_on/state.json`。常驻被看到开启后的第一次调度时，`_adopt_home()` 把这些状态（`applied_goal`、`last_check_in_at`、`last_wake`、`next_wake_at`）复制到那个常驻会话里，之后它像其他会话一样唤醒。

## 唤醒

`wake(session_id, reason)` 在每次计划调度和 **立即唤醒** 时运行。它总会记录 `last_wake` 并安排下次唤醒：`next_wake_after()` 取 `now + wake_minutes`，再用 `schedule.next_allowed()` 顺延到安静时间之外的第一个时刻。一次唤醒最多做一件事，按以下顺序判断：

1. **disabled**：会话的 Agent 关闭了 `always_on.enabled`。计划唤醒到此为止；**立即唤醒** 会被拒绝。
2. **quiet**：计划唤醒（不是 **立即唤醒**）落在安静时段，或落在 `wake_days` 不包含的日子；这发生在计划早于设置保存、或时钟变动时。不启动任何东西，下次唤醒就是安静时间结束时。
3. **busy**：会话里已有一轮正在运行，或在巡检之前有另一轮抢到了运行位。不启动任何东西。
4. **goal started**：常驻 `goal` 不为空且与会话的 `applied_goal` 不同，并且会话中没有未结束的目标。运行时用这个目标创建聊天目标（`origin: "always_on"`），并通过 `goal.chat.start_from_controls()` 启动。之后由普通的目标续跑一轮轮推进，由验证决定是否完成。这种目标的续跑轮和验证轮都带上 `goal.chat.STANDING_GOAL_NOTE`：常驻目标是一个目标，条件一旦满足就算完成，周期性的事交给 check-in。没有这句时，写成例行事务的常驻目标（“检查构建并汇报”）永远不会被提交完成，目标每一轮都重复那次检查。
5. **goal in progress** 或 **goal paused**：有未结束的目标。唤醒不去碰它：自动续跑属于目标运行时，用户的暂停也不会被覆盖。
6. **check-in**：开启了 `research`。运行时启动一次巡检（见下文）。
7. **idle**：无事可做。

安静时间只拦住计划唤醒：正在运行的目标会继续，交接和 **立即唤醒** 照常运行。`schedule.py` 读取 worker 的本地时钟：星期不在 `wake_days` 里，或一天中的时间落在 `[start, end)`（`end < start` 时跨过午夜）的时刻是安静的。安静时间只会在午夜或 `end` 结束，所以 `next_allowed()` 检查之后八天里的这些边界。

所以修改后的常驻目标会在每个会话的当前目标结束后生效。用户可以在会话里结束当前目标（`/goal clear`）来立即切换。

## 巡检轮次

巡检是会话中一轮普通的用户聊天（source `web`），使用会话自己的权限模式和规则，所以目标续跑、验证和授权卡片对待它和用户自己发起的聊天完全一样。它的提示写明上次巡检的时间、常驻目标和自主设置，并要求 agent：

- 回顾记忆、未完成事项和会话中的未完事项；
- 只用只读工具查找与目标有关的新情况；
- 发现用户应当知道的事时调用 `always_on_report`，否则保持安静。

`tools_override` 把这一轮限制为只读工具：`read`、`grep`、`glob`、`list`、`web_search`、`web_fetch`、`read_conversation`、`memory_search`、`memory_get`、`todo_list`、`open_work`、`get_goal` 和 `always_on_report`。`autonomy="act"` 时再加入 `create_goal`、`todo_create`、`todo_update` 和 `handoff`，agent 可以把发现转为自己的目标，之后按普通工具和权限执行，或者交给负责它的会话。不包含 MCP 工具，因为无法仅凭名称判断某个服务器工具是否只读。`open_work` 只写会话自己的清单。

按名称给出的单轮工具列表会带上每个工具的完整 schema（`model_tools.resolve_tools`）：列表里没有 `tool_search`，延迟加载的工具否则永远加载不到。巡检用到的读取工具和报告本身（`get_goal`、`read_conversation`、`always_on_report`）在权限分类器的安全清单上，所以在“询问”或“自动”模式下无人值守的巡检不会停在授权卡片或审查调用上。`act` 额外加入的工具仍遵循会话的权限模式。打开的浏览器 Page 会给一轮加上屏幕工具（`loop_runner._configure_web_use_tools`），但按名称给出工具列表的一轮只有列表里有它时才会拿到：曾有一次巡检拿到了它，然后停在没人回应的“录屏”权限提示上。

## 报告

`always_on_report(title, body, links)` 属于单独的 `always_on` 工具集，不在默认工具集中。`loop_runner` 只在 Agent 设为常驻的会话中提供它（用 `agent_for_session()` 判断），其他地方都会移除；在其他地方调用会被拒绝。报告追加到会话的报告文件，并以带 `session_id` 的 `always_on_report` 帧广播。桌面端通过现有的提醒桥把这个帧变成系统通知（类型 `report`，以报告 id 为键，只在没有 App 窗口处于焦点时显示）。点击通知会打开对应会话。报告也作为产生它的工具调用留在会话记录里，并列在运行记录面板中。它还会立即给会话标上侧栏的未读圆点：`turn_writer.mark_session_unread()` 设置 `unread` 并广播一行 `session_updated`，除非有客户端正显示这个会话；这与一轮结束时 `mark_session_finished()` 的规则相同。巡检轮次启动时带 `TurnRequest.quiet_finish`，所以它结束时只记 `done`，不动 `unread`：只有报告会标未读，没有发现的巡检不留圆点。`last_wake` 照常记下 `check_in` 结果供运行记录面板显示，失败的巡检仍会得到红点。

## 交接

多个会话通过 `handoff(to, message)` 组成团队，它属于 `always_on` 工具集。`loop_runner` 在提供 `always_on_report` 的地方提供它，但不移动 head 或从其他会话派生的一轮（子代理的一轮）除外。`to` 是会话 id 或完整标题（不区分大小写）；标题有歧义时拒绝并列出匹配的 id，找不到时列出用户的会话。目标会话可以使用任何 Agent。

`handoff.send()` 做完检查后立即返回，投递在守护线程中进行：

1. 目标会话通过 `owner_turn.start_owner_turn_when_free()` 得到一轮唤醒，这是唤醒型提醒使用的同一路径：最多等十分钟让正在运行的一轮结束，然后占用会话的运行位，按目标自己的 Agent 和权限设置运行。这一轮的文本以 `📨 Message from “<发送方标题>” (<发送方 id>):` 开头，并说明回答会自动送回。
2. 这一轮结束后，它的最终文本作为另一轮唤醒回到发送方，以 `↩️ Reply from “<目标标题>” (<目标 id>)` 开头。回复不需要回答，也不会再触发回复。
3. 目标在等待期过后仍然忙时，发送方会收到一轮 `↩️`，把未送达的消息退回。

两种行在会话记录里都是普通的用户消息，和提醒的 ⏰ 唤醒一样。防止循环：发送方和目标都必须是用户会话（不是子代理、导入或已归档的会话），发送方的 Agent 必须是常驻的，目标不能是发送方自己，并且一条链带有跳数。每个交接和回复轮次都以已知的用户消息 id 启动，`handoff.py` 把它映射到所属的链和跳数；从这样的一轮发出的交接（工具读取 `TurnRequest.user_msg_id`）再多一跳，第五跳会被拒绝（`MAX_HOPS = 4`）。其他任何一轮都开始一条新链。`handoff` 不在安全清单上：“询问”模式下发送要等授权，“自动”模式下会经过审查。

交接链在 worker 重启后仍然有效。每个链上的轮次是 `handoffs.json` 中以用户消息 id 为键的一项：`chain`、`hop`、`origin`（发起这条链的会话）、`handoff_id`、`session_id`、`at`、`boot`（启动它的 worker 进程）、`phase`（`waiting`、`running` 或 `done`），交接轮次还有 `reply_to`，即它还欠回答的发送方。每次变更都重写整个文件，并丢掉超过一天的项；`ticker.start_in_worker()` 通过 `handoff.restore()` 加载它。被重启打断的一轮会以带 `restart_resume` 的新一轮继续，消息 id 是新的。在这一轮里工具传 `resumed=True`，链取该会话中更早 worker 留下的最新 `running` 项，所以跳数接着算。这一轮结束时（成功或失败），`turn_runtime` 调用 `handoff.resumed_turn_ended()`，把这些项标为 `done`，并发出每一项欠的回复。回复在发出前在锁内从所在项中取走，不论走这条路径还是在线的 `on_done`，所以最多发出一次。

## 内置 Agent

Grok Bot 自带 bot 模板：一个助手只做一件事，每个模板有职责、交付物、边界、完成条件和第一个任务，并互相交接工作。这里的模板就是**内置 Agent**：`agent_registry/builtin_agents.py` 里的完整配置，安装后是普通的已保存 Agent，和其他 Agent 一样显示在 Agents 页上。没有单独的目录、选择器或团队对象；Agents 列表就是模板列表，新建 Agent 对话框创建的是空白记录。它们参考的资料见 [Bot 模板参考资料](agent-configuration/bot-template-references.zh.md)。

安装操作是 `create_builtin_agents()`。注册表索引带有 `builtins`，即这个实例曾经安装过的 id（`manager.installed_builtins()`、`manager.record_builtins()`）；该函数创建既未保存也不在该列表上的内置 Agent，已有记录连同修改原样保留，然后记录全部内置 id。因此用户删掉的内置 Agent 不会被重建。服务在启动序列里运行它，但只在已有默认 Agent 时运行，因为第一条被创建的记录会成为默认，而默认必须是 Main；setup 在创建 Main 之后紧接着运行它。读取注册表从不安装任何东西。

三个内置 Agent 是没有提示词的固定参数专用 Agent（决策、轻量助手、统筹规划）。各个职能 Agent 包含：

- 固定形状的 system prompt：`Job`、`Deliverable`、`Never`（列表）、`Done when`、`Working style`（列表，末尾说明如何把一步交给另一个 Agent 的会话）和 `First task`。提示词两种语言下都是英文；名称和描述是双语的，安装语言决定记录用哪一种。
- 只列内置工具的 `selected` 工具策略，保证全新安装也能用。实现可以编辑；评审没有 `edit`、`write`、`apply_patch`。
- 在 Agent 自己的空间（`self`）上的记忆模式：工程类关闭，写作类只读，需要学习用户偏好的读写。
- 常驻默认值：`enabled` 关、`autonomy: "report"`，以及按 Agent 设定的 `research` 和 `wake_minutes`（收件箱分拣 30，统筹助理 120，研究简报 240，求职侦察 720，知识库管理 1440；工程类和文稿关闭巡检）。
- `hold_outbound` 开启，Agent 替用户发出的内容一律先作为草稿等待。

内置 Agent 通过会话之间的[交接](#交接)协作；安装不创建会话和标题，这由用户完成。

模板所说的自主等级映射到已有控制，不新增字段：只观察是 Ask 模式下 `always_on.research` 开、`autonomy: "report"`；起草是同样设置加 `hold_outbound`（默认）；经批准行动是 Ask 模式下 `autonomy: "act"`，每个对外动作都是审批卡；无人值守的定时工作是 Auto 模式下 `autonomy: "act"` 加常设 `goal`。

## 渠道投递

`always_on.channels` 列出同时收到报告的渠道会话，适用于这个 Agent 所有会话的报告。`channel` 取 `telegram`、`slack`、`discord` 或 `wechat`。`peer_id` 是渠道传输需要的目标：与渠道会话存储的 id 相同，所以 Slack 或 Discord 的目标是带作用域的 `<channel>_<user>` id。`validate_always_on()` 拒绝未知渠道和空 id，并去掉同一 (channel, account, peer) 的重复项。

常驻标签页的可选目标来自 `delivery.channel_targets()`，由 `GET /api/agents/{id}/always-on` 以 `channel_targets` 返回：

- 此 Agent 的渠道会话（带 `channel`、`account_id`、`peer_id` 的会话行），以对方的显示名作为标签；
- 此 Agent 的联系人绑定。没有指定账号的绑定会展开为该渠道的每个账号。

绑定到整个渠道或账号的绑定没有指定联系人，在有人和 Agent 在那里聊天之前不会提供目标。

Agent 有目标时，`runtime.report()` 保存报告时为每个目标写一行状态为 `sending` 的 `deliveries`，照常广播，然后调用 `delivery.deliver()`。它在后台守护线程中发送，工具立即返回；重试和限流可能需要几十秒。线程通过 `channels.outbound.send_full()` 给每个目标发一条 Markdown 消息：加粗的 `<Agent 名称> · <标题>`、正文，然后把链接列成列表。渠道传输按各平台渲染并拆分长文本。每一行变为 `sent`，或 `failed` 并附上传输层的 `error_kind` 和一行 `detail`；异常记为 `unknown`。线程随后用 `store.update_report()` 写回这些行，并广播带会话 `session_id` 的 `always_on_update`，让打开的运行记录面板刷新。发送失败不会删除报告，也不会让工具失败。

## 从反馈中学习

agent 通过 Agent 配置的记忆学习。把长期记忆设为 **读写** 并选 **此 Agent** 时，会话结束时的写入器会把会话中的偏好和纠正提取到 Agent 自己的空间，之后每一轮都会读回。一个会话欠用户的事留在这个会话的未完成事项里；所有会话都该知道的事写进记忆。记忆不是读写时，常驻标签页会提示，但从不自行修改记忆设置。

## 规则

agent 能自己做什么，取决于会话的权限模式加上已保存的权限规则，和每个会话的控制方式一样。某一轮需要的授权会以授权卡片在会话中等待，并发出需要输入的通知。巡检不增加任何权限，只收窄工具列表。

## 调度

`ticker.py` 随 worker 的其他服务启动。每 30 秒，对每个开启 `always_on.enabled` 的 Agent：缺少 `enabled_at` 时记录它，列出 Agent 的会话（每个 Agent 最多 500 个），让新符合条件的会话加入，并唤醒 `next_wake_at` 已过的会话。它和 `join()` 写入的每个 `next_wake_at` 都已顺延过安静时间。worker 重启后沿用已保存的计划，不会一次唤醒所有会话；每个会话的锁保证同一会话不会同时运行两次唤醒。对关闭常驻的 Agent，它清除 `enabled_at`。

## 界面

- **Agents → 常驻 标签页**：只有配置：上述字段和可选的渠道目标。
- **运行记录面板**：Agent 设为常驻的每个会话有一行 **常驻**，显示正在做什么和下次唤醒（安静时段拦住唤醒时会标明）。它的页面显示常驻目标、当前目标、唤醒的日子和安静时段、上次唤醒及结果、各条报告及其投递情况，以及 **立即唤醒**。`status()` 返回已顺延过安静时间的 `next_wake_at` 和 `quiet_now`。
- **HTTP**：`GET /api/agents/{id}/always-on` 返回已保存的配置和 `channel_targets`；`PATCH /api/agents/{id}` 像其他分区一样接受 `always_on`。`GET /api/sessions/{id}/work` 返回会话的常驻状态和报告，以及它的未完成事项和定时任务；`POST /api/sessions/{id}/always-on/wake` 立即唤醒它；`POST /api/sessions/{id}/agent` 供输入框的 Agent 按钮更换会话的 Agent。
- **WebSocket**：`always_on_report` 和 `always_on_update` 帧带 `session_id`。
- **Python**：`openprogram.runtime.conversation.always_on` 提供 `wake()`、`status()`、`report()`、`join()`、`agent_for_session()` 和 `channel_targets()`；`always_on.handoff.send()` 发出交接，`always_on.schedule` 提供 `is_quiet()` 和 `next_allowed()`。

## 替代方案

与本设计比较过的开源常驻 agent：Daimon（MIT 骨架，定时后台巡检，只在有事时开口）、Gobii（每个 agent 自己的计划，短信、邮件、webhook 和 cron 触发）、aidaemon（后台守护进程，目标调度加心跳检查）和 OpenClaw 用 `HEARTBEAT.md` 文件驱动的巡检。OpenAI Codex 的持久模式在休眠前记录目标、状态、完成标准和下次巡检时间；ChatGPT 的定时任务把任务和进行中的目标配对；Claude Code 的 routines 在云端按计划运行。它们的形状和本设计一致：会结束的目标、由代码而不是模型决定的周期巡检、只在有话说时汇报。没有一个作为代码复用，因为它们各自是围绕一个聊天渠道的独立产品，而这里需要的部件（目标、所有者轮次、报告、权限规则、渠道）本来就有。

本设计对照的三款桌面 agent 产品，在这里关心的两个问题上各自的做法：

| | Claude Code | Codex | DeepSeek Harness | OpenProgram |
| --- | --- | --- | --- | --- |
| 你不在时的工作 | Routines：在云端按计划运行；没有常驻目标 | 持久模式：休眠前写下目标、状态、完成标准和下次巡检时间；Automations 在本机按计划运行任务 | 定时任务插件（实验性）：延迟、绝对时间、至少一分钟的间隔、每日、每周或带 IANA 时区的 cron；每次运行是一条送回原对话的指令；只在 App 开着时运行，不能暂停 | 常驻 Agent：每个对话一个常驻目标，巡检由代码决定，只在有话说时汇报，送到渠道，有安静时段 |
| 查看计划 | routines 列表 | automations 列表；没有日历 | 自动化任务页，显示投递记录；没有日历 | 调度器页：列表加日历（月、周、日、议程），用开源组件 Schedule-X 原样绘制 |

它们彼此一致而与本设计不同的地方，本设计跟随它们：常驻目标是一个会结束的目标，不是重复的例程，Codex 的持久模式和 ChatGPT 的“任务配目标”都是这样做的。它们比本设计单薄的地方（没有代码决定的巡检、不送渠道、没有日历），本设计保留自己的选择。DeepSeek Harness 没有常驻目标或后台 agent，没有可借用的形状。

两个参照产品逐项对照，以及这里由什么承担：

| 能力 | Grok Bot | dots | 这里 |
| --- | --- | --- | --- |
| 每个助手一件事 | 每个 Bot 只有一项工作 | 一个带目标的个人助手 | `always_on.goal`：每个会话一个常设目标，作为 Goal 启动，由验证判定完成 |
| 按计划工作 | 例程（routines） | 按节奏主动研究 | `wake_minutes`、`wake_days` 和 `quiet_hours`；ticker 唤醒每个已加入的会话 |
| 翻看自己知道的东西 | — | 记忆、历史对话和已连接的应用 | 巡检用 `memory_search`、`memory_get`、`read_conversation`、`open_work`、`web_search` 和 `web_fetch` 读取；MCP 工具不在其中 |
| 先开口 | 消息落在 Bot 自己的聊天里 | 给用户发消息 | `always_on_report`：报告在会话里、未读点、桌面通知，以及 Agent 的渠道目标 |
| 助手之间协作 | Bot 之间互发消息、交接工作 | — | owner 会话之间的 `handoff(to, message)`，有跳数上限 |
| 自己少做事 | 外发邮件和 Slack 作为草稿等待批准 | 保守的只读默认 | 默认 `autonomy: "report"`；巡检的工具是只读的；`handoff` 和 `act` 下的一切都遵循会话的权限模式和授权卡片 |

## 实现状态

已实现：配置、按会话的唤醒与状态、服务启动时安装的内置 Agent（`builtin_agents.py`）、开启后使用即加入、旧常驻会话的迁移、巡检、带桌面通知和未读圆点的报告、渠道投递、安静时段与唤醒的日子、会话之间的交接（交接链在 worker 重启后仍有效）、调度器、HTTP、Python API、配置标签页以及运行记录面板的常驻页面。

在运行中的实例上按上表逐项核对过：常设目标会启动一个 Goal，之后的唤醒报告 `goal_in_progress`，完成后报告 `idle`；一个被要求每次都报告的 Agent 的巡检只调用了 `always_on_report` 一个工具，写出报告，并给没人打开的会话加上了未读点；覆盖当前时刻的静默时段让 `quiet_now` 为真、把下一次唤醒推到静默结束，而**立即唤醒**照常运行；交接能到达目标，回复也能回来。在上面的屏幕工具规则之前，有一次巡检调用了 `computer_use_agent`，停在“录屏”权限提示上，此后每次唤醒都报告 `busy`，直到那次执行被取消；暂停的一轮按设计仍会阻塞唤醒，所以巡检绝不能拿到会等待 owner 的工具。

未实现：

- 每个会话专属的云端电脑。工作在本机运行，使用会话的工作目录和沙箱。
- worker 重启时仍在等忙碌目标的交接，或仍在等忙碌发送方的回复，不会投递；发送方忙了十分钟而没送出的回复也不会再次投递。
