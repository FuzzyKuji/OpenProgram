# 设计文档

按子系统查找设计与实现边界。每个主题先阅读下方入口，再在侧栏展开对应分类，查看详细设计、对比与关联说明。


侧栏只列出七个一级领域；展开领域后选择子模块，再进入页面。进入页面时自动展开完整路径，过滤同时匹配页面名与分类名。

## 阅读顺序

1. 了解整体系统：[框架总览](framework-overview.zh.md) → [仓库结构](repository-structure.zh.html)。
2. 跟踪一次执行：[调用流程](runtime/execution/agent-call-flow.zh.md) → [执行控制](runtime/execution/control.zh.html) → [会话存储](runtime/session/storage.zh.md)。
3. 修改某个子系统：选择下方主题，阅读设计正文及其实现状态附录，再核对源码和验证要求。

## 架构总览

了解整体架构、源码归属与实现边界。

[框架总览](framework-overview.zh.md) · [仓库结构](repository-structure.zh.html) · [实现状态导航](implementation-status.zh.html)

## Agent 与工作流

依次阅读执行控制、会话存储、分支协作与恢复。

[执行控制](runtime/execution/control.zh.html) · [会话存储](runtime/session/storage.zh.md) · [会话 DAG](runtime/dag/overview.zh.md) · [目标与重启恢复](runtime/reliability/goal-and-recovery.zh.html) · [Agent 配置](runtime/agent-configuration/agent-configuration-ui.zh.html)

先阅读函数调用、工作流组成与应用执行，再查看报告场景。

[函数调用](function/calling-unification.zh.md) · [Workflow](runtime/workflows/workflow.zh.md) · [程序模型](function/agentic-program.zh.html) · [应用运行](runtime/programs/application-runtime.zh.html) · [报告工作流](runtime/workflows/report-suite.zh.html)

先阅读事件约定，再阅读规则、主动执行与调度。

[事件层](proactive/event-layer.zh.md) · [规则执行](proactive/execution-model.zh.md) · [调度与记忆](scheduler/memory-integration.zh.html)

## 上下文与记忆

区分单次请求的上下文组装与持久化记忆、归因。

[上下文总览](context/overview.zh.md) · [上下文组成](context/composition.zh.md) · [上下文压缩](context/compaction.zh.md) · [记忆总览](memory/overview.zh.md) · [实体记忆](memory/entity-memory-proposal.zh.md)

## 界面与交互

先阅读状态与交互约定，再选择对话、浏览器、工作区、设置或终端。

[界面总览](ui/README.zh.md) · [状态层](ui/state-layer.zh.md) · [对话与输入框](ui/composer/composer-interaction-modes.zh.md) · [内置浏览器](ui/browser/built-in-browser.zh.html) · [项目工作区](ui/workspace/project-workspace.zh.md) · [命令行与终端界面](cli/README.zh.md)

## 模型与外部接入

分别查找请求构建、模型参数、账号解析与错误处理。

[模型目录](providers/models/overview.zh.md) · [请求构建](providers/request-build.zh.md) · [账号管理](providers/auth/unified-account-management.zh.md) · [重试行为](providers/reliability/error-retry.zh.md) · [用量统计](usage-metering.zh.md)

查找 Harness、MCP、技能、插件与消息渠道的接口约定。

[Harness 标准](integrations/harness-standard.zh.md) · [MCP 集成](integrations/mcp-integration.zh.html) · [MCP 服务端](integrations/mcp-server.zh.html) · [扩展启用控制](extension-gating/README.zh.md) · [消息渠道](channels/design.zh.md)

## 安全与工程

分别查找执行权限与安装、更新、平台支持。

[执行权限与沙箱](runtime/security/sandbox-architecture.zh.html) · [系统访问](runtime/security/system-access.zh.html) · [依赖安全](security/dependency-security.zh.html) · [安装与打包](distribution/installation-packaging.zh.html) · [自动更新](distribution/automatic-updates.zh.html)

查找统一验证规则、错误处理与文档维护要求。

[测试系统](testing/test-system.zh.html) · [错误处理](error-handling.zh.md) · [文档结构与渲染](docs-site.zh.html) · [站点检索与性能](site-discoverability-performance.zh.html)

## 补充材料

- **交互原型**：布局与交互试验，不代表已实现的产品行为。侧栏集中列出原型，避免与当前设计混排。
- **实施记录**：迁移步骤、实施计划和待核实差异。以对应主题的设计正文为准，不把历史记录当作当前实现状态。
- **研究材料**：探索性方案、威胁分析与评估记录，不作为产品承诺。

## 维护规则

每个页面只有一个侧栏分类。新增页面在 `scripts/docs_site/nav.py` 注册分类与阅读顺序；尚未分类的页面仍显示在“待分类”组。分类调整保持文件 URL 不变。

一个主题维护一份当前设计；图示、对比与实施记录应说明与主设计的关系，避免重复陈述。默认版本使用英文，并同步中文对照版。详细编写要求见[文档规范](docs-site.zh.html)。

文档描述、源码存在、测试通过、发布完成与本地 App 验收分别核实。本目录的分类不表示实现完成度。
