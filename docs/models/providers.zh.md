# Provider 一览

本页列出仓库内置的 provider 实现（`openprogram/models/providers/adapters/` 下每个子目录一个）、各自的接入方式，以及在 Python 代码里直接使用 provider 的方法。内置实现之外，`openprogram providers available` 还能列出几百个走 OpenAI 兼容协议的社区 provider 目录，配置方式相同。

## 内置 provider

接入方式说明：**API key** = 存入凭据库的密钥（`providers login <id>`，也可从环境变量导入）；**OAuth** = 浏览器 / 设备码登录订阅账号；**CLI 凭据** = 直接读外部 CLI 已登录的凭据文件；**云凭据链** = 运行时自动走云厂商的标准凭据链。

| Provider | 协议 | 接入方式 | 备注 |
|---|---|---|---|
| `anthropic` | Anthropic Messages | API key（`ANTHROPIC_API_KEY`） | 显式 prompt caching（`cache_control`，支持 1h TTL） |
| `openai` | OpenAI Responses | API key（`OPENAI_API_KEY`） | Responses 协议自动缓存（`prompt_cache_key`） |
| `openai_responses` / `openai_completions` | OpenAI Responses / Chat Completions | —（共享协议实现，被众多 provider 复用） | |
| `openai_codex` | ChatGPT 后端 | OAuth（ChatGPT 订阅）：浏览器 PKCE 登录；已有的 `codex` CLI 登录态也可用 `providers discover` 导入 | 模型清单从官方端点实时拉取 |
| `azure_openai_responses` | Azure OpenAI Responses | API key（`AZURE_OPENAI_API_KEY`）+ 自填 base URL | |
| `google` | Google Generative AI | API key（`GEMINI_API_KEY` / `GOOGLE_API_KEY`） | thinking 用 token budget 控制 |
| `google_gemini_cli` | Cloud Code Assist | CLI 凭据：直接读 `~/.gemini/oauth_creds.json`，刷新由 Gemini CLI 负责 | |
| `gemini_subscription` | Cloud Code Assist | CLI 凭据：导入 `~/.gemini/oauth_creds.json`（先用 Gemini CLI 登录） | 别名 `gemini`、`gemini-cli` |
| `amazon_bedrock` | Bedrock Converse Stream | 云凭据链（`AWS_PROFILE` / access key / bearer token 等，运行时自动识别） | 显式 prompt caching（`cachePoint`） |
| `github_copilot` | OpenAI Responses 等 | GitHub 浏览器设备码登录，或导入 `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN` 环境变量；按需换取 Copilot 短期 token，不落盘 | 不支持 thinking 档位 |
| `deepseek` | OpenAI Completions | API key（`DEEPSEEK_API_KEY`） | reasoner 型号推理不可调档 |
| `openrouter` | OpenAI Completions | API key（`OPENROUTER_API_KEY`) | 聚合网关 |
| `vercel_ai_gateway` | Anthropic Messages | API key（`AI_GATEWAY_API_KEY`） | 聚合网关 |
| `groq` | OpenAI Completions | API key（`GROQ_API_KEY`） | |
| `cerebras` | OpenAI Completions | API key（`CEREBRAS_API_KEY`） | |
| `mistral` | OpenAI Completions | API key（`MISTRAL_API_KEY`） | |
| `xai` | OpenAI Completions | API key（`XAI_API_KEY`） | |
| `xai_subscription` | OpenAI Responses | OAuth（SuperGrok / X Premium+）：浏览器 PKCE 登录 | 模型与 `xai` 相同，走 `cli-chat-proxy.grok.com`（不是 `api.x.ai`） |
| `zai` | OpenAI Completions | API key（`ZAI_API_KEY`） | |
| `huggingface` | OpenAI Completions | API key（`HF_TOKEN`） | |
| `minimax` / `minimax_cn` | Anthropic Messages | API key（`MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY`） | 国际 / 国内两个端点 |
| `minimax_cn_coding_plan` | Anthropic Messages | API key（`MINIMAX_CN_API_KEY` / `MINIMAX_API_KEY`，与 `minimax_cn` 同账号同密钥） | "MiniMax Token Plan (CN)" coding 套餐 |
| `kimi_coding` | Anthropic Messages | API key（`KIMI_API_KEY` / `MOONSHOT_API_KEY`） | |
| `alibaba_token_plan_cn` | OpenAI Completions | 套餐 API key | 别名 `bailian` |
| `opencode` | OpenAI Completions 等 | API key（`OPENCODE_API_KEY`） | |

流式输出所有 provider 都支持（整个层建立在流式接口上）。多模态输入按模型而非按 provider 决定，来自各 provider 的模型目录数据，界面上以模型实际标注为准。prompt caching 只在上表标注处经代码核实。


## 本地模型服务

Ollama、LM Studio、vLLM、llama.cpp 和通用本地服务作为内置 Provider 提供，支持地址配置、可选 API key、模型发现和手动模型 ID。连接多个服务时，可将自定义 Provider 标记为本地服务。配置方式和部署相关 token 限制见[本地模型](local-models.zh.md)。

## 自定义 provider

上表没覆盖的 OpenAI 兼容端点可以在 Web UI 的 Settings → Providers 里添加：必填项只有显示名和 base URL（不填 id 时从名字自动派生）。之后同一个 Fetch 按钮就能浏览该端点 `/models` 返回的模型列表，启用后无需改代码即可使用。自定义 provider 记在配置的 `providers.<id>` 下，标记 `source: "custom"`。

## 查看每个会话在用哪个模型

Settings → Providers 打开时显示**总览**。左栏列出正在回答、或在所选时间范围（实时、24 小时、7 天）里调用过模型的会话，每个会话下面是它的分支、子 Agent 和程序运行开出的子会话。不属于任何会话的模型调用（比如起标题、记忆整理）归在**后台调用**下。右栏是它们用到的模型，按 provider 分组。每条分支和它的模型之间有一条线：

- 蓝线上有小点在移动，表示请求正在进行；
- 橙色虚线指向刚才失败、被切换掉的模型（见[备选模型](#备选模型)）；
- 某个 provider 的 key 因限流在冷却，或者需要处理时，会在名字旁边标出来。

鼠标移到某一行上会突出它的连线。点会话打开它，点 provider 打开它的设置。图下面的**最近的改道**列出每次切换和原因。时间范围内没有调用模型的会话只计数，不画出来。这张图需要较宽的面板；窗口太窄时，先折叠侧边栏或把窗口拉宽。

## 备选模型

模型遇到限流、过载、故障或无法连接时，OpenProgram 可以改用另一个模型回答，而不是直接显示错误。这个功能默认关闭。在 Settings → System → Models 里开启，或者用命令行：

```bash
openprogram config set model_fallback.mode same-provider
```

| `model_fallback.mode` | 遇到上述失败时 |
|---|---|
| `off`（默认） | 显示错误。 |
| `same-provider` | 依次尝试同一 provider 下最多两个其他已启用的模型，顺序与 provider 设置里的顺序一致。不会联系其他 provider。 |
| `list` | 按顺序尝试 `model_fallback.models` 里的模型，可以来自其他 provider。 |

`list` 模式下填 `provider/model` 形式的 ID：

```bash
openprogram config set model_fallback.models '["anthropic/claude-sonnet-5-5", "openai/gpt-5.5"]'
```

只有在回复还没输出任何文字时才会切换，所以一条回答不会由两个模型拼接而成。鉴权错误、非法请求、上下文已满和内容策略拒绝不会换模型重试，因为换了也会失败。设置了 `OPENPROGRAM_FALLBACK_MODELS` 环境变量时，它优先于这个设置项。

## 请求中隐去密钥

在 Settings → System → Models 里打开 **Redact secrets in requests**（或运行 `openprogram config set privacy.redact_requests true`），凭据和邮箱地址就不会发给模型 provider。每次请求发出之前，下面这些内容会被替换成 `[[SECRET_1]]`、`[[EMAIL_2]]` 这样的占位符：

- 形态可识别的 API key 和 token（Anthropic、OpenAI、GitHub、AWS、Google、Slack、JWT）
- 私钥块
- `password=…`、`api_key: …`、`Authorization: Bearer …` 这类赋值里的值
- 邮箱地址

回复和它发起的工具调用会在你或工具看到之前换回真实值，所以模型写出带 `[[SECRET_1]]` 的命令，执行时用的是真正的 key。对应关系只在内存里保留一次请求。只有上面这些形态能被识别：一段普通文字里的密码，如果前面没有 `password=` 之类的写法，会原样发出。这个功能默认关闭。

## 库方式使用

在自己的 Python 代码里创建 runtime，首选自动检测：

```python
from openprogram.runtime.agent.runtime.factory import create_runtime

runtime = create_runtime()                                        # 自动选第一个可用 provider
runtime = create_runtime(provider="anthropic", model="claude-sonnet-4-6")
```

六个 provider 在 `create_runtime` 背后有专属 runtime 行为（OAuth / CLI 凭据接管、按 provider 的约定）：

```python
runtime = create_runtime(provider="anthropic", model="claude-sonnet-4-6")  # Anthropic API key
runtime = create_runtime(provider="openai", model="gpt-4.1")               # OpenAI Responses API
runtime = create_runtime(provider="gemini", model="gemini-2.5-flash")      # Google Generative AI
runtime = create_runtime(provider="anthropic")   # 需要 Anthropic API key
runtime = create_runtime(provider="openai-codex")  # ChatGPT 订阅（Codex OAuth）
runtime = create_runtime(provider="gemini-cli")    # 复用 Gemini CLI 登录态
```

上表其余 provider：`create_runtime(provider=..., model=...)` 会按该模型的协议自动路由，与聊天界面走同一条路径。

Grok Subscription 在代理路由请求头中保留所选模型 ID。选择 `grok-4.6` 时请求该模型，不替换成 `grok-build` 别名。
