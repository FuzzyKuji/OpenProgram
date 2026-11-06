# API Reference

> Source: [`openprogram/`](https://github.com/FuzzyKuji/OpenProgram/tree/main/openprogram/)

## Core Components

| Component | Source File | Description |
|------|--------|------|
| [`Agent`, `Context`, `agent`, `agent_async`](api/agent.md) | `agent/`, `context/model.py` | Direct calls, configured Agent methods, and automatic execution context |
| [`Runtime`](api/runtime.md) | `agent/runtime.py` | The LLM runtime. Computes context from the DAG, calls the LLM, and writes the response back to the DAG |
| [`create_runtime` and the built-in providers](api/providers.md) | `providers/` | Automatically detect or explicitly create a Runtime; supports Anthropic / OpenAI / Gemini / CLI providers |

The session context is a flat DAG (nodes = user messages / LLM calls / function calls); for the architecture see [`openprogram/runtime/context/README.md`](https://github.com/FuzzyKuji/OpenProgram/blob/main/openprogram/runtime/context/README.md).

## Writing Functions

There are no meta functions like `create()` / `fix()` — writing, modifying, and validating Agent methods or ordinary Program functions is done directly with ordinary file-editing tools. The [Agent and Context API](api/agent.md) defines ordinary methods, automatic context, and legacy compatibility.

## Imports

```python
from openprogram import Agent, Context, agent, agent_async, Runtime, Session, decision
from openprogram.runtime.agent.runtime.factory import create_runtime
```

`Agent`, `Context`, `agent`, `agent_async`, `Runtime`, `Session`, and `decision` are re-exported from
the top-level `openprogram` package. Provider helpers such as `create_runtime`
are imported from their full paths.

## Quick Example

```python
from openprogram import Agent

class Observer(Agent):
    tools = []

    def observe(self, task: str) -> str:
        """Identify the requested UI element."""
        return self(f"Find the UI element for: {task}. Reply with its label only.")

print(Observer().observe("login button"))
```
