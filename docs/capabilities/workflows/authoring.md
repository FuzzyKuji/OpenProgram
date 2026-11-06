# Write and check a Workflow

A Workflow is a small Python package. `Agent` instances define the roles, `Context` objects define what each model call sees, and plain functions decide the order of the calls. The chat agent writes Workflows with its ordinary file tools; you can write them by hand in the same form, or [record a demonstration](recording.md) for the agent to turn into one. Once a package passes `openprogram programs check`, its entries are callable tools.

## Define the contract before writing code

Record the following in the package's `README.md`:

| Item | Required information |
| --- | --- |
| Purpose | The concrete task and the evidence needed to complete it |
| Input | The entry parameters, required context, and invalid-input behavior |
| Output | Return type, files produced, and how success is verified |
| Effects | Model, tool, file, network, and external-submission behavior |
| Failure and cancellation | What remains after a failed or interrupted run; whether retry is safe |
| Dependencies | Imported Workflows, required tools and services |
| Tests | Behavior checks, scripted model replies, and any separate live checks |
| Usage | One reproducible invocation and the expected result |

Keep each function small. Handle expected invalid input explicitly and let runtime cancellation propagate.

## Package layout

User Workflows live in `~/.openprogram/programs/<name>/`. The directory name is the package name: a lowercase Python identifier that is not a standard-library module or another importable package. Each Workflow is its own Git repository.

```text
~/.openprogram/programs/project_report/
├── .git/
├── README.md
├── __init__.py
├── workflow.py
├── steps/
│   └── prepare.py
└── tests/
    └── test_workflow.py
```

The package imports under its own name (`project_report`, `project_report.steps.prepare`). Relative imports inside the package and ordinary imports of other Workflows both work.

## Roles, Context and functions

A package has three kinds of objects:

- **Roles** are `Agent` instances created at module top level. A role holds configuration only: `model`, `instructions`, `tools`, `effort`. A role without a model uses the caller's model.
- **Context** objects are built inside functions and passed to role calls explicitly.
- **Functions** are plain Python functions. They call roles, transform values, branch, loop and call other functions.

```python
"""Prepare a project report from verified notes."""

from openprogram import Agent, Context

writer = Agent(instructions="You write project reports.")
reviewer = Agent(instructions="You check facts.", tools=[])


def project_report(notes: str) -> str:
    """Turn this week's project notes into a report."""
    ctx = Context({"notes": notes})
    draft = write_draft(ctx)
    return check(draft, ctx)


def write_draft(ctx: Context) -> str:
    """Write three sections: progress, problems, plans. At most three items each."""
    return writer("Write this week's report", context=ctx)


def check(draft: str, ctx: Context) -> str:
    """Only check that the draft matches the notes. Do not change the style."""
    return reviewer("Fix any mismatch and return the final text",
                    context=ctx.derive({"draft": draft}))


PROGRAM_ENTRIES = [project_report]
```

Rules:

- Model calls go through roles only. `role(prompt, context=ctx)` runs one model turn with the role's tools; `role.choose(prompt, {id: label}, context=ctx)` returns one of the option IDs. Workflow code does not call the free `llm()` or `agent()` functions.
- `PROGRAM_ENTRIES` lists the functions exposed as tools. Every entry needs a docstring, which becomes the tool description, and a type annotation on every parameter, which becomes the tool schema.
- No decorators, base classes or dispatch tables. One Workflow uses another through a normal Python import.

## What one model call sees

A call `role(prompt, context=ctx)` sends exactly these parts:

| Part | Defined by |
|---|---|
| The role's `instructions`, as the system prompt | The `Agent(...)` instance |
| History, empty by default, as earlier messages | The `history` setting of `ctx` |
| The docstring of the Workflow function that made the call | That function |
| The named blocks of `ctx`, each as `name:` followed by its value | The code that builds or derives `ctx` |
| `prompt` | The call |

Nothing else enters the request: no chat history, no recalled memory, no outputs of other roles, unless the code puts them into `ctx` or `prompt`. Context never changes tools or permissions; tools belong to the role.

The docstring is found by walking the call stack to the nearest function defined in the Workflow package. It applies to that one request only. A function without a docstring adds nothing, so helpers that only transform data can stay undocumented.

### Context

- **Blocks:** `Context({"notes": notes})` or `ctx["notes"] = notes`.
- **Computed blocks:** `Context(providers={"today": lambda c: ...})`. A provider is a synchronous callable evaluated at each call.
- **Derivation:** `ctx.derive({...})` returns an independent copy, so a function can add or remove blocks without changing the caller's `ctx`.
- **History:** `Context(..., history=...)` or `ctx.derive(history=...)`:
  - `None`: no history (the default for a role call);
  - `"thread"`: the earlier calls made with this same `ctx` object, for multi-turn work by one role;
  - `"chat"`: the conversation that invoked the Workflow;
  - a callable `(node, context) -> bool` that selects conversation nodes.

To let a model see where its call sits in the program, add the built-in providers from `openprogram.runtime.context`:

```python
from openprogram.runtime.context import call_path, workflow_source

ctx = Context(providers={"call path": call_path, "program": workflow_source})
```

`call_path` lists the Workflow functions on the stack (for example `project_report → check`; `call_path(docs=True)` adds each docstring), and `workflow_source` returns the entry function's source. A plain block such as `{"flow": "Draft first, then review."}` works too.

### Entry options

An optional `ENTRY_OPTIONS` dict maps an entry name to tool options, such as a form description for each parameter:

```python
ENTRY_OPTIONS = {
    "project_report": {
        "input": {"notes": {"description": "This week's notes", "multiline": True}},
    },
}
```

`"run_in_worker": True` runs the tool in the worker process instead of a forked subprocess, for entries that use worker-owned state such as browser sessions.

### Resume after a restart

Set `"resumable": True` on an entry to let a run continue after a worker restart or a pause. Inside a resumable entry, wrap each piece of work in `step(name, fn, *args)`:

```python
from openprogram.runtime.agent.durable_steps import step


def project_report(notes: str) -> str:
    """Turn this week's project notes into a report."""
    draft = step("draft", write_draft, notes)
    return step("check", check, notes, draft)


ENTRY_OPTIONS = {"project_report": {"resumable": True}}
```

- A step runs once and its result is saved. When the run continues, the entry runs again from the top; a completed step returns its saved result without running, so its role calls are not repeated.
- Code outside steps runs again. Keep it deterministic and free of side effects, and keep step names and order stable.
- Step arguments and results must be JSON values. A `Context` does not survive a restart; build it inside the step that uses it.
- A run interrupted by a worker restart continues automatically within the `execution.auto_resume_window_seconds` window; a paused run continues from the chat.
- A run is tied to the Workflow's commit. If the Workflow changed in the meantime, `execution.code_change_policy` decides: `keep_original` (the default) stops the run with "Workflow code changed", and `use_latest` continues with the new code. With the new code, a removed or reordered completed step also stops the run.
- A resumable entry must be synchronous and cannot use `run_in_worker`.

## The Workflow owns execution parameters

Users describe the task, its evidence and the deliverable. They do not configure model IDs, reasoning effort, iteration counts, timeouts, token budgets or retry counts, and the Workflow does not ask for them. Fixed values belong on the role (`Agent(model=..., effort=...)`) or in code.

When internal parameters depend on the task, make one role call before the work to produce the complete parameter plan, validate it in code (required keys, types, ranges, relationships between limits), and fall back to a complete validated default when planning fails. Explicit user constraints and application limits always win over model output. A resumable Workflow checkpoints the plan and reuses it on resume.

## Write behavior tests

`openprogram.programs._authoring.testing.script_roles` answers each role's calls with scripted replies and records every request, built by the same code path a real call uses:

```python
from openprogram.programs._authoring.testing import script_roles

from project_report import workflow as wf


def test_reviewer_sees_the_draft_but_not_the_writer_prompt():
    with script_roles({wf.writer: ["Draft"], wf.reviewer: ["Final"]}) as calls:
        assert wf.project_report("Shipped the parser.") == "Final"

    request = calls[wf.reviewer][0]
    assert "Do not change the style" in request.text      # check() docstring
    assert "Draft" in request.text                        # the draft block
    assert "Write this week's report" not in request.text
    assert request.history_text == ""
```

- A reply may be a string or any JSON-serializable value, for calls with a `response_format`. A reply to `role.choose` is the option ID.
- An exception in the script is raised by the call. It stays queued, so it also answers the model loop's retries.
- `request.text` holds the instructions, docstring, blocks and prompt; `request.history_text` holds the history.

Patch tools, files and services with `monkeypatch` as usual. Keep live provider checks out of `tests/`; they cannot run during a check.

## Check, commit and list

```bash
openprogram programs check ~/.openprogram/programs/project_report
openprogram programs check ~/.openprogram/programs/project_report -m "Tighten the review step"
openprogram programs list
```

`check`:

1. imports the package in a separate process and validates `PROGRAM_ENTRIES` and the entry signatures;
2. runs `tests/` with pytest, inside the OS sandbox when one is available: no network, the package directory is read-only, and `HOME` is an empty temporary directory;
3. commits the change to the Workflow's Git repository when everything passes. `-m` sets the commit message; `--json` prints the full report.

Only a committed, clean package loads. A package with uncommitted edits keeps serving the version that loaded last, so a passing check is what makes a change callable. History and rollback use Git.

The worker watches `~/.openprogram/programs` and reloads a Workflow within a few seconds of a change; no restart is needed. `programs list` shows each Workflow as a `package` row with its state: `loaded`, `error` (with the error), or `pending` (with the reason, such as uncommitted changes). The Programs page shows the same states next to each Workflow.

## Running a Workflow

- **In chat:** each entry is a tool. Describe the task and the agent calls it.
- **Programs page:** open **Abilities → Programs**, select the Workflow under **Applications** and click **Use** to open its parameter form in chat. Nothing runs until you send the form.
- **Command line:** `openprogram programs run <entry> -a key=value`.
- **Python:** entries are ordinary importable functions.

Each entry call is recorded in the session graph with one child node per role call, holding the exact request the model received. Plain functions are not recorded.
