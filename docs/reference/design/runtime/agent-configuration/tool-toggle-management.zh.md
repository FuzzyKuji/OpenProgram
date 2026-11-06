# 工具开关 / 工具集管理设计

> 核心原则一句话：**会话能调用哪些工具由 Agent 配置决定；会话只存叠加意图，绝不存"展开后的工具名列表"——工具表每次运行时从 registry 实时展开，这样新增工具对所有历史会话自动生效。**

---

## 1. 工具集如何确定

### 1.1 谁来选

| 位置 | 决定什么 | 存在哪 |
|---|---|---|
| Agent 配置（Agents → 能力 → Programs） | 工具范围：全部、指定范围或具名工具配置（Access preset）、不使用；外加禁用名单和 `web_search` 默认值 | Agent profile 的 `tools: {mode, allowed, preset, disabled, web_search}` |
| 输入框的网页搜索开关 | 在 Agent 工具集之上叠加或去掉 `web_search` | 会话 meta 的 `web_search` |
| 带 `allowed-tools` 的 `/skill <name>` | 把这一轮收窄到 skill 的白名单 | 会话 meta 的 `tools_override`（`list[str]`） |

输入框没有 Tools 开关，也没有按对话选的 Access preset。不该调用工具的对话，用一个 Programs 设为"不使用"的 Agent。聊天 WebSocket action 不读消息里的 `tools` / `tools_profile`，只读 `web_search`。

### 1.2 优先级链

一次 turn 给模型的工具由 `resolve_tools(agent_profile, override, source)`（`openprogram/runtime/conversation/model_tools.py`）算出。`override` 是会话意图，由 `tools_override_from_config(cfg)`（`openprogram/runtime/conversation/session_config.py`）产出：

| 会话意图 | override | 行为 |
|---|---|---|
| 什么都没设 | `None` | 由 Agent profile 的 `tools` 决定 |
| 设了 `web_search` | `{"inherit": True, "web_search": <bool>}` | 实时展开 profile 的工具，再加上或去掉 web_search |
| `/skill` 白名单 | `list[str]`（加 web_search 叠加） | `agent_tools(names=[...])`，按名字 |

消费方是 webui 聊天路径（`ws_actions/chat/turn.py`、`context_git_routes.py`）、channels（`channels/_conversation.py`）和 goal chat（`programs/tools/planning/goal/chat.py`）。

### 1.3 为什么存意图而不是列表快照

如果会话在写入时把意图展开成 `list[str]`，工具集就冻结在那一刻：之后每一轮都把旧名单读回来交给 `agent_tools(names=[...])`，此后加进 `DEFAULT_TOOLS` 的工具（list_agents、send_message）永远到不了这个会话。会话只存叠加项（`web_search`），工具范围交给 Agent profile，就能让每个会话都跟着实时 registry 走。唯一存下来的列表是 `/skill` 白名单，那是刻意的、很短的选择。

---

## 2. 其他项目怎么做（共识）

| 项目 | 存什么 | 怎么避免过期 |
|---|---|---|
| **opencode** | per-session `tools: Record<name, boolean>` 意图映射 | 工具表每 turn 由 live registry 现建，再用意图过滤（`config.ts:552`、`session/tools.ts:86`） |
| **claude-code** | `--tools`（选择，哨兵 `""`=无/`"default"`=全）+ `--allowedTools`/`--disallowedTools`（allow/deny 模式串） | 内置集是常量，只存"选择/允许/拒绝意图"，运行时求交（`main.tsx:988`） |
| **pi-ai** | builtin 开关 + extension 工具分开管 | 关 builtin 是布尔意图，不影响 extension 实时装载 |
| **hermes** | named preset（toolset 名） | 存 preset **名**，运行时展开（我们的 `TOOLSETS` 移植自此） |

**共识：三家无一例外存"开关意图"（布尔 / allow-deny / preset 名），从不冻结展开后的工具清单。** 真正的工具表永远请求时从 live registry 现场展开。

---

## 3. 核心原则：存【意图】不存【列表】

会话关于工具只存这些：

| 字段 | 含义 | 取值 |
|---|---|---|
| `web_search` | 在 Agent 工具集之上**叠加** | `True` / `False` / `None`（跟随 Agent） |
| `tools_override` | `/skill` 的 allowed-tools | `list[str]`（短）或不存在 |

工具范围本身（全部 / 指定 / preset / 不使用、禁用名单）在 Agent profile 里，经 `resolve_tools` 的 dict-override 通道实时展开。这样：加新工具 → 老会话下一 turn 自动获得；删工具 / 改 preset → 自动跟随；改一个 Agent 的配置，用它的所有对话一起变。

---

## 4. 工具开关与上下文 / 缓存 / 历史的影响（已逐条核对）

1. **工具数组算不算 token**：ContextCommit 的 `total_tokens` **不含**工具数组（commit 数据类无 tools 字段，`commit/types.py:104-140`）；但 provider 请求侧工具数组**计费**（`anthropic.py:601` 随请求发出）。→ 工具集大小对 compaction 预算不可见，但对每 turn 真实输入成本可见。
2. **缓存**：工具数组在**缓存前缀根部**（`cache_policy.py:80-89`，第一个 breakpoint 打在最后一个工具，仅 Anthropic/Bedrock explicit 模式）。→ **任何对工具数组的增删改都改写缓存前缀 → 整段 prompt 缓存 miss**。**硬约束：展开必须确定性**（稳定排序+去重），同一意图每次展开逐字节一致，缓存才命中。
3. **历史里有、当前工具表没有的调用**：历史 tool_use/tool_result 从 message 渲染（`anthropic.py:328-451`），与当前 `context.tools` 无关，能正常回放；但模型这 turn 无法再发起该调用。→ **改造不要根据当前工具表过滤/重写历史 tool_use**（破坏 tool_use↔tool_result 配对会 400）。
4. **ContextCommit 重放不受影响**：commit 不存工具数组，工具集是请求期产物。→ 把工具快照从存档拿掉**不动任何 commit 重放语义**，降低改造风险。

---

## 5. 三个承载点

**A — chat action 透传意图**（`openprogram/interfaces/server/ws_actions/chat/turn.py`）：只从消息里读 `web_search`。`tools_flag` 初始为 `None`（跟随 Agent）；带 `allowed-tools` 的 `/skill` 把它设成那份名单；新的 Agent 对话把两者都清空，由 Agent 配置决定。这里不展开任何东西。

**B — session_config 存意图**（`openprogram/runtime/conversation/session_config.py`）：`SessionRunConfig` 带 `web_search: Optional[bool]` 与 `tools_override: Optional[list[str]]`。`tools_override_from_config` 输出 `None`、`{"inherit": True, "web_search": ...}` dict，或带 web_search 叠加的 `/skill` 列表。从不写入全部工具的快照。

**C — dict-override 叠加 web_search**（`_model_tools.py`）：web_search 不在 `DEFAULT_TOOLS` 里，所以 dict 分支的 `_overlay_web_search` 在展开后、意图要求而结果缺它时补上，意图为 `False` 时去掉；Agent 的 `disabled` 规则排除它时不补。provider 内建 web_search（`openai_codex.py` 那种）是另一条可选路径，取决于各 provider 支持度（见 §8）。

---

## 6. 应当成立的性质

设计正确时，下列性质同时成立，它们也是回归验证的着眼点：

- **展开确定性**：同一意图连续展开两次逐元素相等（排序稳定 + 去重），避免 §4.2 的缓存抖动。
- **意图往返**：存 `web_search=True` 读回 True；没有该字段的会话读回 None 不报错。
- **由 Agent 决定**：没有会话意图时 override 为 `None`，用 Agent profile 的 `tools`；`web_search` 意图展开 Agent 的工具，只加上或去掉 web_search。
- **写入不物化**：会话开 web_search 后，meta 里没有 `tools_override`；只有 `/skill` 白名单会以列表形式存下。
- **新工具自动可见**：Agent 的自动范围展开后含最新加进 `DEFAULT_TOOLS` 的工具（send_message / list_agents）。
- **缓存稳定**：意图不变的会话连发两 turn，provider usage 显示第二 turn 命中缓存、工具集未抖动。
- **没有按对话的工具开关**：任何客户端发聊天消息都不带 `tools` 或 `tools_profile`，chat action 也不读这两个字段。

---

## 7. 延迟加载：可用 ≠ 常驻

§4.1 已确认工具数组每轮计费。开关决定哪些工具**可用**，延迟加载（defer）决定这些
可用工具里哪些每轮为自己的 JSON Schema 付费。这是两条独立的轴，把它们混为一谈正是
常驻成本随工具数量线性增长的原因。

### 7.1 可用工具的两种形态

一个可用工具以两种形态之一进入请求：

- **常驻（resident）**——完整 JSON Schema 进 provider 的 tools 数组，每轮都带。
- **延迟（deferred）**——在系统提示的目录里只占一行**裸工具名**。模型需要时调
  `tool_search` 加载 schema，随后本轮的下一次 provider 请求就包含该工具。

目录只发名字、不发描述。名字足够让模型认出候选并点名索取，同时无论 defer 多少个
工具，整个目录都压在两百来 token。

延迟工具**不是被禁用**：模型照样能调，只是得先加载 schema。禁用的工具则同时不在
数组和目录里，根本无法调用。

### 7.2 切分逻辑

`split_tools_for_dispatch(tools)`（`programs/_host/runtime.py`）读每个工具的 `_defer`
边车属性，减去本会话已加载集合，把解析后的工具集切成 `(provider_tools, catalog)`：

- 非 defer → 进 provider 数组
- defer 且在已加载集合里 → 进 provider 数组
- defer 且未加载 → 进目录

已加载集合存在 ContextVar 里（`install_loaded_deferred` 由 dispatcher 每会话初始化；
`mark_deferred_loaded` 由 `tool_search` 内部写入）。这个集合里哪些条目真正进数组，
每轮只决定一次——见 §7.4。

### 7.3 哪些工具被 defer

`apply_default_deferral()` 在 import 末尾跑一次，按 `_defer = name not in RESIDENT_TOOLS`
打标。两类工具落到 defer：

1. 在 `full` 暴露白名单里但不在 `DEFAULT_TOOLS` 中的——memory、worktree、
   image 等冷门工具。它们本来就不在默认集，defer 不损失什么。
2. `DEFERRED_DEFAULT_TOOLS`——仍留在 `DEFAULT_TOOLS`（默认可用）但体积大、调用少，
   因此不常驻：

   | 工具 | schema | 为什么不常驻 |
   |---|---|---|
   | `enter_plan_mode` | ~1050 tok | plan mode 通常由用户经档位 chip / TUI 进入（`plan_mode.sync_tier`），不走这个工具。模型自行判断进 plan 是罕见路径。 |
   | `exit_plan_mode` | ~640 tok | 只在 plan mode 激活时有意义，且 plan-mode 提示块已明确点名它，模型据此知道要加载。 |
   | `send_message` | ~380 tok | 跨 session / branch 通信，只在多分支协作时用到。 |

`tool_search` 自身永不 defer——它是加载其它一切的唯一入口，defer 它会死锁。这一点有
双重保险：`RESIDENT_TOOLS` 的并集，以及 `apply_default_deferral` 里的显式 guard。

效果：默认常驻数组从每轮 ~7.9k 降到 ~4.7k token，约减 41%，且没有任何工具变得不可用。

### 7.4 显式发现更新下一次请求

`freeze_turn_tools` 在轮开始时记录延迟工具的初始成员集合。`tool_search`
将明确选择且允许的名称同时加入已加载集合和本轮共享集合。下一次 provider 请求
携带这些工具的真实 schema。仅在工具结果文本中返回 schema，无法满足只允许调用
请求 tools 数组中工具的 provider。

集合必须原地修改：工具线程继承 ContextVar 的值，在工具线程替换整个值不会更新
provider 协程。实际执行始终使用本轮已解析且带权限 wrapper 的工具；注册表的无关
变化不会替换不可变 runtime contract。没有显式发现时数组保持稳定；发现新工具时
允许改变缓存前缀，以确保该工具实际可用。

每个持久化安全点将 `loaded_deferred_tools` 写入 checkpoint，名称必须属于其中的
工具合同。恢复先验证合同没有变化，再恢复名称，不重放已经完成的搜索。
旧 checkpoint 缺少该可选字段时恢复空集合，不从工具结果文本推断权限或加载状态。
每次 provider 派发也记录当前常驻／延迟分类，供上下文检查器使用。

在轮之外装配工具的调用方使用 `release_turn_tools()` 读取实时已加载集合。

### 7.5 目录是装配器组件

目录不由 dispatcher 手工拼接。它是注册的上下文组件（`deferred_catalog`，L1 order 25，
在 `context/components.py`），由 `_build_deferred_catalog` 构建，所以引擎计入预算的
字符串就是实际发出的字符串。该组件从 ContextVar 读工具列表，无 defer 工具时返回空串。

预算口径同样跟随这个切分。`_estimate_one_tool`（`context/budget.py`）按每个工具**实
际发上线的东西**计价：

- **常驻**——`description` **和** `parameters` schema 都算，外加少量包装。两半都要算：
  描述约占常驻成本的 45%，只算 schema 会把数组少估好几千 token。
- **延迟**——只算裸名字加一个换行，与 `deferred_catalog_text` 对齐。按描述给 defer 工
  具计价会把目录高估约一个数量级，因为描述恰恰是目录不发的那部分。

两半中任何一半算错都很难被发现，因为两个误差方向相反，一个看着合理的总数可以同时
掩盖两者。因此 `tests/unit/context/test_budget.py` 拿真实 tokenize 的上线载荷，对两半分别
校验，各自不超 15%。

### 7.6 应当成立的性质

回归保护在 `tests/unit/context/test_tool_defer.py`：

- 新会话的常驻数组里不出现任何 `DEFERRED_DEFAULT_TOOLS` 成员，`RESIDENT_TOOLS` 里也没有
- 它们全都出现在目录里，以及装配后的系统提示里
- `tool_search` 能把延迟工具移入 provider 数组、移出目录
- `tool_search` 永不被 defer；`apply_default_deferral` 幂等
- 轮内显式 `tool_search` 将工具加入下一次 provider 数组，并从延迟目录移除
- `tool_search` 返回完整参数 schema；执行仍使用原有带权限 wrapper 的工具
- checkpoint 恢复验证 runtime contract 未变，再恢复已记录的发现集合

---

## 8. 已知边界

- **provider 内建 web_search vs 工具数组 web_search**（改 C 二选一）：codex/OpenAI Responses 确认走内建 `opts["web_search"]`（`openai_codex.py:376`）；Anthropic / 其它 provider 需逐个核对。确认前保留"web_search 作为工具名叠加"的稳妥路径。
- **dict-override 的 `allowed` 语义**：当前 `allowed`（`_model_tools.py:406`）是对 DEFAULT_TOOLS 过滤、不是 full 全集；本次不扩这块。
- **工具数组的精确 token 数**属服务端口径，本仓库静态测不出，仅确认"计费且在缓存前缀"。

---

## 9. 实现状态

### 9.1 承载文件

| 文件 | 承担什么 |
|---|---|
| `openprogram/runtime/conversation/session_config.py` | `SessionRunConfig` 的 `web_search` 与 `tools_override`（`/skill` 白名单）字段；`save/load` 读写它们（存 git session meta，不需改 DB schema——`update_session(**fields)` 任意 key 透传）；`tools_override_from_config` 输出 `None`、web_search dict 意图或 `/skill` 列表 |
| `openprogram/interfaces/server/ws_actions/chat/turn.py` | 只从消息里读 `web_search`；把它和 `/skill` 白名单交给 `save_session_run_config(tools=, web_search=)` |
| `openprogram/runtime/conversation/model_tools.py` | dict-override 分支（`resolve_tools`，~397-421）的 `web_search` 叠加：`_overlay_web_search` 在 toolset / names 两条路径展开后，若意图含 web_search 且结果缺它则补上 |
| `openprogram/programs/_host/runtime.py` | defer 机制本体：`_defer` 边车、已加载集合、`freeze_turn_tools` / `release_turn_tools`（§7.4）、`split_tools_for_dispatch`、`tool_search` 及它返回的 schema、`deferred_catalog_text` |
| `openprogram/runtime/agent/loop/` | 每轮在外层循环顶部调一次 `freeze_turn_tools`；工具调用按名字在完整工具列表里解析，因此轮内加载的工具仍可派发 |

### 9.2 关键设计点（别破坏）

- **展开必须确定性**：工具数组在 prompt 缓存前缀根部，顺序一抖整段缓存 miss。当前
  `agent_tools` 按 names/registry 顺序返回，天然稳定——`tests/unit/programs/tools/test_tool_expansion_deterministic.py`
  锁住它。**以后改 `agent_tools` / `_filter_agent_tools` 切勿引入 `set()` 迭代 /
  dict churn 破坏顺序**，否则缓存会无声失效（不报错，只是悄悄变贵）。
- **绝不把 Agent 的工具物化成 list 存进会话**：工具范围永远从 Agent profile 实时展开。
  `list[str]` 只表示 `/skill` 白名单。这是整个设计的红线。
- **不改历史**：工具开关只控制"接下来能调什么"，不过滤/重写历史 tool_use（会破坏
  tool_use↔tool_result 配对 → provider 400）。
- **工具数组只在轮边界变**（§7.4）。任何在轮内撑大数组的做法，都会作废本轮剩余部分
  的缓存前缀。若某个工具需要更早可用，就在工具结果里把 schema 交给模型，不要往数组
  里追加。

### 9.3 测试（回归保护）

- `tests/unit/programs/tools/test_tool_expansion_deterministic.py` — 展开确定性（缓存前缀稳定）
- `tests/unit/store/test_session_config_tools_intent.py` — 无意图时跟随 Agent、web_search 叠加（加上、去掉、尊重 Agent 的 `disabled`）、`/skill` 列表原样透传，以及显式 web_search 的冷 provider 路径
- `tests/unit/store/test_session_config.py` — `web_search` 与 `/skill` 白名单在会话 meta 里的往返
- `tests/unit/context/test_tool_defer.py` — §7.6 的各项 defer 性质，含轮边界冻结
- `tests/unit/context/test_budget.py` — 工具计价两半各自对真实 tokenize 载荷校验（§7.5）

### 9.4 扩展点

- **provider 内建 web_search**（§8）：web_search 当前走"工具名叠加"路径；若确认各 provider
  支持内建 web_search，可在 `_overlay_web_search` 处切换。
- **新意图维度**（如按 channel 限工具）：把范围加进 Agent profile，或往 dict 意图加键并在
  `resolve_tools` dict 分支处理，不要回到"存展开列表"的形态。
