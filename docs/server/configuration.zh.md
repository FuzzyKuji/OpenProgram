<span id="配置"></span>
# 服务端配置

OpenProgram 的全部状态存在 `~/.openprogram/` 一个目录里。本页说明目录里有什么、`openprogram config` 怎么读写设置，以及如何用 profile 隔离多套状态。

## ~/.openprogram/ 里有什么

主要文件和子目录（按用途分组）：

| 路径 | 内容 |
|------|------|
| `config.json` | 用户设置：端口、上次使用的模型、provider 配置、禁用的工具等，见[配置参考](../reference/config.zh.md) |
| `sessions/`、`sessions-git/` | 聊天会话数据及其 git 存档 |
| `agents/`、`agents.json` | agent 定义（persona、模型、技能） |
| `auth/` | provider 凭据存储 |
| `skills/` | 安装的技能（SKILL.md 目录） |
| `plugins/` | 安装的插件 |
| `mcp_servers.json` | MCP server 配置 |
| `memory/` | 持久记忆（wiki + journal） |
| `channels/` | 聊天频道机器人（Telegram、Discord、WeChat 等）状态 |
| `browser-states/`、`chrome-profile/` | 浏览器工具的登录态与 sidecar Chrome profile |
| `projects/`、`worktrees/`、`shadow-git/` | 项目工作区与 git worktree 状态 |
| `logs/`、`worker.log` | 日志；另有 `worker.pid` / `worker.port` / `worker.lock` 等 worker 运行时文件 |
| `models/`、`cache/`、`tool_results/`、`usage.db` | 模型目录缓存、通用缓存、工具结果、用量数据库 |

## openprogram config

```bash
openprogram config list              # 列出每个设置：值、分组、生效方式
openprogram config get <key>         # 读一个设置，如 ui.web_port
openprogram config set <key> <value> # 改一个设置
```

每个设置有生效方式：`live`（立即生效）或 `next start`（下次启动 worker 时生效，`config list` 里标注）。核心键：

| key | 含义 | 默认 | 生效 |
|-----|------|------|------|
| `ui.web_port` | worker 单端口（API + WebSocket + web UI） | 18100 | next start |
| `ui.open_browser` | `openprogram web` 是否自动打开浏览器 | true | next start |
| `search.default_provider` | 默认 web 搜索 provider（`auto` 选优先级最高的已配置项） | auto | live |
| `memory.backend` | `local`（磁盘）或 `none`（不注入、不召回、不自动写入、不整理，也不启动记忆线程） | local | next start |
| `memory.writer.model` | 后台写入使用的可选 `provider/model`；留空时沿用默认聊天 agent 及其凭据 | 空 | live |
| `tools.disabled.<name>` | 逐个工具的开关（写入 `tools.disabled` 列表） | 全部启用 | live |

`config list` 还会显示只读的 `providers.<name>` 状态行 —— 它们不能用 `config set` 改，要用 `openprogram providers login` 或 Web UI 的 Providers 页配置。

## 端口的快捷命令

`openprogram ports` 是端口偏好的专用写入口：

```bash
openprogram ports                    # 查看
openprogram ports --port 8101        # 持久化修改
```

## 谁能连上这个服务

API 不要求调用方鉴权，所以决定谁能连上它的只有两个设置。

`web.host` 决定监听哪个网卡。默认 `127.0.0.1` 只接受本机连接。设成 `0.0.0.0`
等于把 UI 连同所有已存的 API key 一起交给整个局域网，`/api/providers/…/reveal`
是明文返回 key 的。

只绑回环还不够，因为浏览器能从你随手打开的任何页面连上回环。有两条攻击正是走这里：
一个页面可以直接向 `127.0.0.1` 开 WebSocket（同源策略管不到 WebSocket）驱动 agent，
而 agent 手里有 `bash` 工具；或者某个站点的域名在页面加载后重新解析到 `127.0.0.1`，
它的请求看上去就是同源的。所以服务在路由之前会检查：

- 绑在回环上时，`Host` 头必须是回环地址；
- 浏览器没有把这次请求标成 `Sec-Fetch-Site: cross-site`；
- `Origin` 存在时，必须等于本次请求的 `Host`，或者本身是回环地址。

其余一律 403。完全不带 `Origin` 的请求不是浏览器发的（终端 UI、`curl`、Python
客户端都属于这类），放行。

如果你自己在前面架了反向代理，把那个域名加进来，它的页面才会被接受：

```bash
openprogram config set web.allowed_origins '["https://agent.example.com"]'
```

## 网络代理

worker 访问公共目标时使用你的普通代理：`web_fetch` 读取的页面、图片与附件下载、内置网页搜索后端（包括 DuckDuckGo）、更新检查等其他固定公共服务，以及 API 或 OAuth origin 位于 provider 审计列表中的模型 provider。路由来自：

1. `OPENPROGRAM_PROXY_URL` 覆盖普通代理配置，支持 `http://`、`https://`、`socks5://`，保留 `NO_PROXY`。
2. HTTPX 解析 `http_proxy` / `HTTP_PROXY`、`https_proxy` / `HTTPS_PROXY`、`all_proxy` / `ALL_PROXY` 和 `no_proxy` / `NO_PROXY`。在适用时，Python 使用 macOS 和 Windows 的系统代理配置。loopback host 从不经过代理。

客户端先验证目标，再检查代理 socket 地址。TLS 继续验证服务 hostname；代理认证只发送给代理，代理失败不回退直连。显式 `security.outbound_url.policy_proxy` 优先，并要求用户声明该代理执行目标策略。

请求经代理发出时，hostname 由代理解析。Clash 等 fake-IP 代理因此可以正常使用：它们的本地 DNS 结果来自 `198.18.0.0/15`，直连时会被判为 `NON_GLOBAL_ADDRESS` 而拒绝。私有、loopback 与 metadata IP 地址，本地名称（`localhost`、单标签 host、`.local`、`.lan`、`.internal` 等），以及本地 DNS 结果为真实私有地址的 hostname 仍然被拒绝。`NO_PROXY` 中的 host 直连并执行完整地址检查。如需确保最终解析结果也受检查，请配置执行策略的代理。

自定义服务 origin（配置的 provider base URL、SearXNG、技能或插件目录）不继承普通代理，继续使用直接地址检查或显式执行策略的代理。CLI provider 继承 worker 的进程环境，由外部 CLI 处理代理。SOCKS 支持已包含。

`openprogram rescue` 会报告解析出的代理配置，并在 SOCKS 代理缺少支持包时给出警告。

## 多实例：--profile

`--profile <name>`（或环境变量 `OPENPROGRAM_PROFILE`）把 config、sessions、logs 全部改道到 `~/.openprogram-<name>/`，让并行的工作区互不共享状态：

```bash
openprogram --profile dev            # 用 ~/.openprogram-dev/ 跑一套独立实例
OPENPROGRAM_PROFILE=dev openprogram status
```

配合不同的 `OPENPROGRAM_WEB_PORT` 可以同时跑多套服务。安装方式见[安装](../install/profiles.zh.md)。

## 阻止空闲系统休眠

macOS 可以在 Agent 执行期间阻止系统因空闲而自动休眠：

```bash
openprogram config set execution.prevent_idle_sleep true
```

默认 `false`。每次 Agent 循环开始时读取设置，独立申请原生电源断言，正常结束、失败或取消后释放。
循环中的审批等待也保留该断言；设置变更不影响已经开始的执行。显示器休眠和用户主动休眠仍然可用，
不会修改永久系统电源设置。不支持的平台或断言失败会记录警告，任务继续执行，但不提供防休眠效果。
独立后台服务或 Agent 循环结束后仍在运行的命令不在此功能范围内。
