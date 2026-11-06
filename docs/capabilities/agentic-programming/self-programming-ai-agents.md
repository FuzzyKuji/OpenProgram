# Self-Programming AI Agents

A self-programming AI agent can create or revise executable workflows while it
works. In OpenProgram, the agent writes a Workflow package in
`~/.openprogram/programs/<name>/` with its normal file tools, runs
`openprogram programs check` to test and commit it, and later turns call its
entries from the same registry as existing tools.

This is narrower than unrestricted self-modification. OpenProgram does not let a
model silently replace the runtime or bypass the check. The editable unit is a
reviewable package with declared entries, explicit tool access per role,
recorded execution, and its own Git history.

## What the agent programs

A Workflow combines deterministic control flow with model decisions:

```python
from openprogram import Agent, Context

reviewer = Agent(instructions="You find concrete defects.", tools=[])
editor = Agent(instructions="You revise drafts.", tools=[])


def review_then_revise(draft: str) -> str:
    """Review a draft, then revise it against the review."""
    ctx = Context({"draft": draft})
    review = reviewer("Identify concrete defects in this draft", context=ctx)
    return editor("Revise the draft using the review",
                  context=ctx.derive({"review": review}))


PROGRAM_ENTRIES = [review_then_revise]
```

The Python body fixes the required order. The two roles handle the semantic
steps, and each sees only the blocks its Context holds. Each role call is
recorded in the session graph.

## How an agent creates one

Install and start OpenProgram:

```bash
curl -fsSL https://openprogram.io/install | sh
openprogram
```

Then ask the agent for a bounded workflow, for example:

```text
Create a Workflow named review_then_revise. It must review a draft, revise it
against the review, return only the final text, and include a behavior test.
```

[Write and check a Workflow](../workflows/authoring.md) defines the package
layout, the rules for roles and Context, the test helper and the check. The
worker loads a checked Workflow without restarting.

## Runtime controls that still apply

- Tool access comes from each role's `tools` and the configured approval policy.
- Each role call and the exact request it sent are recorded in the session
  graph.
- Resource limits, cancellation, structured output validation, and provider
  accounting remain runtime responsibilities.
- Source changes remain ordinary files: they can be inspected, tested and
  reverted, and only a checked, committed version loads.

## When to use it

Use self-programming when a repeated task needs a reusable, inspectable process
but the semantic steps still require model judgment. Use a plain function when
the entire operation is deterministic. Use an existing tool when the operation
already has a stable implementation.

Read the [Agentic Programming guide](README.md),
the [`Agent` method reference](../../reference/api/agent.md), and the
[design rationale](philosophy.md) for the full
execution contract.
