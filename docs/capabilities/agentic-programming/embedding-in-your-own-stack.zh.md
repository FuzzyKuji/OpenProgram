# 嵌入到现有应用

在已有应用中将 Agent 和 Runtime 作为 Python 库使用。宿主提供模型客户端，并决定是否持久化会话。库调用不启动 Web UI 或终端 UI。

## 提供宿主 Runtime

```python
from openprogram import Agent, Runtime


def model_call(content, model="host-model", response_format=None):
    # Replace this offline response with the host's model client.
    return "Host model response"

runtime = Runtime(call=model_call, model="host-model")

class ReviewAgent(Agent):
    tools = []

    def classify(self, review: str) -> str:
        """Classify review sentiment."""
        return self(f"Classify review sentiment:\n{review}")

    def summarize(self, review: str) -> str:
        """Summarize a review."""
        sentiment = self.classify(review)
        return self(f"Summarize this {sentiment} review:\n{review}")

reviewer = ReviewAgent(runtime=runtime)
try:
    summary = reviewer.summarize("The service was fast.")
finally:
    runtime.close()
```

`Runtime(call=...)` 接收宿主回调，向其传递内容块、模型名称和可选返回格式。构造时不请求模型。宿主负责关闭自己提供的 Runtime。

Agent 方法自动继承该 Runtime，无需逐个帮助函数传递。Context 与函数作用域自动管理。示例回调返回固定文本，不需要网络。

## 显式持久会话

默认 Agent 调用不会让实例拥有持久会话。宿主需要续接历史时，显式选择 store 与 session：

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

`Context(store=writer)` 显式在调用之间续接该会话。宿主拥有 store 与 Runtime。`head_id` 可选择已有分支末端。默认 Agent 调用保持独立。

## 检查调用与暴露工具

```python
from openprogram.state.store import SessionNodeWriter

for node in SessionNodeWriter(store, "review-42").load():
    print(node.name, node.caller, node.output)
```

普通公开 Agent 方法自动具有调用作用域。将方法暴露为模型工具时，在 `method_options` 中设置 `tool=True`。显式登记提供 `.spec` 与 `.execute`。记录本身不授予工具权限，见 [Agent 与 Context API](../../reference/api/agent.zh.md)。

## 方法功能与宿主 hook

Agent 方法提供完整执行约定。`set_cancellation_check`（在 `openprogram.host.cancellation`，与 `CancelledError`、`check_cancelled` 同处）和 `set_session_id_provider`（在 `openprogram.runtime.agent.call_state`）保留可用，用于宿主取消与问题路由。

嵌入 import 路径调用库 API，不替代完整安装产品。import 检查位于 `tests/embed/`。参见 [Runtime](../../reference/api/runtime.zh.md) 和 [编程指南](writing-functions/agent.zh.md)。
