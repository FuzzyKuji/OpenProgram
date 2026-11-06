# 工程改进待办

> 跨专项分支的已完成状态、未合并实现和后续实施顺序统一记录在
> [OpenProgram implementation status and handoff](implementation-status.zh.html)。
> 本文件只保留尚未定案、需要讨论后再排期的改进项。

本文只收当前仍需要讨论后再动的项，按影响排序。历史审计日期、一次性计数和已修复
问题不作为当前状态依据；讨论定案一条就删除对应条目。

## 前端

1. **`window.*` 退役（state-layer 阶段 3）**：仍有多处旧状态入口，需按 state-layer
设计逐步收敛。四组：
   `W.currentSessionId` 路由闸门 39 处、`window.conversations` 20 处、
   `W.isRunning` 9 处（最便宜，`runningTasks` 已覆盖）、
   `window.__sessionStore` 38 处。另有 30+ 处 `window.dispatchEvent`
   无类型字符串事件总线（阶段文档未列的第五类）。按设计文档这是阶段 2
   完成后的事，规模大，需专项排期。
2. **WS 层用无类型 CustomEvent 二次广播 store 帧**
   （`apps/web/lib/net/ws/use-ws.ts` 六处）：与 store 平行的第二条状态通路，
   detail 无类型。属于 window.* 退役的同族问题，可并入 window.* 退役专项。

## 仓库结构

全仓结构检查的结论，按下面顺序逐条讨论。预期分层是核心（`openprogram/`）在最底层，
Server（`openprogram/interfaces/server`）和 CLI（`openprogram/interfaces/cli`）依赖核心，反过来不行。

1. **`openprogram/models/providers/` 公共模块平铺一层**：各 provider 目录已收进 `adapters/`，
   但约 30 个公共模块（注册、流式、类型、缓存、订阅、配置）仍在顶层并排。提案：公共模块按
   注册、模型、流式分组。
2. **设计记录缺子目录**：`docs/reference/design/ui` 和 `runtime` 各有约一百个文件平铺，
   `site-*`、`repository-*` 页面散在 `docs/reference/design/` 根部。提案：按领域分子目录，
   保持 `nav.py` 的路由。

## 模块规模（多职责，重构窗口另排）

10. 具体行数不在本设计文档中固定；排期时应以当前源码和职责边界重新测量。
    当前候选包括 `openprogram/programs/tools/computer_use/computer_use_agent/desktop/macos.py`
    和 `windows.py`、`openprogram/state/store/snapshot/checkpoint/store.py`、
    `openprogram/host/security/safe_http.py`、`apps/desktop/main.js`、
    `openprogram/runtime/conversation/process_runner.py`、`openprogram/programs/applications/browser/pages.py`、
    `openprogram/interfaces/server/routes/catalog/programs.py` 和
    `openprogram/programs/_host/runtime.py`。
   `apps/cli/src/runtime/` 下的 yoga-layout 与 ink 运行时属 vendored 移植代码，
   不算多职责问题。

## 回归核验清单

原仓库缺陷快照混合了已修行为、未证实观察和功能提案，在此合并为核验清单，不表示每项当前仍有缺陷。创建实施任务前，需要在当前源码和公开 UI 入口复现；完成状态写回对应主题的正式设计。

| 范围 | 需要核实的行为 | 代码或入口 |
| --- | --- | --- |
| 回退 | Web 在确认后携带 plan hash 和 idempotency key 提交 apply；缺少结果时给出可操作状态 | `ws_actions/chat/rewind.py`、`_rewind.py`、`message-actions.tsx`、`slash-commands.ts` |
| 命令发送 | WebSocket 未连接时不把命令视为成功，不清空草稿 | `wsSend`、输入框提交 |
| 斜杠命令 | 输入 `/` 打开菜单不会意外执行压缩；空 `/skill` 名称和 `/task` 提示有校验反馈 | `slash-commands.ts` |
| 菜单交互 | 收起动画不拦截回车或历史上下键；必填参数保持可编辑 | `selectSlashCommand`、输入框键盘处理 |
| 会话要求 | 没有会话时反馈原因，不静默清空输入 | 输入框与斜杠命令 |
| 上下文压缩 | 忙碌、建议、完成、失败、无变化状态可见；必要时先 compact 后 snip；reactive compact/snip 也有反馈 | `loop_runner.py`、`reactive.py`、`chat-handlers.ts` |
| 上下文历史 | 压缩保留旧轮次及 DAG head；snip 只改下一次请求 history；摘要展开需要可视核验 | 上下文详情与聊天记录 |
| Help 与 doctor | Help 打开并聚焦菜单；doctor 在有无会话时均有明确的结果展示 | `/help`、`/doctor` |
| 控件重叠 | 跳到最新按钮和斜杠菜单在实际位置可用，不能仅凭 z-index 判断遮挡 | 聊天 UI |
| 附件 | 不支持或过大的文件明确反馈 | `image-attach.ts` |
| 桌面启动 | 窗口以预期布局出现，不出现从角落调整大小的过程 | 已安装 App |
| CLI 恢复 | resume 参数将正确会话传入 Ink runtime | `openprogram/interfaces/cli/ink.py`、`apps/cli/src/index.tsx` |
| SSO、语音与插件隔离 | 文档区分已实现方法/provider 与未实现入口；community 插件执行符合隔离合同 | `auth/methods/sso.py`、`speech/tts.py`、`plugins/sandbox.py`、plugin loader |
| 函数恢复 | 区分原帧恢复与新建兄弟重试；间接调用循环符合递归约束 | `ws_actions/chat/retry.py`、`agent/call_state.py` |
| 函数元数据 | 动态 metadata 和源码字面量声明符合表单合同 | 函数表单与元数据文档 |
| 分发 | Linux 桌面产物、升级失败恢复、Workflow 手动发布与沙箱行为门禁符合安装文档 | 安装、源码升级、Workflow 发布 |
| 命令注册表 | 重名命令有明确解析顺序，菜单无歧义 | `runCommand` 与命令菜单 |

闲时自动压缩仍属于产品决策，不默认作为缺陷；环境变量探测不能替代文档规定的 AuthStore 边界。外部 issue 数量与旧快照提交号不作为当前正确性的证据。
