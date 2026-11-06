# Configure an Agent

Open **Agents** in the sidebar. An Agent saves a reusable configuration: model, instructions, available capabilities, memory access and channel conversation settings. It does not have to represent a specialized task.

The page opens on a card for every Agent, showing its [avatar](#avatar), model, reasoning effort, programs and whether it is always on. Search the cards by name, ID or description. Choose **New Agent**, enter a name and choose a model; the internal ID is generated automatically.

Choosing a card opens its quick settings beside the cards: name, description, model, reasoning effort and Always-on, plus **Try draft** and **New conversation**. **Open full settings** (or **Manage** next to the capabilities) moves the cards into a list on the left and opens the full editor. Its header shows the same summary as chips; each chip opens its section. **All Agents** at the top of the list returns to the cards.

| Section | What it changes |
| --- | --- |
| General | Display name, description, [avatar](#avatar), provider, model and reasoning effort |
| Programs | Automatic tool availability, selected programs or no programs |
| Skills | Available skills and exclusions |
| MCP | Allowed, excluded and required servers |
| Memory | Off, read only or read and write; readable and writable spaces |
| Context | Channel conversation isolation, idle reset and daily reset |
| Always-on | Wake on a schedule to work on a standing goal and report findings ([Always-on Agents](always-on-agents.md)) |
| Advanced | Channel identity, mention patterns, optional instructions, and which [AGENTS.md](agents-md.md) files apply |

Changes across sections share one draft. **Save** writes the complete configuration. Changing Agents or starting a destructive action offers Save, Discard or Cancel. Failed saves retain the draft. If another editor saved first, compare your draft with the latest version before choosing which to keep. Keeping your draft does not immediately overwrite the newer version; review it and save again.

The model picker reads the provider catalog without changing another conversation's model. Last used model runs each conversation on the model you used most recently. An unavailable model or unsupported reasoning effort remains visible until you explicitly change it. Missing required MCP servers prevent execution before a model request.

## Avatar

Every Agent has an avatar. It stands beside the Agent's name wherever the Agent appears: its card and editor on this page, the Agent chip in the composer and the menu it opens, the name above a reply from an Agent other than the default one, the Always-on row of the [Activity panel](../interfaces/web.md#conversation-activity), and channel bindings in Settings.

An Agent you have not given an avatar shows a character chosen from its ID: a coloured shape with two eyes. The same ID always gets the same character, and each built-in Agent has one that fits its job. To choose another, open **General** in the full editor and use **Avatar**:

| Type | What you choose |
| --- | --- |
| Character | One of 22 shapes and one of 8 colours |
| Generated | A generated picture: pick a style, then a variant |
| Upload | An image file up to 256 KB (PNG, JPG, SVG, WebP or GIF; animated files play) |

The avatar is part of the Agent's draft, so it is saved with **Save** like every other setting, and a duplicate keeps it.

A character is alive wherever it stands for an Agent: it blinks, sways and looks around on its own, and in the Activity panel it looks busy while the Agent is working. The shape tiles of the avatar picker are still pictures. When the system setting for reduced motion is on, every character is still.

## Built-in Agents

Every instance comes with a set of built-in Agents, the way Grok Bot comes with bot templates: each is a complete configuration for one kind of work, saved as an ordinary Agent card. The server installs the ones this instance has never had when it starts, and from then on each is yours: open its card to start a conversation, edit, duplicate or delete it. Nothing recreates a deleted one.

Three of them are fixed-parameter configurations of the Agent class without a prompt of their own; the task comes from the call and its Context:

| Agent | Purpose | Capabilities |
| --- | --- | --- |
| Decision | Select one of the supplied options with `Agent.choose()` | One model turn, no tools or automatic re-pick |
| Lightweight helper | Extract, classify, format, summarize, or predict candidate next messages when asked | No tools |
| Coordinator | Plan dependencies, delegate authorized tasks and check results | Read/search and Agent coordination tools |

Choose a low-cost model for the lightweight helper and a strong reasoning model for the coordinator in General. Their names do not guarantee price or quality. Predicted messages are suggestions rather than authorization; a planning-only request does not authorize delegated execution. These three start with memory, Skills and MCP disabled.

The others each do one job. Each has a system prompt that states the job, the deliverable, what it never does, when it is done, how it works and its first task; the tools that job needs and nothing more; a memory policy on its own space; and always-on defaults. Always-on starts off for all of them; turn it on in the Always-on tab once the Agent has a conversation to work in.

| Agent | Job | Tools | Memory | Wakes to look around |
| --- | --- | --- | --- | --- |
| Chief of Staff | Keeps open work moving, routes tasks to other Agents, reports | Read, web, conversations, open work, handoff, reminders, Goals | Read and write | Every 2 hours |
| Spec Writer | Turns a request into a specification with acceptance criteria | Read, web, conversations, write files | Read only | No |
| Bug Reproducer | Finds the smallest failing case and pins it as a failing test | Read, shell, code navigation, worktrees | Off | No |
| PR Producer | Implements a specified change with tests in a worktree | Read, shell, edit, worktrees | Off | No |
| PR Verifier | Checks a change against its specification and tests; never edits | Read, shell, code navigation | Off | No |
| Research Desk | Follows topics, reads sources, keeps a cited brief | Web, PDF, write files, reminders | Read and write | Every 4 hours |
| Inbox Triage | Sorts new messages and drafts replies; nothing is sent | Read, conversations, write files, reminders | Read and write | Every 30 minutes |
| Career Scout | Scans job boards, ranks matches, prepares applications | Web, browser, PDF, write files | Read and write | Twice a day |
| Knowledge Keeper | Distils finished conversations into memory, merges and corrects | Read, conversations, edit files | Read and write | Daily |
| Writer | Turns material into finished text in the requested form | Read, web, edit files, canvas, images | Read only | No |

Producer and verifier are separate Agents on purpose: the Agent that wrote a change never passes it. Agents that handle mail or posts stop at a draft; outgoing sends wait for your approval in every permission mode. They work together through [handoffs between conversations](always-on-agents.md#hand-work-to-another-conversation): open one conversation per Agent, give each a clear title, and tell the Chief of Staff (or whichever conversation plans) which conversation does what.

Python can call a saved Agent directly:

```python
from openprogram import Agent
from openprogram.runtime.agent_registry import manager

helper = Agent.from_spec(manager.get("utility"))
result = helper("Extract the city from: the event is in Singapore.")
```

For a single selection, supply option IDs and labels. The return value is the selected ID:

```python
selector = Agent.from_spec(manager.get("decision"))
selected = selector.choose("Classify this message.", {"A": "Question", "B": "Statement"})
```

`choose()` uses the current Context and DAG, disables tools and web search, and does not request a second selection if the answer is invalid. Invalid answers raise `DecisionError`. Model and reasoning settings are caller configuration; this entry does not add a reasoning or advice workflow. Ordinary `__call__()` remains available for normal model responses.

`create_builtin_agents()` in `openprogram.runtime.agent_registry.builtin_agents` is the installation: it creates the built-ins this instance has never installed and leaves every existing record, edits included, as it is. The server runs it at startup once a default Agent exists, and setup runs it when it creates Main. Registry reads never install Agents.

## Start a conversation or try a draft

**New conversation** uses the saved Agent configuration. **Try draft** opens an independent chat with the current draft. It does not save the Agent. The first message records that trial's configuration snapshot; subsequent messages and resumed execution retain it. Trials never write long-term memory: a saved or draft Off setting stays Off; other trials are read only.

### Change a conversation's Agent

The Agent chip in the composer's bottom row, next to the model, names the Agent the conversation uses. Choose it to pick another saved Agent; Agents that are [always on](always-on-agents.md) are marked **Always-on**. In an unsent chat, the pick applies from the first message. In a started conversation, it switches right away, except while a turn is running: later turns use the new Agent's instructions, capabilities and memory, and the conversation moves to that Agent's model when the Agent sets one. Earlier messages stay as they are. **Manage Agents** at the bottom of the menu opens this page, where the Agent's settings are changed.

Multiple unsent conversations retain their own Agent selection and overrides. Sending one does not use another tab's Agent. A rejected first message preserves the selection for retry. Changing the model in an unsent Agent conversation applies only to that conversation.

Saved instructions, capability settings and memory settings apply to subsequent executions using that Agent. Existing conversations keep the model selected when they started, or when their Agent was last switched, and any explicit reasoning choice. When reasoning effort is unset, they use the current Agent default. Explicit conversation overrides remain in effect. Trial conversations keep their snapshot. Context reset settings govern channel conversations; new chats and trials start with new history.

## Memory access

New Agents start with memory Off. Existing configurations without a memory field retain access to the legacy shared memory. **This Agent** stores memory separately for that Agent; **Shared legacy memory** refers to the pre-existing profile-wide store. A read-and-write configuration must include its write destination in its readable spaces.

Off prevents framework memory reads and writes. Read only allows reads without extraction or new records. Background extraction and derived results preserve recorded write restrictions, so turning memory back on does not ingest earlier restricted turns. Turning memory off or deleting an Agent configuration does not delete its already stored memory. These settings govern the framework's memory operations; filesystem tool access follows its own permissions.

If **Require memory to be available** is enabled, unavailable memory prevents execution. Otherwise the execution continues without memory and records the degradation. The [Memory page](memory.md) describes editing the existing shared store; it is not a browser for each Agent's separate memory space.

## Open work

Each conversation keeps a list of open work: what the Agent still owes you there after the task at hand is done, such as a reply it is waiting on, a check it promised or a draft you have not answered. The open items are part of the Agent's instructions on every turn in that conversation, and its [Activity panel](../interfaces/web.md#conversation-activity) lists them. The Agent adds and finishes items with the `open_work` tool; ask it in chat to add, change or drop one, or mark one done in the Activity panel. Finished items stay in the list's history (the latest 50) and leave the instructions. What another conversation should know belongs in [memory](memory.md).

Open work is not the [task list](../interfaces/web.md#task-list): that plans the steps of the task in front of the Agent and ends with it.

## Duplicate and delete

Duplicate copies the configuration, with a new ID. It does not copy conversations or private memory. A `self` memory reference resolves to the new Agent's separate space; an explicit legacy shared reference still points to the shared store. The default Agent cannot be deleted until another Agent is made default.
