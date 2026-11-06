# Agent calls and ordinary methods

Use `agent()` for a direct model request. Use an `Agent` subclass when several methods share model settings and instructions. The framework creates call scopes and Context automatically.


Each Agent execution owns its DAG. Chat records user messages, model requests and directly dispatched tools; ordinary helpers create no durable nodes. Calling another Agent creates an independent DAG; the parent stores the invocation result and a child_session_id reference. Permission, cancellation and file-checkpoint ownership remain with the originating execution, independent of graph ownership.

## Ordinary methods

```python
from openprogram import Agent

class ReviewAgent(Agent):
    tools = []
    instructions = "Preserve facts. Return concise text."

    def classify(self, review: str) -> str:
        """Classify review sentiment."""
        return self(f"Classify as positive, negative, or neutral:\n{review}")

    def summarize(self, review: str) -> str:
        """Summarize a review with its sentiment."""
        sentiment = self.classify(review)
        return self(f"Summarize this {sentiment} review in one sentence:\n{review}")

reviewer = ReviewAgent(model="configured-model")
summary = reviewer.summarize("The service was fast.")
```

`classify` and `summarize` are ordinary Python methods. Internal helper calls do not create DAG nodes. `self(...)` makes a model request through the existing Runtime. The docstring describes the function call. The prompt provides the model instruction and data.

An Agent instance stores configuration. It does not implicitly retain a conversation between independent top-level calls. Nested calls on the same Agent use the active execution; another Agent gets a separate graph. Context selects permitted history and resolves configured content for each request.

## Direct calls and asynchronous code

```python
from openprogram import agent, agent_async

answer = agent("Summarize this text", tools=[])
# In an async function:
# answer = await agent_async("Summarize this text", tools=[])
# answer = await reviewer.arun("Summarize this text")
```

Use `tools=[]` for a request without model tools. With `tools=None`, the runtime resolves available tools and applies the current authorization rules.

## Method metadata and explicit tools

Declare `method_options` when a public method needs input form metadata, visibility rules, or explicit tool registration:

```python
class TextAgent(Agent):
    tools = []
    method_options = {
        "summarize": {
            "tool": True,
            "name": "summarize_notes",
            "input": {"text": {"description": "Text to summarize"}},
            "expose": "io",
        },
    }

    def summarize(self, text: str) -> str:
        """Summarize text."""
        return self(f"Summarize:\n{text}")
```

Recording a method does not make it a tool. `tool=True` explicitly registers the method. Function names and signatures supply the tool schema. Visibility controls history rendering and does not grant tool permissions.

## Ordinary Program functions

The managed loader captures ordinary source-defined functions in authorized Program packages. List public entry functions in `PROGRAM_ENTRIES`. Private helpers retain runtime access without producing DAG nodes or becoming tools. This capture does not extend to arbitrary host files or dependencies.

For deterministic composition, call methods or functions in Python. For model-selected calls, supply explicitly registered tools. See [tool calling](../choosing-the-next-step/tool-calling.md).

## Method behavior

Agent methods retain explicit metadata, tool registration, authorization, and durable steps through `method_options`. The [API reference](../../../reference/api/agent.md) documents Context, method options, and method configuration. Existing [function metadata](function-metadata.md) describes the method fields.

## Persistent conversations

`Agent.run_turn()` executes a persistent session turn. `ChatAgent` is the conversation subtype used by the App, Web, TUI and channel adapters. Both use the same turn runtime for history, permissions, model tools, streaming, compression and final persistence.

```python
from openprogram import Agent, Context, TurnRequest
from openprogram.runtime.context.session_db import default_db

context = Context.for_session(default_db(), "example-conversation",
                              blocks={"reference": "User-supplied reference material"})
worker = Agent(context=context)
result = worker.run_turn(
    TurnRequest(session_id="example-conversation", user_text="Summarize the reference",
                agent_id="main", source="python"),
    on_event=lambda event: print(event["type"]),
)
print(result.final_text)
```

Use the same session ID for subsequent turns. `Context.for_session` selects the store; it does not create a provider. An optional `head_id` selects the predecessor branch. `Context(history=None)` excludes past graph content while retaining the current prompt. Named content and providers are rendered as user content and cannot alter system instructions or tool permissions.

`arun_turn()` and `aresume_turn()` are asynchronous counterparts. Their event callbacks run in the execution thread; use a thread-safe handoff when updating an asyncio consumer. Cancelling the awaiting task signals the running turn and waits for its cooperative cleanup. A synchronous caller can supply a `threading.Event` as `cancel_event`.

`resume_turn(continuation)` consumes an existing Agent continuation and its frozen request. It does not append a new user message or reapply changed instance settings. The existing production driver remains responsible for durable pause, steering and continuation admission through its execution-control service; the Agent API does not create a second job registry. Ordinary helper calls remain unrecorded, nested Agent calls retain independent DAGs, and a tool deadline does not cancel the parent conversation.
