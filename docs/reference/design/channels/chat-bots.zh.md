# 渠道上的聊天机器人行为

通过微信、Telegram、Discord、Slack 接入的 agent，用法和网页里不一样。网页里是一个主人
在一通对话里打字，等一份完整记录，看工具输出。聊天软件里 agent 和别人待在同一个房间，
大多数消息不是冲它说的，一条回复就是手机上的一条通知，没人看得到工具调用。本页说明这种
差别对渠道层提出了什么要求，OpenClaw、Hermes Agent 和 Poke 分别怎么回答，以及
OpenProgram 采用的设计。

先说结论：聊天机器人不是另一种 agent。它就是同一个 `Agent`，同样的运行时、工具和记忆，
只是前面多了一层"房间层"决定哪些消息变成轮次，后面多了一层"投递层"决定回复以什么形状
发出去。两层都在 `channels/` 里；无论从哪个入口进来，agent 只有一份定义。OpenClaw 和
Hermes 也是这么做的：一个 agent，渠道行为放在配置里。

## 1. 房间需要什么

| 需要 | 聊天和网页的区别 |
|---|---|
| 知道是谁说的 | 群聊或 `session_scope: main` 的 agent 会把好几个人放进一通对话 |
| 默认不出声 | 群里大多数消息是人和人在聊 |
| 但要听得见 | "@机器人" 后面第三条消息里的问题，依赖前面那三条 |
| 自己决定开口 | 在房间里有用的助手，是有话可说时才插话，不是每条都回 |
| 像人一样回复 | 短段落、写好一段发一段；干活时显示"正在输入"；不发工具记录 |
| 限制陌生人 | 群成员不是主人，碰主人机器的工具只给主人 |
| 不和别的机器人没完没了 | 同一个群里两个机器人会互相回复，直到有东西把它们停下 |
| 跨软件认出同一个人 | 微信上和 Telegram 上的同一个人，在记忆里是同一个主体 |
| 主动开口 | 提醒、跟进和问候不需要用户先发消息 |

## 2. 参考系统

**OpenClaw**（[channels](https://docs.openclaw.ai/channels)、
[groups](https://docs.openclaw.ai/channels/groups)、
[ambient room events](https://docs.openclaw.ai/channels/ambient-room-events)、
[sessions](https://docs.openclaw.ai/concepts/session)、
[streaming](https://docs.openclaw.ai/concepts/streaming)、
[typing](https://docs.openclaw.ai/concepts/typing-indicators)、
[bot loop protection](https://docs.openclaw.ai/channels/bot-loop-protection)）
的房间层最完整：

- 准入：私聊配对和白名单；每个群的 `groupPolicy` 可设 allowlist、open 或 disabled。
- 提及门槛：`requireMention`、额外的 `mentionPatterns`，回复机器人的消息也算提及；
  `/activation mention|always` 在运行时切换一个群。
- 待处理历史：没被提及的群消息会留着（`historyLimit`，默认 50 条），交给下一个被触发
  的轮次，agent 因此看得到提及之前发生了什么。
- 环境房间：设 `unmentionedInbound: "room_event"` 和 `visibleReplies: "message_tool"`
  后，每条群消息都送到 agent，agent 的最终文本不公开，只有它调用 `message` 工具时房间
  才会收到消息。这类轮次不显示"正在输入"。
- 按群、按发信人的工具策略（`tools`、`toolsBySender`），非主会话可放进沙箱。
- 会话形状：`dmScope` 从一个共享会话到"每账号每渠道每人一个"；`identityLinks` 合并
  同一个人的多个账号；按天或闲置重置；`/new` 和 `/reset`。
- 投递：按段落分块的流式发送（`minChars`、`maxChars`、合并、按换行切），平台允许时
  实时编辑预览，带保活间隔的"正在输入"，确认表情。
- 机器人循环保护、进群一次性自我介绍、跳过群会话的心跳、语音转写、双向媒体。
- 微信是腾讯微信团队维护的外部插件
  （[WeChat](https://docs.openclaw.ai/channels/wechat)）：支持私聊和媒体，不支持群聊，
  经 iLink 扫码登录。

**Hermes Agent**（[文档](https://hermes-agent.nousresearch.com/docs/)、
[仓库](https://github.com/NousResearch/hermes-agent)）把重心放在机器人学到什么。agent
自己维护 `MEMORY.md` 和 `USER.md`，会被定期提醒把学到的东西存下来，从解决过的任务里
写出新技能，并通过全文检索加摘要回忆过去的对话。一个网关服务二十来个平台，一个用户在
这些平台上是同一个身份。定时任务可以投递到任意平台。

**Poke**（[poke.com](https://poke.com)）是同一想法的产品形态：一个住在 iMessage 和
短信里的助手，有固定的说话风格，用户邮件或日历里有事时会先发消息，把这些账号当成自己的
记忆。它说明"会主动开口"和"有个性"是聊天助手显得在场的原因。

## 3. OpenProgram 现状

| 能力 | OpenClaw | OpenProgram |
|---|---|---|
| 平台 | 34 个，微信靠插件 | Telegram、Discord、Slack、微信（iLink） |
| 私聊配对、白名单 | 有 | 有 |
| 发信人身份传给模型 | 正文标签加元数据块 | 输入信封里的结构化 `speaker_*` 字段 |
| 网页记录里显示发信人 | — | 气泡上方显示平台和发信人 |
| 提及门槛 | 所有群渠道、匹配模式、回复机器人 | Telegram、Discord、Slack；回复机器人；没有自定义匹配模式 |
| `/activation`、`/new`、`/reset` | 有 | 有 |
| 群待处理历史 | 有 | 有 |
| 环境房间，agent 自己决定开口 | 有 | `/activation ambient`、`chat_send` 工具 |
| 按群、按发信人的工具策略 | 有 | 按账号的 `sender_access`（owner 或 paired）；群会话开沙盒；按群的记忆策略（`/memory`）；只有提问者能回答 |
| 会话范围、重置策略 | 有 | `session_scope`，按天或闲置重置 |
| 跨渠道身份关联 | 有 | 无 |
| 实时进度 | 编辑预览 | 占位消息随工具步骤编辑 |
| 运行中按段落分块 | 有 | 微信；能编辑的平台保留实时占位消息 |
| "正在输入" | 有 | Telegram、Discord、微信 |
| 确认表情 | 有 | Telegram、Discord、Slack（`ack_reaction`） |
| 机器人循环保护 | 有 | 丢弃机器人消息、每个房间限流 |
| 进群介绍 | 有 | 无 |
| 双向媒体 | 有 | 有 |
| 语音转写 | 有 | 用微信自己的转写；没有转写的语音存为 SILK |
| 向用户反问 | — | `/answer`、`/decline` |
| 主动投递 | 心跳、定时任务 | 常驻 agent 投递到渠道 |
| 自主整理记忆、技能 | Hermes | 共享记忆工作区，按人分主题 |

## 4. 设计

### 4.1 房间模式

每个群绑定有一个模式，在配置里设置，运行时用 `/activation` 切换：

- **mention**（默认）：只有提及、匹配提及模式或回复机器人才开启一轮。其余消息记为
  待处理历史。
- **always**：每条消息都开启一轮。
- **ambient**：每条消息都开启一轮。没点名机器人的消息成为房间事件：文本第一行是
  `[room event]`，不加确认表情、不显示"正在输入"，这一轮的最终文本只留在记录里，
  网页在气泡上标"旁听"。房间只能通过 `chat_send` 工具听到 agent 说话。点名机器人的
  消息是普通轮次。房间事件同样计入限流（4.5）。

账号设置 `require_mention` 给出它下面各群的默认模式；`/activation` 把单个群的覆盖值存在
账号目录的 `rooms.json`。适配器只判断一条消息是不是冲机器人说的（`ChannelMessage.mentioned`）
并剥掉提及；决定放在 `channels/_room.py`，所以每个平台的门槛行为一致。

`chat_send(text)` 把消息发进当前这一轮所在的聊天。渠道层在
`channels/_active_turns.py` 里按会话 key 登记每个正在跑的轮次（渠道、账号、peer、
发言人、是否 ambient），工具从这里查目标而不看会话行，因为 `session_scope: main`
的会话里有好几个聊天。工具只需要 `reply` 能力，在安全自动放行清单里，对所有非渠道
来源隐藏，一轮最多发五条。在点名机器人的轮次里，它用来在长时间干活前发一句短话；
最终回复照常发出。

私聊永远是开启的，不设门槛。

### 4.2 待处理历史

被门槛拦下的消息带着发言人字段按房间存在内存里，不算一轮。下一个开启的轮次取最新的 50 条，
作为一个块放在触发消息前面：先是 `[earlier messages in this chat]` 这一行，然后每条消息一行
`> {"speaker": …, "content": …}` JSON。JSON 会转义换行，所以一条待处理消息不能另起一行冒充
别的发言人。被这一轮用掉的条目随即清除，`/new` 也会清掉，worker 重启后丢失。待处理历史
本身永远不会唤醒 agent。网页记录把这个块收在气泡顶部的一个开关后面。

### 4.3 投递

投递层把一条回复变成聊天形状的消息：

- "正在输入"贯穿整轮，在失效前刷新（Telegram `sendChatAction` 每 4 秒、Discord typing
  接口每 8 秒、微信每 5 秒）。微信要先用该用户最近一条消息的 `context_token` 向 iLink 的
  `getconfig` 取 typing ticket；一轮结束时发 iLink 的显式取消。
- 不能编辑消息的平台（微信）随着回复增长按段落分块发送：一块攒够 200 字后在空行处发出，
  工具调用开始时整个缓冲先发出，未闭合的代码块里不切，单块不超过平台上限。最终回复（含
  `send_file` 附件标记）补上还没发的部分。能编辑的平台保留实时占位消息。
- 支持表情回应的平台，可选用确认表情标记机器人已接手的消息。
- ambient 模式和微信上，工具步骤永远不进房间。

### 4.4 谁能做什么

发信人的权限层级决定一轮能做什么。账号设置 `sender_access` 给所有通过准入的发信人选层级：

- `owner`（默认）让这一轮拿主人的身份和层级，审批可交互，和在网页里打字的一轮完全一样。
  会话的权限模式和规则照常生效；这一轮发起的审批以问题的形式发到聊天里，用 `/answer`
  回答。发言人字段仍然写平台上的发信人，模型和网页记录照样看得到是谁在说话。
- `paired` 只能回复、用 `chat_send` 和记忆；本机工具（文件、shell、网络）都被拒绝。

`owner` 下，群聊会话一开始就开着沙盒：shell 命令只能写工作目录。渠道层在房间第一次说话时
写入会话的沙盒开关，之后主人在网页里改过的值不再覆盖。私聊和本地会话一样沿用项目的沙盒设置。

在这之上，房间级的策略落在记忆上：记忆召回会把主人的记忆带进群里，因此每个房间在 `rooms.json` 里、紧挨着回应模式存一个记忆模式：`on`（沿用 agent 自己的
设置）、`read` 或 `off`，用 `/memory` 切换。渠道层把 `read` 和 `off` 变成
`TurnRequest.memory_policy_override`，它只能收窄 agent 的记忆策略：`off` 停掉召回并
隐藏记忆工具，`read` 隐藏写入类工具。

一轮停下来等待时（`runtime.ask`）提出的问题属于发起这一轮的人。在群里，这一轮还在跑时，
其他人发的 `/answer` 和 `/decline` 会被拒绝。

### 4.5 循环与刷屏

来自机器人账号的消息会被丢弃。一个房间在滑动的一分钟内最多开启 10 轮；超过上限的消息
落入待处理历史。平台把一条消息投递两次（Slack 对一次提及同时推 `message` 和
`app_mention`）也只开启一轮。

### 4.6 跨渠道的同一个人

身份关联把多个 `渠道:speaker_id` 映射到一个人的 id。记忆把这个人归到一个主题下，绑定
也可以选择让关联后的人跨渠道共用一个私聊会话。

### 4.7 主动开口与个性

常驻 agent 已经能按计划投递到渠道。聊天机器人再加一段简短人设（语气、长度、表情使用），
存在 agent 的资料里，只作用于渠道轮次；以及由记忆安排的按人跟进（"周五提醒我"），投递
到这个人最近活跃的渠道。心跳跳过群会话。

### 4.8 微信

iLink 除了文本还承载图片、语音、文件和视频条目。每个媒体条目指向腾讯 C2C CDN 上一个
AES-128-ECB 加密的对象，并带着密钥。适配器把条目变成普通附件、附上密钥，共享的附件通道
边下载边解密，于是图片作为图像输入到达模型，文件和其他平台的文件落在一处。CDN 回的是
`application/octet-stream`，图片类型从解密后的文件头认出。

语音条目通常带着微信自己的转写，转写成为消息文本，这时不下载音频。没有转写的语音条目是
SILK 音频，存成 `voice.silk`。

发文件时先向 iLink 的 `getuploadurl` 要上传位置，用新生成的密钥加密文件，POST 到 CDN，
再发一个图片、视频或文件条目，写明 CDN 给的下载参数和密钥。caption 作为单独一条文字消息
跟在后面。媒体流量走固定 CDN 源站的 HTTP consumer `channel.wechat.cdn`。

iLink 没有群聊也不能编辑消息，所以微信总是按段落分块，从不使用实时占位消息。

## 附录：实现状态

已实现：配对和白名单，输入信封和网页记录里的结构化发言人身份，会话范围和重置策略（按天、
闲置、`/new`），房间模式和 `/activation`（4.1），待处理历史（4.2），ambient 房间和 `chat_send`（4.1），
"正在输入"、微信段落分块和确认表情（4.3），`sender_access`、群会话沙盒、房间记忆模式和只有提问者能回答（4.4），丢弃机器人消息、房间限流和重复投递去重（4.5），实时进度占位消息，
按平台的 markdown 渲染和长度切分，四个平台的附件（含微信媒体和微信语音转写，4.8），
`/answer` 和 `/decline`，常驻投递。

未实现：自定义提及模式，同一账号内按发信人区分层级（4.4），身份关联（4.6），渠道人设和记忆安排的跟进（4.7），没有平台转写的语音的
转写（微信 SILK、Telegram 和 Discord 语音），进群介绍。
