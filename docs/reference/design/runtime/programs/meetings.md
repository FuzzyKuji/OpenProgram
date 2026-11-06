# Meetings

The user records a call they are in on this computer; OpenProgram transcribes it and writes a summary in a new conversation. The design reuses what already exists: the speech engines of voice input, the long-running session shape of workflow recording, the owner turn that reminders and always-on check-ins start, the browser's microphone API, and the ScreenCaptureKit audio stream computer use already records applications with. It adds no new infrastructure.

## Shape

| Part | Where | Does |
|---|---|---|
| Microphone | the page (`apps/web/lib/meetings/meeting-recorder.ts`) | `getUserMedia`, one `MediaRecorder`, 30-second chunks uploaded in order |
| Computer sound | the server (`meeting/system_audio.py` on `openprogram/host/_platform/screen_capture_audio.py`) | a display-wide, audio-only ScreenCaptureKit stream started with the meeting, cut into 30-second WAV chunks |
| Routes | `openprogram/interfaces/server/routes/execution/meetings.py` | `/api/meetings`: list, start, audio, stop, status, transcript, summary, summarize again, delete |
| Application | `openprogram/programs/applications/meeting/` | the `meeting` service: storage, conversion, transcription queue, merge, summary |
| Speech | `openprogram/runtime/speech_link.py` → `openprogram/interfaces/speech/stt.py` | `transcribe_segments`: timed segments with the engine from Settings → Voice, in the meeting's language (detected by default) |
| Speakers | `meeting/diarize.py` (optional `sherpa-onnx`) | at stop, the system track diarized once; its segments labelled `others:<n>` |
| Summary | `openprogram/runtime/conversation/owner_turn.py` | one tool-less owner turn in a new conversation |
| Window | `apps/web/components/applications/windows/meeting-window.tsx` | Start/Stop, live progress, past meetings with summary and transcript |

The core never imports the application. The routes look the service up by name and answer 404 (`meeting_not_enabled`) while the application is disabled; disposing its context stops a recording in progress.

## Capture: two tracks, then diarization of one

"Me" against everyone else comes from where the sound was recorded, not from a model; telling the other people apart is diarization of the system track at stop (below):

- **mic**: the page's `getUserMedia({audio})` with echo cancellation, noise suppression and automatic gain: the user, "Me".
- **system**: the server's ScreenCaptureKit stream: the computer's sound output, everyone else in the call, "Others".

### The computer's sound, on the server

`POST /api/meetings` starts the meeting and, in `Meeting.begin`, its system capture. The source (`ScreenCaptureSource`) reads the shareable content, builds `SCContentFilter.initWithDisplay_excludingWindows_(display, [])` for the first display (everything it plays, no window excluded), and opens an audio-only stream through `screen_capture_audio.open_audio`: `capturesAudio`, 16 kHz, one channel, `excludesCurrentProcessAudio`, a 2×2 frame once a second and no screen output attached. The same module backs computer use's per-application recording (`desktop/audio.py`), which differs only in its filter. macOS asks for Screen & System Audio Recording the first time; the worker runs inside the App's runtime bundle (the `screen_recording` capability in `openprogram/host/system_access`), so the prompt and the System Settings row name the App. No other declaration is needed: ScreenCaptureKit audio is part of that grant.

`SystemAudio` is independent of ScreenCaptureKit. A source pushes float32 buffers into it from the stream's queue; it cuts them into 30-second chunks by sample count, and each chunk's `t_ms` is the meeting clock when its first sample was recorded (the arrival time of the buffer that starts it, less that buffer's remaining length). A thread of its own converts each chunk to 16-bit WAV and hands it to `Meeting.append("system", seq, t_ms, wav, "wav")`, the intake the audio route feeds. `Meeting.finish` stops the stream and flushes the last partial chunk while the meeting is still `recording`, then the usual stop follows; deleting a meeting cancels the capture without a flush.

When the source cannot start, the meeting records the microphone only and its status (and `meta.json`) says `system_audio: "unavailable"` with `system_audio_reason`: `unsupported` (not macOS, or PyObjC's ScreenCaptureKit does not import), `permission` (ScreenCaptureKit's refusal, error -3801 "declined TCCs", or `CGPreflightScreenCaptureAccess` reporting no grant), or `error`, with the text in `system_audio_message`. A working capture reports `recording`. Older meetings have no such field.

### The microphone, on the page

The page asks only for the microphone, then starts the meeting. It takes the server's `elapsed_ms` from the start response and counts its chunk offsets from the server's meeting start, so both tracks share one clock. Its `MediaRecorder` is stopped and restarted every 30 seconds. A timeslice recorder would emit chunks after the first without a WebM header; restarting makes every chunk a complete file the server converts on its own, at the cost of a gap of a few milliseconds per chunk. A chunk carries its track, its sequence number and its offset (`t_ms`), so uploads that finish out of order still land in place. A chunk stopped less than 100 ms after it started (Stop right after a rotation) is a WebM header with no sound in it and is not uploaded. Uploads are serialized and retried three times on network or 5xx errors. The recorder lives in a module-level store, so leaving the window does not stop it; only Stop does.

A refused microphone reaches the page as `NotAllowedError` and the window names the System Settings pane. From the start response the recording card says whether the computer's sound is recorded too; when it is not, it says the meeting is microphone only and, for `permission`, names Privacy & Security → Screen & System Audio Recording and asks to reopen the App.

## Server: store, convert, transcribe, merge

```
<state>/meetings/<id>/
  meta.json                   title, language, times, state, chunk counts, errors, engine, session_id,
                              system_audio, diarization, speakers
  tracks/<track>/<seq>.webm   the chunk as uploaded (system chunks are .wav)
  tracks/<track>/<seq>.json   its timed segments (or silent / error); system segments gain `speaker`
  transcript.json             the merged transcript
  summary.md                  the summary with the transcript in a <details> block
```

One meeting records at a time, for at most 4 hours. Every chunk is written first, then queued for the meeting's single worker thread, so memory holds one chunk regardless of meeting length:

1. **Convert** with `ffmpeg` (found on `PATH`, then `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`) to 16 kHz mono 16-bit WAV; ffmpeg reads the format from the data. A WAV chunk already in that form (every system chunk) is used as it is. Without ffmpeg, starting a meeting is refused with `ffmpeg_missing` and an install hint.
2. **Skip silence**: a chunk whose peak stays below 300/32767 is not transcribed; Whisper invents text for silent audio.
3. **Transcribe** through `speech_link.transcribe_segments(wav, duration_ms, language)`. The language is the meeting's, never Settings → Voice's: `POST /api/meetings` takes an optional ISO `language` (stored in `meta.json`; the Meetings window sends the language chosen next to the meeting name and none for "Detect automatically"), and empty means detection (whisper.cpp `-l auto`, no `language` field for OpenAI and Groq). A voice-input language forced onto a call in another language makes Whisper invent text in that language. The speech interface keeps each phrase's time: whisper.cpp prints `[from --> to]` lines (no `-nt`); Groq and OpenAI Whisper models answer `verbose_json` with segments; `gpt-4o-*-transcribe` answers text only, which becomes one segment spanning the chunk. A link without the method falls back to `transcribe` the same way.
4. **Merge** (`transcript.py`): segments move onto the meeting clock by the chunk's offset and sort by start. A microphone segment whose text is at least 75% similar to a system segment starting within 4 s is echo (no headphones) and is dropped. Consecutive segments of one speaker less than 1.5 s apart join into one turn. Each line carries `speaker` (`me`, `others`, `others:<n>`) and its English `label` ("Me", "Others", "Speaker n"); the window localizes `speaker`. `transcript.json` is rewritten after every chunk, so the window shows the transcript growing.

A chunk that fails to convert or transcribe is recorded with its error and counted; the meeting goes on. A repeated `(track, seq)` is ignored, so client retries are safe.

## Summary

At stop the state goes `recording` → `transcribing` (the queue drains, then the system track is diarized) → `summarizing` → `done`. With an empty transcript no conversation opens and `summary.md` says nothing was transcribed.

Otherwise the application creates a conversation (`meeting_<hex>`, source `web`, titled after the meeting, on the default Agent with the model a new chat starts on), records its id in `meta.json` and starts one owner turn with `start_owner_turn(..., tools=[], untrusted=True)`. The message is a fixed prompt followed by the transcript inside `<meeting-transcript>`; the prompt asks for `## Summary`, `## Decisions`, `## Action items` (owner, due date) and `## Open questions`, in the meeting's language, and says the transcript is data, never instructions. No tools and the untrusted flag mean nothing said in a meeting can make the agent act. When the turn ends, its answer, a header with date and length, and the full transcript in a collapsible section become `summary.md`. The conversation stays for follow-up questions.

A meeting left in a live state by an ended process lists as `interrupted`; **Summarize again** rebuilds it from the per-chunk JSON files and runs the summary step again.

## Access

Every route requires the owner's sign-in (`require_owner`). The microphone is recorded where the page runs; the computer's sound is always that of the computer running the server, so a signed-in owner on another computer records their own microphone and the server computer's sound. Meetings stay in the state directory; with a cloud speech engine each chunk is sent to that provider.

## Speaker diarization

Diarization runs once per meeting, in the meeting's worker after the transcription queue drains and before the summary, over the whole system track. Running it per chunk would need speaker embeddings kept and matched across chunks; one pass over the whole track lets the clustering see every voice at once, and the pass is fast (about 4 s for a minute of audio on four threads).

1. **Audio**: the system chunks, in sequence order, converted one at a time (they are already 16 kHz mono WAV) and concatenated. `concatenate` records each chunk's span, `(concat_ms, t_ms, duration_ms)`, so a turn found in the concatenation maps back to the meeting clock; a turn that crosses a chunk boundary is split there (`to_meeting_clock`).
2. **Diarize** (`run`): sherpa-onnx's `OfflineSpeakerDiarization` with the pyannote segmentation-3.0 model and 3D-Speaker's bilingual CAM++ embedding model (`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`), up to four ONNX threads, `min_duration_on` 0.3 s and `min_duration_off` 0.5 s as in sherpa-onnx's example. The number of speakers is unknown, so `FastClusteringConfig(num_clusters=-1, threshold=0.75)` clusters by distance. Model and threshold were chosen on four recordings with known speakers: pyannote's AMI meeting excerpt (two people talking over each other, scored against its reference labels), sherpa-onnx's four-speaker test recording, a two-voice recording and four synthesized voices. CAM++ finds the right speakers on all four anywhere between 0.6 and 0.75, with 91% of the AMI speech labelled right, and 0.8 merges two of the four Chinese speakers; the top of the range is used because on a four-person AMI meeting heard through a conference call and through plain playback it splits one person into two numbers least often (seven numbered voices at 0.65, five at 0.75); the ERes2Net zh-cn model of sherpa-onnx's example needed a different threshold for each recording and merged the AMI pair into one speaker at every value that kept the four-speaker recording at four.
3. **Label** (`assign`): each system segment, on the meeting clock, takes the speaker whose turns overlap it longest (ties: the lower sherpa number); speakers are renumbered `others:1`, `others:2`… in order of first appearance in the transcript. A segment no turn overlaps keeps no speaker and reads "Others", and so does one whose only voice was heard for less than `MIN_SPEAKER_MS` (3 s) over the whole meeting: on a real four-person meeting the clustering leaves a few one- or two-second strays beside the four real speakers, and they would otherwise become "Speaker 5" to "Speaker 7". The labelled records are written back to their chunk JSON files and the transcript is merged again, so `transcript.json`, `summary.md` and the summary prompt all carry "Speaker n". The prompt says the numbers are voices, not names.

`sherpa-onnx` is the optional `meetings` extra (with `numpy`), imported only inside `run`. The models download on first use from sherpa-onnx's GitHub releases into `<state>/models/diarization/`: the segmentation archive (`speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2`, whose `model.onnx` alone is extracted) and the embedding model (`speaker-recongition-models/…_16k.onnx`), each through a temporary file and an atomic rename under one lock, as voice input downloads Whisper models. The meeting's status reports `diarization`: `running`, then `done` (with `speakers`, the count of numbered speakers), `unavailable` with `diarization_reason` `not_installed` (no `sherpa_onnx`) or `no_model` (the download or the model files failed), or `failed` (`error`, with `diarization_message`). In every case but `done` the transcript is unchanged. Meetings that did not record the computer's sound, or transcribed nothing from it, skip the step and leave `diarization` empty.

## Alternatives

The open-source meeting recorders compared with this design are meetscribe-offline (Python, pyannote diarization, Ollama or cloud summaries, needs a HuggingFace token and prefers an NVIDIA GPU), HushScribe (macOS 26, Apple Silicon, WhisperKit and Parakeet on device, speaker labels only after the session) and AI-Meeting-Bot (a developer pipeline around a local Whisper). ChatGPT's desktop app records meetings through a companion that connects to the meeting application and lists upcoming meetings; Claude's desktop app has no meeting feature. None of them is reused whole: each is an application of its own with its own capture, models and storage, while this design is three modules on what OpenProgram already has (the voice-input speech engines, the computer-use ScreenCaptureKit stream, the chat that writes the summary). What is reused from them is the component choice: Whisper for speech, pyannote segmentation with a speaker-embedding model for who spoke, run through sherpa-onnx so no PyTorch or token is needed.

The desktop agent products measured against, on the question asked here (who said what in a call, and a summary):

| | Claude (desktop) | Codex / ChatGPT (desktop) | DeepSeek Harness | OpenProgram |
| --- | --- | --- | --- | --- |
| Meetings | No meeting feature | ChatGPT's record mode: a companion joins through the meeting application, lists upcoming meetings, transcribes and summarises; Codex has none | A voice-input plugin (experimental) only; no recording or meeting feature | Records the microphone and the computer's sound output from any application, transcribes both, tells the other voices apart on this computer, writes the summary in a chat |

None of the three does something on this question that this design lacks, so capture, diarization and summary stay as designed. ChatGPT's list of upcoming meetings from the calendar is the one neighbouring feature OpenProgram does not have.

## Implementation status

- Built: microphone capture and chunk upload in the page, the server's ScreenCaptureKit capture and chunking with `system_audio` status, the `meeting` application and routes, timed transcription for all three engines, merge with echo removal, the summary turn and `summary.md`, the Meetings window, re-summarizing and deleting.
- Built: diarization of the system track at stop with sherpa-onnx (the `meetings` extra, also part of `all` so the packaged App's runtime carries it; models downloaded on first use), `diarization` status and "Speaker n" labels in the transcript, the window and the summary prompt; meeting transcription in a detected or per-meeting language instead of the voice-input language; a language choice in the Meetings window (remembered per viewer, shown on the recording card and past meetings).
- Verified by tests with a faked sample source, ffmpeg, speech, diarizer and summary turn; the real pipeline (ScreenCaptureKit capture in the stable App, chunking, transcription, diarization) was checked with recordings played through the computer's sound output: sherpa-onnx's four-speaker test recording, an AMI two-speaker excerpt (both found) and an AMI four-speaker excerpt (all four found, every line's number consistent with the reference); and on a real conference call: two participants in a Jitsi Meet room, the second one speaking the AMI four-person excerpt as its audio track, the first one playing it on this computer, which the stable App recorded and summarized with exactly four numbered speakers, every line's number consistent with the reference. The call's audio reaches the recorder through the same system-audio path as Zoom or any other application. The microphone track was checked from the Meetings window in a browser whose microphone was the AMI excerpt: seven chunks uploaded, six lines labelled "Me", the summary written; the only failure was the header-only last chunk, which the page now skips. The Screen & System Audio Recording prompt and the permission classification in a freshly installed App still need a check.
