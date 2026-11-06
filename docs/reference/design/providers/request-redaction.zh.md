# 请求脱敏

请求脱敏让凭据和邮箱地址不出现在模型 provider 收到的内容里，而 agent 自身仍然使用真实值工作。默认关闭，由 `privacy.redact_requests` 设置项开启。面向用户的说明见 [Providers](../../../models/providers.zh.md#请求中隐去密钥)。

## 位置

`openprogram/models/providers/utils/redaction.py` 包装 agent loop 的 `stream_fn`（`(model, context, options) -> EventStream`）。它是最外层，在[模型故障转移](reliability/llm-fault-tolerance.zh.md)之外，所以一个 vault 覆盖所有候选模型，回复也只还原一次。

```
agent_loop ─ redacting_stream_fn ─ failover_stream_fn ─ snapshot_stream ─ provider
              脱敏 Context   ──────────────────────────────────────────▶
              还原事件       ◀──────────────────────────────────────────
```

## 请求脱敏

`Vault.redact` 作用于 `Context` 中所有模型可见的字符串：system prompt、用户文本、助手文本和 thinking、工具调用参数、工具结果和工具定义。不是给模型读的字段（图片和媒体的 `data`、`thought_signature`、`thinking_signature`、各种 id、`cache_control`）保持不动。调用方的 `Context` 不会被修改；没有变化的部分与脱敏副本共用。

只识别高精度的形态，因为误判会弄坏它替换掉的那段请求：

| 类别 | 形态 | 占位符 |
|---|---|---|
| 整体是密钥的 token | 私钥块、`sk-ant-…`、`sk-…`/`sk-proj-…`、`ghp_…` 一族、`github_pat_…`、AWS `AKIA`/`ASIA` ID、Google `AIza…`、Slack `xox?-…`、JWT | `[[SECRET_n]]` |
| 赋值里的值 | `Bearer` 之后的值，以及 `password`、`api_key`、`secret`、`access_token`、`auth_token`、`client_secret` 等键后接 `:` 或 `=` 的值 | `[[SECRET_n]]` |
| 邮箱地址 | `local@domain.tld` | `[[EMAIL_n]]` |

编号按首次出现的顺序分配，同一个值始终对应同一个占位符。因此同样的历史每次都脱敏成同样的请求文本，provider 的 prompt 缓存保持有效，模型带着占位符写出的推理块被发回时也完全一致。

没有任何内容需要脱敏的请求会原样交给内层 `stream_fn`，所以对这类请求打开设置项没有额外开销。

## 还原回复

每个事件都会被复制一份，并把占位符换回 vault 里的值：`partial` 消息、`text_end`/`thinking_end` 的 content、`toolcall_end.tool_call`，以及 `done`/`error` 的消息。所以工具调用用的是真实值，对话记录里存的也是真实值。

delta 需要额外处理，因为一个占位符可能被拆在几个 delta 里（`"[["`、`"SECRET_"`、`"1]]"`）。`_DeltaRestorer` 按内容块保留一段可能是占位符开头的尾部（距结尾不超过 `len("[[SECRET_99999]]")` 的 `[`，且后面没有 `]]`），拼到下一个 delta 前面。对应的 `*_end` 事件到来时，把保留的内容作为最后一个 delta 在 end 事件之前发出，不会丢字。delta 事件的 `partial` 也会在这样的尾部之前截断，所以界面上不会出现半个占位符。

## 生命周期

vault 只存在于一次 provider 调用期间，且只在内存里。不写磁盘；下一次调用从（真实值的）历史重新建立 vault。

## 限制

- 没有可识别形态、也没有键名的普通文字里的密钥会原样发出。
- 模型如果改写了占位符（例如写成 `[[SECRET 1]]`），收到的就是这段改写后的文字。
- 只在 provider 端工具里出现的值（例如托管的网页搜索）不受覆盖，因为它们不经过 `Context`。
