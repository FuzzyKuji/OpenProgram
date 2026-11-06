# Function metadata

This document defines what metadata a function in this framework must carry — whether or not it calls an LLM — where that metadata lives, and which components consume it.

Scope: every function defined as an ordinary Agent method, plus any plain Python callable passed into `render_options` or any other component of the decision-menu protocol. (`runtime.exec(tools=[...])` does not accept plain callables — entries must be an `Agent` method, a `{"spec", "execute"}` dict, or an object with `.spec`/`.execute`; anything else raises `TypeError`.)

## 1. Why this spec exists

Historically the same piece of information lived in multiple places:

- Parameter descriptions could be written in the docstring `Args:` section or in `method_options = dict(input={...})`
- Decision-menu callers hand-wrote a verbose `available` registry dict at the call site, repeating information already present on the function
- Different consumers (tool_use spec, WebUI, decision menu, meta tooling) followed slightly different read-order conventions

The result: authors of new functions didn't know where to put descriptions, the framework read metadata from inconsistent sources, and generated code didn't always match what other consumers expected.

This spec defines a single source-of-truth so every consumer reads metadata by the same rules.

## 2. Who consumes function metadata

| Consumer | Required fields |
|---|---|
| `runtime.exec(tools=[fn])` (provider-native tool_use) | function name, overall description, parameter JSON schema (type / required / enum / description) |
| `render_options(options)` (decision menu) | function name, when-to-pick description, parameter name / type / description / enum, whether each parameter is system-filled |
| `parse_args(reply, options, ...)` (decision extract + dispatch + retry) | parameter names + types + enum + hidden flag, `runtime`-style auto-inject allowlist |
| WebUI parameter form | description / placeholder / multiline / options / hidden |
| `llm()` rendered context | docstring — carried as `metadata.doc` and prefixed into the rendered context text. The default system prompt comes from the ambient runtime (plus the skills block), not from the docstring. |
| Session-DAG rendering (`render_context`) | `expose` mode + `render_range` |
| auto-trace / persistence | function identity, argument values, return value, timing |

## 3. Metadata fields and their canonical locations

Every piece of information has exactly one source-of-truth. This table is the spec:

| Field | Where it lives | How to read it |
|---|---|---|
| Function name | `def name(...)` | `fn.__name__` |
| Parameter names | signature | `inspect.signature(fn).parameters` |
| Parameter types | annotation | `param.annotation` |
| Parameter defaults | annotation default | `param.default` |
| One-line summary (what / when-to-pick) | first paragraph of docstring (up to first blank line) | `inspect.getdoc(fn)`, first paragraph |
| Per-call LLM instructions (prompt + data for one specific `llm()`) | the prompt passed to that `llm()` call | passed directly at call time |
| Per-parameter description | `method_options = dict(input={"x": {"description": ...}})` | `fn.input_meta["x"]["description"]` |
| Per-parameter enum | `method_options = dict(input={"x": {"options": [...]}})` | `fn.input_meta["x"]["options"]` |
| Whether the parameter is LLM-visible | `method_options = dict(input={"x": {"hidden": True}})` | `fn.input_meta["x"]["hidden"]` |
| WebUI placeholder | `method_options = dict(input={"x": {"placeholder": "..."}})` | `fn.input_meta["x"]["placeholder"]` |
| WebUI multiline input | `method_options = dict(input={"x": {"multiline": True}})` | `fn.input_meta["x"]["multiline"]` |
| Dynamic option source | `method_options = dict(input={"x": {"options_from": "functions"}})` | `fn.input_meta["x"]["options_from"]` |
| Framework-auto-injected parameters | two constants in two files, both `{"runtime", "exec_runtime", "review_runtime"}`: `_RUNTIME_PARAMS` in `agent/call_state.py` (injection + tool-spec filtering) and `_AUTO_PARAMS` in `agent/decision.py` (menu hiding + dispatch) | module level |
| Override of the ambient LLM system prompt | `method_options = dict(system="...")` | `fn.system` |
| DAG expose mode | `method_options = dict(expose="io"\|"llm"\|"full"\|"hidden")` — controls what **callers** see of this function in their DAG render | `fn.expose` |
| DAG render range | `method_options = dict(render_range={"callers": N, "subcalls": M})` — controls how much DAG history **this function's own** `llm()` calls read. Both are node-count slices on `seq`: `callers` = most-recent N nodes written **before** this function's frame started (default `None` = uncapped, `0` = wall off all prior context); `subcalls` = most-recent N nodes written **since** this function's frame started (default `-1` = uncapped — the frame sees its own progress; child internals are hidden by *their* `expose` setting, not by subcalls counting; set `N>=0` only to actively cap prompt size in a loop). | `fn.render_range` |
| Skill trigger words / agent discovery | sibling `SKILL.md` frontmatter | loaded separately by the skill loader |

**Core principle**: anything expressible in the signature / annotation is not repeated in method_options; anything expressible in `input=` is not repeated in the docstring.

The method configuration accepts the shared tool-registration / gating kwargs (`name`, `description`, `toolset`, `unsafe_in`, `requires_approval`, `available_if`, `defer`, ...) documented in `docs/reference/design/function/calling-unification.md`; `cache` / `cache_ttl` (memoize results on name + args) and `timeout` (hard-kill the body after N seconds, returning an error result) behave as in `@function`.

### Effective defaults for ordinary Agent methods

| Aspect | Default | Resulting behavior |
|---|---|---|
| `expose` | `"full"` for ordinary methods, `"io"` for explicit tools | Callers see my name + input + output. My internal `llm()` calls are hidden from them. |
| `render_range` | `None` → `render_context` falls through to `callers=None, subcalls=-1` | Pre-frame history is uncapped. In-frame nodes (the frame's own progress: earlier `llm()` results, returned sub-function io) are also uncapped. A child configured with `expose="io"` hides its internals, not because subcalls trims them. |
| top-level chat turn | `frame_entry_seq=-1`, no pre-frame | Same code path as any other frame — all nodes are in-frame and visible. No special-casing. |
| tools | full toolset | A bare `runtime.exec` with neither `tools=` nor `toolset=` resolves the full registry toolset by default — tools are ON. Pass `tools=[...]` for an explicit menu; pass `toolset="none"` or `tools=[]` for a tool-free reasoning call. A nested `exec` inside a tool body inherits the outer `tools=` list via the `_current_tools` contextvar. |
| `system` | `None` | Use the runtime's existing system prompt as-is. |

Implication: a frame naturally accumulates its own work. Set `subcalls=N` explicitly only to bound prompt size in a long loop. Set `subcalls=0` explicitly to fully wall off in-frame nodes (rare).

## 4. The role of the docstring vs `content`

These two channels can carry overlapping information, but they have **different responsibilities** — neither replaces the other:

| Channel | Scope | What goes here |
|---|---|---|
| docstring | Whole-function level. Describes what the function as a whole does (it may run preprocessing, several LLM calls, and postprocessing). Read by humans, decision menus, tool_use specs, and meta tooling. | One-line summary required. May also describe in detail what each LLM call does, expected output, edge cases — as much detail as you want, for readers and for context. |
| `llm(prompt)` | One specific LLM call inside the function. Each call is its own request; the function may make several with different prompts. | The actual prompt + data for *this* LLM call: what task, what output format, what constraints, plus the data to operate on. **This must be written even if the docstring already describes it.** |

A function may have a rich docstring explaining "this function classifies sentiment by asking the LLM and normalizing the reply", but the body still needs an explicit `llm(prompt)` containing the actual instruction + data going to the LLM. **Documentation in the docstring does not propagate into the LLM call** — the framework sends the docstring as descriptive context (carried on the DAG node as `metadata.doc` and rendered into the inner call's situation prompt), not as authoritative instruction. Always put the per-call instruction and data in the `llm()` prompt.

Docstring writing rules:

- One-line summary (the first paragraph) is required — that's what decision menus and tool_use specs read.
- The body may be as detailed as is useful for code readers — including describing what each LLM call does.
- Do not write filler ("You are a helpful assistant", "Complete the task").
- A detailed docstring does NOT eliminate the need for explicit `content=[...]` text on each exec call.

`content` writing rules:

- Each item is a dict like `{"type": "text", "text": ...}` or `{"type": "image", "path": ...}`.
- Embed both the instruction *and* the data for this LLM call. Example:
  ```python
  llm([{"type": "text", "text": (
      f"Classify the sentiment of the following text. Reply with exactly one "
      f"word: positive, negative, or neutral.\n\nText:\n{text}"
  )}])
  ```
- Define the exact output format inline; don't rely on the docstring or external context to convey it.

## 5. `input=` vs. docstring `Args:` section

Historically the same parameter description could appear both in the docstring `Args:` section and in `method_options = dict(input={...})`. This spec makes `input=` the source-of-truth.

### Recommended style (required for new code)

Minimal example:

```python
from openprogram import Agent

class ExampleAgent(Agent):
    method_options = {
        'polish': {'tool': True, 'input': {'text': {'description': 'Text to polish.'}, 'style': {'description': 'Output style.', 'options': ['academic', 'casual']}}},
    }

    def polish(self, text: str, style: str) -> str:
        """Polish a text in the given style."""
        ...

_example_agent = ExampleAgent()
polish = _example_agent.polish
```

Fuller example exercising more metadata features (placeholder, multiline, hidden, mixed types):

```python
from openprogram import Agent

class ExampleAgent(Agent):
    method_options = {
        'review_essay': {'tool': True, 'input': {'essay': {'description': 'Essay to review.', 'placeholder': 'Paste the essay text here...', 'multiline': True}, 'rubric_id': {'description': 'Which rubric to apply.', 'options': ['ielts_writing', 'toefl_writing', 'gre_argument']}, 'max_score': {'description': 'Upper bound for the numeric score.'}, 'show_rubric_internals': {'description': 'Include rubric breakdown in the output.'}, 'session_id': {'hidden': True}}},
    }

    def review_essay(self,
        essay: str,
        rubric_id: str,
        max_score: int,
        show_rubric_internals: bool,
        session_id: str,           # filled by Python via context, not LLM
    ) -> dict:
        """Score an essay against a named rubric and return a structured report."""
        ...

_example_agent = ExampleAgent()
review_essay = _example_agent.review_essay
```

The docstring keeps only the one-line summary — **no `Args:` section and no `Returns:` section**. If the meaning of return-value fields matters to downstream LLM-driven calls, encode it with a structured return type (e.g. `TypedDict` or a dataclass) so consumers can introspect it; do not duplicate the schema in a docstring paragraph.

### Legacy style (still supported)

```python
from openprogram import Agent

class ExampleAgent(Agent):
    method_options = {
        'polish': {'tool': True},
    }

    def polish(self, text: str, style: str) -> str:
        """Polish a text in the given style.

        Args:
            text: Text to polish.
            style: Output style.

        Returns:
            Polished text.
        """
        ...

_example_agent = ExampleAgent()
polish = _example_agent.polish
```

Legacy functions still run, but the `Args:` section is dead text — **no docstring-`Args:` parser exists anywhere in the framework** (see §10). `_build_agentic_tool_spec` falls back as follows:

```
fn.input_meta[name]["description"]
    ↓ not found
fn.input_meta[name]["placeholder"]  (rendered as "e.g. {placeholder}")
    ↓ not found
no description; only parameter name + type
```

`render_options` reads only `description` and `options` from `input_meta`; parameters without them get name + type only.

## 6. Plain Python callables (undecorated)

`Agent` method is not required for the decision-menu path: plain callables can be passed to `render_options` (and as `decision.make` / `choices=` options), but they carry less metadata. They can **not** be passed to `runtime.exec(tools=[...])` — `_adapt_tools` raises `TypeError` for anything that is not an `Agent` method, a `{"spec", "execute"}` dict, or an object with `.spec`/`.execute`.

| Field | Decorated | Undecorated |
|---|---|---|
| Parameter description | from `input=` | empty (no docstring fallback exists) |
| Parameter enum | `input={"x": {"options": [...]}}` | none |
| Hidden flag | `input={"x": {"hidden": True}}` | only `_AUTO_PARAMS` names (`runtime`, etc.) are auto-hidden |
| Recorded in session DAG | yes | no |

Use plain callables for: simple decision branches with few parameters, no WebUI surface, and no need for rich menu hints. Upgrade to `Agent` method as soon as you need enums, hidden parameters, or detailed descriptions.

## 7. Auto-injected parameters

The following parameter names are reserved by convention: if a function's signature includes any of them, the framework auto-injects them at call time. The LLM does not see them and does not need to fill them.

| Parameter name | Meaning |
|---|---|
| `runtime` | The current Runtime instance |
| `exec_runtime` | The runtime used for execution (multi-runtime setups) |
| `review_runtime` | The runtime used for review (multi-runtime setups) |

New Agent methods do not declare these parameters: a method runs on its Agent's Runtime (`Agent(runtime=...)`) or the caller's, and nested calls inherit it. Injection remains for existing functions that still declare them.

These names live in two constants in two files: `_RUNTIME_PARAMS` in `agent/call_state.py` (runtime injection + filtering from tool specs) and `_AUTO_PARAMS` in `agent/decision.py` (hiding from decision menus + dispatch). To add a new auto-injected name, edit both. Do not mark them per-callsite via `input={"x": {"hidden": True}}`.

## 8. WebUI rendering behavior

The WebUI does not introspect live Python objects: it AST/regex-parses the source files (`openprogram/interfaces/server/function_catalog.py`). Consequently `input=` must be written as a literal dict in the method configuration call to show up in the form — metadata built dynamically (variables, helper calls) is invisible to the WebUI.

The WebUI form renders each parameter by the following rules (implemented in `apps/web/components/chat/composer/modes/fn-form/fn-form.tsx` and `fn-form-fields.tsx`). When configuring `method_options["method"]["input"]`, use this table to predict what kind of input control your function will produce:

| Parameter trait | WebUI control |
|---|---|
| `bool` type | Yes / No toggle buttons (not a checkbox) |
| `str` type, `multiline` not set | Defaults to a textarea (`multiline=True` is implied) |
| `str` type, `multiline: False` | Single-line `<input>` |
| Non-`str` non-`bool`, `multiline` not set | Single-line `<input>` |
| `options: ["a", "b", ...]` | Clickable chips plus a free-form text input (user can pick a preset OR type a custom value) |
| `options_from: "functions"` | `<select>` dropdown populated from currently-registered non-builtin / non-meta functions |
| `hidden: True` | Omitted from the form entirely |
| Has a Python default and no explicit `placeholder` | the raw default value becomes the placeholder ghost text (no `"default: "` prefix); pressing Tab in the empty field promotes it into the actual value; defaults of `None` or starting with `_` are suppressed |

Parameter `description` renders as a small label next to the parameter name; the type annotation is shown on the same row, and non-required parameters get an "optional" marker (there is no "required" marker).

## 9. Out of scope (deferred for future expansion)

The following fields were discussed and are **intentionally not introduced now**, because no consumer exists yet:

| Field | Intended use | Why deferred |
|---|---|---|
| `effects=["fs", "net", "state"]` | Mark function side effects for permission gating / dangerous-op blocking | A gating surface already exists on the method configuration (`requires_approval`, `check_fn`, `unsafe_in`, `available_if`, `defer`); a declarative `effects=` field on top of it remains future work |
| `permissions=[...]` | Required permission scope before calling | Same as above |
| `idempotent=True` | Whether the function can be safely retried | No auto-retry component exists |
| `latency_hint="long"` | Scheduler hint | No scheduler exists |
| `cost_hint=...` | Quota management | Same as above |

Revisit this section once a real upstream consumer appears.

## 10. Migration path (informational)

The recommended order for migrating existing code to this spec; not strictly required:

1. Add a shared helper `_parse_docstring_args(fn) -> dict[name, description]` in `agent/call_state.py`
2. `_build_agentic_tool_spec` calls this helper as a fallback (currently the spec does not read docstring `Args:` at all)
3. `render_options` calls the same helper for the same fallback
4. Existing All executable entries use ordinary Agent methods and explicit method_options

## 11. Style checklist

When writing a new `Agent` method:

- [ ] First paragraph of the docstring is a one-line summary (state what the function does / when to pick it, directly)
- [ ] No `Args:` or `Returns:` sections in the docstring (unless you specifically want them for debugging / reading)
- [ ] Every LLM-visible parameter has a `description` in `input=`
- [ ] Enum parameters use `options` in `input=` (not buried in the description text)
- [ ] System-filled parameters (DB session, current user, etc.) are marked `hidden: True`
- [ ] No `runtime` parameter: the method runs on its Agent's Runtime
- [ ] The function name is clear (`fn.__name__` is what the LLM sees as the action name)
- [ ] No role-play, no empty directives, no metaphors in the docstring

## 12. References

- `openprogram/runtime/agent/call_state.py` — Agent method execution implementation
- `openprogram/runtime/agent/decision.py` — options-menu rendering, reply parsing, and the next-step decision primitive (`decision.make`, `render_options`, `parse_args`, `DecisionError`)
- `docs/capabilities/agentic-programming/writing-functions/agent.md` — method configuration usage guide
- `docs/reference/design/function/calling-unification.md` — function/tool calling framework
- `docs/capabilities/agentic-programming/choosing-the-next-step/tool-calling.md` — per-turn native tool-use loop mechanics
