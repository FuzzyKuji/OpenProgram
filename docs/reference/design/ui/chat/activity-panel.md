# Activity panel

The right sidebar's **Activity** lists one conversation's main agent
(the sub-agents it starts are on its page), separately the programs and
commands they run in a shell, and then what the conversation keeps doing
on its own: its always-on wakes, its open work and the Scheduler tasks
set from it. What waits for the reader is never a group
of its own: it is the row it concerns, with a red count on its glyph's
corner, like an app's badge in the Dock. Statuses use the common words:
Running, Completed, Failed, Cancelled, Interrupted, Waiting for your
answer, Waiting for approval; a row at rest shows only its time.
Messages are never rows; they stay in the chat.

Related: [`indicator-dots.md`](../visual-system/indicator-dots.md) (status dots),
[`sub-agent-row.md`](sub-agent-row.md) (a sub-agent's own conversation).
Code: `apps/web/components/right-sidebar/running/running-panel.tsx`,
`apps/web/components/right-sidebar/agents-view-menu.tsx`,
`apps/web/lib/execution/activity-model.ts`, `apps/web/lib/prefs/activity-view.ts`,
`openprogram/runtime/execution/activity_calls.py`, `apps/web/lib/chat/conversation-work.ts`,
`openprogram/interfaces/server/routes/execution/conversation_work.py`.

## Branches, runs and waits

A **sub-agent** is an execution whose display kind is `job_agent`. Every
execution belongs to one **branch**: a sub-agent runs its own branch and
every execution under it that no deeper sub-agent owns; everything else is
the **main agent**. A sub-agent hangs under the nearest sub-agent
above it, or under the main agent.

Underneath, executions form **runs**: one top-level execution, normally one
message and everything done for it. Child executions, function calls that
have not returned, and managed programs belong to the run whose execution
tree holds them. A run has a page (reached from the main agent's
latest run, a sub-agent's **From**, or a message waiting on a question) but
no row of its own.

An `agent` call that has returned is paired with the sub-agent it started.
The server reads these calls from the transcripts: a Job records the reply
that spawned it (`spawn_caller`) and its prompt, and the call with the same
caller and prompt started it; calls that did not fail pair first, since a
failed call may share its prompt with the retry. When the prompts do not
line up, a caller left with one Job and one call that did not fail pairs
those. A call paired with no Job **failed to start** (its result is
`[agent error] …` or its outcome is `failed`) or did not start. The
transcript row's caller names the branch that made the call: a `j_…` reply
is a sub-agent's, anything else the main agent's. Effects are not
read for this: their metadata carries whole provider payloads.

Only a run paused on a question or an approval **waits for the reader**
(the model's `issues` filtered to paused executions). A call or run cut
short by a restart reads as **Interrupted** and a program whose
supervisor is gone as **Status unknown**: both are history in the muted
tone, with nothing to do about them.

An execution whose only missing records are model responses
(`provider_response_incomplete`) reads as ended.

## Overview

Five groups in a fixed order; an empty group is not shown and no header
carries a count. Each header is the sidebar's `SectionHeader`: hovering the
group shows its chevron, and clicking the header folds the group to it.
Which groups are folded is a view preference kept in this browser with the
Agents view (`lib/prefs/activity-view.ts`).

1. **Agents**: the main agent alone (the conversation's own agent, named
   and drawn like the sub-agents). It reads as running (with the call it
   is on, or "Waiting for a sub-agent", and the time so far, in blue),
   "Failed · <time>" (red), or otherwise just the time of its last
   message, followed by how many sub-agents the model started ("Oct 15 ·
   5 sub-agents"). What waits for the reader, its own runs and its
   sub-agents', is the red count on the ghost. The sub-agents themselves are listed on the
   main agent's page, so the overview stays one row however many the
   model starts. Calls and programs whose execution is not listed count as
   the main agent's.

   When the conversation has more than one branch (forks and edits the
   reader made in the DAG), each branch is a main agent of its own, one
   row each, all equal: the branch's name, a ghost in its lane colour, a
   **Current** tag on the checked-out one, and the same status and
   sub-agent line computed from the runs on that branch (the server's
   `branches[].execution_ids`; a sub-agent belongs to the branch of its
   top-level run). Unlisted calls and programs, and calls that started no
   sub-agent, count as the checked-out branch's. A branch's page is the
   main agent's page for that branch, titled **Branch**, with **Switch to
   this branch** (the Branches panel's checkout) when it is not the
   current one. A branch with no run listed shows the branch's own time.
   Sub-agents' own conversations are not branches here: an older session
   keeps a sub-agent's turns inline, and their tip, whose chain starts
   at a spawn root, comes marked `sub_agent` in the server's branch rows
   (`build_branches_payload`) and is left out.
2. **Programs and commands**: shell calls still running, shell calls cut
   short when their run was interrupted ("Command · Interrupted ·
   Yesterday", muted), and every background program. Running rows first,
   then the rest, newest first within each, 20 at a time. A command's status names
   its kind ("Command · Running · 12 s"). A program is titled by what it
   does (the bash call's `description`, else the script or module it runs,
   past setup steps such as `cd` and `mkdir`), with its command in
   monospace under the title. While it runs, the status line is its
   progress ("45 / 100 samples · 3.4/s") over a thin bar with the time
   left at its end ("16s left"), or, with no amount known, how long it has run and its last output
   line over a sweeping bar. Once it ends the status says how ("Completed ·
   10 / 10 epochs · 4 min 5 s", "Failed at 62 / 200 · exit 1").
   A program's record and its output stay for a day after it ends
   (`RETENTION_SECONDS` in `openprogram/host/processes/store.py`); one whose
   supervisor went silent ("Status unknown") stays a day after its last
   heartbeat. The worker's process sweep then deletes it, and with it any
   exit notice still due: a day late, it would only be stale.
   `agent` calls never appear here; they are reached through the agents.

3. **Always-on**: one row while the conversation's Agent is
   [always on](../../runtime/always-on-agents.md): "Always-on · <Agent>",
   reading "Working now" (blue) during a wake's turn, otherwise the
   Goal's state and "Next wake <time>". A conversation that has not
   joined yet reads "Joins on its next use".
4. **Open work**: the conversation's open items
   ([open work](../../../../capabilities/agents.md#open-work)), one row each,
   "Open · <time>". Done items leave the overview.
5. **Scheduled tasks**: Scheduler tasks, reminders and webhooks set from
   this conversation (the task's `session_id`, or its signed spec's),
   newest first, each with its kind and when it runs ("Webhook · when
   called", "Recurring · 0 9 * * 1-5 · when its check changes").

Calls and programs are placed only after the executions are read, so they
never flash as unowned. Groups 3 to 5 come from one read,
`GET /api/sessions/{id}/work`, made when the panel opens, on the
`always_on_update`, `always_on_report` and `open_work_update` frames, on
focus, and every 30 seconds for Scheduler tasks, which publish no event.

## Pages

Every row opens a page; a stack of pages backs the panel, and the back
arrow names the page it returns to. Nothing expands in place.

- **Main agent**: the conversation title (one line) and its state. What
  waits for the reader comes first, each naming its message, then
  **Running**, **Last message** (the row opens that run's page), and
  **Sub-agents**: every sub-agent, depth first and newest first. The first
  level is the page's own list; a deeper sub-agent is indented under the
  one that started it, a hairline elbow runs from under that agent's
  glyph into its own, the line carries on to its later siblings, and the
  lines of rows above with siblings still to come run past it. A
  sub-agent reads as running with its call, Interrupted (an `agent` call
  cut short shows as the sub-agent it started), or its final state with
  the time; one waiting for the reader is listed once, in place, with the
  time and a red count on its ghost (its own waits; a sub-agent below it
  carries its own). An `agent` call that started no sub-agent sits in the
  tree where that sub-agent would, as **Failed to start** or **Not
  started**. The list shows 20 rows at a time with **Show earlier**.

  The section heading's button opens the view menu, built from the
  composer options menu's pieces: the same radix wrapper and
  `MENU_PANEL` frame, a value row per setting that opens a submenu, and
  check rows in it. **Show** is All, Waiting for you (rows with a red count)
  or Running (rows in the running tone). By structure, a filter keeps
  each match and the agents above it (`pruneBranches`) and redraws the
  lines for what is left. **Arrange** is By structure (the tree) or By
  time: one flat list, live rows first, then by the time each row shows,
  every sub-agent's status ending with who started it ("· by Research").
  A filter that leaves nothing says so under the heading, so the menu
  stays reachable. The button stays lit while the view differs from the
  default; the view is a per-browser preference in local storage.
- **Sub-agent / run**: kind, start and duration, the name or message, its
  state. A question or approval it waits on comes first, its action a
  raised pill. A pause with a
  queued decision (`pendingDecisions`, matched by execution) shows its
  prompt and choices, and **Answer in chat** / **Review in chat** scrolls
  to the composer's decision card (`data-decision-output`) and focuses its
  first control; the choice is made there, not in Activity. A pause with
  no queued decision is answered in the run page's own record (below);
  from the main page, **Open** opens that page. A
  single such pause reads as "Waiting for your answer" or "Waiting for
  approval" in the list and on the page. A sub-agent adds **Open its conversation**,
  **Started by** (the main agent or the sub-agent above it),
  **From** (the run of the message that started it) and **Task**, from
  its `agent` call. Then **Steps**: open calls (an `agent`
  call is reached through the sub-agent it started), child executions,
  the sub-agents it started and the ones that failed to start, programs.
  Last, under **Progress**, the run's own record: the `DebuggerPanel` in
  its `embedded` layout (no header or scroller of its own), which lists
  the progress rows first, then the reason and controls the execution
  allows (pause, continue, step, retry, add instruction, create branch),
  its open waits, and the raw ids, revisions, checkpoints and events
  folded under **Technical details**. Opening a run page selects that
  execution in the inspector hook, which reads events and debugger data
  only while a run page is open. There is no separate inspector page:
  a run is one page, and the main agent's page has no inspector of its
  own.
- **Failed start**: the call's description, when it was made and that it
  failed to start, a note that it has no conversation, **Started by**, the
  error line and the task.
- **Call**: titled by its description, with its kind, start and state, the
  run it came from, and the task (`prompt`) or the command. A call cut
  short reads **Interrupted**, with a line saying the run was interrupted
  before it returned. Tasks read as
  prose, commands as monospace; both show a few lines until **Show all**.
- **Program**: titled like its row. A progress card comes first: the
  count and percent, the bar, then elapsed time, speed and time left while
  it runs, or how long it took, when it ended and its exit code. Then
  **Stop program** while it runs, the command, and the output as a
  terminal shows it: a line redrawn with carriage returns keeps its last
  frame, colours stay, and the view follows new lines while the reader is
  at the end (marked **Live**). Last come the run it came from, the
  program name when a description titles it, folder and environment. An
  open program page is read every second.

- **Always-on**: the Agent's name, the conversation title and its state,
  a note on how the conversation wakes and how to stop it (archive it;
  the schedule is the Agent's), **Wake now**, then the standing goal, the
  current Goal, the interval, the last wake and its outcome, the next
  wake, and **Reports**: each report's title, time, body, links and where
  it was sent.
- **Open work**: the item, when it was added and its state, **Mark done**
  (**Reopen** once done) and **Remove**, then its note.
- **Scheduled task**: the title and its schedule, a webhook's address
  and key behind **Copy**, the command it watches, its prompt, reminder or
  command, and **Open in Scheduler**, where tasks are paused, changed and
  deleted.

### Program progress

The server reads progress out of a program's output
(`openprogram/host/processes/progress.py`), most trusted source first:
`##progress 45/100 samples` lines the program prints on purpose (the bash
tool asks the model to print them for long loops), the OSC 9;4 terminal
progress sequence, tqdm and pip bars, and counters such as `Epoch 3/10`,
`step 120 of 1000` or `[45/100]`. Once a more trusted source has spoken,
less trusted ones are ignored, so an inner per-batch bar never overwrites
an explicit sample count. Speed and time left are the bar's own, or
measured since the count began. Output is stored as a terminal shows it,
so a redrawn bar takes one line of the 2,000-line limit, and the agent
reading a background command gets each redraw once.

## Look

Rows have no frame at rest: a bare glyph in its kind's colour, the name
over a one-line status coloured by its tone (no dot), a chevron. Hover lifts
the row into a raised card: the file cards' shadow over a solid fill a
step toward the text colour (4%), since the panel is the input surface
itself and a card of the same colour would show no edge. Rows stack above the
tree lines, so a lifted card and its shadow cover the line instead of
being crossed by it. The line is one solid colour, the muted text mixed
into the panel's own background rather than a translucent stroke, so
where its pieces overlap at a joint it never darkens. A wait on a page is a
soft amber tint with no border.
