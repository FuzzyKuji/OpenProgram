<div id="self-programming-ai-agents"></div>

# 自编程 AI Agent

自编程 AI agent 可以在工作过程中创建或修改可执行工作流。在 OpenProgram 中，
agent 用常规文件工具在 `~/.openprogram/programs/<name>/` 中编写 Workflow 包，
运行 `openprogram programs check` 测试并提交，之后的轮次通过与现有工具相同的注册表调用它的入口。

这项能力的范围小于不受限制的自我修改。OpenProgram 不允许模型静默替换 runtime
或绕过检查。可编辑单元是能够审查的包，具有声明的入口、每个角色显式的工具访问、
执行记录和独立的 Git 历史。

<div id="what-the-agent-programs"></div>

## Agent 编写什么

Workflow 将确定性控制流与模型决策结合：

```python
from openprogram import Agent, Context

reviewer = Agent(instructions="You find concrete defects.", tools=[])
editor = Agent(instructions="You revise drafts.", tools=[])


def review_then_revise(draft: str) -> str:
    """Review a draft, then revise it against the review."""
    ctx = Context({"draft": draft})
    review = reviewer("Identify concrete defects in this draft", context=ctx)
    return editor("Revise the draft using the review",
                  context=ctx.derive({"review": review}))


PROGRAM_ENTRIES = [review_then_revise]
```

Python 函数体固定所需的执行顺序，两个角色处理语义步骤，各自只看到自己 Context 中的块。
每次角色调用都记录在会话图中。

<div id="how-an-agent-creates-one"></div>

## Agent 如何创建

安装并启动 OpenProgram：

```bash
curl -fsSL https://openprogram.io/install | sh
openprogram
```

然后向 agent 请求一个范围明确的工作流，例如：

```text
创建一个名为 review_then_revise 的 Workflow。它必须审查草稿，
根据审查意见修订，只返回最终文本，并包含行为测试。
```

[编写和检查 Workflow](../workflows/authoring.zh.md) 定义包结构、角色与 Context
规则、测试工具和检查流程。worker 无需重启即可加载通过检查的 Workflow。

<div id="runtime-controls-that-still-apply"></div>

## 仍然适用的 Runtime 控制

- 工具访问由每个角色的 `tools` 和配置的审批策略决定。
- 每次角色调用及其发送的完整请求记录在会话图中。
- 资源限制、取消、结构化输出验证和提供商用量核算仍由 runtime 负责。
- 源码修改仍是普通文件：可以检查、测试和回退，只有通过检查并已提交的版本才会加载。

<div id="when-to-use-it"></div>

## 何时使用

当重复任务需要可复用、可检查的流程，而语义步骤仍需要模型判断时，使用自编程。
当整个操作都是确定性操作时，使用普通函数。
当操作已有稳定实现时，使用现有工具。

完整执行合同见 [Agentic Programming 指南](README.zh.md)、
[`Agent` method 参考](../../reference/api/agent.zh.md)和
[设计理由](philosophy.zh.md)。
