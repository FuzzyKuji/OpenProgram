# Always-on Agents

An always-on Agent keeps its conversations working while you are away. Each conversation that uses it wakes on a schedule, works on a standing goal, checks for news with read-only tools when it has nothing to do, and notifies you when it finds something worth your attention.

Always-on is part of an [Agent](agents.md)'s configuration, like its model, instructions, capabilities and memory. What it does happens in conversations: every conversation with that Agent is its own always-on assistant, with its own Goal, check-ins and reports. To run two separate always-on assistants, start two conversations.

## Turn it on

1. Open **Agents** in the sidebar and select the Agent.
2. Open the **Always-on** tab and check **Keep conversations with this Agent always on**.
3. Optionally enter a **Standing goal**, for example "Keep the docs site free of broken links and tell me when a fix needs review."
4. Choose how often it wakes (**Wake every**, 5 to 10080 minutes; 60 by default).
5. Optionally, under **When it wakes**, pick the days it wakes on and set **Quiet hours** (below).
6. Choose **Save changes**.
7. Talk to it: choose **New conversation** on the Agents page, or pick the Agent from the Agent chip in a chat's composer.

## Quiet hours and wake days

By default a conversation wakes on its interval around the clock. Under **When it wakes** in the Always-on tab:

- **Wake on**: the weekdays scheduled wakes happen on. At least one stays on.
- **Quiet hours**: a daily stretch without scheduled wakes, **From** and **Until**, for example 22:00 to 08:00. An end before the start runs past midnight.

Both use this computer's local time. A wake that would fall in quiet time moves to its end, for example to 08:00 or to the next wake day, and the Activity panel shows that time as the next wake. **Wake now** and messages from your other conversations (below) still run during quiet time, and a Goal that is already running continues.

## Which conversations wake

A conversation with the Agent takes part once you use it after always-on is turned on: a new chat, or an older one you send a message in. Switching a conversation to the Agent with its Agent chip also counts. Its first wake comes one interval later, so a chat you just opened is never interrupted. Conversations you have not used since stay quiet.

Sub-agent and imported conversations never wake. Archive a conversation to stop its wakes; turning always-on off for the Agent stops all of them. When you turn it on again, each conversation that took part before counts its interval from that moment.

## What a wake does

Each wake does at most one thing:

| Situation | What happens |
| --- | --- |
| A scheduled wake falls in quiet hours or on a day without wakes | Nothing; the next wake moves to the end of the quiet time |
| A turn is already running in the conversation | Nothing; it tries again next time |
| You set a standing goal the conversation has not started | It starts the goal as a [Goal](goal.md) in the conversation |
| A Goal is in progress or paused | Nothing; the Goal continues on its own, and a pause you made stays in place |
| No Goal to work on, and check-ins are on | It checks in (below) |
| Otherwise | Nothing |

A goal you change while another Goal is unfinished starts once that Goal ends. To switch right away, enter `/goal clear` in the conversation.

Write the standing goal as something to achieve ("Get the docs site free of broken links"), not as a routine ("Check the links every hour"). The Goal ends once its requirements hold; checking again later is what check-ins do.

## Check-ins

When it has no Goal to work on, the conversation checks in. The agent reviews its memory, the conversation's [open work](agents.md#open-work) and the conversation itself for open threads and looks for anything new, using only read-only tools: file reading and search, web search and fetch, conversation and memory reading, and the todo, open work and Goal readers. It cannot run commands, edit files or call MCP servers during a check-in.

If it finds something worth your attention, it sends a report. Otherwise it says so in one line. Under **What a check-in may do**:

- **Report findings** (default): it proposes work in its report, and you decide what to start.
- **Start goals on its own**: it may turn a finding into a Goal, which then runs with the conversation's normal tools and permissions, or hand it to another conversation that owns that kind of work (below).

Turn off **Check in when there is no goal to work on** to have it wake only for the standing goal.

Wakes are ordinary turns in the conversation, so you see everything it did there and can answer it like in any chat. Its permission mode and rules are that conversation's settings, and any approval it needs waits there and notifies you.

## Hand work to another conversation

Conversations can work as a team, one owner per job: a planning conversation can hand a task to the conversation that does that kind of work, for example "check the links" to a docs conversation. In a conversation whose Agent is always-on, the agent has a `handoff` tool that sends a message to another of your conversations, named by its title or ID. The other conversation may use any Agent.

- The message arrives in the other conversation as its next turn, shown as a message starting with 📨 and the sender's title. If a turn is running there, it waits for it to end, up to ten minutes.
- When that turn ends, its answer comes back to the sending conversation as a new turn, shown starting with ↩️. If the other conversation stayed busy, the message comes back undelivered instead.
- Each turn runs under its own conversation's Agent, permission mode and rules. In Ask mode, sending a handoff waits for your approval like any other action; in Auto mode it is reviewed.
- A conversation cannot message itself, and a chain of messages and replies stops after four hops. Sub-agent, imported and archived conversations cannot send or receive handoffs.
- Chains survive a restart of the OpenProgram service for a day: the hop count still applies, and a conversation that was working on a message when the service restarted still sends its answer back once it finishes.

To set up a team, give each conversation a clear title and job, and tell the planning conversation which conversation does what.

## In the conversation's Activity panel

The conversation's [Activity panel](../interfaces/web.md#conversation-activity) has an **Always-on** row while its Agent is always-on. It shows what the conversation is doing and when it wakes next, after quiet hours. Its page shows the standing goal, the current Goal, the wake schedule, the last wake and its result, and the conversation's reports. **Wake now** runs a wake immediately.

## Reports and notifications

A report has a title, a short body and optional links. It appears as a tool call in the conversation and in the Activity panel, and the conversation gets the sidebar's unread dot unless it is on screen. A check-in that finds nothing to report leaves no unread dot; the Activity panel still shows its result. In the desktop App, each report shows a system notification while no App window has focus. Clicking it opens the conversation.

## Send reports to channels

Reports can also reach you on a [chat channel](../integrations/channels.md) (Telegram, Slack, Discord or WeChat). Under **Also send reports to** in the Always-on tab, check the conversations that should get each report as a message. Up to 10 can be picked. They apply to reports from every conversation with this Agent.

The list shows the channel conversations this Agent already has, plus the people and groups it is bound to with a peer binding (`openprogram channels bindings add <agent> --channel telegram --account <id> --peer <id>`). An Agent bound to a whole channel or account only lists the people who have talked to it.

Each report is sent once to each picked conversation, after it is saved in the App. Under each report, the Activity panel shows whether it was sent to each conversation. A failed send (for example, the account is signed out) is shown there. The report itself is kept.

## Learning from feedback

The agent improves through its memory. Set Memory to **Read and write** in the Agent's **Memory** tab: corrections and preferences from your conversations are then saved to its memory and used in later turns. The Always-on tab reminds you when memory is not read-write.

## Limits

- Work runs on this computer, in the conversation's working folder and sandbox. The worker must be running for conversations to wake.
- Quiet hours and wake days follow this computer's clock and time zone.
- A duplicated Agent starts with always-on turned off.

The [engineering design](../reference/design/runtime/always-on-agents.md) describes how wakes, check-ins, reports and handoffs work.
