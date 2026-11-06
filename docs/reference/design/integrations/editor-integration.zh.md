<div id="editor-integration-lsp-tools-and-acp-server"></div>

# 编辑器集成：LSP 工具与 ACP 服务器

于 2026-08-10 与所有者确认。功能矩阵中的编辑器集成缺口里，两项值得实现，五项是明确不做的内容。

<div id="lsp-tools-first"></div>

## LSP 工具（优先）

受益方是 Agent，而非编辑器。OpenProgram 将语言服务器作为后台分析进程运行，并通过 Agent 工具提供结果：

- `lsp_diagnostics(file)`：提供文件的编译器级错误和警告，Agent 完成编辑后立即可用，无需运行测试。
- `lsp_references(file, line, column)`：返回符号的所有真实调用位置；grep 会遗漏动态调用，也会误匹配同名字符串。
- `lsp_definition(file, line, column)`：返回符号跨文件、跨包的真实定义位置。

范围为 Python（pyright）和 TypeScript（typescript-language-server），即本仓库实际包含的两种语言。每个 workspace 每种语言运行一个服务器，首次使用时启动并缓存，随会话关闭。缺少服务器二进制时降级为明确的“不可用：请安装 X”工具结果，不导致崩溃；工具仍保持注册，使模型知道可用能力。

与 CodeGraph 的关系：CodeGraph 是用于理解代码库的预构建符号索引；LSP 提供索引无法实现的能力，即针对工作树当前未保存状态的实时诊断。

<div id="acp-server-second"></div>

## ACP 服务器（其次）

ACP（Agent Client Protocol）是让编辑器驱动外部 Agent 的编辑器无关标准。实现服务端可同时对应矩阵中的三行：Zed 等编辑器直接驱动 OpenProgram 会话（IDE 通过 ACP 驱动）；编辑器随每个请求发送选区和已打开文件上下文（把选区与打开文件加入上下文）；编辑器无需自建扩展即可成为入口（部分覆盖官方 IDE 扩展）。在现有会话/工具循环上增加一个 stdio 协议适配器，LSP 完成后开始。

<div id="non-goals"></div>

## 不做的内容

自建 IDE 扩展（由 ACP 替代）、行内补全（另一种产品）、行内聊天 / CodeLens / 状态栏动作（依赖自建扩展）、终端快捷键自动配置（收益太小）。这些矩阵条目有意保留为未完成。

<div id="implementation-status"></div>

## 实现状态

LSP 工具已实现。客户端位于 `openprogram/host/lsp/`，使用 stdio 上的 JSON-RPC，每个 workspace 每种语言一个服务器，首次使用时启动，退出时关闭；三个工具位于 `openprogram/programs/tools/code/lsp/`，用户说明见[语言服务器工具](../../../capabilities/lsp.zh.md)。服务器进程与其他子进程使用同一沙箱包装入口，因此 `sandbox.mode` 原样适用。

ACP 服务器已实现。`openprogram/interfaces/acp/` 包含 JSON-RPC ndjson 传输（`jsonrpc.py`）与协议映射（`server.py`），通过 `openprogram acp` 启动。实现协议版本 1：接收编辑器的 `initialize`、`session/new`、`session/load`、`session/prompt` 和 `session/cancel`，向编辑器发送 `session/update` 和 `session/request_permission`。用户配置见[编辑器（ACP）](../../../interfaces/acp.zh.md)。

适配器基于 `dispatcher.process_user_turn`，与 webui 线程、子 Agent 和任务执行器使用同一非 HTTP 入口，因此共享工具门控、权限与持久化，而非重新实现。轮次携带 `local_owner_authority()`：同机编辑器代表所有者交互式发言，这使 `approval.request` 可用。批准通过订阅 `question.asked` 事件到达编辑器，并通过 `resolve_question_and_broadcast` 回答，因此现有门控、规则及“始终允许”的规则持久化路径不变。

明确未实现：`session/set_mode` 和 `session/set_model`（Agent id 与权限模式由进程参数指定）、编辑器的 `fs/*` 与 `terminal/*` 客户端能力（OpenProgram 自有工具已能读写工作树），以及 `session/new` 传入的 MCP 服务器（OpenProgram 使用自身 MCP 配置）。
