# Embedding in your own stack

Use Agent and Runtime as a Python library inside an existing application. The host supplies its model client and decides whether to persist sessions. Library calls do not start the Web UI or terminal UI.

## Supply a host Runtime

```python
from openprogram import Agent, Runtime


def model_call(content, model="host-model", response_format=None):
    # Replace this offline response with the host's model client.
    return "Host model response"

runtime = Runtime(call=model_call, model="host-model")

class ReviewAgent(Agent):
    tools = []

    def classify(self, review: str) -> str:
        """Classify review sentiment."""
        return self(f"Classify review sentiment:\n{review}")

    def summarize(self, review: str) -> str:
        """Summarize a review."""
        sentiment = self.classify(review)
        return self(f"Summarize this {sentiment} review:\n{review}")

reviewer = ReviewAgent(runtime=runtime)
try:
    summary = reviewer.summarize("The service was fast.")
finally:
    runtime.close()
```

`Runtime(call=...)` accepts the host callback. It receives content blocks, a model name, and an optional response format. Construction does not make a model request. The host closes the Runtime it supplies.

Agent methods inherit this Runtime automatically. The host does not pass it through every helper. Context and function scopes are automatic. The callback example returns a fixed response and requires no network access.

## Persist an explicit session

The default Agent invocation does not give the instance a persistent conversation. Use an explicit store and session when the host needs continuity:

```python
from openprogram import Agent, Context
from openprogram.state.store import SessionStore, SessionNodeWriter

store = SessionStore(root_path="/var/lib/myapp/sessions")
store.create_session("research", agent_id="main")
writer = SessionNodeWriter(store, "research")
researcher = Agent(context=Context(store=writer), tools=[])
try:
    first = researcher("List the project requirements.")
    second = researcher("Review the requirements from the previous call.")
finally:
    store.close()
```

`Context(store=writer)` explicitly continues this session across calls. The host owns its store and Runtime. `head_id` can select an existing branch tip. Default Agent calls remain independent.

## Inspect calls and expose tools

```python
from openprogram.state.store import SessionNodeWriter

for node in SessionNodeWriter(store, "review-42").load():
    print(node.name, node.caller, node.output)
```

Ordinary public Agent methods receive call scopes. To expose a method as a model tool, set `tool=True` in its `method_options`. This explicit registration supplies `.spec` and `.execute`. Recording alone does not grant tool access. See the [Agent and Context API](../../reference/api/agent.md).

## Method behavior and host hooks

Agent methods provide the complete execution contract. `set_cancellation_check` (in `openprogram.host.cancellation`, next to `CancelledError` and `check_cancelled`) and `set_session_id_provider` (in `openprogram.runtime.agent.call_state`) remain available for host cancellation and question routing.

The embedded import path uses library APIs. It does not replace the complete installed product. Import checks are in `tests/embed/`. See [Runtime](../../reference/api/runtime.md) and the [programming guide](writing-functions/agent.md).
