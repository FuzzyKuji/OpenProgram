<div id="channels"></div>

# 通信渠道

通信渠道让你在 Telegram、Discord、Slack 和个人微信里和自己的 agent 对话。在这些平台上发给机器人的消息，会给该账号绑定的 agent 开启一轮对话，回复发回同一个聊天。渠道运行在 `openprogram` 启动的后台 worker 里，不需要公网 webhook：每个适配器都是向外连接（Telegram 长轮询、Discord Gateway、Slack Socket Mode、微信 iLink 长轮询）。

目前一条消息的流转：

1. `openprogram/interfaces/channels/implementations/` 里的平台适配器把原生事件解析成统一的 `ChannelMessage`（文本、附件元数据、引用文本）。
2. `base.Channel.handle_inbound` 跑共用流水线：配对门禁（陌生发送者拿到一小时有效的配对码，只有主人能在 CLI 或仅限本机的 Web UI 里批准）、附件下载、引用块。
3. `dispatch_inbound` 按绑定选出 agent、算出会话 key、在每会话锁下运行这一轮，并广播这一轮，让 Web UI 和 TUI 实时显示。
4. 回复经由唯一的发送模块发出，它负责分段、各平台格式（Telegram HTML、Slack mrkdwn、微信纯文本）、限流重试和文件上传。平台支持编辑时，进度会流式写进同一条占位消息。

脚本、定时任务和 agent 方法也可以不依赖 worker，用 `outbound.send(...)` 发一条消息。账号、配对和路由用 `openprogram channels setup`、`accounts`、`access`、`bindings` 管理。

## 文档

- [`design.md`](design.zh.md) —— 结构与消息流：两条发送路径、`dispatch_inbound`、发送层、支持的平台和用户入口。
- [`audit.md`](audit.zh.md) —— 渠道层守住的要求和不变量，并与 OpenClaw、Hermes 对比。
- [`chat-bots.md`](chat-bots.zh.md) —— agent 在聊天室里怎么表现：何时回答、怎么显示进度、群聊对它的要求。
