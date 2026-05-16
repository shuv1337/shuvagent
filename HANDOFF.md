# HANDOFF

## Objective
Get shuvagent to a first usable read-only conversational voice slice and harden
the read-only voice session enough for live validation.

## Current status
- **Done (source-complete):** M1.0–M1.8.
  - M1.6 — `OpenAIRealtimeSession` over WebSocket against
    `wss://api.openai.com/v1/realtime` (`shuvagent/realtime/openai_session.py`).
    Unit-tested via direct `_handle_event` / send-helper drives (no
    network). Gated behind `OPENAI_API_KEY`.
  - M1.7 — Read-only builtin tools in
    `shuvagent/tools/builtins/`: `get_selected_text`,
    `get_clipboard_text`, `get_active_window`, `get_shuvoice_status`.
    Backed by `shuvagent/selection.py` (wl-paste) and
    `shuvagent/window.py` (hyprctl).
  - CLI `run` is wired: starts the control server, and on
    `control start` launches a streaming `ConversationApp` against the
    real OpenAI session (when `OPENAI_API_KEY` is set), feeding it 24kHz
    PCM16 from sounddevice and piping audio out to the speaker.
    If the configured API key env var is missing, `control start` is denied
    with `missing_api_key:<ENV>` and status remains idle.
    If a background session exits after start failure, the control status is
    returned to idle.
- **Done (hardening source-complete):**
  - `ConversationApp.run_streaming()` now accepts `session_monitors`,
    starts them only after `session.connect()`, and cancels them during
    shutdown. Streaming shutdown also sends a best-effort `response.cancel`
    before closing the session and emits `realtime.response_cancel_requested`
    or `realtime.response_cancel_failed`.
  - `_SessionRunner` now wires `coordination.monitor_shuvoice()` into
    live sessions, so ShuVoice can pause/resume the Realtime session
    mid-call. Pause/resume events emit `shuvoice.mic_arbitration` with safe
    action/reason fields.
  - `_SessionRunner` now makes an explicit best-effort
    `shuvoice control tts_stop` request on every session start before opening
    the Realtime session, and emits `shuvoice.tts_stop_requested`.
  - ShuVoice pre-start arbitration now fails closed when status cannot be read
    reliably. The observed 0.5s timeout was too short while ShuVoice was
    recording, so the default/example timeout is now 2.0s.
  - `_SessionRunner` now enforces
    `config.realtime.session_max_duration_sec` via a duration-cap task
    that emits `agent.session.interrupted` with `reason=duration_cap`
    and sets the stop event. Covered by `tests/test_session_runner.py`.
  - `ConversationApp._stream_audio_out()` emits
    `realtime.first_audio_response_latency_ms` on the first model audio
    chunk.
  - Added opt-in `tests/integration/test_live_realtime.py`; skipped unless
    both `OPENAI_API_KEY` and `SHUVAGENT_RUN_LIVE_REALTIME=1` are set.
  - Added `shuvagent/usage.py` and wired `realtime.output_token_cap` into the
    streaming loop and outbound Realtime `max_output_tokens` fields. Realtime
    `response.done` usage now emits `realtime.usage`; cap crossing emits
    `agent.session.interrupted` with `reason=output_token_cap` and stops the
    session as a telemetry backstop.
  - Realtime `rate_limits.updated` and `error` events are surfaced as safe
    telemetry without raw user text. Covered by
    `tests/integration/test_streaming_loop_with_fake.py`.
  - Mic queue overflow/status paths emit content-free audio telemetry; capture
    and playback device open/write failures raise stable coded errors through
    `shuvagent/audio/runtime.py` and emit `audio.device_error` before the
    generic session failure event.
  - PLAN-02 write-tool foundation exists as opt-in builtins:
    `paste_text`, `replace_selected_text`, and `copy_to_clipboard`. They are
    not in the default live read-only tool set yet; tests cover default denial,
    confirmation-required paths, focus invalidation for visible writes, command
    execution with fakes, and redaction-safe result summaries.
- **Live verified:** `shuvagent doctor`, the opt-in live Realtime WebSocket
  smoke, synthetic selected-text tool round trip with model audio bytes,
  foreground `shuvagent run`, and control-socket
  `status/start/status/stop/status` against the live backend.
- **Not done:** human microphone/speaker QA and real ShuVoice arbitration
  drills from `docs/live-validation-checklist.md`.

## Validation status
- `uv run ruff check .` — clean.
- `uv run pytest` — **112 passed, 3 skipped** (paid live Realtime tests skipped
  in the normal suite).
- `uv run mypy` — clean (23 strict source files).
- `uv run shuvagent doctor` — pass with `$OPENAI_API_KEY` set and all desktop
  probes available.
- Live `SHUVAGENT_RUN_LIVE_REALTIME=1 uv run pytest tests/integration/test_live_realtime.py -q` — **2 passed in 10.55s**.
- Live `uv run shuvagent run` + control socket:
  `OK idle`, `OK started session=...`, `OK active session=...`, `OK stopped`,
  `OK idle`.
- Real Wayland context probe with synthetic content: primary selection present,
  clipboard present, and `hyprctl activewindow -j` returned an active window.
- `sounddevice.check_input_settings` and `check_output_settings` passed for
  24 kHz mono PCM16 on default devices.
- Actual shuvagent audio helpers ran locally: `_mic_stream()` yielded a
  non-empty PCM chunk without telemetry errors, and `_speaker_playback()` wrote
  a 20 ms silent PCM buffer.
- Live duration-cap drill with a temporary 2-second config emitted
  `agent.session.interrupted reason=duration_cap`, duration/usage/cancel
  telemetry, and returned control status to `OK idle`.
- Direct live output-token accounting drill with `max_output_tokens=1` returned
  Realtime usage `output_tokens=1`; `UsageTracker(output_token_cap=1)` returned
  `reason=output_token_cap` with no API errors.
- Live ShuVoice idle CLI probe returned `OK idle`; `shuvoice control tts_stop`
  returned `OK tts already idle`; status remained `OK idle`.
- Live foreground/control start emitted `shuvoice.tts_stop_requested ok=true`
  before `agent.session.start_requested` / `agent.session.connected`; control
  stop returned status to `OK idle`.
- Live telemetry privacy probe with synthetic selected/clipboard text emitted
  lifecycle, TTS-stop, duration, usage, and cancel events without raw synthetic
  selected text, clipboard text, or API key.
- Live ShuVoice pre-start recording drill passed: `shuvoice control status`
  returned `OK recording`; `shuvagent control start` returned
  `ERROR start denied: shuvoice-recording`; shuvagent status stayed `OK idle`;
  ShuVoice returned to `OK idle` after stop.
- Live ShuVoice mid-session recording drill passed: active shuvagent session
  remained active while ShuVoice recorded, emitted
  `shuvoice.mic_arbitration action=pause reason=shuvoice-took-mic`, then
  emitted `action=resume reason=shuvoice-released-mic` after ShuVoice stopped.
- Live ShuVoice active-TTS arbitration drill passed: `shuvoice control
  tts_status` returned `OK playing` before shuvagent start; shuvagent emitted
  `shuvoice.tts_stop_requested ok=true` before connecting; TTS status returned
  `OK idle` after start.

## Key context
- `cli.py._SessionRunner` bridges control-socket start/stop to a
  background streaming session task. Only one active session at a time;
  `control stop` waits up to 5s for graceful shutdown.
- Pre-start ShuVoice arbitration still comes from `ControlServer`'s
  default `start_decision=can_start_agent_session`. Mid-session
  arbitration is now handled by a monitor passed to
  `ConversationApp.run_streaming()`.
- Mic capture in `cli.py._mic_stream` uses a `sounddevice.RawInputStream`
  callback that pushes 20 ms PCM16 blocks (480 frames @ 24 kHz) into an
  asyncio queue and emits content-free telemetry for status/overflow.
- Speaker playback is a tiny async wrapper around
  `sounddevice.RawOutputStream` — opened lazily on first chunk so
  headless test runs don't touch PortAudio.
- Read tool results include `text` (the model needs it) plus
  `text_len` + `text_sha256_prefix` (redaction-safe summary for audit).
- `tests/integration/test_streaming_loop_with_fake.py` now asserts that
  session monitors run after connect and that first-audio latency
  telemetry is emitted.

## Important files
- `PLAN-01-bootstrap-and-first-slice.md` — milestone definitions / exit gates.
- `shuvagent/realtime/openai_session.py` — live WS implementation; strict mypy-covered.
- `shuvagent/tools/builtins/` — read-only tool catalogue,
  `default_read_only_tools()`, and opt-in PLAN-02 write specs via
  `default_write_tools()`.
- `shuvagent/selection.py`, `shuvagent/window.py` — desktop I/O helpers.
- `shuvagent/app.py` — `ConversationApp.run_streaming()`, first-audio telemetry, usage/rate-limit/error handling, session monitor lifecycle; strict mypy-covered.
- `shuvagent/cli.py` — `_SessionRunner`, duration cap, token cap wiring, ShuVoice monitor wiring, `_mic_stream`, `_speaker_playback`; strict mypy-covered.
- `shuvagent/control.py` — control socket lifecycle and finished-session cleanup; strict mypy-covered.
- `shuvagent/audio/runtime.py` — content-free audio status/overflow telemetry helpers and stable audio runtime error codes.
- `shuvagent/doctor.py` — live-validation preflight checks for config,
  credentials, optional desktop helpers, and Python audio/network modules.
- `shuvagent/usage.py` — token usage parsing/tracking and rate-limit parsing.
- `tests/test_openai_session.py` — wire-format lock-down (no network).
- `tests/test_session_runner.py` — duration-cap interruption behavior.
- `tests/integration/test_streaming_loop_with_fake.py` — full streaming loop against `FakeRealtimeSession`.
- `tests/integration/test_live_realtime.py` — opt-in live WebSocket smoke and
  selected-text tool round trip.
- `docs/live-validation-checklist.md` — release-owner checklist for live
  Realtime, hardware audio, selected text, ShuVoice arbitration, safety caps,
  and telemetry.
- `docs/issue-1-completion-audit.md` — prompt-to-artifact evidence map and
  explicit list of unverified live gates.

## Next steps
1. **Run manual hardware QA** with `docs/live-validation-checklist.md`,
   especially spoken mic input, speaker playback, selected-text Q&A by voice,
   stop during active model speech, and a foreground/control-socket
   output-token-cap stop drill.
2. **Consider further strict mypy expansion** to remaining modules once
   runtime APIs settle.

## Risks / open questions
- The Realtime API wire format used here matches the GA shape in current
  OpenAI docs: no beta header, `type=realtime`, nested `audio.input/output`,
  `output_modalities`, and GA `response.output_audio.delta` /
  `response.output_item.done` events. If OpenAI ships breaking changes,
  lock-down tests in `test_openai_session.py` will need updating.
- The live smoke opens/closes a Realtime session and waits briefly for async
  session-update errors. It still does not verify spoken microphone input or
  actual speaker playback because those require human/hardware QA.
- License file still "TBD" in README — non-blocking.
