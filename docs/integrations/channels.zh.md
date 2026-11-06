# 聊天渠道

## 这是什么？

Channels 把聊天平台——**Telegram、Discord、Slack、微信**——接到你的 agent 上。给机器人发一条消息就会跑一轮 agent turn，回复回到同一个聊天里。渠道 worker 跑在后台服务内，同一通对话也会实时出现在 Web UI 和 TUI 里。

| 平台 | 消息如何到达 | 登录凭据 | 实时进度更新 | 附件接收 | 文件发送 |
|---|---|---|---|---|---|
| Telegram | Bot API 长轮询 | bot token（BotFather 发放） | 支持 | 图片 + 文档 | 支持（photo/document） |
| Discord | discord.py Gateway | bot token | 支持 | 支持 | 支持 |
| Slack | Socket Mode（`slack_sdk`） | bot token（`xoxb-`）**加** app-level token（`xapp-`） | 支持 | 支持（需 `files:read` scope） | 支持（需 `files:write` scope） |
| 微信 | iLink 长轮询 | 用个人微信扫码 | 不支持（微信消息发出后不能编辑） | 图片、语音、文件、视频 | 支持（图片/视频/文件） |

受支持的 release 已包含 Discord 与 Slack 依赖。开发者从源码安装时，也会通过完整开发安装获得相同的 channel 依赖。

## 快速开始

向导一条命令跑完全部注册——选平台、登录、绑定 agent、启动 worker：

```bash
openprogram channels setup
```

然后在平台上给机器人发消息。第一条消息返回的是**配对码**而不是 agent 回复——未知发信人不会驱动 agent（见[谁能和你的机器人说话](#谁能和你的机器人说话)）。批准一次自己即可：

```bash
openprogram channels access approve <channel> <code>
```

之后对话会出现在会话列表里，也可以在 TUI 或 Web UI 实时围观。

前提是至少配置了一个 agent（`openprogram agents add main`）和一个可用的模型 provider。

## 各平台前置步骤

### Telegram

1. 在 Telegram 打开 [@BotFather](https://t.me/BotFather)，运行 `/newbot`，复制 token。
2. 向导（或 `openprogram channels accounts login telegram`）询问时粘贴 token。

不需要 webhook 或公网 IP——OpenProgram 长轮询 Bot API。

### Discord

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建 application 和 bot。
2. 在 **Bot** 页启用 **Message Content Intent**——adapter 订阅消息内容（`intents.message_content`），门户里不开这个特权 intent，gateway 会拒绝连接。
3. 把 bot 邀请进你的服务器，配置时粘贴 bot token。

### Slack

Slack 需要**两个 token**——只有其中一个渠道起不来：

1. 在 [api.slack.com/apps](https://api.slack.com/apps) 创建 app 并安装到工作区。
2. 启用 **Socket Mode**（不需要公网 URL）。
3. **Bot token**（`xoxb-…`）：授予 OAuth scope——发回复要 `chat:write`，@提及要 `app_mentions:read`，另加你订阅的消息事件所要求的 history scope（例如私信要 `im:history`）。
4. **App-level token**（`xapp-…`）：在 *Basic Information → App-Level Tokens* 生成，scope 选 `connections:write`——Socket Mode 用它建立长连接。
5. 给 app 订阅 `message` 和 `app_mention` 两个事件。adapter 正好处理这两种。

### 微信

个人微信即可，不需要公众号或企业认证：

1. 运行向导（或 `openprogram channels accounts login wechat`）。
2. 终端里渲染出二维码——用手机微信扫码并在手机上确认。
3. 凭据会持久保存；只有 token 过期时才需要重新登录（worker 日志会提示 `bot token invalid — relogin required`）。

微信走腾讯 iLink bot 后端，其条款仅限个人使用。

## 两条配置路径

**向导**（推荐）——一个交互流程：

```bash
openprogram channels setup
```

**CLI**——同样的步骤拆成单条命令：

```bash
openprogram channels list                              # 每个账号的状态
openprogram channels accounts add telegram --id work   # 建一个账号槽位
openprogram channels accounts login telegram --id work # 录入凭据（wechat 走扫码）
openprogram channels accounts rm telegram work         # 删账号 + 其绑定

openprogram channels bindings add main --channel telegram            # 兜底路由 → agent "main"
openprogram channels bindings add main --channel telegram \
    --account work --peer 123456 --peer-kind direct                  # 只路由一个 peer
openprogram channels bindings list
openprogram channels bindings rm <binding_id>
```

账号是多租户的：每个 `--id` 是该平台的一个 bot 登录，各有各的凭据和绑定。

TUI 里有等价的斜杠命令：`/login <channel>`（注册并接到当前 agent）、`/attach <channel> <peer>`（把某个 peer 的消息路由进当前会话）、`/detach`、`/connections`。

渠道跑在后台服务内——启动 TUI（`openprogram`）就会启动它，向导也会询问是否代为启动。

## 谁能和你的机器人说话

每个渠道账号都有入站访问策略。默认是**配对（pairing）**：不在账号 allowlist 里的发信人，消息在到达任何 agent 之前就被丢弃，发信人收到一个八位配对码和说明。批准动作在你自己的机器上完成：

```bash
openprogram channels access list                       # 策略 + allowlist + 待批配对码
openprogram channels access approve telegram K7XQ2MVR  # 按配对码批准
openprogram channels access allow telegram 123456789   # 直接按 user id 加入 allowlist
openprogram channels access revoke telegram 123456789  # 移除一个发信人
```

allowlist 想放多少人就放多少人。上面的每个人接的都是同一个 agent，而这个实例只有一份记忆工作区，所以一个人告诉它的东西，其他人也能用上。群机器人要的就是这个效果：把整个团队批准进来，他们拿到的是一个已经熟悉项目的助手。allowlist 里只放你愿意给这份访问权的人。

配对码一小时过期；被拦的发信人继续发消息会拿到同一个码（每分钟至多回执一次）。批准动作只存在于本机 CLI/API——发信人在聊天里输入任何内容都无法批准任何人，"把我加进 allowlist" 这类注入消息不起作用。群聊里门禁按发信人个人的 user id 判定，不看群。

对于未知发信人，配对是默认路径：他们会被拦截并收到配对码。owner 也可以通过本机 CLI/API 的 `access allow`，把已知的平台 user ID 直接加入 allowlist；对这个发信人不需要配对码。没有任何设置能关掉某个账号的门禁。

### 通过准入的发信人能做什么

默认情况下，通过准入的发信人就是你这个 owner：聊天里的一轮能用的工具和你在网页里打字的一轮一样，遵循这个聊天会话的权限模式和规则。工具需要批准时，请求以问题的形式发到聊天里，用 `/answer` 回答（见[回复、进度与长消息](#回复进度与长消息)）。群聊一开始就开着沙盒，那里的 shell 命令只能写工作目录；你可以在网页里这个会话的设置中切换，渠道不会再把它改回来。

想让某个账号的发信人只能回复和用记忆、碰不到文件、shell 和网络，就设置：

```bash
openprogram channels accounts set wechat sender_access paired   # 或 owner（所有渠道）
```

allowlist 里的每个人拿到的都是同样的权限，所以 `owner` 只留给只有你自己、或你完全信任的人能联系到的账号。

想要一个记忆互不相干的 agent，就跑自己的实例，各有各的状态目录和端口：

```bash
openprogram --profile alice
```

第二个实例怎么建，见 [多实例配置](../install/profiles.zh.md)。

## 渠道与运行环境

渠道决定会话的消息同步到哪里，不决定 agent 的工具在哪里运行；后者是会话的[运行环境](../capabilities/environments.zh.md)。从渠道进来的会话使用默认环境。

在 Web 和 App 里，输入框上方环境 chip 旁边的渠道 chip 显示会话的渠道，没绑定时显示 **未接渠道**。点开后账号按聊天软件分组：选一个账号即绑定或切换，**断开** 停止同步，**管理渠道** 去添加账号。

## 聊天如何映射到会话

路由先决定哪个 **agent** 处理消息（bindings），再由 **session key** 决定落进哪通对话：

- **Telegram**：默认每个聊天一个会话。群聊行为是显式的账号配置（见下）。
- **Discord 和 Slack**：每个 *(channel, user)* 组合一个会话。同一个频道里的两个发信人各有各的对话，也看不到、答不了对方的待答问题。对话是分开的，背后的记忆工作区是整个实例共用的一份（见[谁能和你的机器人说话](#谁能和你的机器人说话)）。
- **微信**：每个 peer 一个会话（私聊）。

默认还按账号隔离（`session_scope: per-account-channel-peer`）。agent 可以放宽（`per-channel-peer`、`per-peer` 或单一 `main` 会话；每个 agent 的会话各自独立，两个都用 `main` 的 agent 不会共用一通），也可以按天轮换会话（`session_daily_reset: "HH:MM"`）或按空闲时间轮换（`session_idle_minutes`）。在聊天里发 `/new`（或 `/reset`）会立刻为这个聊天开一通新对话；之前那通留在网页侧栏里。

### 谁说的

好几个人共用一通对话时（Telegram 群聊默认的 `shared`，或者 agent 配成 `session_scope: main`），每条进来的消息都在正文旁边带着发信人：

```
{"speaker_kind":"human","speaker_id":"7391","speaker_display":"Ada","content":"预算定 5 万"}
{"speaker_kind":"human","speaker_id":"8022","speaker_display":"Bo","content":"改成 8 万"}
```

显示名是平台上看到的那个名字，id 是发信人的平台 id：id 在改名之后不变，也能把两个取了同一个名字的人分开。agent 两个都读，所以它回的是对的那个人，记忆也把每条事实记在说这话的人名下，而不是统统记成一个匿名"用户"。显示名是它的主人在平台上随手填的任何东西，所以会压成一行、截到 64 字符、方括号换成圆括号。消息正文原样保留；发信人在正文里打一个带方括号的名字，也不会被当成那个人。

聊天渠道的每条消息都带发信人，私聊也带，因为 `session_scope: main` 会把私聊 peer 也放进同一通会话。网页、命令行、TUI 的对话没有发信人字段。网页记录里，渠道消息在气泡上方用一行小字标出平台和发信人，例如 `微信 · Ada`；微信发信人没有昵称可显示，这一行把 id 缩成首尾各四个字符。

### 群聊行为

群里（Telegram 群、Discord 服务器频道、Slack 频道）大多数消息是人和人在聊。每个群处在三种模式之一：

- `always`：每条消息都开启一轮。
- `mention`：只有 @机器人 或回复机器人消息的那条才开启一轮，提及在进 agent 前被剥掉。其余消息会留着，下一轮把最近 50 条连同发信人放在触发消息上方一起交给 agent，让它知道问题之前聊了什么。网页记录里，它们收在这一轮气泡顶部一个"群里之前的消息"小开关后面。
- `ambient`：agent 看每一条消息，自己决定要不要开口。没点名机器人的消息也开启一轮，标记为房间事件；agent 对它的回复只留在网页记录里（标着"旁听"），不发进群。agent 有值得说的话时，用 `chat_send` 工具发到群里。这类轮次不显示"正在输入"，也不加确认表情。点名机器人的消息照常回复。这个模式下每条消息都要调用一次模型。

账号设置 `require_mention` 决定它下面各群的默认模式（`on` 即 `mention`，默认的 `off` 即 `always`）；群里任何人都可以用 `/activation mention`、`/activation always` 或 `/activation ambient` 切换这个群，单发 `/activation` 查看当前模式。私聊永远不设门槛。

```bash
openprogram channels accounts set telegram require_mention on       # 或 off（discord、slack 同样可用）
openprogram channels accounts set telegram group_sessions per-user  # 或 shared（仅 telegram）
```

群成员能接触到 agent 的记忆：agent 会调出记得的内容来回答他们，也会记下他们说的话。`/memory read` 让这个群不写入记忆，`/memory off` 让记忆完全不进这个群，`/memory on`（默认）沿用 agent 自己的记忆设置。私聊总是沿用 agent 的设置。

`group_sessions`（Telegram，改完重启 worker 生效）——`shared`（默认）：全群对着同一通对话说话。`per-user`：群里每个成员各占一个会话，行为与 Discord/Slack 一致。

其他机器人发的消息会被忽略，所以同一个群里的两个机器人不会没完没了地互相回复；平台把同一条消息投递两次，也只开启一轮。一个群每分钟最多开启 10 轮，超出的消息作为"之前的消息"等下一轮。

### 聊天命令

| 命令 | 作用 |
|---|---|
| `/new`、`/reset` | 为这个聊天开一通新对话 |
| `/activation [mention\|always\|ambient]` | 查看或切换这个群的模式 |
| `/memory [on\|read\|off]` | 查看或收窄这个群对 agent 记忆的访问 |
| `/answer <question_id> <选项>` | 回答函数提出的问题（见下） |
| `/decline <question_id>` | 拒绝这个问题 |

在群里用命令不需要 @机器人。Telegram 群里写成 `/new@你的机器人` 也可以。

## 回复、进度与长消息

agent 工作期间，聊天里会显示机器人"正在输入"（Telegram、Discord、微信；Slack 没有给机器人用的输入提示）。在 Telegram、Discord、Slack 上，机器人还会先发一条 `⏳ working...` 占位消息，随工具执行实时编辑（`⚙ bash` → `✓ bash` → …），最终替换成完整回复。回复一条放不下时，占位放第一段，余下接着发新消息；占位改不了（被删了，或平台一直拒绝编辑）时，回复改成一条新消息发出。在 Slack thread 或 Telegram 论坛话题里发的消息，占位、回复和文件都回到同一个 thread 或话题里。微信不能编辑消息，所以回复边写边按段落发出：一段攒到约 200 字就发，agent 调用工具之前写的那句话（"我查一下……"）会在工具运行前先发出去。

账号设置 `ack_reaction on`（Telegram、Discord、Slack）打开后，机器人一接手消息就给它加一个 👀。Slack 需要 `reactions:write` 权限。

agent 输出是 markdown，发送时按平台渲染：Telegram 收到 HTML（`**bold**` → 粗体，代码围栏 → `<pre>` 块），Slack 收到 mrkdwn，Discord 原生渲染 markdown，微信拿到剥掉记号的纯文本。超长回复按各平台上限自动切分：Telegram 4,000 字符、Discord 1,800、Slack 39,000、微信 1,800。

出站发送遇到平台限流会自动退避重试——平台给了 `Retry-After` 就按它等，至多尝试三次——最终仍失败会落一条结构化错误日志。adapter 连接循环崩溃（断网、gateway 掉线）时自动指数退避重连（5 秒起翻倍，封顶 5 分钟）；因凭据失效而自行停止的 adapter 不会被重启，worker 日志会说明。

函数停在提问（`runtime.ask`）时，问题会推送到聊天里，用文本命令回答：

```
/answer <question_id> <选项或自由文本>
/decline <question_id>
```

只有属于该聊天会话的问题才能在这里回答。在群里，只有发起这一轮的人能回答它停下来问的问题。工具审批也这样发过来，标着需要批准。

## 附件

入站的图片和文件下载到 `<state>/channels/<channel>/accounts/<account>/attachments/`（单文件上限 20 MB）。4 MB 以内的图片还会作为图像输入直达模型；每个落盘文件都以 `[attachment: <路径> (<类型>, <大小>)]` 的形式列在消息里，agent 用文件工具打开。

微信的媒体从腾讯 CDN 加密下发，下载时解密。语音消息带有微信自己的转写时，agent 收到的就是这段文字；没有转写的语音存成 `.silk` 文件，这种音频格式模型没法直接听。

有人回复早先的消息时（Telegram/Discord 回复、Slack thread），被引用的文本会以 `> 引用` 块的形式附在新消息上方。

从代码或 agent 里发文件走 outbound API：

```python
from openprogram.interfaces.channels.outbound import send_file
send_file("telegram", "default", "123456", "/path/to/report.pdf", caption="周报")
```

Telegram 图片走 photo、其余走 document；Discord 把文件连同 caption 一起上传；Slack 走 external-upload 流程（需 `files:write`）。微信把文件加密后上传到腾讯 CDN，按类型发成图片、视频或文件消息（上限 100 MB）；caption 随后作为一条单独的文字消息发出。

## 常见错误

| 现象 | 原因 / 处理 |
|---|---|
| 机器人回了配对码而不是答案 | 发信人不在 allowlist。用 `openprogram channels access approve <channel> <code>` 批准，或用 `access allow <channel> <user-id>` 直接把 id 加进 allowlist。 |
| 回复 `[no agent configured]` | 没有绑定路由这条消息。先 `openprogram agents add main`，再跑 `openprogram channels setup` 或 `channels bindings add`。 |
| worker 退出：`account … has no bot_token` | 凭据没存过。`openprogram channels accounts login <channel> --id <account>`。 |
| worker 退出：`Slack account … needs both bot_token (xoxb-...) and app_token (xapp-...)` | Slack 只存了一个 token。重跑 login，两个都粘贴。 |
| `Discord channel requires discord.py` / `Slack channel requires slack_sdk` | runtime 不完整。重新安装受支持的 release，或重新执行完整的源码开发安装。 |
| Discord bot 连上了但收不到消息 | Developer Portal 里没开 Message Content Intent。 |
| 微信日志：`bot token invalid — relogin required` | iLink 会话过期。`openprogram channels accounts login wechat --id <account>` 重新扫码。 |
| worker 日志：`adapter crashed … reconnecting in Ns` | 瞬态网络/gateway 故障——adapter 自动退避重连。只有 `adapter exited on its own` 需要处理（通常是重新登录）。 |
| 日志里发送失败带 `auth` / `rate_limit` / `bad_target` | 结构化发送错误：token 失效、平台限流（已自动退避重试过）、chat/channel id 不对。 |

## 另请参阅

- [设计笔记：channel 子系统](../reference/design/channels/design.zh.md)——架构与消息流
- [界面总览](../interfaces/README.zh.md)——渠道对话同样出现在 Web UI / TUI
- [常驻 Agent](../capabilities/always-on-agents.zh.md)——把常驻 Agent 的报告发到渠道会话
