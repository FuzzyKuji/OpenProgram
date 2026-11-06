# Record a workflow

Do a task once on your Mac while OpenProgram records it, and the chat agent turns the recording into a Workflow. The recording works in any application: a website, a desktop app, Finder, or several of them in one task.

## Before you start

- Recording is in the OpenProgram desktop App on macOS. The **+** menu does not offer it in a browser or on other systems.
- Recording is the built-in application **Workflow Recording**. It is on by default; while it is switched off on the **Applications** page (or with `openprogram programs disable workflow_recording`), the **+** menu has no **Record a workflow** item. See [Applications](../applications.md).
- OpenProgram needs **Accessibility** and **Screen & System Audio Recording** access in System Settings → Privacy & Security. If one is missing, the start dialog says which and opens the right settings pane.
- Spoken narration uses the speech engine chosen in **Settings → Voice** and the microphone. Without a speech engine the recording still works, without narration.

## Record

1. In the composer, open the **+** menu and choose **Record a workflow**.
2. The dialog lists what is recorded. Turn **Narrate with the microphone** on or off, pick a microphone if you have several, and click **Start recording**.
3. The OpenProgram window steps aside and a small bar stays above every window: a red recording dot, the elapsed time, the number of steps, the microphone switch, **Discard** (the trash can) and the red **Stop** button. Do the task the way you always do it. Say what you are doing, especially what would change next time ("the date is always last Monday", "this file name changes every week").
4. Click **Stop**. The OpenProgram window comes back with the recording in the composer: "Recorded demonstration · 12 steps · 48.3 s · 9 images".
5. Add a sentence if you like, such as when the Workflow should run, and send the message.

You can also start without a chat: open **Workflow Recording** from the new tab page, or click **Open** on its row on the **Applications** page. Its window shows the same setup with **Start recording**; starting opens a new chat, and when you click **Stop** the recording waits in that chat's composer.

The agent reads the steps and the screenshots, asks about anything that decides the Workflow's inputs, writes the package, runs `openprogram programs check` and summarizes the steps, inputs and assumptions for you to correct. In the conversation the recording shows as a card; click it to see each step with its screenshot.

A recording stops by itself after ten minutes, as if you had clicked **Stop**; the bar warns you 30 seconds before. **Discard** stops and deletes the recording. Removing the recording from the composer before sending keeps it on disk.

## What is recorded

| Recorded | Not recorded |
|---|---|
| Clicks, with the application, window and control under the pointer | Text typed into password fields (the step says only that a password was typed) |
| Text typed into a field, and keys such as Return, Tab, Escape and shortcuts | Anything done in OpenProgram itself, password managers, Keychain Access and system credential prompts |
| Scrolling, and switching to another application or window | Audio: narration is turned into text and the sound is discarded |
| Screenshots of the display at clicks, Return and window switches, without OpenProgram's own windows | |
| Your narration, as text | |

Recordings stay on your computer in `~/.openprogram/recordings/<id>/`: `session.json`, `events.jsonl` (one line per step) and `images/`. When you send one, the step list and up to 12 screenshots go to the model you chat with, like any other message content. You can delete a recording folder at any time; a card whose folder is gone shows that the recording is no longer on this computer.

## Recording as context

A recording can also carry the purpose `context` instead of `workflow`: the agent then uses the steps, screenshots and narration only as context for the request in the same message and writes no Workflow unless you ask. The start dialog records for a Workflow; the `context` purpose is taken by the recording API (`POST /api/recordings` with `{"purpose": "context"}`).

## Tips

- Record one task per recording, from its usual starting point.
- Use the real inputs of one typical run. The agent turns values that change into Workflow parameters and asks when it cannot tell.
- If the agent already has enough from the conversation, you do not need a recording: ask for the Workflow directly, and it fills gaps from earlier conversations and memory before asking you.

For the package format and the checks the agent runs, see [Write and check a Workflow](authoring.md).
