# Tool guides

A tool with many rules keeps a short schema and hands the model the rest of
its instructions when a call needs them. This is the mechanism behind the
single-entry tools (`computer_use_agent`, `self_update`): one tool, a few
parameters, and the instructions of each target or action delivered on first
use.

## Why

Every schema ships in every request. A tool whose schema carries all of its
actions, arguments and policies costs that context in every turn, including
the turns that never use it, and long schemas are read less carefully than a
short one. Splitting a domain into many flat tools moves the cost without
removing it. The alternative, used by Codex for computer use and by Claude
Code for skills, is progressive disclosure: the schema names the entry and
its shape; the instructions arrive with the first call that needs them.

Two things make that reliable instead of hopeful:

- The model is not asked to remember to read anything. A guide either rides
  on the result of the call that needs it, or the call is refused and the
  refusal carries it.
- Delivery follows what the model can see. A guide that left the context
  (compaction, a cleared tool result, a new agent) is delivered again the
  next time a call needs it.

## Declaring guides

`openprogram/programs/_authoring/guides.py`. A tool registers a list of `Guide`s under
its name:

```python
guides.register("self_update", [
    Guide("self_update", overview, mode="open", activates=("worktree_create",)),
    Guide("self_update.prepare", prepare_text, summary="parameters, iteration policy and verification plan",
          required_for=lambda args: args.get("action") == "prepare"),
])
```

| Field | Meaning |
|---|---|
| `name` | Dotted name the model passes to `help`; unique across tools |
| `text` | The guide, or a function returning it (for host-specific text such as the app guide's platform variants, or lists read from code) |
| `mode` | `open`: the first result of the tool carries it. `included`: the first result of a call whose arguments match `when`. `lookup`: listed by name and `summary`, read with `help`. `on_error`: a failed result of a matching call carries it |
| `when(args)` | Which calls an `included` or `on_error` guide applies to; for `lookup`, whether it appears in the index |
| `required_for(args)` | Calls that may not run until the guide is known |
| `activates` | Deferred tools the guide teaches; delivering it loads their schemas, as `tool_search` would |

An `open` or `included` guide ends with the index of the tool's applicable
lookup guides (`help("self_update.retry"): install the repaired candidate
after a rollback`), so a short entry still tells the model where the rest is.

## Delivery

The agent loop does all of it; tools only declare.

1. `_run_loop` opens a view for the loop (`guides.begin_loop`). Outside an
   agent loop there is no view, and guides do nothing: direct Python calls
   and tests see plain results.
2. Before each model request, `_stream_assistant_response` records the text
   of the messages being sent (`guides.observe_request`).
3. A guide is **known** while its marker `<guide name="…">` is in that text,
   or was delivered since that request.
4. When a call ends, `_rewrite_tool_result` puts the guides it is due in
   front of the result (`guides.attach`): an unknown `open` guide, a matching
   unknown `included` guide, a matching `on_error` guide on failure, and the
   required guides of a refused call. Each is wrapped in its marker, so the
   next request holds it and it is known from then on.
5. Before a call runs, `permission_decision` refuses it with
   `GUIDE_REQUIRED` when a `required_for` guide is unknown. The refusal is
   automatic (it is not a failure that counts towards repeated-failure
   handling, and no approval card is shown), and step 4 attaches the missing
   guide to it. The model reads it and calls again.

Reading knowledge from the request rather than keeping a ledger is what makes
re-delivery free: compaction summarizes the old result away, microcompaction
replaces it with a placeholder, a worker restart loses memory, a fresh agent
starts with its own prompt, and in each case the marker is gone and the next
call that needs the guide receives it. A fresh agent whose prompt already
holds the marked guides (`computer_use_agent` with `context="fresh"`) is not
sent them again.

## `help`

`help(name)` is a resident tool (`openprogram/programs/tools/runtime/help.py`)
that returns a guide by name, or a tool's opening guide when given a tool
name, marked like any delivered guide. It needs no approval and is
`runtime.control` authority. An unknown name lists the guides that exist.

Inside `computer_use_agent` code, Python's own `help` and `dir` work on the
`cu` objects: each method's docstring is its action's line from the target
guide.

## Single entries built on it

| Tool | Guides |
|---|---|
| `self_update` | `self_update` (open: the workflow; activates `worktree_create`), `self_update.prepare` and `self_update.retry` (lookup, required for that action) |
| `computer_use_agent` | `computer_use_agent.app` / `.browser` / `.vm` (included when a call operates that target), `computer_use_agent.code` (lookup, required by `code`) |

A single entry keeps two levels: the tool, then an `action` (or `target`).
Permission, authority and approval decide per action: for `self_update`,
`status` reads (`fs.read`, no approval), `cancel` is `runtime.control`, and
`prepare` and `retry` always ask for one-shot owner approval
(`policy._self_update_install`).

What can be checked from the arguments alone is checked before the approval
card (`openprogram/programs/_authoring/prechecks.py`, called by `permission_decision`
after the guide check): a `prepare` with a malformed SHA, or an iteration
policy or verification plan out of bounds, is refused with
`INVALID_ARGUMENTS`, so the owner never approves a call that cannot run.

## Choosing a mode

- Instructions every use needs: `open`.
- Instructions for one variant (a target, a platform): `included` with
  `when`.
- Instructions for an action whose mistakes are costly or whose arguments are
  long: `lookup` with `required_for`.
- Background that only some situations need: `lookup` without
  `required_for`; the index names it.
- Recovery advice: `on_error`.

## Implementation files

- `openprogram/programs/_authoring/guides.py`
- `openprogram/programs/tools/runtime/help.py`
- `openprogram/programs/_authoring/prechecks.py`
- `openprogram/runtime/agent/loop/` (`_run_loop`, `_stream_assistant_response`, `_rewrite_tool_result`)
- `openprogram/runtime/permissions/policy.py` (`permission_decision`)
- `openprogram/programs/tools/system/self_update/__init__.py`
- `openprogram/programs/tools/computer_use/computer_use_agent/tool.py`, `code.py`
- Tests: `tests/unit/programs/test_guides.py`, `tests/unit/programs/test_prechecks.py`
