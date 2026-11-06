# 网页搜索：先用提供商自带的，再用本地工具

## 问题

聊天里的 Search 开关过去只做一件事：把本地 `web_search` 函数工具加进模型的工具列表。没有配搜索 key 时这个工具抓 DuckDuckGo 的页面，抓几次就会遇到机器人验证。而大家实际在用的模型后端（走 `openai-codex` 的 ChatGPT 订阅、OpenAI Responses API、Anthropic、Gemini）都自带服务端网页搜索：模型决定搜什么，提供商在自己的基础设施里执行查询，结果带引用返回。Claude Code、Codex、Gemini CLI 从不抓页面，它们的 WebSearch 就是提供商的这个工具。我们从来没把它打开过。

## 设计

每个请求根据两个事实决定搜索方式：会话的意图（Search 开关，存为会话运行配置的 `web_search`）和请求要去的 API 提供商的能力。

1. **提供商有就用提供商的。** API 提供商注册表在 `supports_idempotency_key` 旁边声明 `supports_web_search`（`_StreamFnProvider`、`ApiProviderSnapshot`）。会话意图打开且解析出的模型所属提供商声明了这个能力时，agent 运行时把请求选项 `web_search=True` 置上，并把本地 `web_search` 工具从这次请求的工具列表里去掉。请求构造器加上提供商自己的工具：
   - `openai-responses` 与 `openai-codex`：`{"type": "web_search"}`。
   - `anthropic-messages`：`{"type": "web_search_20250305", "name": "web_search"}`。
   - `google-generative-ai` 与 `gemini-subscription`：`{"google_search": {}}`，但只在没有函数工具的请求里。Gemini 的 `generateContent` 不接受 Google 搜索 grounding 与函数声明并存（Gemini 3 只在 Interactions API 上支持组合），而 agent 请求总是带函数工具，所以这两个 API 不声明该能力，聊天仍用本地工具；无工具的请求（带 `web_search=True` 的普通补全）用到 grounding 时，其元数据照样解析。
   没有声明这个能力的提供商（DeepSeek、Kimi、本地模型、所有 OpenAI 兼容端点、Gemini）仍然拿到本地工具，和以前一样。
2. **本地工具仍是兜底，而且直说该怎么办。** 没有提供商工具也没有搜索 key 时，唯一的后端就是 DuckDuckGo 页面抓取。所有后端都失败时，工具的报错告诉模型：配一个搜索 key（Settings > Search；Brave 和 Tavily 有免费额度）才是解法，有浏览器工具的话也可以直接打开搜索页，而不是让它"稍后重试"。未指定提供商时的回退顺序跳过 `arxiv`——它是论文索引不是网页索引；指名时仍可用。
3. **提供商的搜索像普通工具调用一样显示。** 流处理器把提供商的搜索条目转成 `ServerToolUse` 内容块和 `servertool_start` / `servertool_end` 事件。agent 循环不执行它们（提供商已经执行了），只转发；运行时把它们投影给客户端，用的是现有的 `tool_use` / `tool_result` 事件，带 `tool: "web_search"`、`provider_executed: true`，`input` 是 `{"query": ...}`，`result` 是提供商报告的来源（每行一个 `title — url`，没有来源时为 `completed`）。回复的 blocks 里持久化同样的形状，所以重新加载的对话在原位置显示"Searched the web: …"。
4. **引用挂在正文上。** URL 引用（Responses 的 `url_citation` 注解、Anthropic 文本块的 `citations`、Gemini 的 `groundingMetadata`）汇总为 `TextContent` 块上的 `citations: [{url, title, start, end}]`，随 `text_end` 转发、随块持久化，客户端在回答下方渲染成一行紧凑的来源。
5. **回放。** `ServerToolUse` 块回传给产生它的 API 时用原生形状（Responses 的 `web_search_call` 条目；Anthropic 的 `server_tool_use` + 原始 `web_search_tool_result`，其中每条命中带 `encrypted_content` 必须原样返回，所以没留原始结果的块会被丢弃），对话保持合法；换了 API 就丢弃，和丢弃别家的 thinking 签名一样。Gemini 的 grounding 块只有合成 id，不回传。

## 线上契约

内容块（`openprogram/models/providers/types.py`）：

```python
class ServerToolUse(BaseModel):
    type: Literal["serverToolUse"] = "serverToolUse"
    id: str                 # 提供商条目 id
    name: str               # "web_search"
    input: dict             # {"query": str}
    status: str             # "searching" | "completed" | "failed"
    results: list[dict]     # [{"title": str, "url": str}]
    raw: Any | None = None  # 提供商原条目，用于回放
```

`TextContent.citations: list[Citation] | None`，`Citation(url, title, start, end)`。

助手消息事件：`EventServerToolStart(type="servertool_start", content_index, partial)` 和 `EventServerToolEnd(type="servertool_end", content_index, server_tool: ServerToolUse, partial)`。

客户端事件（`apps/web/lib/net/ws/chat-stream.ts`）：带 `provider_executed: true` 的 `tool_use` 和 `tool_result`；文本块结束时的 `citations`。持久化块：`{"type": "tool", "tool": "web_search", "provider_executed": true, "input": "{\"query\": ...}", "result": ...}`。

## 各框架的长处，以及我们取了什么

- Claude Code：搜索就是提供商的 `web_search` 服务端工具；结果带引用，回答引用它们。取：提供商工具优先，引用挂在正文上。
- Codex：`--search` 打开 Responses 的 `web_search` 工具；对话里每次搜索一行"Searched the web: query"。取：每次搜索一条可见步骤，不刷屏。
- Gemini CLI：`google_web_search` 是 Google Search grounding；回答末尾附编号来源列表。取：回答下方的来源行。
- OpenProgram 保留它们没有的：给没有提供商搜索的模型准备的本地工具和十六个 key 后端，以及跟着会话所用模型走的会话级开关。

## 实现状态

- 提供商能力标志：openai-responses、openai-codex、anthropic-messages。五个 API 都有请求构造；Google 只在没有函数工具时加，且不声明能力。
- 流处理到 `ServerToolUse` 和引用：Responses（共享处理器）、Anthropic、Gemini。
- 运行时：意图到请求选项、去掉本地工具、事件投影、持久化；本地工具的报错文案和回退顺序。
- 客户端：提供商搜索卡片和引用行。
