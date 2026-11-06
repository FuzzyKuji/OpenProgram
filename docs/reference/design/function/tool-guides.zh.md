# 工具指南

规则很多的工具保持简短的 schema，在调用需要时才把其余说明交给模型。单一入口工具
（`computer_use_agent`、`self_update`）都建立在这个机制上：一个工具、几个参数，每个
目标或动作的说明在第一次用到时送达。

## 为什么

每个 schema 都随每次请求发送。一个把所有动作、参数和策略都写进 schema 的工具，在每一轮
都占用这些上下文，包括根本不用它的那些轮；而且长 schema 不如短 schema 被读得仔细。把一个
领域拆成很多平铺工具只是转移了成本，并没有去掉。另一种做法是渐进披露，Codex 的 computer
use 和 Claude Code 的 skill 都这样做：schema 只说明入口和形状，说明随第一次需要它的调用
到达。

有两点让它可靠，而不是寄希望于模型：

- 不要求模型记得去读什么。指南要么附在需要它的那次调用结果上，要么这次调用被拒绝，
  拒绝结果里就带着指南。
- 送达跟着模型能看到的内容走。离开上下文的指南（压缩、工具结果被清理、新 agent）在下一次
  有调用需要它时重新送达。

## 声明指南

`openprogram/programs/_authoring/guides.py`。工具以自己的名字注册一组 `Guide`：

```python
guides.register("self_update", [
    Guide("self_update", overview, mode="open", activates=("worktree_create",)),
    Guide("self_update.prepare", prepare_text, summary="parameters, iteration policy and verification plan",
          required_for=lambda args: args.get("action") == "prepare"),
])
```

| 字段 | 含义 |
|---|---|
| `name` | 模型传给 `help` 的点分名字；在所有工具中唯一 |
| `text` | 指南本身，或返回它的函数（用于按主机变化的文字，例如 app 指南的平台版本，或从代码读出的列表） |
| `mode` | `open`：工具的第一次结果附带它。`included`：参数符合 `when` 的调用的第一次结果附带它。`lookup`：按名字和 `summary` 列出，用 `help` 读取。`on_error`：符合条件的调用失败时附带它 |
| `when(args)` | `included` 或 `on_error` 指南适用于哪些调用；对 `lookup`，决定它是否出现在索引里 |
| `required_for(args)` | 在指南已知之前不能执行的调用 |
| `activates` | 指南讲到的延迟加载工具；送达指南时加载它们的 schema，效果同 `tool_search` |

`open` 或 `included` 指南末尾附上该工具适用的查阅型指南索引
（`help("self_update.retry"): install the repaired candidate after a rollback`），所以入口
很短也能告诉模型其余内容在哪里。

## 送达

全部由 agent loop 完成；工具只负责声明。

1. `_run_loop` 为这个 loop 打开一个视图（`guides.begin_loop`）。agent loop 之外没有视图，
   指南什么也不做：直接的 Python 调用和测试看到的是原样结果。
2. 每次请求模型之前，`_stream_assistant_response` 记录即将发送的消息文本
   （`guides.observe_request`）。
3. 指南的标记 `<guide name="…">` 在这段文本里，或在这次请求之后已经送达，就算**已知**。
4. 调用结束时，`_rewrite_tool_result` 把应送达的指南放在结果前面（`guides.attach`）：
   未知的 `open` 指南、匹配且未知的 `included` 指南、失败时匹配的 `on_error` 指南，以及被拒绝
   调用所需的指南。每份都包在标记里，所以下一次请求包含它，此后它就是已知的。
5. 调用执行之前，如果某个 `required_for` 指南未知，`permission_decision` 以 `GUIDE_REQUIRED`
   拒绝它。这是自动拒绝（不计入重复失败处理，也不显示审批卡），第 4 步把缺少的指南附在
   拒绝结果上。模型读过后再次调用。

从请求里读取"是否已知"而不是另记账本，重新送达才不需要额外机制：压缩把旧结果概括掉，
微压缩把它换成占位符，worker 重启丢掉内存，fresh agent 从自己的提示开始——每种情况下
标记都不在了，下一次需要指南的调用就会收到它。提示里已经带着带标记指南的 fresh agent
（`context="fresh"` 的 `computer_use_agent`）不会再收到一遍。

## `help`

`help(name)` 是常驻工具（`openprogram/programs/tools/runtime/help.py`），按名字返回指南；
传入工具名时返回该工具的开场指南，和其他送达的指南一样带标记。它不需要审批，权限类别是
`runtime.control`。名字不存在时列出现有的指南。

在 `computer_use_agent` 的代码里，Python 自带的 `help` 和 `dir` 对 `cu` 对象有效：每个方法的
docstring 就是目标指南里对应动作的那一行。

## 基于它的单一入口

| 工具 | 指南 |
|---|---|
| `self_update` | `self_update`（open：流程；激活 `worktree_create`）、`self_update.prepare` 和 `self_update.retry`（lookup，对应动作需要） |
| `computer_use_agent` | `computer_use_agent.app` / `.browser` / `.vm`（操作该目标的调用附带）、`computer_use_agent.code`（lookup，`code` 需要） |

单一入口保持两级：工具，然后是 `action`（或 `target`）。权限、authority 和审批按动作决定：
对 `self_update`，`status` 只读（`fs.read`，无需审批），`cancel` 是 `runtime.control`，
`prepare` 和 `retry` 总是请 owner 单次审批（`policy._self_update_install`）。

只凭参数就能检查的内容在审批卡之前检查（`openprogram/programs/_authoring/prechecks.py`，由
`permission_decision` 在指南检查之后调用）：SHA 格式不对、迭代策略或验证计划越界的
`prepare` 以 `INVALID_ARGUMENTS` 拒绝，owner 不会批准一次根本无法执行的调用。

## 选择模式

- 每次使用都需要的说明：`open`。
- 只针对一个变体（一个目标、一个平台）的说明：带 `when` 的 `included`。
- 出错代价高或参数很长的动作：带 `required_for` 的 `lookup`。
- 只有某些情况才需要的背景：不带 `required_for` 的 `lookup`；索引会列出它。
- 恢复建议：`on_error`。

## 实现文件

- `openprogram/programs/_authoring/guides.py`
- `openprogram/programs/tools/runtime/help.py`
- `openprogram/programs/_authoring/prechecks.py`
- `openprogram/runtime/agent/loop/`（`_run_loop`、`_stream_assistant_response`、`_rewrite_tool_result`）
- `openprogram/runtime/permissions/policy.py`（`permission_decision`）
- `openprogram/programs/tools/system/self_update/__init__.py`
- `openprogram/programs/tools/computer_use/computer_use_agent/tool.py`、`code.py`
- 测试：`tests/unit/programs/test_guides.py`、`tests/unit/programs/test_prechecks.py`
