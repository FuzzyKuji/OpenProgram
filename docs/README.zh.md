# 概览

每个 Markdown 文档页面通过 `text/markdown` alternate 链接提供原始源文件。文档首页源文件位于 [index.html.md](https://openprogram.io/docs/index.html.md)，[llms.txt](https://openprogram.io/llms.txt) 列出自动化读取入口。

<!-- Compatibility anchors for existing incoming links. -->
<a id="1-dag-上下文-原生多-agent-系统的地基"></a>
<a id="2-agentic-工作流-可信且自我演化的-agent-的地基"></a>
<a id="3-事件基础设施-主动-agent-的地基"></a>

<a id="安装"></a>
<a id="快速开始"></a>
<a id="新闻"></a>
<a id="为什么是-openprogram"></a>
<a id="1-dag-上下文--原生多-agent-系统的地基"></a>
<a id="2-agentic-工作流--可信且自我演化的-agent-的地基"></a>
<a id="3-事件基础设施--主动-agent-的地基"></a>
<a id="另外还带着这些"></a>
<a id="引用"></a>
<a id="许可证"></a>


<b>OpenProgram：自编程 AI Agent 框架</b>

这里提供 OpenProgram 的安装、Agent 使用、服务配置和框架扩展文档。可按下方任务选择入口；每一页都可通过语言菜单切换到英文对照。

[English](README.md) · [简体中文](README.zh.md) · [项目介绍](https://github.com/FuzzyKuji/OpenProgram/blob/main/README.zh.md) · [发行版](https://github.com/FuzzyKuji/OpenProgram/releases)

## 初次使用

1. 按平台[安装](install/install.zh.md)桌面应用或 CLI。
2. 阅读[快速上手](start/GETTING_STARTED.zh.md)，完成模型服务配置和首次对话。
3. 学习[日常操作](start/daily-use.zh.md)，或查询[常见问题](start/faq.zh.md)。

## 文档栏目

| 栏目 | 内容 |
|---|---|
| [开始使用](start/GETTING_STARTED.zh.md) | 首次对话、日常使用和常见问题。 |
| [安装](install/install.zh.md) | 平台要求、更新和卸载。 |
| [能力](capabilities/README.zh.md) | 工具、记忆、目标、应用和可复用工作流。 |
| [界面](interfaces/README.zh.md) | 桌面、浏览器和终端界面。 |
| [模型](models/README.zh.md) | 模型服务、账号、模型选择和配置。 |
| [集成](integrations/anthropic.zh.md) | 外部客户端和聊天渠道。 |
| [服务与运维](server/README.zh.md) | 远程访问、部署和服务管理。 |
| [参考](reference/README.zh.md) | Python API、CLI 参数、配置键和模型服务明细。 |
| [设计](reference/design/README.zh.md) | 当前子系统设计、约束和实现状态。 |

## 常用任务

- 从目录、git URL 或 GitHub `owner/repo` [安装程序](capabilities/installing-programs.zh.md)。
- [编写函数](capabilities/agentic-programming/writing-functions/agent.zh.md)或[编写工作流](capabilities/workflows/authoring.zh.md)。
- [配置模型](models/README.zh.md)和[连接渠道](integrations/channels.zh.md)。
- [使用记忆](capabilities/memory.zh.md)和[管理目标](capabilities/goal.zh.md)。
- 查阅[全局 CLI 参数](reference/cli/README.zh.md)、[配置键](reference/config-keys.zh.md)或[模型服务配置](reference/provider-registry.zh.md)。

## 阅读约定

导航名称采用简短的主题名称，页面完整标题和介绍说明具体范围。中英文页面对应同一主题，命令标识符保持一致。生成参考页由当前命令解析器、配置 schema 和模型服务清单重新生成。

设计页解释工程决策，并与代码同步维护。计划中的行为在实现状态部分注明。操作步骤和支持的命令以产品指南及自动生成的参考页为准。

## 项目信息

项目背景、示例、动态、引用和许可证信息见[相关项目](reference/comparisons/related-projects.zh.md)、[框架比较](reference/comparisons/ai-agent-frameworks.zh.md)、[编程原则](capabilities/agentic-programming/philosophy.zh.md)及[仓库 README](https://github.com/FuzzyKuji/OpenProgram/blob/main/README.zh.md)。
