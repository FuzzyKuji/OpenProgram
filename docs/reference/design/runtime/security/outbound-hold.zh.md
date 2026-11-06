# 代发暂存

Agent 替用户发出去的东西（邮件、聊天消息、评论）会到达没有向 Agent 提过任何要求的人。暂存把每个这类调用当作草稿，在任何权限模式下都要用户批准。

## 哪些调用被暂存

MCP 适配器在注册每个工具时判断一次（`mcp/adapter.py` 的 `sends_on_behalf`），结果存为 AgentTool 上的 `_sends_on_behalf`。一个工具算作发送，需要同时满足：

- 服务器没有声明 `readOnlyHint: true`；
- 原始工具名按标点和驼峰拆开后，不以读取类动词开头（`get`、`list`、`read`、`search`、`fetch`、`find`、`query`、`view`、`describe`、`count`、`check`、`lookup`）；
- 包含发送类动词（`send`、`reply`、`respond`、`post`、`publish`、`forward`、`invite`、`share`、`comment`、`tweet`、`broadcast`、`notify`、`dm`），或者以创建类动词（`create`、`add`、`new`、`write`、`compose`）开头、后面跟着对外的名词（message、email、mail、comment、reply、post、tweet、invite、dm）。

所以 `send_email`、`chat.postMessage`、`create_comment` 会被暂存；`list_messages`、`get_posts`、`create_draft` 不会。MCP 的 `openWorldHint` 默认就是 true，多数服务器也不设，分不出发送和读取，所以不用它。内置工具不暂存：`chat_send` 是在会话自己的聊天里说话，`send_message` 是和其他 OpenProgram 会话通信。

## 在哪里生效

`permissions/policy.py`：

- `permission_decision` 在 deny 规则和强制审批之后、在模式、allow 规则和 Auto 分类器之前检查 `_held_outbound(name, req)`。被暂存的调用在 Bypass、Auto、Ask、Accept edits 下，以及有 allow 规则时，都是 `ask`，原因 `OUTBOUND_HOLD`。非交互来源（scheduler、cron、agent_spawn、mcp）照常变成 `APPROVAL_UNAVAILABLE_NON_INTERACTIVE` 拒绝。
- `_held_outbound` 读这一回合的 Agent（`req.agent_id`，缺省为 `main`）的 `AgentSpec.hold_outbound`，默认 `true`。找不到 Agent 时也暂存。
- `one_shot_approval` 包含所有发送类工具，无论是否暂存，所以审批不会提供"总是允许"，也不会写 allow 规则：每条消息单独批准。

审批卡片本来就显示工具名和完整参数（`approval._approval_detail` 对一次性调用不截断），这就是草稿。**拒绝并附言**把用户要改的地方作为工具结果交还给模型；模型下一次调用就是一份新草稿，再次请求审批。

## 配置

`hold_outbound` 是 `agent.json` 顶层的布尔值，`PATCH /api/agents/{id}` 接受它。缺省读作 `true`；只有显式 `false` 才关闭暂存，这时调用和其他工具一样按会话的模式和规则处理。

## 实现状态

已实现：MCP 工具分类、所有模式下的暂存、一次性审批、通过 `agent.json` 和 HTTP API 的按 Agent 设置。未实现：Agents 页面上的开关，以及通过 computer use 或浏览器完成的发送（点击页面上的"发送"按钮，从调用本身认不出是在发送）。
