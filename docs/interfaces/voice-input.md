# Voice input

The round microphone button in the bottom-left corner of the chat input box turns speech into text. Click it and speak; click it again to stop. While you type, you can also hold ⌥Space (Alt+Space) to talk and release it to stop.

While recording, a strip before the send button shows a dot for every quiet moment and a bar sized by loudness while you speak. Each phrase is transcribed when you pause and is inserted at the cursor, so text arrives phrase by phrase rather than word by word. Nothing is sent: the text stays in the box for you to edit and send. Press Esc to discard the recording and remove the text it inserted. When you stop, the last phrase is transcribed before the button becomes available again.

The browser or the desktop App asks for microphone access the first time.

## Choosing the speech-to-text engine

Open **Settings → Voice**. The microphone has no options of its own; everything is set there.

| Setting | Values | Meaning |
|---|---|---|
| Engine (`voice.engine`) | `auto`, `openai`, `groq`, `local` | Which service transcribes audio. |
| Spoken language (`voice.language`) | `auto`, `zh`, `en`, `ja`, `ko`, `fr`, `de`, `es` | A hint for the language you speak; `auto` detects it. With `zh`, Chinese is written in simplified characters. |
| Model (`voice.model`) | text | Model name for the chosen engine; empty uses the engine's default. Ignored when the engine is `auto`. |

The engines:

- **openai** sends each phrase to the OpenAI transcription API with `gpt-4o-mini-transcribe` by default. It uses the OpenAI API key from Settings → Providers.
- **groq** sends each phrase to Groq with `whisper-large-v3-turbo` by default, using the Groq API key from Settings → Providers.
- **local** runs [whisper.cpp](https://github.com/ggml-org/whisper.cpp) on this computer, so audio never leaves it. Install it with `brew install whisper-cpp`. The `large-v3-turbo-q5_0` model (about 570 MB) downloads into the state directory the first time you use it; on Apple silicon a phrase takes one to two seconds.

With `auto`, OpenProgram uses local whisper.cpp when it is installed and its model is already downloaded, then OpenAI, then Groq, then local whisper.cpp (which downloads its model on first use). The page shows which engine is in use and which engines work on this computer.

The same settings can be changed from the command line, for example:

```bash
openprogram config set voice.engine local
```

The same engine transcribes the sound [`computer_use_agent`](../capabilities/computer-use.md#recording-sound) records from an application.

## Limits

- Audio is recorded as 16 kHz mono and sent one phrase at a time; a phrase longer than 25 seconds without a pause is cut there.
- One upload may be up to 20 MB.
- If no engine is usable, clicking the microphone shows a notice pointing to Settings → Voice instead of recording.
