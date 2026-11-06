<div id="providers"></div>

# 模型服务

模型服务层把 OpenProgram 接到各家模型：Anthropic、OpenAI、Google Gemini、Amazon Bedrock、Azure OpenAI、xAI、DeepSeek、Mistral、Groq、OpenRouter、GitHub Copilot 等，以及 Ollama、LM Studio、vLLM、llama.cpp 这类本地服务。每家是 `openprogram/models/providers/adapters/` 下的一个适配器目录，其中的 `provider.json` 声明它的模型、线路 API 和登录方式。

目前一次模型调用的工作方式：

- **一种请求格式。** 运行时把准备好的 `Context`（system、messages、tools）交给模型服务层。适配器把它翻译成该家的线路请求，并套用该家的 prompt 缓存机制；这一层之上不认识任何厂商格式。
- **每家多个账号。** 凭证按 `(provider, account)` 池存放，来自 API key 或订阅 OAuth 登录。同一时刻一个账号生效；可以打开账号间的轮换和故障转移，Settings → Providers 显示哪个会话、哪条分支在用哪个模型。
- **失败有分类。** 每个错误映射到同一套分类，按类别重试或转移，受超时约束，并作为结构化错误一路传到界面。
- **一个模型目录。** 模型来自各适配器的 `provider.json`、订阅目录和 models.dev；thinking 力度、Fast 档这类能力按 provider 声明，而不是在代码里特判。

用 `openprogram providers`（`login`、`list`、`use`、`status`、`doctor`、`accounts`）或 Settings → Providers 管理模型服务。

文档按职责分四组:

## 翻译 + 缓存(核心)

provider 无关的统一格式如何翻译成各家 wire 格式,以及 prompt 缓存如何按 provider 落地 —— providers 层的核心机制。

- [`request-build`](request-build.zh.md) — **总设计**:统一格式 Context、每 provider 翻译、缓存三 mode。
- [`cache-control-passthrough`](../plans/cache-control-passthrough.zh.md)(在 `plans/`)— Anthropic `cache_control` 逐块透传。
- [`routing-overview`](routing-overview.zh.md) —— Settings → Providers 的总览：哪个会话、哪条分支在用哪个模型，以及账本记下的改道。
- [`request-redaction`](request-redaction.zh.md) — 请求发出前把密钥和邮箱替换成占位符，并在流式回复里还原。
- [`web-search`](web-search.zh.md) — Search 开关：提供商自带服务端搜索就用它，否则用本地 `web_search` 工具，以及提供商搜索和引用如何进入对话。
- [`record-replay`](record-replay.zh.md) — 把 provider 调用录成脱敏 JSONL 录制文件,离线回放跑确定性测试。
- 上游(内容怎么分层组装,L0/L1/L2)见 [`context/composition.md`](../context/composition.zh.md)。

## [auth/](auth/) — 凭证 · 认证 · 账号

API key 与订阅 OAuth 的解析、校验、存储,以及多账号池与轮换。

- [`credential-validation-unification`](auth/credential-validation-unification.zh.md) — 凭证校验入口
- [`credential-status-redesign`](auth/credential-status-redesign.zh.md) — 凭证状态(可用或停用)
- [`api-key-resolution-unification`](auth/api-key-resolution-unification.zh.md) — API key 解析链
- [`unified-auth-storage`](auth/unified-auth-storage.zh.md) — 自包含的认证存储
- [`unified-account-management`](auth/unified-account-management.zh.md) — 账号管理 + 池轮换/回退

## [reliability/](reliability/) — 容错 · 错误 · 重试 · 超时

模型调用失败时的分类、重试、超时与错误向上传播。

- [`llm-fault-tolerance`](reliability/llm-fault-tolerance.zh.md) — 容错与超时总设计
- [`error-retry`](reliability/error-retry.zh.md) — 错误处理与重试决策
- [`error-taxonomy-propagation`](reliability/error-taxonomy-propagation.zh.md) — 结构化错误一路传到 UI
- [`error-and-timeout-mechanism.html`](reliability/error-and-timeout-mechanism.zh.html) — 错误/超时机制可视化

## [models/](models/) — 模型目录 · 能力

模型清单的数据布局、配置结构,以及 thinking/effort 等能力的声明式映射。每个模型都绑定在它所属的 provider 下,所以归在 providers 内。

- [`models`](models/overview.zh.md) — 模型目录与 provider 配置(数据布局、fetch、合并)
- [`thinking-effort`](models/thinking-effort.zh.md) — thinking/effort 子系统(声明式 per-provider 映射)
- [`fast-tier`](models/fast-tier.zh.md) — Fast(高速)档:两层判定(订阅入口手写 / models.dev 自动)、存储与线路
