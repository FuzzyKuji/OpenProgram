# Agent and Context

`agent()` runs a model tool loop. `Agent` stores reusable configuration and scopes ordinary subclass methods. `Context` supplies named content and history selection. All entries use the existing Runtime and Session DAG.

## Direct calls and Agent classes

No manual Context construction or binding is required for ordinary calls.

```python
from openprogram import Agent, agent, agent_async

answer = agent("Summarize this text", tools=[])

class Researcher(Agent):
    instructions = "Return a short, factual answer."
    tools = []

    def prepare(self, question):
        """Remove surrounding whitespace."""
        return question.strip()

    def research(self, question):
        """Answer the prepared question."""
        return self(self.prepare(question))

researcher = Researcher(model="configured-model")
answer = researcher.research("A question")
# In async code: answer = await researcher.arun("A question")
# Or: answer = await agent_async("A question", tools=[])
```

`agent()` accepts a string or content blocks. Common keyword options are `model`, `effort`, `tools`, `choices`, and `runtime`. `choices` makes the closing reply a [next-step decision](../../capabilities/agentic-programming/choosing-the-next-step/next-step-decision.md) and returns the resolved pick. See [Runtime](runtime.md) for tool execution options. `tools=None` resolves available tools. `tools=[]` requests no tools. `agent_async()` accepts the same options.

`Agent(model=..., instructions=..., context=..., tools=..., runtime=..., effort=..., **options)` uses instance settings over class defaults. Per-call options override instance settings. `Agent.from_spec(spec, **overrides)` uses an existing AgentSpec configuration without creating a saved Agent entry.

Construction makes no model request and creates no execution session. An invocation inherits an active execution. Otherwise, it owns a separate execution and releases its resources. Reusing an instance does not continue a previous independent conversation.

Ordinary instance, static, and class methods receive automatic call scopes, including single-underscore helpers. Dunder methods and generators are excluded. Method recording does not register a model tool. Set `"tool": True` in that method's `method_options` to request explicit registration. `method_options = {"method_name": {"expose": "io", "render_range": {...}}}` supplies method metadata without a decorator.

## Context content and visibility

The framework derives and binds Context automatically. Explicit configuration is optional:

```python
from openprogram import Agent, Context

context = Context(
    {"notes": "Use the project terminology."},
    providers={"current_topic": lambda current: "Agent context"},
)
researcher = Agent(context=context, tools=[])
```

`Context(blocks=None, *, parent=None, providers=None, history=..., call_id=..., store=None, head_id=None)` implements a mutable mapping of named content. `derive()` creates a child with independent content. `Context.current()` returns the task binding, or `None`. `merge(other)` overlays named content and explicit selection without replacing the scope call identity. `bind()` is available for host integrations that need an explicit binding.

Providers are synchronous Python callables that accept the current Context. They run for each model request. A provider failure aborts that request. The framework does not execute expression strings.

`history` selects the history a model request sees. `None` sends none. `"thread"` sends only the earlier requests made with this same Context object. `"chat"` (the default for a Context) sends the visible conversation. A callable receives `(node, context)` and filters conversation nodes after the existing visibility checks. A Workflow role call that does not set `history` explicitly sends no history. These settings cannot expand tool permissions.

Context has one model: parent inheritance, named content, request-time evaluation, and history visibility. Agent instance content is an instance binding of that model. Model interactions remain in the execution session. Content is separate from system instructions and tool authority.

## Explicit session lifetime

Use `Context(store=writer, head_id=None)` when several independent calls must continue the same session. The writer is an existing `SessionNodeWriter`:

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

`head_id` selects an existing branch tip for the initial predecessor. `None` continues the current session head. The caller owns and closes the supplied store. Execution scopes do not close it.

This explicit Context session supplies the event lifetime needed for NOOA-style repeated instance calls. It uses the existing Session DAG. The Agent still stores configuration, and its default calls remain independent.

## Managed Program sources

The managed loader captures source-defined functions within explicitly authorized package roots. These include selected first-party sources, installed and catalogued Program packages, owner-recorded external harnesses, published Programs, and retained source snapshots. Capture includes submodules and nested source definitions. Arbitrary host files, unrelated dependencies, lambdas, generated code, and unavailable source are outside this boundary.

A package lists public entries in `PROGRAM_ENTRIES`. A plain entry can supply an explicit `__agent_options__` mapping for its existing entry metadata. Captured helpers do not become tools. The loader preserves explicit method metadata and excludes generator capture.

The class-and-method interface takes inspiration from [NVIDIA-labs OO Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents). OpenProgram does not claim NOOA API compatibility.

## Method behavior

Ordinary Agent methods create code nodes. Model requests create llm nodes. Agent owns method metadata, execution controls, and explicit registration. Context dynamically constructs each request.

Agent owns method execution and registration. Context resolves request content and visible history.

### Usage

```python
from openprogram import Agent
from openprogram.runtime.agent import llm

class ExampleAgent(Agent):
    method_options = {
        'f': {'tool': True},
    }

    def f(self, x: str) -> str:
        """One-line summary of what f does."""
        return llm([{"type": "text", "text": f"...{x}..."}])

_example_agent = ExampleAgent()
f = _example_agent.f
```

Every ordinary method receives a call scope. Configure named methods in the class `method_options` mapping.

### Method configuration

### Execution and Context settings

| Parameter | Type | Default | Description |
|------|------|------|------|
| `capture_io` | `bool` | ordinary method: `False`; explicit tool: `True` | Record arguments and return values when enabled. Structural call identity remains available without full values. |
| `resumable` | `bool` | `False` | Opt in to explicit durable steps, JSON state, and function code selection after restart. See below. |
| `expose` | `str` | ordinary method: `"full"`; registered tool: `"io"` | **Outward-facing**: what others can see about me when they render the DAG. `"io"` = only the function's name and return value are visible externally, while its internals (LLM exchanges, sub-calls) are hidden; `"llm"` = the reverse, exposing only the internal LLM exchanges and hiding the function's own name/return value and nested code sub-calls; `"full"` = everything visible (docstring + params + output + LLM replies + internals); `"hidden"` = no DAG nodes are written at all. Any other value raises `ValueError` when the Agent class configures the method |
| `render_range` | `dict` | `None` | **Inward-facing**: how many history nodes to read from the DAG when this function's internal `llm()` call assembles its prompt. Shape `{"callers": N, "subcalls": M}`, where both numbers are **node counts (sliced by `seq`)**:<br>• `callers` — nodes written **before** this function's frame started; take the most recent N (`None` default = unlimited, `0` = a full wall)<br>• `subcalls` — nodes already written **after** this function's frame started; take the most recent N (`-1` default = unlimited, so the frame naturally sees its own progress; `N>=0` = set explicitly when you want to truncate the prompt; `0` = wall off in-frame entirely)<br>`{"callers":0,"subcalls":0}` = cut off from both the outside world and your own frame |
| `input` | `dict` | `None` | Per-parameter UI metadata; the WebUI renders the input form from it. Supported fields per parameter: `description` (label next to the name), `placeholder` (example text), `multiline` (`True` = textarea), `options` (list of allowed values, rendered as a dropdown and emitted as a JSON-schema `enum`), `hidden` (`True` = exclude from the form and from the LLM tool schema) |
| `system` | `str` | `None` | The system prompt for this function's LLM calls (applied over the injected runtime for the duration of the call, then restored afterward) |

### Tool-registration parameters

An Agent method with `tool=True` registers as an LLM-callable tool in the shared registry (`openprogram.programs`), alongside `@function`-decorated tools. These parameters control that registration and share their names and semantics with `@function`:

| Parameter | Type | Default | Description |
|------|------|------|------|
| `tool` / `as_tool` | `bool` | `False` | Register this function as an LLM-callable tool. `False` = Python-direct-invoke only |
| `name` | `str` | `None` | Tool name override. Default: the function's `__name__` |
| `description` | `str` | `None` | Tool description override. Default: the function's docstring |
| `parameters` | `dict` | `None` | JSON-schema parameter override. Default: auto-generated from the signature's type hints plus `input` metadata (runtime-injected and `hidden` parameters excluded) |
| `label` | `str` | `None` | Human-readable label shown in tool UIs |
| `toolset` | `tuple` | `()` | Toolset names this tool belongs to (used by `exec(toolset=...)` presets) |
| `unsafe_in` | `tuple` | `()` | Channel sources in which the tool is considered unsafe and filtered out |
| `check_fn` | `Callable` | `None` | Per-call gate: called before dispatch; a falsy result blocks the call |
| `requires_env` | `tuple` | `()` | Environment variable names that must be set for the tool to be offered |
| `can_use` | `Callable` | `None` | Dynamic availability predicate evaluated at tool-resolution time |
| `max_result_chars` | `int` | `None` | Truncation cap for the tool result fed back to the model. `None` = the registry default `DEFAULT_MAX_RESULT_CHARS` (30,000 chars) |
| `persist_full` | `bool` | `False` | Persist the untruncated result to an independent path in the state directory so the agent can read it back; later saves do not overwrite earlier references. Return the path only after a successful write |
| `head_ratio` | `float` | `None` | When truncating, the fraction kept from the head, rest from the tail. `None` = the registry default `DEFAULT_HEAD_RATIO` (0.7) |
| `requires_approval` | — | `None` | Approval requirement forwarded to the tool registry (same shape as `@function`) |
| `cache` | `bool` | `False` | Memoize results on `(name, args)` for tool-dispatched calls |
| `cache_ttl` | `float` | `300.0` | Cache lifetime in seconds when `cache=True` |
| `timeout` | `float` | `None` | Hard wall-clock kill for a tool-dispatched call, in seconds; on expiry the model receives an error result |
| `available_if` | `Callable` | `None` | Tool-registration gate: if it returns falsy (or raises), tool registration is skipped. Ordinary method scopes remain active |
| `defer` | `bool` | `False` | Register as a deferred tool (schema loaded on demand instead of shipped with every call) |
| `register_globally` | `bool` | `True` | `False` = build the tool but keep it out of the global registry |

The signature and docstring supply method names, parameter types, defaults, and summaries. `method_options` supplies fields that the signature does not represent.

### Choosing the Runtime

A method runs on its Agent's configured Runtime, or on the caller's when the Agent has none: `ExampleAgent(runtime=rt).f("x")` runs `f` and every model request inside it on `rt`, and Agent methods it calls inherit `rt`. Configure Runtimes where the program starts (CLI, script, test), not by passing them through method arguments. For two models in one workflow — an author and a reviewer, say — give the second role its own Agent instance with its own Runtime.

### Runtime injection

Older functions may still declare parameters named `runtime`, `exec_runtime`, or `review_runtime`; they are auto-injected: if the caller passes none (or `None`), the runtime is taken from the current call chain, or — for an entry-point call — created via `create_runtime()` (auto-detection) and closed again when the function returns. A function may declare more than one runtime parameter; all of them are filled with the same runtime. These parameters never appear in the LLM tool schema or the WebUI form. New methods do not declare them.

### Introspection and safety

- `fn.spec` — the auto-generated JSON-schema tool spec (`{"name", "description", "parameters"}`); `fn.execute(**kwargs)` invokes the wrapper with LLM-provided kwargs.
- Self-recursion backstop: a function that re-enters itself more than 5 levels deep raises `RecursionError` (the model is also steered away from self-calls by an injected situational prompt).
- Pre-invocation hooks (`add_pre_invocation_hook` / `remove_pre_invocation_hook`) run at the top of every call and may raise `CancelledError` to abort it (this is how the WebUI stop button works).

### Recording to the DAG

- **Entering the function**: write a `code` node (`output=None`, `status="running"`), and store the function docstring into that node's `metadata.doc`, which is prepended to `function_name(args)` when rendering context.
- **`llm()` inside the function body**: each call writes an `llm` node.
- **Exiting the function**: backfill the same `code` node's `output` / `status`.

When `expose="hidden"`, no nodes are written. In standalone runs (with no DAG store installed), all recording is a no-op and the function executes as usual.

### Durable steps and code selection

Set `method_options = {"report": {"resumable": True}}` for synchronous orchestration whose external work is inside explicit steps:

```python
from openprogram import Agent
from openprogram.runtime.agent.durable_steps import step

class ExampleAgent(Agent):
    method_options = {
        'report': {'tool': True, 'resumable': True},
    }

    def report(self, topic: str):
        research = step("research", collect_research, topic)
        return step("write", write_report, research)

_example_agent = ExampleAgent()
report = _example_agent.report
```

Define `collect_research` and `write_report` as ordinary source-defined functions. Step inputs and results must be JSON-compatible. A completed step returns its saved result on continuation, without calling its action again. Repeated step names are distinguished by occurrence; keep their order and completed inputs stable. Put nested orchestration in `workflow("name", function, *args, **kwargs)`. `parallel({"branch": (function, args, kwargs)})` runs named workflows concurrently and waits for every branch before releasing ownership. Each branch has independent durable progress.

In Settings, `execution.code_change_policy` selects `keep_original` (default) or `use_latest`. The task's Continue control can override that policy. Python function and helper source is retained with the execution. After adopting B, a later restart with `keep_original` retains B, even if the installed code is now C. A candidate that fails compatibility before adopting any remaining step does not replace the retained active version. Imported module identities are checked; an unavailable or changed pinned dependency pauses recovery. With `use_latest`, completed results remain saved and the current function executes the remaining compatible steps. Deleted or reordered recorded steps and changed completed inputs pause the task instead of repeating an action. Changes to permissions or tool parameter contracts still require compatibility checks. If B needs a different local state shape, write that conversion as pure orchestration over saved JSON before its remaining steps.

Manual calls resume the same execution and function record. Chat calls return their eventual result to the original pending tool call. The existing two-hour automatic restart window applies to restart-owned interruptions. Explicit pauses, cancellation, unanswered approvals, and uncertain external results do not become automatic retries.

This contract restores execution at explicit steps, not arbitrary Python stack frames. Calls and external mutations outside steps, asynchronous orchestration, generators, live handles, and non-JSON results are not supported. If a process dies after an external action starts but before its result is committed, recovery requires reconciliation; it cannot assume that action failed. The function run dialog distinguishes functions that declare this contract from ordinary functions that require a new run after interruption.

Do not share mutable Python globals, closures or defaults between steps. Pass persistent state through JSON step inputs and results; process-local mutations are not a recovery protocol.

Import step dependencies at module scope. Imports inside retained helpers, dynamic import APIs and generated code are rejected before executing steps. Source-defined Python helpers are retained recursively. Opaque module and class dependencies currently support only the pinned standard library; third-party and user package objects are rejected because an initializer alone does not identify their implementation.

## Session turns and continuation

`Agent.run_turn(request, *, context=None, on_event=None, cancel_event=None, execution_context=None)` returns `TurnResult`. Import `TurnRequest` and `TurnResult` from `openprogram`. Instance configuration applies before a fresh turn; `Context.for_session(store, session_id, head_id=..., blocks=..., providers=...)` binds its persistent store and branch. A request for a different session is rejected. `Context.session_id` exposes the selected graph identity.

`arun_turn(request, **options)` runs the same operation asynchronously with cooperative cancellation. `resume_turn(continuation, **options)` and `aresume_turn(...)` reuse the checkpoint's request without repeating admission. Event callbacks receive the existing runtime event dictionaries and run on the execution thread. Durable pause and steering retain the existing execution-control owner and safe-point protocol.

`ChatAgent` inherits this contract and is the production conversation type. Overriding the turn entry methods does not automatically wrap them as ordinary helper calls. The old `openprogram.runtime.conversation.turn_runtime` imports alias the shared `openprogram.runtime.conversation.turn_runtime` modules; they do not implement another execution loop.
