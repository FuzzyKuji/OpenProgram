# 概览

这一页帮你回答一个问题：OpenProgram 能做什么，以及每种能力去哪页看。能力分三层：编程范式、现成的工作流、扩展机制。

## Agentic Programming 范式

OpenProgram 的底座是 Agentic Programming：**Python 控制流程，LLM 提供推理**。你把任务拆成函数调用图，不需要推理的节点写普通 Python，需要理解 / 生成 / 判断的节点用 `Agent` method 装饰，在函数体里通过 `llm(...)` 调用模型。执行顺序、状态、重试都是普通代码，可以单元测试。

- [Agentic Programming 指南](agentic-programming/README.zh.md) —— 编写函数的学习路径与三种"选择下一步"机制
- [设计哲学](agentic-programming/philosophy.zh.md) —— 范式解决什么问题、为什么反转控制权

## Agentic Workflows：现成的 agent

基于该范式写成的成品工作流（代码里叫 harness / agentic program），每个都是一个 git 仓库，用 `openprogram programs install <source>` 安装。用 `openprogram programs list` 查看状态和已注册的函数；函数注册后既能在聊天里作为工具触发，也能用 `openprogram programs run` 直接跑。

- [Agentic Workflows 总览](workflows/README.zh.md)
- [安装程序](installing-programs.zh.md) —— 从目录、git URL 或 GitHub `owner/repo` 安装程序，以及 harness 的目录契约

## 扩展机制

不写 harness 也能扩展 agent 的能力：

- [Skills](skills.zh.md) —— `SKILL.md` 注册表：给模型按需加载的领域知识与操作手册
- [Commit, push, PR](commit-push-pr.zh.md) —— 把做完的活从工作区送到可评审的 pull request，并在 `git log` 里留下 AI 共同作者署名
- [Plugins](plugins.zh.md) —— 从 pip / npm / git / 本地路径安装插件，向宿主贡献 commands、skills、MCP server 等
- [MCP](mcp.zh.md) —— 接入任意 MCP server，其工具直接出现在聊天里
- [内置工具](tools.zh.md) —— 随框架自带的工具清单（shell、文件、网络检索、图像、PDF 等）及各自需要的 key

- [配置 Agent](agents.zh.md) —— 模型、指令、能力范围、记忆和独立试运行对话
