<div id="mcp-server-implementation-plan"></div>

# MCP 服务器实现计划

> **面向 agent worker：** 必须使用子技能 superpowers:executing-plans 逐项实现本计划。每项任务使用 superpowers:test-driven-development，在报告完成前使用 superpowers:verification-before-completion。

**目标：** 添加经过身份验证、仅支持 stdio 的 `openprogram mcp serve` 端点，恰好公开六个固定 MCP 工具，并将其映射到现有会话、Runtime 工具、审批、取消、进度与审计机制，不授予 owner 权限。

**架构：** 新增同级 `openprogram/extensions/mcp/server/` 包，与现有 MCP 客户端包及 Web owner 控制面分离。入口在打开 stdin 前完成身份验证，创建由凭据派生的客户端身份，固定使用 `paired` 权限和 `non-interactive` 交互，并在协议基线 2025-11-25 上运行锁定的 MCP 1.29.0 SDK 服务器。六个面向协议的工具委托给服务层；底层 Runtime 工具的公开集合为默认空配置允许列表、实时注册表与固定 paired 能力表的交集。SDK 取消负责 JSON-RPC 取消错误；OpenProgram 仅停止后续副作用、清理请求/问题状态并生成审计证据。

**技术栈：** Python 3.11+、`mcp==1.29.0`、MCP 2025-11-25、AnyIO、Pydantic、jsonschema、pytest、stdio JSON-RPC，以及现有 SessionDB/dispatcher/Runtime/事件总线。

<div id="global-constraints"></div>

## 全局约束

- 从 `origin/main@9fb70113fd31dc2acf80a341e5ac51d244e1c35a` 创建隔离 worktree 实现。不得修改有未提交更改的 main checkout。
- 服务器唯一传输方式为 `openprogram mcp serve` 的 stdio。不得新增 HTTP、SSE、Streamable HTTP、OAuth、Web 路由、socket 或部署监听器。
- 行为锁定为仓库的 `mcp==1.29.0` 和协议版本 `2025-11-25`；不得增加自定义握手字段或扩大依赖版本范围。
- 恰好公开以下 MCP 工具名：`sessions_list`、`session_get`、`prompt_send`、`prompt_cancel`、`tools_list`、`tool_call`。
- 使用独立且由凭据派生的 MCP 客户端身份。`initialize.clientInfo` 仅为诊断元数据，不得影响身份验证、身份、作用域、允许列表或审批。
- 每个请求使用 `source="mcp"`、`permission_mode="ask"`、`authority_tier="paired"` 和 `interaction="non-interactive"`；调用方均不可配置。
- `mcp_server.exposed_tools` 默认为 `[]`。底层 Runtime 工具的发现与执行均使用 `configured allowlist ∩ live registry ∩ paired capability`。
- 读取 POSIX 权限为 `0600` 的 `<state>/mcp_server_token`，并在进入 SDK stdio 上下文前用 `hmac.compare_digest()` 与 `OPENPROGRAM_MCP_TOKEN` 比较。`serve` 永不生成 token。
- 不得导入或复用 `openprogram.interfaces.server.owner_auth`、`backend_endpoint`、Web owner token、cookie 或 owner bearer header。
- 未知和未公开的底层工具名不可区分，均返回方法级 MCP 错误。已配置工具缺少 paired 作用域、硬约束/审批拒绝或工具执行失败时返回 `CallToolResult(isError=True)`。
- 被取消的原始 `prompt_send` 永不返回应用工具结果。MCP SDK 1.29.0 返回标准 JSON-RPC 取消错误；服务停止后续副作用，清理活跃请求与问题，并记录 `mcp.request.cancelled`。
- `prompt_cancel` 是独立普通工具。它只能取消由同一已验证服务器连接发起的当前活跃轮次，并返回自己的正常执行结果。
- 普通问题与审批不得等待非交互式 MCP 请求。审批门禁立即拒绝；活跃 MCP 会话的其他 `question.asked` 事件立即解析为 declined。
- 不得修改或扩展现有 ACP 服务器。共享 Runtime 类型发生变化时运行 ACP 回归。
- 每项任务严格遵循 RED → 验证失败 → GREEN → 验证通过 → 提交。不得合并任务提交。

<div id="fixed-protocol-contract"></div>

## 固定协议约定

全部六个 schema 设置 `additionalProperties: false`。空输入工具使用 `{ "type": "object", "properties": {} }`。

| MCP 工具 | 输入 schema | 成功 payload |
|---|---|---|
| `sessions_list` | 无字段 | 最多 100 条最近的 `{id,title,updated_at}`，按 SessionDB 顺序排列 |
| `session_get` | 必需的非空字符串 `session_id` | 活跃分支消息 `{id,role,content,timestamp}` |
| `prompt_send` | 必需的非空字符串 `prompt`；可选非空字符串 `session_id` | `{session_id,text,assistant_msg_id,failed}`；缺少 `session_id` 时创建 `mcp_<uuid>` 会话，提供未知 id 则无效 |
| `prompt_cancel` | 必需的非空字符串 `session_id` | `{session_id,cancelled}`；仅同一连接的活跃 MCP 轮次使 `cancelled` 为 true |
| `tools_list` | 无字段 | 允许列表/注册表/paired 交集中的底层工具，格式为 `{name,description,inputSchema}` |
| `tool_call` | 必需的非空字符串 `name`；可选对象 `arguments`，默认为 `{}` | 转换后的底层 `AgentToolResult` 内容与错误状态 |

成功的结构化应用 payload 序列化为一个 UTF-8 JSON `TextContent`；v1 不增加第二种输出表示。`tool_call` 保留 Runtime 文本/图像内容：文本映射为 MCP 文本内容，图像映射为含媒体类型的 MCP 图像内容。不支持的内容以执行错误拒绝，不转换为字符串。

MCP `tools/list` 本身始终返回六个固定包装工具。名为 `tools_list` 的包装工具返回筛选后的底层 Runtime 工具。这是两个不同约定，必须分别断言。

---

<div id="task-1-freeze-the-six-json-schemas-and-protocol-validation"></div>

### 任务 1：固定六个 JSON Schema 与协议验证

**文件：**

- 创建：`openprogram/extensions/mcp/server/__init__.py`
- 创建：`openprogram/extensions/mcp/server/contracts.py`
- 创建：`tests/unit/test_mcp_server_contracts.py`

**接口：**

```python
MCP_TOOL_SCHEMAS: tuple[mcp.types.Tool, ...]
TOOL_BY_NAME: Mapping[str, mcp.types.Tool]
def validate_tool_call(name: str, arguments: Mapping[str, Any] | None) -> dict[str, Any]
```

对于六个固定名称之外的包装工具名，`validate_tool_call()` 必须抛出 `mcp.shared.exceptions.McpError(ErrorData(code=METHOD_NOT_FOUND, ...))`；schema 验证失败时抛出 `McpError(... INVALID_PARAMS ...)`。它返回复制的 dict，永不修改调用方输入。

**RED：** 为六个名称的顺序、每个完整输入 schema、`additionalProperties: false`、必需字段、空/空白 prompt 和 id、非对象 arguments、未知包装工具名和输入不可变性添加严格相等测试。还要断言锁定依赖解析为 `mcp==1.29.0`，且 `LATEST_PROTOCOL_VERSION == "2025-11-25"`。

运行：

```bash
uv run --locked pytest -q tests/unit/test_mcp_server_contracts.py
```

预期：FAIL，因为 `openprogram.extensions.mcp.server.contracts` 不存在。

**GREEN：** 将 schema 定义为不可变模块数据，从中构造 SDK `Tool` 对象，并使用 `jsonschema.Draft202012Validator` 验证。仅将省略/`None` 的 `tool_call.arguments` 归一化为 `{}`；拒绝所有其他未声明或类型错误的字段。不得添加服务器、传输、身份验证或执行逻辑。

运行相同命令；预期：PASS。

**提交：**

```bash
git add openprogram/extensions/mcp/server/__init__.py openprogram/extensions/mcp/server/contracts.py tests/unit/test_mcp_server_contracts.py
git commit -m "feat: define MCP server tool contracts"
```

<div id="task-2-make-runtime-tool-errors-typed-end-to-end"></div>

### 任务 2：让 Runtime 工具错误在全流程中类型化

**文件：**

- 修改：`openprogram/runtime/agent/loop/types.py`
- 修改：`openprogram/programs/_host/runtime.py`
- 修改：`openprogram/extensions/mcp/adapter.py`
- 修改：`openprogram/runtime/agent/loop/`
- 修改：`openprogram/runtime/permissions/approval.py`
- 修改：`openprogram/runtime/agent/call_state.py`
- 修改：`openprogram/programs/tools/files/bash/bash.py`
- 修改：`tests/unit/test_tools_runtime.py`
- 修改：`tests/agent/test_loop_options.py`
- 修改：`tests/agent/test_tool_gate.py`
- 修改：`tests/unit/test_acp_server.py`

**接口：**

```python
class AgentToolResult(BaseModel):
    content: list[TextContent | ImageContent]
    details: Any = None
    is_error: bool = False
```

**RED：** 修改测试，对归一化的 `ToolReturn` 失败、超时、异常、远程 MCP `isError`、审批拒绝和 bash 失败断言 `result.is_error`。添加 agent-loop 断言，要求 `ToolResultMessage.is_error` 等于 `AgentToolResult.is_error`。断言 `details` 保留 `denied`、`timeout`、`reason_code` 等诊断字段，但不再传递权威 `is_error` 标志。

运行：

```bash
uv run --locked pytest -q tests/unit/test_tools_runtime.py tests/agent/test_loop_options.py tests/agent/test_tool_gate.py tests/unit/test_acp_server.py
```

预期：FAIL，因为 `AgentToolResult` 没有独立错误字段，使用方仍检查 `details`。

**GREEN：** 添加带默认值的字段；在 `_normalize_result()`、MCP 客户端转换、审批 `_denied()`、超时/异常路径和显式失败工具中设置它。将缓存及 agent-loop 转换中的 `details.get("is_error")` 替换为 `result.is_error`。保留默认 false，使无关构造器保持源码兼容。不得改变 ACP 协议结构。

运行相同命令；预期：PASS。

**提交：**

```bash
git add openprogram/runtime/agent/loop/types.py openprogram/programs/_host/runtime.py openprogram/extensions/mcp/adapter.py openprogram/runtime/agent/loop/ openprogram/runtime/permissions/approval.py openprogram/runtime/agent/call_state.py openprogram/programs/tools/files/bash/bash.py tests/unit/test_tools_runtime.py tests/agent/test_loop_options.py tests/agent/test_tool_gate.py tests/unit/test_acp_server.py
git commit -m "refactor: type runtime tool error results"
```

<div id="task-3-add-default-empty-exposure-paired-mcp-identity-and-non-interactive-gates"></div>

### 任务 3：添加默认空公开集合、paired MCP 身份与非交互门禁

**文件：**

- 修改：`openprogram/state/settings.py`
- 修改：`openprogram/runtime/permissions/authority.py`
- 修改：`openprogram/runtime/permissions/approval.py`
- 修改：`tests/unit/test_config_schema.py`
- 修改：`tests/unit/test_authority_scope.py`
- 修改：`tests/unit/test_permission_rules.py`
- 修改：`tests/unit/test_spawn_hard_constraints.py`
- 创建：`tests/unit/test_mcp_server_security.py`

**接口：**

```python
def mcp_client_authority(client_id: str) -> dict[str, Any]

SettingSpec(
    key="mcp_server.exposed_tools",
    path=("mcp_server", "exposed_tools"),
    default=[],
    apply=APPLY_NEXT_START,
    ...,
)
```

权限映射固定为 `speaker_kind="client"`、`speaker_id=f"mcp/{client_id}"`、`speaker_display="MCP client"`、`principal_id=owner_principal_id()`、`authority_tier="paired"`、`interaction="non-interactive"`。拒绝空或格式错误的客户端 id，不合成身份。

**RED：** 断言缺失设置读取为 `[]`；验证拒绝非列表及非字符串条目；归一化 MCP 权限稳定且仅拥有 paired 能力。添加 `source="mcp"` 用例，证明 `_NON_INTERACTIVE_SOURCES` 立即拒绝审批，且 `_hard_constraint_violation()` 在规则、允许列表或 bypass 授权之前拒绝 `_RISKY_TOOLS`、worktree 工具和工作目录之外的 write/patch 路径。断言未注册任何问题。

运行：

```bash
uv run --locked pytest -q tests/unit/test_config_schema.py tests/unit/test_authority_scope.py tests/unit/test_permission_rules.py tests/unit/test_spawn_hard_constraints.py tests/unit/test_mcp_server_security.py
```

预期：FAIL，因为设置、权限构造器和 MCP source 门禁均缺失。

**GREEN：** 添加 JSON 列表设置验证器、`mcp_client_authority()`、将 `"mcp"` 加入 `_NON_INTERACTIVE_SOURCES`，并在 `_hard_constraint_violation()` 中显式处理 MCP。硬约束保持在权限规则及所有 bypass 之前。不得扩展 `_PAIRED_CAPABILITIES`。

运行相同命令；预期：PASS。

**提交：**

```bash
git add openprogram/state/settings.py openprogram/runtime/permissions/authority.py openprogram/runtime/permissions/approval.py tests/unit/test_config_schema.py tests/unit/test_authority_scope.py tests/unit/test_permission_rules.py tests/unit/test_spawn_hard_constraints.py tests/unit/test_mcp_server_security.py
git commit -m "feat: add MCP server security boundary"
```

<div id="task-4-implement-the-independent-0600-token-lifecycle"></div>

### 任务 4：实现独立的 0600 token 生命周期

**文件：**

- 创建：`openprogram/extensions/mcp/server/auth.py`
- 修改：`openprogram/_cli_cmds/mcp.py`
- 修改：`openprogram/cli.py`
- 创建：`tests/unit/test_mcp_server_auth.py`
- 创建：`tests/unit/test_mcp_server_cli.py`

**接口：**

```python
MCP_TOKEN_ENV = "OPENPROGRAM_MCP_TOKEN"
def token_path() -> Path
def create_token(path: Path | None = None) -> str
def authenticate_from_environment(
    environ: Mapping[str, str] = os.environ,
    path: Path | None = None,
) -> str  # returns credential fingerprint/client id
def _cmd_mcp_token_create() -> int
```

指纹为 `sha256(stored_token.encode()).hexdigest()[:16]`；它是稳定客户端 id，绝不包含 token 文本。`create_token()` 使用 `secrets.token_urlsafe(32)`，拒绝已存在目标，以 `0600` 写入独占临时文件，执行 flush 和 `fsync()`，然后通过不覆盖操作安装（POSIX 使用 `os.link(temp, target)` 后删除临时链接；其他平台使用经过同等测试的禁止替换原语）。它重新应用仅用户可访问权限，验证权限，并返回 token 供 CLI 仅打印一次。不得在预检查后使用 `os.replace()`，因为它可能覆盖并发进程创建的 token。

**RED：** 覆盖创建、长度/熵形式、已有文件不覆盖并拒绝、父目录创建、POSIX `0600`、不可读/权限错误 token 拒绝、缺失环境变量、不匹配、使用 `hmac.compare_digest`、稳定指纹、异常/日志无 token，以及 `mcp token create` 解析器/退出行为。对 `_require_backend_endpoint` 打补丁，使其被调用即失败，以证明 token 创建在本地完成。

运行：

```bash
uv run --locked pytest -q tests/unit/test_mcp_server_auth.py tests/unit/test_mcp_server_cli.py
```

预期：FAIL，因为 token 身份验证和嵌套 `mcp token create` 命令不存在。

**GREEN：** 在 `mcp/server/auth.py` 实现独立写入器；不得导入 Web 身份验证辅助函数。为现有 `mcp` 解析器扩展 `token create`，保留所有管理命令。在任何后端 HTTP 辅助函数之前直接分发 token 创建。

运行相同命令；预期：PASS。

**提交：**

```bash
git add openprogram/extensions/mcp/server/auth.py openprogram/_cli_cmds/mcp.py openprogram/cli.py tests/unit/test_mcp_server_auth.py tests/unit/test_mcp_server_cli.py
git commit -m "feat: add MCP server token lifecycle"
```

<div id="task-5-implement-session-reads-and-filtered-runtime-discovery"></div>

### 任务 5：实现会话读取和筛选后的 Runtime 发现

**文件：**

- 创建：`openprogram/extensions/mcp/server/service.py`
- 创建：`openprogram/extensions/mcp/server/tools.py`
- 创建：`tests/unit/test_mcp_server_tools.py`

**接口：**

```python
@dataclass(frozen=True)
class MCPClientContext:
    client_id: str
    authority: Mapping[str, Any]

class MCPService:
    def sessions_list(self) -> AgentToolResult: ...
    def session_get(self, session_id: str) -> AgentToolResult: ...
    def tools_list(self) -> AgentToolResult: ...
    def exposed_runtime_tools(self) -> tuple[AgentTool, ...]: ...

def json_result(payload: Any, *, is_error: bool = False) -> AgentToolResult: ...
```

**RED：** 使用伪造 SessionDB 和注册表，断言 `sessions_list` 调用 `list_sessions(limit=100)` 且仅输出 `id/title/updated_at`；`session_get` 拒绝未知 id，通过 `get_branch(session_id)` 读取当前活跃分支，且仅输出 `id/role/content/timestamp`。断言 `tools_list` 默认为空，忽略已配置但未注册名称，排除缺少 paired 能力的已注册名称，去重后保留配置顺序，并返回精确的 `name/description/inputSchema` 键。断言它从不读取 `clientInfo` 或 Web 身份验证。

运行：

```bash
uv run --locked pytest -q tests/unit/test_mcp_server_tools.py -k "sessions or session_get or tools_list"
```

预期：FAIL，因为服务与转换模块不存在。

**GREEN：** 向 `MCPService` 注入 SessionDB/config/registry 访问器，以实现确定性测试。使用 `functions._runtime.get()`/注册表公开机制和 `decide_tool_authority()` 求交集。返回确定性 JSON 文本。本任务不实现 `tool_call`、prompt 执行、传输或 owner 回退。

运行相同命令；预期：PASS。

**提交：**

```bash
git add openprogram/extensions/mcp/server/service.py openprogram/extensions/mcp/server/tools.py tests/unit/test_mcp_server_tools.py
git commit -m "feat: add MCP session and tool discovery"
```

<div id="task-6-implement-fail-closed-tool_call-and-progress-mapping"></div>

### 任务 6：实现失败时拒绝的 `tool_call` 与进度映射

**文件：**

- 修改：`openprogram/extensions/mcp/server/service.py`
- 修改：`openprogram/extensions/mcp/server/tools.py`
- 修改：`tests/unit/test_mcp_server_tools.py`

**接口：**

```python
async def MCPService.tool_call(
    self,
    name: str,
    arguments: Mapping[str, Any],
    *,
    call_id: str,
    cancel_event: asyncio.Event,
    on_progress: Callable[[str], None] | None,
) -> AgentToolResult: ...

def to_mcp_content(result: AgentToolResult) -> list[mcp.types.ContentBlock]: ...
```

**RED：** 添加表驱动测试：未知名称与已知但未公开名称返回相同 `METHOD_NOT_FOUND` 错误；已公开名称缺少 paired 能力时返回 `is_error=True` 并说明缺失能力；硬约束、策略和不可用审批的拒绝返回类型化错误；无效底层参数返回 `INVALID_PARAMS`；成功文本/图像转换；底层异常/失败转换；每种拒绝均不执行调用。验证执行使用固定 `source="mcp"`、`permission_mode="ask"`、paired 权限且无请求可控覆盖的 `TurnRequest`。验证更新回调保序，缺少 `on_progress` 时忽略。

运行：

```bash
uv run --locked pytest -q tests/unit/test_mcp_server_tools.py -k tool_call
```

预期：FAIL，因为 `tool_call()` 缺失。

**GREEN：** 先解析公开范围且不泄露注册表成员关系，验证所选 Runtime 工具 schema，检查 `decide_tool_authority()`，通过 `wrap_with_approval()` 包装，再调用 `AgentTool.execute(call_id, arguments, cancel_event, on_update)`。仅转换支持的内容。保留 `AgentToolResult.is_error`；不得从自由文本推断失败。

进度约定：服务仅报告有序更新消息。任务 8 的传输层将其转换为单调递增的 MCP 进度值，且仅在请求元数据包含 `progressToken` 时发送。

运行相同命令；预期：PASS。

**提交：**

```bash
git add openprogram/extensions/mcp/server/service.py openprogram/extensions/mcp/server/tools.py tests/unit/test_mcp_server_tools.py
git commit -m "feat: add scoped MCP runtime tool calls"
```

<div id="task-7-implement-prompt-ownership-non-interactive-questions-and-cancellation-cleanup"></div>

### 任务 7：实现 prompt 归属、非交互问题和取消清理

**文件：**

- 修改：`openprogram/extensions/mcp/server/service.py`
- 修改：`openprogram/extensions/mcp/server/tools.py`
- 创建：`tests/unit/test_mcp_server_turns.py`

**接口：**

```python
@dataclass
class ActiveMCPRequest:
    request_id: str
    session_id: str
    client_id: str
    thread_cancel: threading.Event
    tool_cancel: asyncio.Event

async def MCPService.prompt_send(..., request_id: str, ...) -> AgentToolResult: ...
def MCPService.prompt_cancel(session_id: str) -> AgentToolResult: ...
def MCPService.cancel_request(request_id: str, *, reason: str) -> None: ...
def MCPService.close() -> None: ...
```

**RED：** 断言省略 session id 时使用 agent `main` 和 source `mcp` 创建 `mcp_<uuid>`；提供已有会话时保留存储的 agent id；提供未知 id 返回 `INVALID_PARAMS`；`process_user_turn()` 接收固定安全字段和已注册线程事件。断言并发请求拥有请求级记录。`prompt_cancel` 仅对同一客户端、同一连接的活跃轮次成功；未知、已完成或外部轮次均拒绝，且不设置其事件。

订阅测试事件总线，为活跃及无关会话发出 `question.asked`。活跃 MCP 问题必须立即解析为 `declined`；无关问题不得受影响。取消时断言 `thread_cancel.set()`、`tool_cancel.set()`、`mark_cancelled(session_id)`、`kill_active_subprocess(session_id)`、`kill_active_runtime(session_id)`、`QuestionRegistry.cancel_session(session_id)`、`unregister_cancel_event(session_id, exact_event)`、移除活跃映射，以及包含 request/session/client 指纹但不含 prompt/token 的 `mcp.request.cancelled` 审计。重复取消和清理以证明幂等性。

运行：

```bash
uv run --locked pytest -q tests/unit/test_mcp_server_turns.py
```

预期：FAIL，因为 prompt 生命周期及活跃请求归属缺失。

**GREEN：** 使用 `anyio.to_thread.run_sync(..., abandon_on_cancel=True)` 运行同步 `process_user_turn()`，并始终在 `finally` 中注销精确的取消事件。问题总线订阅限定于服务生命周期，在 `close()` 中取消订阅。在请求边界捕获取消，调用 `cancel_request()` 后重新抛出，让 SDK 1.29.0 生成标准 JSON-RPC 取消错误。该取消路径绝不构造 `AgentToolResult`。保护完成操作，防止被放弃的 worker 后续发布结果或修改活跃请求记录。

运行相同命令；预期：PASS。

**提交：**

```bash
git add openprogram/extensions/mcp/server/service.py openprogram/extensions/mcp/server/tools.py tests/unit/test_mcp_server_turns.py
git commit -m "feat: add MCP prompt lifecycle and cancellation"
```

<div id="task-8-wire-mcp-1290-stdio-and-add-end-to-end-protocol-tests"></div>

### 任务 8：连接 MCP 1.29.0 stdio 并添加端到端协议测试

**文件：**

- 创建：`openprogram/extensions/mcp/server/server.py`
- 修改：`openprogram/extensions/mcp/server/__init__.py`
- 修改：`openprogram/_cli_cmds/mcp.py`
- 修改：`openprogram/cli.py`
- 修改：`tests/unit/test_mcp_server_cli.py`
- 创建：`tests/integration/test_mcp_server.py`

**接口：**

```python
def build_server(context: MCPClientContext) -> mcp.server.Server: ...
async def serve_stdio(context: MCPClientContext) -> None: ...
def serve() -> int: ...
def _cmd_mcp_serve() -> int: ...
```

`serve()` 在进入 `mcp.server.stdio.stdio_server()` 前调用 `authenticate_from_environment()` 并构造 `MCPClientContext`。身份验证错误向 stderr 打印脱敏文本，返回非零值，保持 stdout 为空，且从不读取 stdin。

使用 `Server.run(read, write, server.create_initialization_options())`。在 `server.request_handlers` 中显式注册 `CallToolRequest` 处理器，不能仅依赖将全部异常转换为 `isError` 的装饰器；包装工具名和无效参数错误必须保留为 MCP 错误。从 `server.request_context` 取得 request id、`progressToken` 和 session。仅为脱敏诊断读取 `client_params.clientInfo`。

**RED：** 先扩展 CLI 单元测试：`mcp serve` 在本地分发且永不调用 `_require_backend_endpoint`；身份验证发生在 stdio 上下文之前。再添加 SDK 客户端子进程测试，覆盖：

1. 缺失 token 文件、错误权限、缺失环境变量和环境变量不匹配均在 initialize 前退出，状态非零、stdout 为空、stderr 脱敏；
2. 有效 token 完成 2025-11-25 initialize，更改 `clientInfo.name/version` 不影响身份、工具列表或结果；
3. MCP `tools/list` 恰好返回有序的六个固定工具，`tools_list` 包装工具仅返回允许列表/注册表/paired 交集；
4. 六种映射均返回固定结构；未知包装工具名和无效参数为 MCP 错误；
5. 未知/未公开底层名称不可区分，作用域/硬约束/审批失败为 `isError`，且被拒绝工具均不执行；
6. 审批或普通问题永不阻塞 MCP 调用；
7. 当且仅当请求提供 `progressToken` 时，进度通知按单调顺序到达；
8. 取消进行中的 `prompt_send` 为原请求产生 SDK 1.29.0 标准 JSON-RPC 取消错误，绝不产生工具结果/`isError`；后续副作用停止，活跃请求/问题状态清除，且存在审计事件；
9. `prompt_cancel` 保持普通工具调用，不能取消外部/已完成轮次；
10. stdout 仅包含 JSON-RPC；诊断和审计文本绝不写入其中。

运行：

```bash
uv run --locked pytest -q tests/unit/test_mcp_server_cli.py tests/integration/test_mcp_server.py
```

预期：FAIL，因为 stdio 服务及 `mcp serve` 缺失。

**GREEN：** 仅实现 stdio 服务器和本地 CLI 分发。通过内存对象流或 `loop.call_soon_threadsafe` 将 worker 线程回调的进度转交 AnyIO 循环；仅在存在 token 时调用 `ServerSession.send_progress_notification()`。请求处理器捕获普通执行失败并按固定矩阵转换，但重新抛出取消。确保关闭时执行 `MCPService.close()`。

运行相同命令；预期：PASS。

同时运行共享回归：

```bash
uv run --locked pytest -q tests/unit/test_authority_scope.py tests/unit/test_permission_rules.py tests/unit/test_spawn_hard_constraints.py tests/agent/test_questions.py tests/unit/test_acp_server.py tests/unit/test_tools_runtime.py
```

预期：PASS。

**提交：**

```bash
git add openprogram/extensions/mcp/server/server.py openprogram/extensions/mcp/server/__init__.py openprogram/_cli_cmds/mcp.py openprogram/cli.py tests/unit/test_mcp_server_cli.py tests/integration/test_mcp_server.py
git commit -m "feat: serve authenticated MCP over stdio"
```

<div id="appendix-current-implementation-status"></div>

## 附录：当前实现状态

本计划描述的 MCP 服务器已存在于当前源码。
实现位于 `openprogram/extensions/mcp/server/`（`auth.py`、`contracts.py`、
`server.py`、`service.py` 和 `tools.py`），CLI 分发位于
`openprogram/_cli_cmds/mcp.py` 和 `openprogram/cli.py`。当前服务器
在进入 stdio 前完成身份验证，公开固定包装工具，应用
paired 非交互权限，并负责取消清理。锁定的
依赖和协议基线仍为 `mcp==1.29.0` 与 MCP 2025-11-25。

下面的计划记录历史实现顺序，保留它是为了
说明约定和审查顺序，不是未实现工作列表。
当前完成证据及剩余的已安装/运行时验收
边界由权威 MCP 服务器设计页及其测试维护。本次
审计未运行测试或文档门禁，因此不声称新增的
通过数量或发布验收。

<div id="historical-task-9-record-implementation-evidence-and-run-the-complete-release-gate"></div>

### 历史任务 9：记录实现证据并运行完整发布门禁

**文件：**

- 修改：`docs/reference/design/integrations/mcp-server.html`
- 修改：`docs/reference/design/plans/mcp-server-implementation.md`，仅在执行路径或命令明显不同时修改
- 更新：`.superpowers/sdd/2026-08-12-mcp-server/ledger.md` （已 gitignore；不得提交）

**RED：** 编辑状态前运行完整门禁，在台账中记录精确命令/输出/提交证据：

```bash
uv run --locked pytest -q tests/unit/test_mcp_server_contracts.py tests/unit/test_mcp_server_auth.py tests/unit/test_mcp_server_cli.py tests/unit/test_mcp_server_security.py tests/unit/test_mcp_server_tools.py tests/unit/test_mcp_server_turns.py tests/integration/test_mcp_server.py
uv run --locked pytest -q tests/unit/test_authority_scope.py tests/unit/test_permission_rules.py tests/unit/test_spawn_hard_constraints.py tests/agent/test_questions.py tests/unit/test_acp_server.py tests/unit/test_tools_runtime.py
uv run --locked --with mdit-py-plugins python -m scripts.docs_site.build
uv run --locked --with mdit-py-plugins python -m scripts.docs_site.checklinks
git diff --check
```

预期：全部测试和文档命令通过。若任一命令失败，保持 HTML 实现状态不变，返回对应任务；如果缺少覆盖，则新增 RED 测试并在该任务修复。

**GREEN：** 仅在完整门禁通过后，使用实际文件、测试、SDK/协议版本和观测数量更新 HTML 实现状态表与证据单元格。保留文档顺序：当前状态 → 竞品设计 → 后续计划 → 实现证据。不得声称 HTTP/OAuth/Web 路由、ACP 修改、SDK 扩展或门禁未证实的结果。取消措辞保持明确：SDK JSON-RPC 取消错误、无应用工具结果、OpenProgram 仅清理/审计。

文档编辑后重新运行上述五个命令。预期：PASS 且 diff 检查无问题。

**提交：**

```bash
git add docs/reference/design/integrations/mcp-server.html docs/reference/design/plans/mcp-server-implementation.md
git commit -m "docs: record MCP server implementation evidence"
```

<div id="review-checkpoints"></div>

## 审查检查点

- 继续实现前审查任务 1：schema 是公开 v1 接口，后续任务不得附带修改。
- 合并审查任务 3–4 的安全性：不复用 owner 凭据，不以 clientInfo 授权，空列表不回退为全部工具，请求不能控制权限字段。
- 合并审查任务 6–7 的失败拒绝行为：每次拒绝发生在调用前，问题不等待，取消后不留下后续结果或副作用。
- 使用 SDK 客户端审查任务 8，不使用手写 JSON-RPC 帧。SDK 实测取消行为属于验收基线。
- 原任务 9 是记录 Layer 3 证据的历史步骤；当前实现状态由权威 MCP 服务器设计页维护。
