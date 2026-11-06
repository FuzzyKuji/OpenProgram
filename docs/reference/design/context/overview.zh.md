<div id="context-上下文层"></div>

# 概览

**上下文层决定每次调用时模型读到什么。** 每条用户消息、每次模型调用和工具调用都是会话执行 DAG 里的一个节点。每次调用不重放一份越来越长的对话记录，而是渲染这些节点中的一部分：它所延续的那条分支，旧的工具输出被缩短；窗口快满时，最早的若干轮被一段摘要替代。结果是一个 `Context`（system / messages / tools），由[模型服务层](../providers/README.zh.md)翻译成各家的线路请求。本层决定**喂什么、怎么分层**；providers 决定**怎么发出去**。

> 每次调用如何按稳定度分层、如何让模型知道自己的处境，见
> [`composition.md`](composition.zh.md)。数据模型和渲染规则见
> [`../runtime/dag/overview.md`](../runtime/dag/overview.zh.md)；压缩见 [`compaction.md`](compaction.zh.md)。
> 本文是把它们串起来的总览。

---

## 一、组装链路

主聊天路径有一个上下文组装引擎（`openprogram/runtime/context/engine.py`）：

```
process_user_turn  (openprogram/runtime/conversation/turn_runtime/)
  → engine.prepare()            ← 产出 TurnPrep
      1. 引用扫描（之后被引用的 tool_use id）
      2. 从 DAG 渲染历史：确定 head → render_context → render_dag_messages
      3. 取调用方组装好的 system prompt（身份 + AGENTS.md 链 + 技能 + 工具）
      4. 计算 token 预算（system / history / tools / 输出预留）
      5. 用量对账（上次 provider 实测 + 之后新增部分的本地估算）
      6. 返回 TurnPrep
  → 预算 ≥ 80%? → engine.compact()（内联，由 LLM 写摘要）
  → agent loop → Context(system, messages, tools) → provider
       └ provider 报上下文溢出 → 反应式压缩，重试一次
```

DAG 渲染是唯一的管线，没有兜底组装路径。渲染失败时这一轮明确报错，而不是悄悄发出一个形状不同的 prompt。

**主路径与辅助路径**：主路径之外，几个功能各自发起单次 LLM 调用（总结、记忆整理、分支总结、mixture-of-agents）。它们绕过 `engine.prepare`，自己构造最小的 `Context`（基本就是一段 system prompt 加一条用户消息，不带工具）。这是有意的分层——这些调用不需要完整的聊天上下文。

---

## 二、存储模型：DAG

对话历史就是会话 DAG，存在基于 git 的会话存储里（`openprogram/state/store/session/`）。它只追加，任何规则都不改写节点。

### 节点

```python
@dataclass
class Call:
    id: str
    seq: int                      # 会话内单调递增；唯一的排序依据（≠ 墙钟时间）
    created_at: float
    role: str                     # "user" | "llm" | "code"
    name: str                     # 模型 id / 函数名 / 用户名；context/* 名字是管线节点
    input: Any                    # prompt 块 / 参数
    output: Any                   # 回复文本 / 返回值 / 用户内容（永久原文）
    caller: str                   # 调用边：谁调起了我（顶层轮次用 "ROOT"）
    predecessor: Optional[str]    # 对话边：这一轮延续的那一轮
    reads: list[str]              # 哪些节点进入了这次调用的 prompt
    metadata: dict
```

`output` 是永久原文，aging 和压缩都不碰它。两类管线节点像普通节点一样进入链条：`context/system_prompt` 在 system prompt 变化时记下它的确切内容；`context/summary` 代替被压缩掉的那些轮次。

### git 隐喻：retry / edit / fork 是同一操作

每个 turn 是一个"commit"，`predecessor` 是它回应的对象。retry / edit / fork 本质相同——在某节点的父节点下挂一个分叉的兄弟，区别只在触发方式：

| 操作 | 含义 |
|---|---|
| 发新消息 | 在当前 HEAD 下追加节点，HEAD 前移 |
| retry | 同内容的兄弟（assistant 重新采样 / 函数重跑） |
| edit | 不同内容的兄弟（在同一父节点下分叉） |
| 切换版本 `< N/M >` | checkout 到兄弟，**只改显示，不重跑** |
| 复制会话 | 新 Session，内容是到 HEAD 为止的历史，之后各自发展 |

要点：**checkout 永不触发重跑**（切 HEAD 只重新渲染）；**agent 运行中禁止 edit/retry/checkout**（避免把正在执行的树挂到即将"过时"的节点上）；**workdir 不随 checkout 回滚**（副作用属于用户，就像 `git checkout` 不会重跑你的测试）。

---

## 三、渲染、aging 与压缩

### 读哪些节点

`render_context(graph, head_id, frame)` 从 head 沿 predecessor 链走回分支起点，对链上每一轮，按 frame 和 `expose` 规则放入它的调用子树。兄弟分支永远不会被读到，派生子代理的内部过程留在它自己的分支里。这个遍历是纯的：什么都不写。随后 `render_dag_messages` 把选中的节点翻译成 provider 消息：工具调用成为所属 assistant 消息里真正的 ToolCall/ToolResult 对，直接函数调用成为一对文本。

### Aging

最近 `TAIL_TURNS`（默认 3）个 assistant 轮次的工具输出完整保留；更早的工具结果渲染成简短的 `[aged]` 存根。aging 边界只在一轮提交时前移，绝不在一轮内部移动，所以同一轮里的两次请求共享缓存前缀。每次模型调用记下 `render_manifest`（策略版本、aging 边界、溢出到磁盘的节点），历史调用可以逐字节重新渲染。超过溢出阈值的节点在写入时落盘，绝不在读取时。

### 压缩

一轮开始前预算达到 80%（或用户运行 `/compact`，或 provider 以过长拒绝请求）时，`engine.compact` 把最早的若干完整轮次总结成一个 `context/summary` 节点，它的 `covers_ids` 列出被替代的轮次。包含整段被覆盖片段的分支渲染为 `[summary, 保留的尾部…]`；其他分支按原样渲染。每个会话最多一个生效的摘要：下一次压缩会吸收上一次的摘要。摘要写入前要通过校验（非空，且严格小于它替代的内容），HEAD 和原始历史保持不变。完整规范见 [`compaction.md`](compaction.zh.md)。

---

## 四、Attach / Merge（跨分支引用与聚合）

两者复用同一机制：**attach 指针**，一个 `function="attach"` 的节点，作为侧子节点挂在某个用户轮次下，携带另一条分支的内容。因为它位于该轮的调用子树中，正常渲染就会放入它；它渲染为带分隔的 `[Attached from "label"]` … `[End of attached content]` 文本。

- **Attach** 是被动的：指针先暂存，下一次模型调用时读入内容。
- **子代理汇报**：派生的子代理完成后，结果以 attach 指针的形式回到调用方，包含任务、最终回复和完整记录的 `read_conversation(session_id, head_id)` 地址。同步派生则在 `agent` 工具结果里返回回复。调用方看到的是子代理的结论，而不是它的每一步。
- **Merge** 是主动的：`process_merge_turn()` 在目标 head 之后为每条对等分支写一个 attach 指针，加上合并指令，然后在目标会话上跑一轮普通对话。可以把一条对等分支标为基准，它的内容保持原文，其余的可以被总结。这一轮之后，被合并分支的 head 标为已合并，一个多父 context commit 记下结果来自哪些分支，供 Context 时间线显示来源。

---

## 五、跨 turn tool 上下文

**问题**:历史里的工具调用若被丢掉,模型跨 turn 看不到自己调过哪些 tool、
参数、返回 —— 会重复调用、瞎编调过的文件。这与整段历史的 summarize 是两件事(逐条
tool aging vs 整段语义压缩)。

**策略**(§三中 tool aging 的细节):

- **tail-window 全文**:最近 `TAIL_TURNS=3` 个 assistant turn 的 tool_use /
  tool_result 完整保留。
- **老 turn aging**:更早的 tool_use 头保留(args 截 `MAX_TOOL_ARGS_CHARS=200`),
  tool_result 换 1 行语义 stub。
- **单条上限**:任何 tool_result 超 `MAX_TOOL_RESULT_CHARS=4000` 截首尾(tail 内也
  截,防单 turn 爆)。
- **关键 tool 保护**:`PRUNE_PROTECTED_TOOLS={todo_create, todo_update, todo_list, open_work, web_search}`
  不参与 aging。

数据流:`render_context` 选出分支上的轮次及其工具调用 → aging 预处理标出边界之前的 code 节点(tail
全文 / 老的换 stub)→ 单条截断 → `render_dag_messages` 产出 ToolUse +
ToolResult content blocks；整段总结另在压缩中进行。代码:`openprogram/runtime/context/tool_aging/`、`aging.py`、`render.py`。

阈值取自参考框架:tail-window(OpenCode)、逐条 stub(Hermes)、单条截断 + 关键
tool 保护(OpenCode)。

---

## 六、不变式

1. DAG 只追加；aging 和压缩永不改节点内容。
2. 读路径是纯的：渲染不写任何东西；溢出落盘发生在写入时。
3. aging 边界只前移，且只在一轮提交时前移。
4. 历史调用按它记下的 `render_manifest` 重新渲染，而不是按今天的策略。
5. 每个会话最多一个生效的摘要；摘要从不移动 HEAD，也不改写边。
6. 一条分支永远读不到兄弟分支或派生子代理的内部过程；其他分支只通过 attach 指针进入。
7. checkout 只改显示，不重跑，不回滚 workdir。

---

## 七、UI

- **History 视图**：完整 DAG，每种角色一种节点形状，显示所有工具调用 / retry 分支 / merge 汇流。
- **Context 时间线**（右侧栏）：`apps/web/components/right-sidebar/context-commit-timeline/`
  + `ws_actions/context_commits.py`。列出会话已记录的 context commit，把同一分叉点上的兄弟尝试归为一组，并显示每个 commit 的条目、状态徽章和 token 数。

### 占用统计：一个数，两个读者

报告窗口占用的有两处——composer 里的进度圆环
（`apps/web/components/chat/badges/context-badge.tsx`）和点开它弹出的 `/context` 分解面板
（`apps/web/components/chat/badges/context-breakdown-panel.tsx`）。两者渲染的是服务端算好的
同一份记录，因此任何时刻都一致：

```python
{"window": int, "total_used": int, "basis": "measured" | "estimated",
 "estimated": int, "calibration": float}   # calibration 仅在 measured 时给出
```

由 `openprogram/runtime/context/session_stats.py` 构建，`server.session_context_stats`
供给 `/context`，`server._broadcast_context_stats` 通过 `context_stats` WS 帧推送。
圆环从 store 读 `total_used / window`；面板的头行读同样的字段，并据此推出
`Free space`，所以分项行永远不和总数打架。

面板分两层。总览显示四类（系统提示、工具、记忆、对话），点一类或它在分段条上的那一段
进入详情。系统提示详情按组件列出（基础提示词、输出风格、Agent 自己的系统提示、环境、
AGENTS.md、技能索引、工作流与工具说明、日期、计划模式）并附原文；工具分为已加载 /
按需加载 / MCP；记忆列出每一层的 `MEMORY.md`；对话按类型拆分
（`messages_detail.groups`）并列出最大的几条消息（`messages_detail.top`），每条链接到
聊天里对应的那一行。明细行随所属类别一起缩放，加起来等于类别总数。还没有会话的新对话读
`GET /api/context/draft?provider=&model=`（`session_stats.compute_draft_breakdown`）：
Agent 的提示词和完整工具集，窗口按该模型计算。每轮记录 `context/system_prompt` 节点时，
节点 metadata 带 `sections: [{name, chars}]`，即各组件块的长度，`session_stats` 据此把
记录下的文本精确切回各组件。更早记录的节点没有这项，就在其中查找一次新构建的各块；
找不到的部分显示为“其他”。

当前 WebSocket 聊天入口在每次 provider 请求结束时记录 prompt 用量，
因此函数调用之间圆环和面板会更新。轮次结束时，它更新当前分支的 HEAD 并保存最终读数。加载会话时，如果旧轮次保存的
provider 用量比已有统计新，且之后没有修改会话状态，会据此恢复实测统计。

**这个数永远描述"此刻"。** 两种来源：

| basis | 何时 | `total_used` |
|---|---|---|
| `measured` | 一次真实请求刚完成 | provider 为该次调用 prompt 计费的量（`input_tokens + cache_read`） |
| `estimated` | 那次请求之后图变了 | 按当前分支用本地分词器重算 |

measured 读数同时记下 `calibration`——同一张图上实测 ÷ 估算——说明本地估算相对
provider 实际计费偏离多少。

**图变化的触发点。** 凡是改变下一次请求所携带内容的操作，都经
`server.refresh_context_stats` 重估并重播，圆环因此跟着图走，而不是滞后一次请求：

| 变化 | 落点 |
|---|---|
| turn 中压缩落地 | `openprogram/interfaces/server/ws_actions/chat/context_usage.py`（压缩后的那次实测请求） |
| 切换模型 | `openprogram/interfaces/server/routes/execution/runtime.py`、`openprogram/interfaces/server/ws_actions/runtime.py` |
| 分支 checkout / 删除 | `openprogram/interfaces/server/ws_actions/branch.py` |
| 兄弟版本 checkout | `openprogram/interfaces/server/context_git_routes.py` |

一次实测只属于它测量的那条分支：`session_context_stats` 仅在 HEAD 未移动时保留
`measured` basis，换到别的 head 就重新估算。

**窗口解析只有一条路**——`get_model(provider, model)` + `real_context_window()`，
`"provider:model"` 按冒号拆分（`server._resolve_context_window`）。会话的 picker
override 优先于持久化的 model，所以切换在下一次落盘前就生效。

---

## 八、与三层组成的关系

[`composition.md`](composition.zh.md) 把每次 LLM 调用按"多久变一次"分三层，
既服务缓存（稳定的靠前），也让模型知道自己的处境。本文的机制为这三层提供材料：

| 层 | 内容 | 变化频率 | 材料来自 |
|---|---|---|---|
| **L0 恒定** | 身份 / 全局指令 / 工具清单 | 整 session 不变 | engine 的 system prompt 步骤（§一） |
| **L1 处境** | 我是哪个函数的零件 / 谁调我 / 在程序哪一步 / 输出去哪 | 每进一个 frame 变 | 从 DAG 渲染出的调用树（§二） |
| **L2 任务** | frame 内进展 / 继承的上游结果 / 当前输入 / 输出格式 | 每步变 | 历史选取 + 压缩（§一、§三） |

---

## 附录：实现状态

- §一至§三描述的 DAG 渲染是唯一的聊天上下文管线；以 `openprogram/runtime/context/engine.py`、`nodes.py`、`render.py`、`aging.py`、`compaction_view.py` 为准。
- context commit 生成器及其规则管线（`openprogram/runtime/context/commit/`、`rules/`）已不在聊天路径上。现在只有 merge 轮次写 context commit，所以 Context 时间线显示的是 merge commit 和 DAG 渲染之前的会话留下的 commit；它还不显示普通轮次的渲染视图。
- 辅助路径的 system prompt 不跟 agent 走：总结与分支总结用固定的总结提示（`openprogram/runtime/context/prompts.py`），不随用户的 AGENTS.md、身份、技能变。
- 用户不能手动 pin/unpin 单个上下文条目。

当前上下文占用使用最后一次请求的实测值，不使用一轮多次请求的累计输入量。无用量的结束事件保留此前实测值；没有实测值时界面使用本地估算。旧累计统计格式保存的占用与校准系数失效，累计计费用量保持不变。
