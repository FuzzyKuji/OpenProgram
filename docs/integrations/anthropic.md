# Anthropic API

Use the official Anthropic API with an API key and API-account billing. All calls must comply with Anthropic service terms and usage policies.

```bash
openprogram providers login anthropic
```

```python
from openprogram.runtime.agent.runtime.factory import create_runtime

runtime = create_runtime(provider="anthropic", model="claude-sonnet-4-6")
```

See [authentication](../models/auth.md) and [provider configuration](../models/providers.md).
