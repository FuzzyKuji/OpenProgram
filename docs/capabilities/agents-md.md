# Instructions with AGENTS.md

Write standing instructions for agents in files named `AGENTS.md`. Every Agent reads them; there is no per-Agent copy. To give one Agent instructions of its own, use **System prompt** on its **Advanced** tab ([Configure an Agent](agents.md)).

## Where the files go

| File | Applies to |
| --- | --- |
| `~/.openprogram/AGENTS.md` | Every project |
| `AGENTS.md` at a project root (the folder holding `.git`) | That project |
| `AGENTS.md` in any folder below it | That folder and everything below it |

At the start of a turn the agent reads the global file, then every `AGENTS.md` from the project root down to the working directory, in that order. A folder above the project root is never read. Without a `.git` folder, only the working directory's own `AGENTS.md` is read.

A file deeper than the working directory, or in another project, is read the first time the agent reads, writes or edits a file in that folder. Its text is attached to that tool result once per conversation.

The working directory is the conversation's project folder or worktree, otherwise the default working directory (`OPENPROGRAM_WORKDIR`, or `default_workdir` in `~/.openprogram/config.json`).

## How conflicts resolve

Files are concatenated with the most general first. A file closer to the files being worked on comes later and wins on a conflict, so a folder's `AGENTS.md` can narrow or override the project root's.

## Limits

The global and project files share a 32 KB budget per turn. When the total is larger, the deepest files are cut off and the cut is marked in the prompt. A file containing text that looks like a prompt injection is still included, with a warning in front of it.

## See which files apply

**Agents → Advanced → AGENTS.md** shows the working directory, the global file's path (even before you create it), and every project file the next turn reads. Use **Copy path** to open one in your editor.

## Earlier workspace files

Agents used to have their own `AGENTS.md`, `SOUL.md`, `USER.md` and `TOOLS.md` under `~/.openprogram/agents/<id>/workspace/`. These are no longer read. When the worker starts, an unedited template is deleted; an edited file is appended to that Agent's system prompt under a `## From workspace <file>` heading and moved to `workspace/.retired/`.
