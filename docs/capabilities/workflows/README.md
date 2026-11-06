# Agentic workflows

This page covers agentic workflows: how to install one, how the chat agent writes one for you, and how to manage and trigger them. If you want to use agents directly instead of writing your own functions, start here.

## What they are

An agentic workflow is a finished workflow built with [Agentic Programming](../agentic-programming/README.md) — called a **harness** or **agentic program** in the code: a self-contained git repository holding a set of `Agent` methods. A release bundles none; you install the ones you want with `openprogram programs install`. Installed workflows register into OpenProgram and appear like built-in functions in chat, on the Web UI Programs page, and in `openprogram programs run`.

## Management commands

```bash
openprogram programs list          # every Program: tools, applications, your packages, harnesses
openprogram programs install <owner>/<repo>   # any harness (a git URL or directory also works)
openprogram programs install <ref> --upgrade  # reinstall / upgrade
openprogram programs uninstall <Harness-Name> # set a harness aside
openprogram programs run <name> -a key=value  # run a program directly
```

`programs run` also accepts `--provider` (openai-codex / gemini-cli / anthropic / openai / gemini, auto-detected by default) and `--model` to override the model.

In a mutable environment (a source checkout or a CLI/server installation), `programs install` clones a harness, installs its declared dependencies, and records the approved source. The packaged desktop runtime refuses Program installation.

`openprogram programs list` shows each Workflow in `~/.openprogram/programs` as a `package` row with its entries and load state: `loaded`, `error` (failed to load), or `pending` (not callable yet, for example because it has uncommitted edits).

<div id="self-programming-workflows"></div>

## Workflows the agent writes for you

The chat agent can write reusable Workflows for you. A Workflow is worth writing when a task needs a stable multi-stage structure, repeated use, or reviewable version history. A one-off task that the agent can finish directly does not need one.

There are no special authoring tools. The agent uses its ordinary file tools and the command line:

1. It creates `~/.openprogram/programs/<name>/` as a Git repository and writes the package: roles, functions, `PROGRAM_ENTRIES`, a `README.md` and behavior tests.
2. It runs `openprogram programs check ~/.openprogram/programs/<name>`. The check imports the package, runs its tests in the OS sandbox and commits when they pass.
3. On a failure it reads the report, fixes the package and checks again.

The running worker loads the committed Workflow within a few seconds. Its entries then appear as tools in every chat and on the Programs page, without a restart. Changing a Workflow works the same way: edit the files, check again. Earlier versions stay in the Workflow's Git history.

## How to trigger them

- **Web parameter form**: click **Use** in Programs or a sidebar favorite. A new-tab page becomes a draft chat; an existing chat keeps its draft and running task. Fill in the task requirements and send explicitly. Opening or closing the form does not run the Workflow.
- **In chat**: entry functions register as tools (`as_tool=True`). Describe the task in natural language and the model calls them (e.g. `paper_agent` from an installed `owner/paper-harness`). Operating apps, built-in browser Pages and a VM is the [`computer_use_agent`](../computer-use.md) tool, not a workflow.
- **From the command line**: `openprogram programs run paper_agent -a task="Survey recent work on agent memory"`.
- **From Python**: harness functions are ordinary importable Python functions.

## Model selection

Programs whose bodies do not call a model can execute without a configured model. An unavailable model or credential fails when the body calls the Runtime; it does not prevent model-free steps from running and does not select another provider automatically.

Direct tool runs also need an explicit provider and model for internal model calls. An omitted or incomplete selection does not use global provider detection or a provider's default model.

When run from a chat, internal Workflow model calls inherit the turn's provider and model selection. A per-turn override takes priority over the session selection, followed by the agent profile. The selected provider and model also apply to tool subprocesses. Provider authentication must still be valid for that selected model; setup failures retain the selected model's error instead of silently using another provider.

Browser workflows retain an explicit initial URL when a backend is selected. Official MCP backends support guarded waits and propagate snapshot failures. Page recovery stays within the current window scope and does not replay the failed action. A verified result retains its actual evidence and observed target.

## Writing your own

Any repository that follows the directory contract (`<package>/agentics/__init__.py` exposing `PROGRAM_ENTRIES`) can be installed with the same `programs install` command. See [Installing programs](../installing-programs.md) for the contract, a minimal template, and the publishing flow.

That harness contract is different from a single Workflow package in `~/.openprogram/programs`. For the package form, a complete tested example and the `programs check` command, see [Write and check a Workflow](authoring.md). Workflows the chat agent writes go through the same check. To show the agent a task instead of describing it, [record a workflow](recording.md).

Workflow forms ask for task information, not execution settings. Text polishing infers its style from the text in the same model request; it does not require a style selection. Browser backend and session handles remain internal. Document page ranges and output destinations are optional task requirements. Explicit Python callers retain supported overrides.

## Weekly reports

If `weekly_report` is installed in your Workflow catalog, call it with the report text or the change you want. For example, ask it to submit this week's report, update only next week's plan, inspect the existing record, or prepare a local draft at a named path.

It reads the configured Feishu form and matches the name and year/week before writing. A missing record is submitted once; an existing editable record is opened from the submission history and saved. Partial updates preserve untouched fields. Explicit draft and read-only requests do not submit. Unknown inspection results, login failures and ambiguous records stop the operation. A submission cap does not by itself rule out editing an existing record.

Success requires a fresh page confirmation and persisted values. If a write result is uncertain, the Workflow reports it without automatically retrying. Ordinary browser authorization remains required. It uses bounded browser steps rather than a `goal()` loop, and does not invent progress, metrics or paper titles.

### Group weekly report drafts

`group_weekly_report(task)` autonomously retrieves group scope, report material and author evidence from memory, relevant local files and WeChat, then prepares an unsent draft. Missing fields do not trigger questions. Unknown authors and unavailable sources are listed as limitations. Explicit `source: "supplied"` restricts collection to supplied materials. See [weekly reports](reports.md) for source options.

Inspection of complete structured supplied-only inputs uses code without model calls. Summaries use bounded per-member model contexts, checked source references and explicit uncertainty. Local files are saved under `reports/group-weekly/<week>/<unique-run>/` (or `output_dir`). Missing material is not proof of non-submission. Review the draft and send it yourself.
