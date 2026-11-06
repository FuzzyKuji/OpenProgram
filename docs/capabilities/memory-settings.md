# Tune Memory

Open **Settings → Memory**. Every change saves as soon as you make it and takes
effect on the next turn; only **Enable Memory** needs a restart. The same
settings are config keys, listed under `memory.*` in
[Configuration keys](../reference/config-keys.md).

## Background writing

| Setting | What it does |
|---|---|
| **Writer model** | The model that writes and organizes Memory. **Automatic** uses the default Agent's model, or the last used model when that Agent has none. |
| **Automatic writing** | Turns finished conversation into Topic records in the background. |
| **Write frequency** | How much conversation, about 8K, 16K or 32K tokens, gathers before a write. |
| **Verify after writing** | After each write, asks a question about one fact it just recorded, looks the answer up in a copy of Memory, and repairs the Topics when it is not found. Off by default: each write costs at least three more model calls, and a repair three more. |

`openprogram memory status` shows the result of the checks under
`verification`: how many passed, were repaired, stayed unrepaired, or ended in
an error, and the latest one.

## Recall

| Setting | What it does |
|---|---|
| **Recall method** | **Agent** adds nothing automatically and lets the model read Memory with its tools. **Keyword** ranks by BM25. **Semantic** ranks by embeddings. **Hybrid** runs both and merges them. Semantic and Hybrid need the embedding model. |
| **Hybrid weighting** | How Hybrid balances keyword and semantic matches: **Keyword first** (70 / 30), **Balanced** (50 / 50) or **Semantic first** (30 / 70). **Automatic** leans on keywords when a message contains a date, a quoted phrase or a name, and balances them otherwise. |
| **Favour well-matched Topics** | In Hybrid, ranks a Topic higher when several of its paragraphs match. On by default. |
| **Recall depth** | The most records added to a turn: 3, 5, 8 or 10. |

Hybrid weighting and Favour well-matched Topics apply only when the recall
method is Hybrid.

Semantic and Hybrid need the embedding model and the packages that run it,
sentence-transformers and PyTorch. The App does not include those packages, so
**Install** next to **Embedding model** downloads them together with the model.
The packages take about 1 GB of disk and the model about 90 MB. The packages go
into `~/.openprogram/extras/embedding/`, not into the App, so an App update
keeps them.

## Project memory

A conversation in a project can keep what belongs to that project apart from
what holds everywhere.

| Setting | What it does |
|---|---|
| **Project memory** | A conversation in a project also reads that project's own Memory, kept in `~/.openprogram/projects/<project>/memory`. Recall, the Memory tools and Core Memory then cover both, the project first. On by default. |
| **Write to project memory** | Writes what a project's conversations record into that project's Memory instead of your personal one. Needs Project memory on. On by default. |

Conversations outside a project belong to the home project and read your
personal Memory only; that personal Memory is the home project's, at
`~/.openprogram/projects/default/memory`. A project's Memory counts once
something is written to it. Nothing is written into the project's
own folder. History shows each project's Memory under its Memory tab. With both layers in play, the Memory tools
name the layer in every path, such as `project:topics/api.md`. A turn is
written to one layer only, so switching project writes on or off never copies
a conversation into the other, and a chat moved to another project writes
only its later turns to that project's Memory; what the old project's Memory
already holds stays there.

## Context and history

| Setting | What it does |
|---|---|
| **Core Memory in every chat** | Adds the compact Core view to every system prompt. |
| **Recent view size** | How many latest records the Recent view keeps. |

To read and edit what Memory holds, see [Read and edit Memory](memory.md).
