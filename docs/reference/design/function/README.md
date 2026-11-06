# Function Design

Internal design notes for the function/tool-calling framework.

**Writing functions?** The authoring-facing docs (usage patterns, metadata
rules, the three "choose the next step" mechanisms, pure-python helpers)
moved to the user guide:
[`docs/agentic-programming/`](../../../capabilities/agentic-programming/README.md).

## Current sources

| Topic | Source |
|---|---|
| Program model: tools and applications, `ProgramContext` as the one registration interface, what a plugin is, exposure tiers, the user directory and CLI | [`program-model.md`](program-model.md) |
| Function/tool calling framework (`@function` / `Agent` method, shared registry, gating, deferred loading) | [`calling-unification.md`](calling-unification.md) |
| Tool guides: instructions a tool hands the model when a call needs them, required reading, re-delivery after compaction, the `help` tool, single-entry tools | [`tool-guides.md`](tool-guides.md) |
| Agentic program: tools, skills and agentic functions as one concept on one continuum, how to pick which shape to write, whether the two decorators should merge, what the model should see | [`agentic-program.html`](agentic-program.html) |
| Decorator usage, metadata spec, the tool-call loop, pure-python helpers | product pages under [`capabilities/agentic-programming/`](../../../capabilities/agentic-programming/README.md) — these are the single home; the former design duplicates here were deleted |

## Implementation files

- `openprogram/runtime/agent/call_state.py`
- `openprogram/runtime/agent/runtime.py`
- `openprogram/runtime/agent/decision.py`
- `openprogram/programs/tools/<name>/`
