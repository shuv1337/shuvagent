# HANDOFF

## Objective
Get shuvagent to a first usable read-only conversational voice slice.
PLAN-01 milestones M1.0–M1.8 are source-complete. This session continued
post-M1.7 hardening: mid-session ShuVoice arbitration, duration-cap stop,
first-audio telemetry, and an opt-in live Realtime smoke test.

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
- **New hardening completed after source-complete checkpoint:**
  - `ConversationApp.run_streaming()` now accepts `session_monitors`,
    starts them only after `session.connect()`, and cancels them during
    shutdown.
  - `_SessionRunner` now wires `coordination.monitor_shuvoice()` into
    live sessions, so ShuVoice can pause/resume the Realtime session
    mid-call.
  - `_SessionRunner` now enforces
    `config.realtime.session_max_duration_sec` via a duration-cap task
    that emits `agent.session.interrupted` with `reason=duration_cap`
    and sets the stop event.
  - `ConversationApp._stream_audio_out()` emits
    `realtime.first_audio_response_latency_ms` on the first model audio
    chunk.
  - Added opt-in `tests/integration/test_live_realtime.py`; skipped
    unless both `OPENAI_API_KEY` and `SHUVAGENT_RUN_LIVE_REALTIME=1`
    are set.
- **Not done:** live hardware smoke/manual QA (§13.2 of PLAN-01), token
  output cap, audio overflow telemetry.

## Validation status
- `uv run ruff check .` — clean.
- `uv run pytest -q` — **55 passed, 1 skipped** (live Realtime smoke skipped).
- `uv run mypy` — clean (12 strict source files).
- Live `OPENAI_API_KEY=... SHUVAGENT_RUN_LIVE_REALTIME=1 uv run pytest tests/integration/test_live_realtime.py` — **not run**.
- Live `uv run shuvagent run` + voice I/O — **not run** in this session.

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
  asyncio queue.
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
- `shuvagent/realtime/openai_session.py` — live WS implementation.
- `shuvagent/tools/builtins/` — read-only tool catalogue + `default_read_only_tools()`.
- `shuvagent/selection.py`, `shuvagent/window.py` — desktop I/O helpers.
- `shuvagent/app.py` — `ConversationApp.run_streaming()`, first-audio telemetry, session monitor lifecycle.
- `shuvagent/cli.py` — `_SessionRunner`, duration cap, ShuVoice monitor wiring, `_mic_stream`, `_speaker_playback`.
- `tests/test_openai_session.py` — wire-format lock-down (no network).
- `tests/integration/test_streaming_loop_with_fake.py` — full streaming loop against `FakeRealtimeSession`.
- `tests/integration/test_live_realtime.py` — opt-in live WebSocket smoke.

## Next steps
1. **Run opt-in live Realtime smoke** when API credentials are available:
   ```bash
   OPENAI_API_KEY=... SHUVAGENT_RUN_LIVE_REALTIME=1 \
     uv run pytest tests/integration/test_live_realtime.py -q
   ```
2. **Run manual hardware QA** from PLAN-01 §13.2:
   - `uv run shuvagent run` in one terminal.
   - `uv run shuvagent control start` in another; speak; verify reply.
   - Select text and ask "what does this say?"; verify the model calls
     `get_selected_text` and answers using the selected text.
   - `uv run shuvagent control stop`; verify speech stops promptly.
   - Start while ShuVoice records; verify clear denial.
   - Start ShuVoice PTT mid-agent-session; verify pause/resume behavior.
3. **Implement output token cap** from PLAN-01 §10:
   - Add `RealtimeConfig.session_max_output_tokens` default `20_000`.
   - Parse token/rate-limit usage events in `OpenAIRealtimeSession`.
   - Emit `cost.audio_output_tokens` / close on cap.
4. **Add audio overflow telemetry** in `_mic_stream` (queue full/status
   path should emit `audio.overflow`; current implementation silently drops).
5. **Consider strict mypy expansion** to `shuvagent/app.py`,
   `shuvagent/cli.py`, and `shuvagent/realtime/openai_session.py` once
   runtime APIs settle.

## Risks / open questions
- The Realtime API wire format used here matches the v1 beta as of
  May 2026. If OpenAI ships breaking changes, lock-down tests in
  `test_openai_session.py` will need updating.
- The live smoke currently opens/closes a Realtime session only; it does
  not verify first audio because that requires microphone/hardware flow
  and potentially paid token usage.
- `_mic_stream` drops audio on queue overflow silently — acceptable for
  v1 but should emit `audio.overflow` telemetry per PLAN-01 §8.1.
- License file still "TBD" in README — non-blocking.
