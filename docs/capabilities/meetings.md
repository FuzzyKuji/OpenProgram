# Meetings

Record a call you are in on this computer, in Zoom, Teams, a browser meeting or any other app, and get a transcript and a summary. OpenProgram records two things: your microphone, which is you ("Me"), and the computer's sound output, which is everyone else in the call ("Others"). It transcribes both while the call goes on, and when you stop, it writes a summary with the decisions, action items and open questions in a new chat.

## Before the first meeting

| You need | Why |
| --- | --- |
| OpenProgram on macOS 13 or later | OpenProgram records the computer's sound itself, through macOS ScreenCaptureKit, on the computer it runs on. On other systems only the microphone is recorded. |
| `ffmpeg` | Converts the recorded audio for speech recognition. Install it with `brew install ffmpeg` (or your package manager), then restart OpenProgram. The Meetings window says so while it is missing. |
| A speech engine | The engine chosen in **Settings → Voice**, the same one [voice input](../interfaces/voice-input.md) uses: OpenAI or Groq with an API key, or whisper.cpp on this computer. |
| A chat model | The summary is written by your default Agent, with the model a new chat starts on. |
| Optional: the `meetings` extra | Tells the other people in the call apart (see [Who said what](#who-said-what)). Without it they are all "Others". |

## Record a meeting

1. Open **Meetings** from its tile on the new tab page, or with **Open** on its row on the **Applications** page.
2. Optionally type a name for the meeting and choose the spoken language next to it (**Detect automatically** by default; the window remembers your last choice), then press **Start recording** when the call begins.
3. The first time, OpenProgram explains the two macOS permission prompts that follow:
   - **Microphone** records you. The Meetings window asks for it.
   - **Screen & System Audio Recording** lets OpenProgram record the sound the computer plays. macOS asks for it, for the OpenProgram App, when the meeting starts. Nothing on the screen is recorded.
4. While recording, the window shows the elapsed time and how many 30-second pieces have been uploaded and transcribed. You can switch to other tabs or windows; the recording continues until you press **Stop recording**.
5. After you stop, the last pieces are transcribed and the summary is written. The meeting appears under **Past meetings**.

Unless you choose a language for the meeting, it detects the spoken language of every piece on its own; the recording card and **Past meetings** show the chosen language, or "detected". The language set in **Settings → Voice** applies to voice input only, so an English call is transcribed in English even when voice input is set to Chinese.

Recording never starts on its own. Headphones give the cleanest transcript: without them your microphone also hears the other side, and OpenProgram drops lines that repeat what the computer's sound already said.

If you decline the microphone, the window names the System Settings pane to change, **Privacy & Security → Microphone**; allow OpenProgram there and start again. If the computer's sound cannot be recorded, the meeting records the microphone only and the window says so while it records; when the reason is the missing permission, it names **Privacy & Security → Screen & System Audio Recording**. Allow OpenProgram there, reopen the App, and the next meeting records both. A past meeting recorded without the computer's sound says so under its transcript.

## Read a meeting

Click a meeting under **Past meetings** to open it:

- **Summary**: the summary, decisions, action items (with owner and due date when one was said) and open questions.
- **Transcript**: every line with its time from the start of the recording and its speaker: Me, or Speaker 1, Speaker 2… for the other people (Others when they could not be told apart).
- **Open chat** opens the conversation that wrote the summary. Ask follow-up questions there, such as "draft the follow-up email" or "what did they say about the budget?".
- **Summarize again** writes the summary again, for example after the model was unavailable or the App was closed while a meeting was being processed (such a meeting is marked **Interrupted**).
- The delete button deletes the meeting's audio, transcript and summary. The summary chat stays.

The summary turn runs without tools and treats the transcript as what people said, never as instructions, so nothing anyone says in a meeting makes the agent act.

## Who said what

Your microphone is always "Me". When you stop a meeting, OpenProgram listens to the whole recording of the computer's sound once more and groups it by voice, then labels the other people's lines "Speaker 1", "Speaker 2" and so on, in the order they first speak. The number of people is worked out from the voices; a voice heard for only a moment in the whole meeting gets no number and stays "Others". The numbers are voices, not names; the summary uses a name where the meeting makes clear who someone is. A line that falls where no voice was found keeps "Others".

This runs on this computer with [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) speaker diarization. The desktop App includes it. In a source checkout it is the optional `meetings` extra; add it to the environment:

```bash
uv sync --locked --extra dev --extra meetings
```

The first meeting stopped after that downloads two speech models (about 34 MB in all) into `models/diarization/` under the state directory. Telling voices apart takes roughly a tenth of the meeting's length after you stop, before the summary starts. Without the extra, or when the models cannot be downloaded, the other people stay "Others" and everything else works as before.

## Where meetings are stored

Everything stays on this computer, under the OpenProgram state directory (`~/.openprogram` by default):

```
meetings/<id>/
  meta.json             name, start time, length, progress, the summary chat,
                        whether the computer's sound was recorded and
                        whether its speakers were told apart
  tracks/mic/…          your microphone, in 30-second WebM pieces
  tracks/system/…       the computer's sound, in 30-second WAV pieces
  transcript.json       the merged transcript
  summary.md            the summary, with the full transcript at the end
```

With the OpenAI or Groq engine, each 30-second piece is sent to that service for transcription. With whisper.cpp, audio never leaves the computer. Telling speakers apart always runs on this computer.

## Limits

- One meeting records at a time, for at most 4 hours; at the limit it stops by itself.
- Speakers are told apart by voice only after the meeting stops, not live. Two people with similar voices can share a number, and one person can get two numbers when their sound changes a lot (another microphone, a bad connection).
- Silent pieces are skipped. A piece that cannot be converted or transcribed is reported under the transcript and the rest of the meeting goes on.

## Turn Meetings off

Meetings is a built-in application. Its switch on the **Applications** page, or `openprogram programs disable meeting`, turns it off; a recording in progress stops. `openprogram programs enable meeting` turns it back on. See [Applications](applications.md).
