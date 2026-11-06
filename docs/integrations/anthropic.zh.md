# Anthropic API

通过官方 Anthropic API 接入，使用合法获取的 API key，按 API 账户计费。所有调用必须遵守 Anthropic 的服务条款与使用政策。

```bash
openprogram providers login anthropic
```

```python
from openprogram.runtime.agent.runtime.factory import create_runtime

runtime = create_runtime(provider="anthropic", model="claude-sonnet-4-6")
```

参见[认证](../models/auth.zh.md)与 [provider 配置](../models/providers.zh.md)。
