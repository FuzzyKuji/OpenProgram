# Read and edit Memory

Open **History → Memory**, then select a topic. Documents and Core source
records open in Preview. Choose **Edit** to change Markdown text. There are no
Save, Saved, or Changes controls.

Each edit is immediately retained in this browser's local draft storage and
queued for automatic file persistence. Writes are serialized so an earlier
response cannot overwrite newer typing. Use Cmd+Z or Ctrl+Z to undo, and
Cmd+Shift+Z, Ctrl+Shift+Z, or Ctrl+Y to redo; automatic saving does not clear
this document's undo history while the app stays open.

File persistence and Git history are separate. Manual edits are grouped into
five-minute checkpoints by the server, with a scheduling tolerance of 15 seconds.
The deadline survives server restart and does not depend on keeping the editor
open. The state before a manual editing interval is retained.

Every other change to Memory is a commit of its own, named for what made it:

- each background write, named for the conversation it came from;
- the reorganizing a write triggers, separate from the write;
- each pass of the nightly reorganization, one per file it splits;
- each `memory_update` the agent makes in a conversation, named for that
  conversation;
- edits made outside OpenProgram, for example in the Memory folder opened in
  another editor. They are committed on their own just before the next write
  installs, so restoring an earlier version of a write never takes them with it.

A write that fails its checks changes neither the files nor the history.

**History** lists revisions from newest to oldest with local date and time.
Select one to inspect the added and removed lines. **Restore this version**
restores that document, first recording the current state, then recording the
restoration as a new commit. Existing history is retained, so restoration can
itself be reversed by selecting another version. Restoration preserves valid
source references and refuses to break links from other Memory documents.

Rejected or conflicting writes retain the draft and show the error. **Review
latest** compares the latest saved text with the draft inside History;
**Replace latest with this draft** explicitly retries against that reviewed
version. A further concurrent change is still rejected.

## When automatic writing stops

Conversations reach Memory through a background writer, and it repairs what
it can before anything is shown:

- If the writer model cannot be used at all (a rejected sign-in, a plan
  without access, a model the provider does not offer, an exhausted usage
  plan), the writer switches to the default agent's model, then to the last
  used model, and keeps writing.
- If its edits fail the format checks, it is sent back to fix them in place,
  up to three times, then redoes the turn once from scratch.
- If a topic file was broken by a hand edit, a repair agent fixes its format
  before any new conversation is written. The repair keeps the file's facts
  and block IDs and has its own entry in the history.

When the last run still failed, a red strip at the top of Memory says why,
when it last wrote, and how many conversation turns are waiting. A failure
that is retried on its own says so and stays in that strip. A failure nothing
will retry also shows a notice once, and again only if the reason changes.
Turns that could not be written are retried; a conversation the writer finds
nothing worth keeping in counts as written.

## Format checks

Every Topic paragraph ends in a footnote that cites the chat message it came
from, as a link to that chat: `[keyword](/s/<session>#<message>)`. Memory keeps
no copy of the conversation; the chat history is the record. A substantive
paragraph without one is rejected with `INVALID_TOPIC_FORMAT` before any write
is installed, and so is a new citation of a message the chat does not hold or
one that is not a person's or the assistant's words, such as a tool result. A
rejected batch commits nothing: no Topic change, derived view or Git history.

The background writer runs the same checks after every file it changes, so it
learns about a broken rule on the edit that broke it and fixes it before its
turn ends. A footnote definition written twice, or one left behind by a
paragraph that was moved or deleted, is removed instead of rejected.

Clicking a footnote shows the cited message with the turns around it, and
**Open original session** jumps to it in the chat. If that session was deleted,
the view says **Original session deleted**; the memory itself remains.
Archiving hides a session, preserves its content and links, and does not
automatically delete it after an age or capacity threshold.

A workspace written before footnotes linked chats directly had a `sources/`
folder holding a copy of each cited conversation. On first use its footnotes
are rewritten to chat links and the folder is removed, in one commit,
`memory: cite chats directly`; Git history keeps the old copy.

Agent-specific memory modes and separate spaces are configured in [Agents](agents.md). This editor manages the existing shared memory store.
