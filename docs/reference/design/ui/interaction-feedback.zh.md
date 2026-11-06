<div id="interaction-feedback-the-0ms-rule"></div>

# 交互反馈：0ms 规则

用户点击后，只要操作耗时超过约 100ms，就必须立即提供可见反馈。客户端在 0ms 渲染乐观过渡状态；真实数据到达后替换；失败时回滚并显示错误。

网络请求等待期间，点击不能没有任何可见变化。

<div id="the-three-layers"></div>

## 三个层次

1. **0ms 乐观状态**：点击后，在任何网络 I/O 之前立即切换客户端可见状态，例如加载卡片、目标版本高亮、“正在停止…”、聊天记录中的待处理消息。直接写入 session store（消息或 store 对象上的乐观标志、状态补丁），不另建一套状态记录。
2. **服务端快速确认**：后端确认请求。函数运行时，dispatcher 在分发时预先创建运行节点，因此点击后约 0.13s 的 `load_session` 会返回真实的待处理卡片，`chat_ack {function_run:true}` 则立即触发 hydration。hydration 的 `setMessages` 替换整份聊天记录，使用临时 id 的客户端占位项随之移除，不产生闪烁。
3. **流式更新**：`tree_update` / `stream_event` 增量实时填充卡片，最终的 `result` / `running_task_clear` 完成状态更新。

**失败回滚（必需）**：每个乐观状态都必须结束。真实数据替换它，或者超时（控制操作为 10s，`OPTIMISTIC_TIMEOUT_MS`）后恢复状态并显示错误提示。无限等待的乐观状态会误导用户，比没有反馈更差。

<div id="shared-helper"></div>

## 共享辅助函数

`apps/web/lib/runtime-bridge/optimistic-action.ts` 提供 `optimisticAction({apply, settled, revert, onTimeoutMessage})`。`apply` 设置 0ms 状态；真实数据替代后，`settled()` 返回 true，例如消息已从 store 移除、树已重新填充、`branch.active` 已切换。超时时若 `settled()` 仍为 false，则运行 `revert` 并显示提示。确认过程通过 `load_session` 重新加载的界面使用它，例如重试和版本切换。纯本地短暂状态（停止、fn-form 占位、分支切换）直接在对应代码中实现这一模式。

<div id="per-surface-behaviour"></div>

## 各界面的行为

| 界面 | 点击后的前 100ms |
|---|---|
| 聊天发送 | 欢迎页在 0ms 隐藏；`chat_ack` 到达时加入用户消息和回复占位项（约一次网络往返） |
| 停止按钮 | 0ms 清除 runningTask，并把助手消息修改为 `[cancelled by user]`；同时处理发送队列 |
| 函数调用重试 | 0ms 将卡片正文改为加载状态并显示“运行中”，切换器变为 N+1/N+1；重新加载后填充；10s 后回滚 |
| fn-form / 欢迎页提交 | 0ms 插入待处理运行卡片；hydration 无缝替换；POST 失败则移除并提示 |
| Runtime `< N/M >` 切换器 | 0ms 将当前卡片改为加载状态并显示目标同级索引；重新加载后替换内容；10s 后回滚 |
| 聊天消息 `< N/M >` 切换器 | `N/M` 标签在 0ms 更新到目标；重新加载后填充；失败时恢复标签并提示 |
| 分支面板切换 | 0ms 高亮所点击的行为 active；真实 `branch.active` 替换；10s 后自行清除 |
| 聊天重试 / 编辑 / 分支 / 回退 | `setBusy(true)` 使按钮变暗，`setRunActive` 禁用编辑/重试；busy 标志就是过渡反馈 |
| 侧栏会话切换 | 调用 `router.push`；store 已有历史消息，因此路由切换时直接渲染缓存消息 |
| 启用/禁用模型、工具、开关 | 立即更新本地 store |

新增乐观状态使用 store 的既有机制：`updateMessage` 状态/树补丁、`siblingIndex`、`setRunningTaskFor` 和 `appendMessage` 占位项。不建立并行状态。
