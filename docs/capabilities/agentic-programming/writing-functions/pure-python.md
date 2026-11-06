# Pure Python

## When to use

The task is pure deterministic logic with no need for LLM reasoning. For
example:
- Word counting
- File reading / writing
- Data format conversion
- Math

## Design points

- Do **not** use the Agent method execution
- Do **not** call `llm()`
- No `runtime` parameter needed
- Use a standard Google-style docstring

## Examples

```python
def word_count(text: str) -> int:
    """Count the number of words in a text.

    Args:
        text: Input text.

    Returns:
        The word count.
    """
    return len(text.split())
```

```python
def extract_emails(text: str) -> list[str]:
    """Extract every email address from a text.

    Args:
        text: Input text.

    Returns:
        List of email addresses.
    """
    import re
    return re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
```

## Session DAG

Ordinary helpers in managed Program sources and ordinary Agent methods receive call scopes automatically. Arbitrary host functions do not receive source capture. Deterministic behavior alone does not determine whether a call appears in the DAG.

Use an ordinary Agent method when a deterministic helper belongs to a recorded workflow. It does not need a model request or tool registration. Set `tool=True` only when the model should be allowed to call it.

```python
from openprogram import Agent

class TextAgent(Agent):
    def word_count(self, text: str) -> int:
        """Count words."""
        return len(text.split())
```

## Deterministic and model operations

| Operation | Implementation |
|---|---|
| Fixed algorithm, data conversion, counting | Ordinary Python helper or Agent method |
| Natural-language generation, classification, reasoning | Explicit `agent()` or `self(...)` model request |
