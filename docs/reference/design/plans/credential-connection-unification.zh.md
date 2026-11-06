<div id="credential-connection-unification"></div>

# 凭证与连接统一

六种 payload 类合并为一个 `CredentialData`（共享字段和一个 `data` 字典），统一的 `resolve_connection()` 向通信层提供单次请求需要的全部信息：认证值、Base URL、请求头和类型。因此，每个 key 可以携带自己的 Base URL，已存储凭证会一次性迁移至新结构。

设计来源为
[`../providers/auth/credential-connection-unification.md`](../providers/auth/credential-connection-unification.zh.md).

<div id="data-model"></div>

## 数据模型

此前 `Credential.payload` 存放 `ApiKeyPayload`、`OAuthPayload`、`DeviceCodePayload`、`CliDelegatedPayload`、`ExternalProcessPayload` 或 `SsoPayload`，现在统一存放 `CredentialData`：

```python
@dataclass
class CredentialData:
    kind: str
    auth_value: str = ""
    base_url: str = ""
    headers: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
```

公共字段统一描述每种凭证“发送什么”。`data` 存放特定类型的数据，例如 refresh token、外部文件路径和 device-code 流程 ID。

序列化采用扁平结构 `{kind, auth_value, base_url, headers, data}`，不含 `__type__` 判别字段，因为 `kind` 现在是真实字段，而不是类身份。`_payload_from_dict` 仅接受此结构；运行时不兼容旧的六类 JSON。

`Credential.metadata` 及显示信息（email、name、org）保留原位置，既不属于 `CredentialData`，也不属于 `ResolvedConnection`。

<div id="kind-matching-replaces-isinstance"></div>

### 用 kind 匹配替代 isinstance

统一类后，类型检查变为值检查：

| 旧写法 | 新写法 |
|---|---|
| `isinstance(payload, ApiKeyPayload)` | `payload.kind == "api_key"` |
| `isinstance(payload, OAuthPayload)` | `payload.kind == "oauth"` |
| `isinstance(payload, (OAuthPayload, DeviceCodePayload))` | `payload.kind in ("oauth", "device_code")` |
| `isinstance(payload, DeviceCodePayload)` | `payload.kind == "device_code"` |
| `isinstance(payload, CliDelegatedPayload)` | `payload.kind == "cli_delegated"` |
| `isinstance(payload, ExternalProcessPayload)` | `payload.kind == "credential_process"` |
| `isinstance(payload, SsoPayload)` | `payload.kind == "sso"` |
| `payload.access_token` / `payload.api_key` | `payload.auth_value` |
| `payload.refresh_token` | `payload.data.get("refresh_token", "")` |
| `payload.expires_at_ms` | `payload.data.get("expires_at_ms", 0)` |
| 其他旧字段（`store_path`、`client_id` 等） | `payload.data.get(...)` |

<div id="construction-mapping"></div>

### 构造映射

| 旧构造方式 | 新构造方式 |
|---|---|
| `ApiKeyPayload(api_key=K)` | `CredentialData(kind="api_key", auth_value=K)` |
| `OAuthPayload(access_token=A, refresh_token=R, expires_at_ms=E, scope=S, client_id=C, token_endpoint=T, id_token=I, extra=X)` | `CredentialData(kind="oauth", auth_value=A, data={"refresh_token":R,"expires_at_ms":E,"scope":S,"client_id":C,"token_endpoint":T,"id_token":I,"extra":X})` |
| `DeviceCodePayload(access_token=A, refresh_token=R, expires_at_ms=E, device_code_flow_id=F, extra=X)` | `CredentialData(kind="device_code", auth_value=A, data={"refresh_token":R,"expires_at_ms":E,"device_code_flow_id":F,"extra":X})` |
| `CliDelegatedPayload(store_path=P, access_key_path=A, refresh_key_path=R, expires_key_path=E)` | `CredentialData(kind="cli_delegated", data={"store_path":P,"access_key_path":A,"refresh_key_path":R,"expires_key_path":E})` |
| `ExternalProcessPayload(command=C, parses=Pa, json_key_path=J, cache_seconds=S)` | `CredentialData(kind="credential_process", data={"command":C,"parses":Pa,"json_key_path":J,"cache_seconds":S})` |

<div id="resolution-one-read-exit"></div>

## 解析：统一读取出口

返回单独 `str` 的 `_extract_token` 被 `resolve_connection` 替代，后者返回请求需要的全部信息：

```python
@dataclass
class ResolvedConnection:
    kind: str
    auth_value: str
    base_url: str | None
    headers: dict


def resolve_connection(cred: Credential) -> ResolvedConnection | None:
    ...
```

解析器执行以下规则：

- `cli_delegated` 在解析时读取外部文件，因此 token 始终是磁盘上的最新值。
- `credential_process` 和 `sso` 尚未接入请求流程，没有认证值的凭证也无法发起请求；这些情况均返回 `None`，由调用方回退。
- 空 `base_url` 转为 `None`，使通信层区分“此凭证未指定端点”和“此凭证指定了端点”，并据此回退。

`acquire_pooled(provider, profile=None)` 返回 `tuple[ResolvedConnection, str, str] | None`，不再返回 token 三元组，使连接信息完整传至通信层。

<div id="credential-first-catalogue-as-fallback"></div>

### 凭证优先，目录回退

通信层优先使用凭证信息，由模型目录补充缺失值：

```python
base_url = (conn.base_url if conn and conn.base_url else None) or model.base_url
headers  = {**(opts.headers or {}), **(conn.headers if conn else {})}
```

这样，一个 API key 可以使用自己的端点，同一 provider 的其他 key 仍使用目录默认值。OAuth 检测采用相同方式：通信层不再检查 token 字符串，而是接收根据 `conn.kind in ("oauth", "device_code")` 计算的 `is_oauth`。

<div id="stored-credential-migration"></div>

## 已存储凭证迁移

运行时不支持旧格式，因此通过独立流程进行一次性转换。`migrate_payload_dict(old) -> dict` 将携带 `__type__` 的旧 payload 字典映射为新的扁平结构，并保持幂等：已经采用新结构的 payload 原样返回。`migrate_store(root) -> int` 遍历 `<root>/auth/<provider>/<profile>.json`，原子重写各文件，并返回修改数量。管理文件（`_rotation`、`_active`、`_disabled`、`_order.json`）没有 `credentials` 列表，因此跳过。

迁移在存储首次加载、读取任何凭证池之前自动运行，同时提供 `openprogram auth migrate` 命令。迁移失败不得阻止存储启动；真正损坏的文件随后通过 `from_dict` 的 `AuthCorruptCredentialError` 显示。

本次结构调整递增 `CREDENTIAL_SCHEMA_VERSION`。旧 `v` 值触发迁移，而非损坏错误。

<div id="appendix-implementation-status"></div>

## 附录：实现状态

当前认证路径已实现。`CredentialData` 和 schema 版本 3 定义于 `openprogram/models/auth/types.py`；`ResolvedConnection` 与 `resolve_connection` 位于 `openprogram/models/auth/resolver.py`；payload 转换和存储迁移位于 `openprogram/models/auth/_migrate_payload.py`；`openprogram/models/auth/store.py` 接入首次加载迁移；CLI 的 `openprogram/interfaces/cli/commands/providers/accounts.py` 暴露 `openprogram providers migrate`。Provider 凭证池现在接收已解析连接，通信层可以优先使用凭证的端点和请求头。原始构造/匹配表仍作为设计契约。尚需验收真实凭证存储副本的迁移及常规 auth/provider 回归套件；本页不声称这些检查已在此执行。
