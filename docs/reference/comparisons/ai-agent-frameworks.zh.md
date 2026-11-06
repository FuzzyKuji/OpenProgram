<div id="openprogram-vs-langgraph-autogen-and-crewai"></div>

# OpenProgram 与 LangGraph、AutoGen、CrewAI 对比

本页比较各项目文档公开描述的编程模型，帮助开发者选择合适的抽象，不对无关功能排名。比较内容最后于 **2026-08-13** 依据链接中的官方文档核实。

| 框架 | 文档中的主要抽象 | 文档中的编排模型 | 文档中的重点 |
|---|---|---|---|
| **OpenProgram** | `Agent` method 与执行运行时 | 普通控制流、模型选择工具以及共享执行 DAG | Agent 可以编写可审查的 agentic function；运行时管理上下文、工具、记忆、界面与多 Agent 协作 |
| **LangGraph** | 包含节点与边的 Graph API，或使用 `@entrypoint` 和 `@task` 的 Functional API | 显式状态图，或在同一运行时上使用标准 Python 控制流 | 持久执行、持久化、流式输出和人工参与控制 |
| **AutoGen** | AgentChat 的 Agent 与团队，或 Core 的 Agent 与运行时 | Agent 消息、团队模式以及事件驱动的 Core API | 对话式单/多 Agent 应用和可扩展的多 Agent 运行时 |
| **CrewAI** | Agent、任务、crew 和 flow | 基于角色的 Agent crew 与事件驱动 flow 结合 | 协作 Agent 团队与结构化工作流自动化 |

来源：[OpenProgram Agentic 编程](../../capabilities/agentic-programming/README.zh.md)、
[LangGraph 概览](https://docs.langchain.com/oss/python/langgraph/overview)、
[LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)、
[AutoGen 概览](https://microsoft.github.io/autogen/) 和
[CrewAI 文档](https://docs.crewai.com/)。

<div id="choose-openprogram-when"></div>

## 适合选择 OpenProgram 的情况

- Agent 需要能够提出或编写新的工作流，并以可审查函数的形式表达，而不只是从固定图或团队配置中选择；
- 需要由一个运行时提供终端、Web、模型 provider、工具、记忆、上下文和多 Agent 界面；
- 需要将执行上下文表示为由用户、模型、函数和工具调用组成的 DAG。

从[自编程 AI Agent](../../capabilities/agentic-programming/self-programming-ai-agents.zh.md)和
[OpenProgram 安装指南](../../start/GETTING_STARTED.zh.md)开始。

<div id="choose-langgraph-when"></div>

## 适合选择 LangGraph 的情况

系统需要持久执行、持久化、流式输出以及人工参与的状态控制。LangGraph 提供显式 Graph API 和支持普通 Python 分支、循环、函数调用的 Functional API。其概览将 LangGraph 描述为底层编排运行时，并建议需要预构建 Agent 架构的用户使用更高层的 LangChain Agent。

官方来源：[LangGraph 概览](https://docs.langchain.com/oss/python/langgraph/overview)
和 [Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)。

<div id="choose-autogen-when"></div>

## 适合选择 AutoGen 的情况

设计以 Agent 交换带类型的消息或参与团队模式为中心。AutoGen 提供高层 AgentChat API 和底层事件驱动 Core 运行时；其文档涵盖团队、状态管理、人工反馈、自定义 Agent 和分布式运行时。

官方来源：[AutoGen](https://microsoft.github.io/autogen/) 和
[Agent 与 Agent 运行时](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/agent-and-agent-runtime.html)。

<div id="choose-crewai-when"></div>

## 适合选择 CrewAI 的情况

应用可以明确映射为具有角色、目标和任务并组织为 crew 的 Agent，或者映射为调用 crew 执行自主工作的结构化事件驱动 flow。CrewAI 文档将 crew 用于协作，将 flow 用于受控工作流执行。

官方来源：[CrewAI 文档](https://docs.crewai.com/)。

<div id="verification-boundary"></div>

## 核实边界

表格总结的是文档公开描述的抽象，并不意味着未列出的功能无法通过扩展或自定义代码实现。项目 API 会变化，在作出长期迁移决定前，应核实链接中的文档。
