# Agent 与 Context

`agent()` 执行模型工具循环。`Agent` 保存可复用配置，并为普通子类方法建立作用域。`Context` 提供命名内容与历史选择。所有入口复用现有 Runtime 和 Session DAG。

## 直接调用与 Agent 类

普通调用不需要手动构建或绑定 Context。

```python
from openprogram import Agent, agent, agent_async

answer = agent("Summarize this text", tools=[])

class Researcher(Agent):
    instructions = "Return a short, factual answer."
    tools = []

    def prepare(self, question):
        """Remove surrounding whitespace."""
        return question.strip()

    def research(self, question):
        """Answer the prepared question."""
        return self(self.prepare(question))

researcher = Researcher(model="configured-model")
answer = researcher.research("A question")
# 异步代码：answer = await researcher.arun("A question")
# 或：answer = await agent_async("A question", tools=[])
```

`agent()` 接收字符串或内容块，可指定 `model`、`effort`、`tools`、`choices` 和 `runtime`。`choices` 让收尾回复成为一次[下一步决策](../../capabilities/agentic-programming/choosing-the-next-step/next-step-decision.zh.md)，并返回解析后的选择结果。工具执行选项见 [Runtime](runtime.zh.md)。`tools=None` 选择可用工具，`tools=[]` 禁用工具。`agent_async()` 使用同样的选项。

`Agent(model=..., instructions=..., context=..., tools=..., runtime=..., effort=..., **options)` 用实例设置覆盖类默认值，调用参数再覆盖实例设置。`Agent.from_spec(spec, **overrides)` 使用现有 AgentSpec 配置，不创建已保存 Agent 条目。

构造对象不请求模型，也不创建执行会话。调用继承当前执行；没有外层执行时创建独立执行，并在结束时释放资源。复用实例不自动续接上一次独立会话。

普通实例方法、静态方法与类方法自动建立调用作用域，包括单下划线帮助方法。双下划线特殊方法与生成器不采集。方法记录不会注册模型工具。在对应 `method_options` 设置 `"tool": True` 可显式登记工具。 `method_options = {"method_name": {"expose": "io", "render_range": {...}}}` 无需装饰器即可设置方法元数据。

## Context 内容与可见性

框架自动派生并绑定 Context。显式配置是可选的：

```python
from openprogram import Agent, Context

context = Context(
    {"notes": "Use the project terminology."},
    providers={"current_topic": lambda current: "Agent context"},
)
researcher = Agent(context=context, tools=[])
```

`Context(blocks=None, *, parent=None, providers=None, history=..., call_id=..., store=None, head_id=None)` 是命名内容的可变映射。`derive()` 创建具有独立内容的子上下文。`Context.current()` 返回当前任务绑定，无绑定时返回 `None`。`merge(other)` 覆盖命名内容和显式选择规则，不替换作用域调用身份。宿主集成可使用 `bind()` 显式绑定。

提供函数是接收当前 Context 的同步 Python callable，在每次模型请求时运行。提供函数失败会终止该请求。框架不执行表达式字符串。

`history` 选择模型请求看到的历史。`None` 不发送历史。`"thread"` 只发送之前用同一个 Context 对象发起的请求。`"chat"`（Context 的默认值）发送可见的对话。callable 接收 `(node, context)`，在现有可见性检查之后筛选对话节点。没有显式设置 `history` 的 Workflow 角色调用不发送历史。这些设置不能扩大工具权限。

Context 使用同一模型：父继承、命名内容、请求时求值和历史可见性。Agent 实例内容是该模型的实例绑定。模型交互仍归执行会话保存。内容与系统指令、工具权限分别处理。

## 显式会话生命周期

多次独立调用需要续接同一会话时，使用 `Context(store=writer, head_id=None)`。writer 是现有 `SessionNodeWriter`：

```python
from openprogram import Agent, Context
from openprogram.state.store import SessionStore, SessionNodeWriter

store = SessionStore(root_path="/var/lib/myapp/sessions")
store.create_session("research", agent_id="main")
writer = SessionNodeWriter(store, "research")
researcher = Agent(context=Context(store=writer), tools=[])
try:
    first = researcher("List the project requirements.")
    second = researcher("Review the requirements from the previous call.")
finally:
    store.close()
```

`head_id` 选择已有分支末端作为初始前序节点。`None` 续接当前会话末端。调用者拥有并关闭显式 store，执行作用域不会关闭它。

该显式 Context 会话提供 NOOA 式重复实例调用需要的事件生命周期，复用已有 Session DAG。Agent 仍保存配置，默认调用保持独立。

## 受管 Program 源码

受管加载器采集显式授权包目录内的源码函数，包括已选择的第一方源码、已安装及目录登记的 Program 包、所有者登记的外部 harness、已发布 Program 与保留源码快照。采集包含子模块与嵌套源码定义。任意宿主文件、无关依赖、lambda、动态生成代码与不可用源码不在该范围内。

包通过 `PROGRAM_ENTRIES` 列出公开入口。普通入口可用显式 `__agent_options__` 映射提供已有入口元数据。被采集的帮助函数不会自动成为工具。加载器保留方法配置，并排除生成器采集。

类与方法接口参考 [NVIDIA-labs OO Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents)。OpenProgram 不声称 NOOA API 兼容。

## 方法配置

普通 Agent 方法产生 code 节点，模型请求产生 llm 节点。Agent 承担方法元数据、执行控制与显式登记。Context 动态构建每次请求。

Agent 定义方法执行、配置与登记，Context 动态构建每次请求。

### 用法

```python
from openprogram import Agent
from openprogram.runtime.agent import llm

class ExampleAgent(Agent):
    method_options = {
        'f': {'tool': True},
    }

    def f(self, x: str) -> str:
        """One-line summary of what f does."""
        return llm([{"type": "text", "text": f"...{x}..."}])

_example_agent = ExampleAgent()
f = _example_agent.f
```

每个普通方法自动建立调用作用域。通过类的 `method_options` 映射配置指定方法。

### 方法配置

### 执行与 Context 设置

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `expose` | `str` | 普通方法 `"full"`；登记工具 `"io"` | **朝外**:别人渲染 DAG 时能看到我的什么。`"io"` = 对外只露函数名和返回值,内部(LLM 交换、子调用)隐藏;`"llm"` = 反过来,只露内部 LLM 交换,藏函数自己的名字/返回值和嵌套的 code 子调用;`"full"` = 全可见(docstring + 参数 + 输出 + LLM 回复 + 内部);`"hidden"` = 根本不写 DAG 节点。其余值在装饰时抛 `ValueError` |
| `render_range` | `dict` | `None` | **朝内**:本函数内部 `llm()` 拼 prompt 时,从 DAG 读多少历史节点。形状 `{"callers": N, "subcalls": M}`,两个数字都是 **节点计数(按 `seq` 切片)**:<br>• `callers` — 本函数 frame **启动前**的节点,取最近 N 个(`None` 默认 = 不限,`0` = 全墙)<br>• `subcalls` — 本函数 frame **启动后**已写入的节点,取最近 N 个(`-1` 默认 = 不限,frame 自然看见自己的进度;`N>=0` = 只想截 prompt 时显式设;`0` = 完全墙掉 in-frame)<br>`{"callers":0,"subcalls":0}` = 跟外界和自己 frame 全断绝 |
| `input` | `dict` | `None` | 每个参数的 UI 元数据,WebUI 据此渲染输入表单。每个参数支持的字段:`description`(参数名旁的标签)、`placeholder`(示例文字)、`multiline`(`True` = textarea)、`options`(允许值列表,渲染为下拉框并写进 JSON-schema `enum`)、`hidden`(`True` = 从表单和 LLM 工具 schema 里排除) |
| `system` | `str` | `None` | 本函数 LLM 调用的 system prompt(调用期间盖到注入的 runtime 上,调用后恢复) |

### 工具注册参数

设置 `tool=True` 的 Agent 方法注册进共享注册表(`openprogram.programs`),成为 LLM 可调用的工具,与 `@function` 装饰的工具并列。以下参数控制这次注册,名字和语义与 `@function` 一致:

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `tool` / `as_tool` | `bool` | `False` | 注册为 LLM 可调用工具。`False` = 只能 Python 直接调用 |
| `name` | `str` | `None` | 工具名覆盖。默认取函数的 `__name__` |
| `description` | `str` | `None` | 工具描述覆盖。默认取函数 docstring |
| `parameters` | `dict` | `None` | JSON-schema 参数覆盖。默认由签名类型注解加 `input` 元数据自动生成(runtime 注入参数和 `hidden` 参数被排除) |
| `label` | `str` | `None` | 工具 UI 里显示的可读标签 |
| `toolset` | `tuple` | `()` | 本工具所属的工具集名(供 `exec(toolset=...)` 预设使用) |
| `unsafe_in` | `tuple` | `()` | 在哪些渠道来源下视为不安全并被过滤 |
| `check_fn` | `Callable` | `None` | 逐次调用的门禁:分发前调用,返回假值则拦下 |
| `requires_env` | `tuple` | `()` | 必须设置的环境变量名,缺了就不提供该工具 |
| `can_use` | `Callable` | `None` | 工具解析时求值的动态可用性谓词 |
| `max_result_chars` | `int` | `None` | 回喂给模型的工具结果截断上限。`None` = 注册表默认 `DEFAULT_MAX_RESULT_CHARS`(30,000 字符) |
| `persist_full` | `bool` | `False` | 把未截断的完整结果保存到状态目录中的独立路径，供 agent 回读；后续保存不覆盖旧引用。仅在写入成功后返回路径 |
| `head_ratio` | `float` | `None` | 截断时头部保留的比例,其余留尾部。`None` = 注册表默认 `DEFAULT_HEAD_RATIO`(0.7) |
| `requires_approval` | — | `None` | 转发给工具注册表的审批要求(与 `@function` 同形) |
| `cache` | `bool` | `False` | 工具分发调用按 `(name, args)` 记忆化结果 |
| `cache_ttl` | `float` | `300.0` | `cache=True` 时的缓存寿命(秒) |
| `timeout` | `float` | `None` | 工具分发调用的硬性墙钟超时(秒),到点模型收到错误结果 |
| `available_if` | `Callable` | `None` | 工具登记门禁：返回假值或抛异常时不登记工具，普通方法作用域仍有效 |
| `defer` | `bool` | `False` | 注册为延迟工具(schema 按需加载,不随每次调用发送) |
| `register_globally` | `bool` | `True` | `False` = 构建工具但不进全局注册表 |

函数名、参数名 / 类型 / 默认值、一句话摘要都从函数签名和 docstring 自动读取,不在 method_options 中重复。

### 选择 Runtime

方法在它所属 Agent 配置的 Runtime 上运行;Agent 没有配置时用调用方的:`ExampleAgent(runtime=rt).f("x")` 让 `f` 及其中每次模型请求都在 `rt` 上运行,它调用的 Agent 方法也继承 `rt`。Runtime 在程序入口(CLI、脚本、测试)配置,不通过方法参数往下传。一个工作流要用两个模型时——比如作者和评审——给第二个角色一个自带 Runtime 的 Agent 实例。

### Runtime 注入

旧函数仍可能声明名为 `runtime`、`exec_runtime` 或 `review_runtime` 的参数,它们会自动注入:调用方没传(或传 `None`)时,先从当前调用链取 runtime;作为入口调用时经 `create_runtime()`(自动检测)新建,函数返回时再关闭。一个函数可以声明多个 runtime 参数,全部填同一个 runtime。这些参数不会出现在 LLM 工具 schema 和 WebUI 表单里。新写的方法不声明这些参数。

### 自省与安全

- `fn.spec` — 自动生成的 JSON-schema 工具 spec(`{"name", "description", "parameters"}`);`fn.execute(**kwargs)` 用 LLM 提供的 kwargs 调用 wrapper。
- 自递归兜底:函数自我重入超过 5 层抛 `RecursionError`(注入的情境 prompt 也会引导模型不要自调用)。
- 预调用钩子(`add_pre_invocation_hook` / `remove_pre_invocation_hook`)在每次调用开头运行,可以抛 `CancelledError` 中止本次调用(WebUI 的停止按钮就是这么实现的)。

### 记录到 DAG

- **进入函数**:写一个 `code` 节点(`output=None`, `status="running"`),函数 docstring 一并存进该节点的 `metadata.doc`,渲染上下文时拼在 `函数名(参数)` 前面。
- **函数体内 `llm()`**:每次调用写一个 `llm` 节点。
- **退出函数**:回填同一个 `code` 节点的 `output` / `status`。

`expose="hidden"` 时不写任何节点。standalone 运行(没安装 DAG store)时记录全部 no-op,函数照常执行。

### 可恢复步骤与代码版本

为同步编排函数声明 `method_options = {"report": {"resumable": True}}`，将外部操作放入 `step("稳定名称", 操作函数, *args, **kwargs)`。步骤输入和结果必须可保存为 JSON；继续执行时，已完成步骤直接返回保存的结果，不再调用操作函数。重复名称按出现次数区分，已执行步骤的顺序和输入必须保持兼容。

嵌套编排使用 `workflow("名称", 函数, *args, **kwargs)`。并行编排使用 `parallel({"分支名": (函数, args, kwargs)})`；各分支独立保存进度，所有分支停止后才释放任务所有权。

设置项 `execution.code_change_policy` 默认是 `keep_original`，继续使用保存的原函数和 Python 辅助函数源码；`use_latest` 保留已完成步骤的结果，并用当前代码执行后续兼容步骤。任务的“继续”操作可以覆盖此设置。A 已采用 B 后，再更新到 C 时选择保留原代码，会继续 B；尚未通过已有进度兼容性检查的候选版本不会取代已采用版本。新代码需要转换局部状态时，应在剩余步骤之前通过纯编排代码转换已保存的 JSON。已记录步骤被删除、重排、输入不兼容或固定依赖不可用时，任务保持暂停。权限和工具参数约定仍然需要通过兼容性检查。

手动调用恢复原执行记录；聊天调用将最终结果交给原来的待完成工具调用。重启导致的中断沿用两小时自动继续期限。主动暂停、取消、未回答的授权请求以及结果不确定的外部操作不会自动重试。

此功能在显式步骤处恢复，不保存任意 Python 调用栈。步骤外的外部调用和状态修改、异步编排、生成器、活动句柄及非 JSON 结果不支持此恢复约定。外部操作已经开始、但结果尚未保存时进程退出，必须先核对操作结果。函数运行界面显示是否声明可恢复步骤，普通函数中断后需要重新运行。

步骤之间不得依赖可变的 Python 全局变量、闭包或默认参数。需要持续保存的状态应通过步骤的 JSON 输入和结果传递，进程内变量修改不能作为恢复依据。

步骤依赖需要在模块级导入；辅助函数内部导入、动态导入 API 和动态生成代码会在执行步骤前被拒绝。Python 辅助函数源码递归保存。模块和类对象目前仅支持固定的标准库身份，第三方及用户包对象会被拒绝，因为只保存包初始化文件无法确定完整实现。

## 会话轮次与恢复

`Agent.run_turn(request, *, context=None, on_event=None, cancel_event=None, execution_context=None)` 返回 `TurnResult`。从 `openprogram` 导入 `TurnRequest` 和 `TurnResult`。新轮次执行前应用实例配置；`Context.for_session(store, session_id, head_id=..., blocks=..., providers=...)` 绑定持久化存储和分支。请求与 Context 的会话不一致时拒绝执行。`Context.session_id` 返回所选图的标识。

`arun_turn(request, **options)` 提供协作式取消的异步执行。`resume_turn(continuation, **options)` 与 `aresume_turn(...)` 复用断点请求，不重复执行准入。事件回调在执行线程接收现有运行时事件字典。持久化暂停和执行中追加输入沿用已有执行控制及安全点协议。

`ChatAgent` 继承这套契约，是实际聊天使用的类型。子类重写轮次入口时，不会将其自动包装为普通函数调用。旧 `openprogram.runtime.conversation.turn_runtime` 导入与共享 `openprogram.runtime.conversation.turn_runtime` 指向同一模块，不再维护另一份执行循环。
