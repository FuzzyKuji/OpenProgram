# Run a task when something happens

A [reminder](reminders.md) or scheduled task runs at a time. Two triggers run one when something happens instead: when a command's output changes, or when another service calls a webhook. Ask for either in plain words:

- "Every 10 minutes, check `gh pr list --repo me/app` and tell me about new pull requests."
- "Give me a webhook that triages new issues from our tracker."

The agent sets them up with its `scheduler` tool. Each one runs the task you give it: an agent prompt, a reminder that wakes the agent in this conversation, or a shell command.

## When something changes

A recurring or monitor task can carry a `watch` command. Its cron is then how often the command is checked, and the task runs only when the command's output differs from the previous check. The first check records the baseline and runs nothing; changing the command starts a new baseline.

The run receives what changed, as a diff of the output. The command runs in the task's sandbox, like any scheduled command, and must finish within 2 minutes. A check that fails or times out runs nothing and keeps the previous baseline.

## When a service calls

A `webhook` task has no schedule. Creating one gives a URL and a key:

```text
POST http://127.0.0.1:18100/hooks/<task id>
X-OpenProgram-Key: <key>
```

The key can also be a GitHub webhook's secret: GitHub signs each delivery with it (`X-Hub-Signature-256`), and the run is told the GitHub event name. A call without the right key, or to an unknown task, gets `404`. A paused task answers `409`. A task starts at most once every 10 seconds; calls in between get `429`. Request bodies up to 64 KB are accepted, and the run receives the first 8,000 characters.

The URL is on this computer. A service on the internet reaches it only through a tunnel or a [public Web address](../server/configuration.md#who-can-reach-the-server) you set up.

## Outside text is data

The text that started a run, a request body or a changed output, comes from outside. The run receives it fenced as an event and marked as data: the agent is told to do only the task you gave it and to ignore any request inside the event.

Runs started this way also never act without asking:

- A prompt task runs in the background with no one to ask, so any call that needs approval is refused.
- A reminder that wakes the agent starts its turn in **Ask** mode when the conversation is in Bypass, Auto or Accept edits, so every change waits for your approval in that conversation.
- A shell command receives the event in the `OPENPROGRAM_EVENT` environment variable, and `OPENPROGRAM_EVENT_SOURCE` says `webhook` or `watch`.

## See, pause or delete

Watched and webhook tasks are listed in **Scheduler** with the other tasks; a webhook task shows **When called** as its schedule. Pause, resume or delete them there, or ask the agent. Each run's log, including the event that started it, is in the scheduler's `logs` folder.
