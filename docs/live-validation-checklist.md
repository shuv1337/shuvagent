# Live Validation Checklist

Use this checklist before treating the read-only voice slice as
production-validated. These checks intentionally require a real
Linux/Hyprland desktop, PipeWire/PortAudio devices, ShuVoice on `PATH`,
`wl-paste`, `hyprctl`, an OpenAI API key for the default provider, and a
Google API key for the opt-in Gemini/Pipecat provider check.

## Preconditions

- `uv sync` has completed.
- `~/.config/shuvagent/config.toml` exists and includes sane safety caps:
  - `realtime.session_max_duration_sec > 0`
  - `0 < realtime.output_token_cap <= 4096`
- `~/.config/shuvagent/local.dev` contains `OPENAI_API_KEY=...` for OpenAI
  validation.
- Gemini/Pipecat validation uses a temporary config with
  `realtime.provider = "gemini"` and `GOOGLE_API_KEY=...`.
- `shuvoice control status` returns a status or fails cleanly when ShuVoice is
  not running.
- `wl-paste --primary --no-newline` works for selected text on this desktop.
- `hyprctl activewindow -j` works for active-window context.

## Automated Live Smoke

Run the local prerequisite doctor first. It must not print secret values:

```bash
uv run shuvagent doctor
```

Expected result:

- Config and safety caps pass.
- `$OPENAI_API_KEY` is reported as set.
- `sounddevice` and `websockets` are available.
- Missing optional desktop helpers are reported as `WARN`, not as leaked raw
  desktop content.

`shuvagent doctor` and `shuvagent run` load `~/.config/shuvagent/local.dev`.
The pytest smoke runs as a test process, so source the env file explicitly
before running it. It must open and close a live WebSocket session with the
configured model, voice, and tool schema:

```bash
set -a
. ~/.config/shuvagent/local.dev
set +a
SHUVAGENT_RUN_LIVE_REALTIME=1 uv run pytest tests/integration/test_live_realtime.py -q
```

Expected result:

- The test passes.
- It is not skipped.
- No raw selected text, clipboard text, transcripts, or API key appears in the
  output.

## Gemini Live Via Pipecat

Create a temporary config that selects Gemini Live:

```toml
[realtime]
provider = "gemini"
model = "models/gemini-3.1-flash-live-preview"
api_key_env = "GOOGLE_API_KEY"
voice = "Charon"
session_max_duration_sec = 300
output_token_cap = 800
request_timeout_sec = 10.0
```

Then run the same foreground/control and voice-path checks with
`GOOGLE_API_KEY` loaded:

```bash
set -a
. ~/.config/shuvagent/local.dev
set +a
uv run shuvagent --config /path/to/gemini-config.toml run
```

The opt-in live connection smoke can be run before the hardware pass:

```bash
GOOGLE_API_KEY=... SHUVAGENT_RUN_LIVE_GEMINI=1 \
  uv run pytest tests/integration/test_live_gemini.py -q
```

Expected result:

- The session is constructed through Pipecat's `GeminiLiveLLMService`.
- Mic audio is sent as PCM with an explicit sample rate and model audio is
  returned as 24 kHz PCM.
- Read-only tool calls still route through `ToolRegistry -> PermissionGate ->
  handler -> audit event`.
- Missing `GOOGLE_API_KEY` denies `control start` with
  `missing_api_key:GOOGLE_API_KEY`.
- The same safe telemetry boundaries apply; no transcripts, selected text, or
  API keys appear in logs by default.

## Issue #1 Closure Gates

Issue #1 should remain open until all of these target-desktop checks have
fresh evidence:

- [ ] Spoken microphone input through `uv run shuvagent run` +
  `uv run shuvagent control start`.
- [ ] Audible model speech through the default speaker.
- [ ] Spoken selected-text Q&A using real `wl-paste --primary` selected text.
- [ ] Gemini Live/Pipecat session with `GOOGLE_API_KEY` using
  `models/gemini-3.1-flash-live-preview`.
- [x] `uv run shuvagent control stop` interrupts active model speech promptly.
- [x] A foreground/control-socket session with `output_token_cap = 1` stops via
  `agent.session.interrupted reason=output_token_cap` through the mic path.

Safe evidence to record:

- The control command outputs (`OK started`, `OK active`, `OK stopped`,
  `OK idle`).
- The safe telemetry event names and structured reasons.
- Expected safe events for the final human run:
  `audio.capture_chunk`, `realtime.first_audio_response_latency_ms`,
  `audio.playback_chunk`, `tool.requested`, `tool.executed`, and
  `agent.session.stopped`.
- `sounddevice`/doctor pass/fail status.
- Confirmation that audio was heard, without including transcripts or raw
  selected text.

Do not close the GitHub issue from automated tests alone. The live Realtime
smoke proves API/tool compatibility; it does not prove human-audible playback
or spoken microphone-path behavior.

Use this command to print the same closure gates alongside the doctor preflight:

```bash
uv run shuvagent issue1-qa
```

## Foreground Process And Control Socket

Without an API key loaded, `control start` must fail safely:

Terminal 1:

```bash
env -u OPENAI_API_KEY uv run shuvagent run
```

Terminal 2:

```bash
env -u OPENAI_API_KEY uv run shuvagent control start
env -u OPENAI_API_KEY uv run shuvagent control status
```

Expected result:

- `start` returns `ERROR start denied: missing_api_key:OPENAI_API_KEY`.
- `status` remains `OK idle`.

With an API key loaded, verify normal foreground and control behavior.

Terminal 1:

```bash
uv run shuvagent run
```

Terminal 2:

```bash
uv run shuvagent control status
uv run shuvagent control start
uv run shuvagent control status
uv run shuvagent control stop
uv run shuvagent control status
```

Expected result:

- `run` stays foreground and reports the control socket path.
- `start` returns `OK started session=...`.
- active `status` includes `OK active session=...`.
- `stop` returns `OK stopped` promptly.
- final `status` returns `OK idle`.

## Voice Path

1. Start `uv run shuvagent run`.
2. Start a session with `uv run shuvagent control start`.
3. Ask a short spoken question.
4. Listen for a concise spoken answer.
5. Stop with `uv run shuvagent control stop`.

Expected result:

- Mic audio is accepted at 24 kHz PCM16 without device errors.
- `audio.capture_chunk` emits once with a byte count and no audio content.
- Speaker playback uses the default output device.
- First model audio emits `realtime.first_audio_response_latency_ms`.
- `audio.playback_chunk` emits with byte counts and no audio content.
- Stop interrupts speech promptly.

## Selected Text Q&A

1. Select a short paragraph in any Hyprland window.
2. Start a session.
3. Ask: "What does the selected text mean?"

Expected result:

- The model answers using the selected text.
- Telemetry/audit output includes only safe summaries such as length or hash
  prefix, not raw selected text.
- `debug_log_raw_text = false` remains the default.

## ShuVoice Arbitration

Pre-start denial:

1. Hold ShuVoice push-to-talk so `shuvoice control status` reports recording.
2. Run `uv run shuvagent control start`.

Expected result:

- The command returns `ERROR start denied: shuvoice-recording`.
- No shuvagent mic session starts.

Mid-session pause/resume:

1. Start a shuvagent session.
2. Trigger ShuVoice recording during the session.
3. Release ShuVoice recording.

Expected result:

- shuvagent pauses when ShuVoice records.
- shuvagent resumes after ShuVoice releases the mic.
- Realtime receives `input_audio_buffer.clear` and `response.cancel` during
  pause.
- The session does not need to be restarted to continue.
- Telemetry emits `shuvoice.mic_arbitration` with `action=pause` and
  `action=resume` without raw transcript or selected text.

TTS arbitration:

1. Start ShuVoice TTS.
2. Start a shuvagent session.

Expected result:

- shuvagent calls `shuvoice control tts_stop` before using its own voice.
- Telemetry emits `shuvoice.tts_stop_requested` with `ok=true` when the stop
  request succeeds.

## Safety Caps And Telemetry

Use a temporary config with a short duration cap:

```toml
[realtime]
session_max_duration_sec = 2
output_token_cap = 800
```

Expected result:

- A forgotten session stops around the duration cap.
- Telemetry emits `agent.session.interrupted` with `reason=duration_cap`.
- Completed sessions emit `agent.session.duration_ms`.

Use a temporary config with a small output token cap:

```toml
[realtime]
session_max_duration_sec = 300
output_token_cap = 1
```

Expected result:

- A response that crosses the cap stops the session.
- Telemetry emits `realtime.usage`, `realtime.usage.summary`, and
  `agent.session.interrupted` with `reason=output_token_cap`.

## Failure Evidence To Capture

If any step fails, capture only safe diagnostics:

```bash
uv run shuvagent control status
shuvoice control status
hyprctl activewindow -j
```

Do not paste raw selected text, clipboard contents, transcripts, or API keys
into logs or issue comments unless `debug_log_raw_text = true` was explicitly
enabled for a private diagnostic run.
