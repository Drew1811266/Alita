# Local Qwen ASR Voice Input Design

## Goal

Add a local voice input module that lets users speak a request, transcribes the recorded audio with Qwen3-ASR-1.7B on CPU, inserts the resulting text into the existing chat draft, and leaves final Agent submission under user control.

## Confirmed Scope

The first version is a development-only integration. The Qwen3-ASR model is not downloaded or managed by Alita. Developers configure an existing local model directory with `ALITA_ASR_MODEL_PATH`. The feature is Chinese-first, records at most 60 seconds per attempt, transcribes only after recording stops, and never sends the transcript to the Agent automatically.

Audio is treated as temporary input method data. The application deletes the temporary recording after transcription succeeds or fails, does not attach it to the project, and does not store it in chat history.

Out of scope for this version: model download UI, model import UI, persistent speech model preferences, multilingual language selection, streaming subtitles, saved audio history, and third-party ASR server frameworks. The integration owns its module boundaries and uses only the model/runtime package needed to run Qwen3-ASR.

## Architecture

Voice input is an input method layered onto the current chat draft flow:

```text
microphone recording -> temporary WAV file -> ASR transcription -> draft insertion -> user presses Send -> existing Agent flow
```

The existing Agent message protocol and graph execution path do not change. The ASR module produces draft text only.

Responsibilities:

- React chat UI records microphone audio, displays recording state, renders a live audio-level track, captures the textarea selection at transcription start, and inserts the transcript into the draft.
- Tauri commands provide the desktop bridge. They check ASR status, receive WAV bytes from the webview, write a temporary audio file under the system temp directory, call the sidecar, and delete the file in a `finally`-style cleanup path.
- The Python sidecar exposes ASR status and transcription endpoints. It lazily imports and loads Qwen3-ASR only when transcription is first requested.
- The ASR provider runs on CPU. GPU usage is not allowed for this feature because the Agent model owns GPU memory.

## Frontend Interaction

The chat composer action row becomes:

```text
Add file / Microphone / Send
```

The microphone button is always visible. If `ALITA_ASR_MODEL_PATH` is missing, inaccessible, or the ASR runtime is unavailable, the button is disabled and exposes a localized "voice model is not configured" message.

Button states:

- Idle: click starts recording.
- Recording: click stops recording and starts transcription.
- Recording timeout: at 60 seconds, recording stops automatically and transcription begins.
- Transcribing: the button is disabled and shows a transcribing state.
- Failed: the draft is left unchanged and a visible error is shown.

While recording, a compact audio track appears below the chat textarea. It shows live microphone activity with a small bar waveform and a timer such as `00:12 / 01:00`. The waveform is UI-only feedback generated from Web Audio API levels. It is not the transcription input.

If microphone permission is denied, no input device exists, or capture fails, the waveform is not shown, recording stops, and the user sees a clear error.

## Audio Capture

The frontend captures microphone audio through `navigator.mediaDevices.getUserMedia`. It uses the Web Audio API to collect mono PCM samples and encodes them as a 16 kHz WAV payload before passing the bytes to Tauri. This avoids depending on WebView-specific `MediaRecorder` container support and avoids adding FFmpeg only to decode browser-created audio formats.

The frontend enforces the 60 second limit. The Tauri bridge also validates a conservative maximum payload size for defense in depth.

## Draft Insertion Rules

When transcription starts, the UI records the current textarea `selectionStart`, `selectionEnd`, and draft value.

When transcription completes:

- If the current draft is empty, the transcript becomes the whole draft.
- If the current draft is not empty and a selection range was captured, the transcript is inserted at that range.
- If text was selected, the transcript replaces the selected text.
- If no reliable selection exists, the transcript is appended to the end.
- If the user edited the draft while transcription was running, the captured offsets are clamped to the current draft length before insertion.

The user can continue editing during transcription. Because transcripts are never auto-sent, the user can review or adjust the result before sending.

## Sidecar API

The Python sidecar gains:

```http
GET /asr/status
```

Response:

```json
{
  "available": true,
  "configured": true,
  "modelPath": "D:\\Models\\Qwen3-ASR-1.7B",
  "message": "voice model is configured"
}
```

`available` is false when the model path is missing, inaccessible, dependencies cannot be imported, or the provider is otherwise unable to transcribe.

```http
POST /asr/transcribe
```

Request:

```json
{
  "audioPath": "C:\\Users\\...\\AppData\\Local\\Temp\\alita-asr-....wav",
  "language": "zh"
}
```

Response:

```json
{
  "text": "transcribed Chinese text"
}
```

The sidecar endpoint is called by Tauri with the existing sidecar auth token. The endpoint validates that the audio path exists and is a file before invoking the provider.

## Model Loading

The sidecar does not load Qwen3-ASR during startup. It performs lazy initialization on the first transcription request:

- Read `ALITA_ASR_MODEL_PATH`.
- Verify the directory exists.
- Import ASR dependencies lazily.
- Create a CPU-only provider instance.
- Reuse the provider for subsequent transcription requests.

Only one transcription runs at a time. A second concurrent request returns a clear "transcription is already running" error instead of starting another CPU-heavy job.

Errors are mapped to stable error codes and Chinese user-facing messages:

- `asr_not_configured`: model path is missing.
- `asr_model_missing`: configured path does not exist.
- `asr_dependency_missing`: ASR runtime package is not installed.
- `asr_model_load_failed`: model initialization failed.
- `asr_audio_invalid`: temporary audio file is missing or unreadable.
- `asr_busy`: another transcription is already running.
- `asr_transcription_failed`: provider returned an error.

## Tauri Bridge

The frontend does not send arbitrary file paths to the sidecar. It sends WAV bytes to a Tauri command. The command:

1. Validates payload size.
2. Writes bytes to a generated file under the system temp directory.
3. Calls `/asr/transcribe` with that generated path.
4. Deletes the temp file whether transcription succeeds or fails.
5. Returns the transcript or a mapped error.

This preserves the temporary-file architecture while keeping path creation under desktop app control.

## Testing

Frontend tests cover:

- Disabled microphone state when ASR is unavailable.
- Idle, recording, timeout, transcribing, success, and failure state transitions.
- Audio-level track rendering from supplied level samples.
- Draft insertion for empty draft, append fallback, cursor insertion, selected text replacement, and edits made during transcription.
- Failure leaving the original draft unchanged.

Python sidecar tests cover:

- Missing `ALITA_ASR_MODEL_PATH` status.
- Missing model directory status.
- Missing dependency status through lazy import failure.
- Successful transcription through a fake provider.
- Busy rejection for concurrent transcription.
- Stable error mapping.

Tauri tests cover:

- Temporary audio path generation under the system temp directory.
- Temp file deletion on success and failure.
- Payload size validation.
- Sidecar error propagation.

Manual development verification covers loading a real Qwen3-ASR-1.7B model from `ALITA_ASR_MODEL_PATH`, CPU-only transcription, microphone permission behavior in the Tauri WebView, and the 60 second recording timeout.
