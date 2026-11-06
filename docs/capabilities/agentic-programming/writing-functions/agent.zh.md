# Agent 调用与普通方法

单次模型请求使用 `agent()`。多个方法共用模型设置和指令时，定义 `Agent` 子类。框架自动建立调用作用域并管理 Context。


每个 Agent 执行分别管理自己的 DAG。聊天只记录用户消息、模型请求和直接工具调用；普通辅助函数不产生持久化节点。调用另一个 Agent 时创建独立 DAG，父图只保存调用结果和 child_session_id 引用。权限、取消与文件修改备份仍由原执行负责，不依赖图所有权。

## 普通方法

```python
from openprogram import Agent

class ReviewAgent(Agent):
    tools = []
    instructions = "Preserve facts. Return concise text."

    def classify(self, review: str) -> str:
        """Classify review sentiment."""
        return self(f"Classify as positive, negative, or neutral:\n{review}")

    def summarize(self, review: str) -> str:
        """Summarize a review with its sentiment."""
        sentiment = self.classify(review)
        return self(f"Summarize this {sentiment} review in one sentence:\n{review}")

reviewer = ReviewAgent(model="configured-model")
summary = reviewer.summarize("The service was fast.")
```

`classify` 和 `summarize` 是普通 Python 方法，作用域记录父子关系。`self(...)` 通过现有 Runtime 请求模型。docstring 描述函数调用，prompt 提供模型指令与数据。

Agent 实例保存配置，不默认在独立顶层调用之间保存会话。嵌套调用使用当前执行。Context 为每次请求选择允许读取的历史，并求值已配置内容。

## 直接调用与异步代码

```python
from openprogram import agent, agent_async

answer = agent("Summarize this text", tools=[])
# 在异步函数内：
# answer = await agent_async("Summarize this text", tools=[])
# answer = await reviewer.arun("Summarize this text")
```

`tools=[]` 禁用模型工具。`tools=None` 由 Runtime 选择可用工具，并执行当前授权规则。

## 方法元数据与显式工具

公开方法需要表单元数据、可见性规则或工具登记时，声明 `method_options`：

```python
class TextAgent(Agent):
    tools = []
    method_options = {
        "summarize": {
            "tool": True,
            "name": "summarize_notes",
            "input": {"text": {"description": "Text to summarize"}},
            "expose": "io",
        },
    }

    def summarize(self, text: str) -> str:
        """Summarize text."""
        return self(f"Summarize:\n{text}")
```

方法记录不会自动注册工具。`tool=True` 显式登记该方法。函数名称与签名提供工具 schema。可见性控制历史呈现，不授予工具权限。

## 普通 Program 函数

受管加载器采集授权 Program 包中的普通源码函数。通过 `PROGRAM_ENTRIES` 列出公开入口。私有帮助函数保留调用作用域，不自动成为工具。该采集不作用于任意宿主文件或依赖。

确定性编排直接调用 Python 方法或函数。模型选择调用时，提供显式登记的工具，见 [工具调用](../choosing-the-next-step/tool-calling.zh.md)。

## 方法功能

Agent 方法通过 `method_options` 承担输入元数据、工具登记、权限与持久步骤。[API 参考](../../../reference/api/agent.zh.md) 说明 Context、方法选项和方法配置。各字段见 [函数元数据](function-metadata.zh.md)。

## 持续会话

`Agent.run_turn()` 执行持久化会话轮次。`ChatAgent` 是 App、Web、TUI 和渠道入口使用的聊天子类，两者共用历史、权限、工具、流式事件、压缩和持久化运行时。

```python
from openprogram import Agent, Context, TurnRequest
from openprogram.runtime.context.session_db import default_db

context = Context.for_session(default_db(), "example-conversation",
                              blocks={"reference": "用户提供的参考内容"})
worker = Agent(context=context)
result = worker.run_turn(
    TurnRequest(session_id="example-conversation", user_text="总结参考内容",
                agent_id="main", source="python"),
    on_event=lambda event: print(event["type"]),
)
print(result.final_text)
```

后续轮次使用同一个 session ID。`Context.for_session` 选择存储，不创建模型客户端。可选的 `head_id` 指定分支前驱；`Context(history=None)` 排除历史图内容，保留当前输入。具名内容和 provider 以用户内容参与请求，不改变系统指令或工具权限。

`arun_turn()` 和 `aresume_turn()` 是异步入口。事件回调在执行线程运行，与 asyncio 消费者通信时使用线程安全的传递方式。取消等待任务会通知执行轮次，并等待协作式清理；同步调用可通过 `cancel_event` 传入 `threading.Event`。

`resume_turn(continuation)` 使用已有断点和冻结请求，不重复追加用户消息，也不重新应用实例中改变的设置。持久化暂停、执行中追加输入和恢复准入仍由现有执行驱动及控制服务负责，不创建第二套任务管理。普通函数不记录节点，嵌套 Agent 保持独立 DAG，工具超时不取消父聊天。
