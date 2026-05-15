# HANDOFF

## Objective
Get shuvagent to a first usable read-only conversational voice slice.
PLAN-01 milestones M1.0–M1.8 are now all implemented in source.
Remaining work is **live validation** (manual QA + opt-in smoke test).

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
  - CLI `run` is now wired: starts the control server, and on
    `control start` launches a streaming `ConversationApp` against the
    real OpenAI session (when `OPENAI_API_KEY` is set), feeding it 24kHz
    PCM16 from sounddevice and piping audio out to the speaker.
  - `ConversationApp.run_streaming()` is the new public entrypoint for
    long-running sessions (the old `run_once` remains for the existing
    integration test).
  - Added `websockets>=13.0` to `pyproject.toml` deps. Mypy strict now
    also covers `shuvagent/selection.py` and `shuvagent/window.py`.
- **Not done:** live smoke test, manual QA checklist (§13.2 of PLAN-01).

## Validation status
- `uv run pytest` — **55 passed**.
- `uv run ruff check .` — clean.
- `uv run mypy` — clean (12 source files under strict).
- `uv run shuvagent --help` — works.
- Live `OPENAI_API_KEY=... shuvagent run` — **not yet executed** on
  hardware. This is the remaining gate.

## Key context
- `cli.py._SessionRunner` bridges control-socket start/stop to a
  background streaming session task. Only one active session at a time;
  `control stop` waits up to 5s for graceful shutdown.
- Mic capture in `cli.py._mic_stream` uses a `sounddevice.RawInputStream`
  callback that pushes 20 ms PCM16 blocks (480 frames @ 24 kHz) into an
  asyncio queue.
- Speaker playback is a tiny async wrapper around
  `sounddevice.RawOutputStream` — the stream is opened lazily on the
  first chunk so headless test runs don't touch PortAudio.
- `OpenAIRealtimeSession` exposes Protocol-compatible attributes
  (`audio_out`, `tool_calls`, `errors`, `state`, `is_open`) and adds
  `pause()` / `resume()` so `coordination.monitor_shuvoice` can also
  drive it (same Protocol shape as `FakeRealtimeSession`).
- Tool specs are passed into the session at connect time so
  `session.update.tools` mirrors what the registry will accept.
- Read tool results include `text` (the model needs it) plus
  `text_len` + `text_sha256_prefix` (redaction-safe summary for audit).

## Important files
- `PLAN-01-bootstrap-and-first-slice.md` — milestone definitions / exit gates.
- `shuvagent/realtime/openai_session.py` — live WS implementation.
- `shuvagent/tools/builtins/` — read-only tool catalogue + `default_read_only_tools()`.
- `shuvagent/selection.py`, `shuvagent/window.py` — desktop I/O helpers.
- `shuvagent/app.py` — `ConversationApp.run_streaming()` entrypoint.
- `shuvagent/cli.py` — `_SessionRunner`, `_mic_stream`, `_speaker_playback`.
- `tests/test_openai_session.py` — wire-format lock-down (no network).
- `tests/integration/test_streaming_loop_with_fake.py` — full streaming
  loop against `FakeRealtimeSession`.
- `tests/test_builtin_tools.py`, `tests/test_selection.py`, `tests/test_window.py`.

## Next steps
1. **Live smoke test.** With `OPENAI_API_KEY` set:
   - `uv run shuvagent run` in one shell.
   - `uv run shuvagent control start` in another; speak; verify reply.
   - Verify `get_selected_text` round-trip by selecting some text and
     asking "what does this say?".
   - Add `tests/integration/test_live_realtime.py` (skipped without API
     key) per §9.4 of PLAN-01.
2. **Run the manual QA checklist** in PLAN-01 §13.2 and check the
   boxes. Capture issues as separate plans.
3. **Wire `coordination.monitor_shuvoice`** into `_SessionRunner` so
   live sessions pause when ShuVoice grabs the mic. (Currently the
   pre-start check happens via `ControlServer.start_decision`, but
   mid-session arbitration isn't connected yet.)
4. **Session duration / token caps** (PLAN-01 §10) — wire the
   `realtime.session_max_duration_sec` hard cap into `_SessionRunner`
   (asyncio.wait_for around the streaming task).
5. **Telemetry pass:** `_SessionRunner` already emits lifecycle
   events; consider adding `realtime.first_audio_response_latency_ms`
   inside `OpenAIRealtimeSession._handle_event` when the first
   `response.audio.delta` arrives.

## Risks / open questions
- The Realtime API wire format used here matches the v1 beta as of
  May 2026. If OpenAI ships breaking changes, lock-down tests in
  `test_openai_session.py` will need updating — they assert on
  `session.update`, `input_audio_buffer.append/commit`,
  `response.audio.delta`, `response.function_call_arguments.done`.
- `_mic_stream` drops audio on queue overflow silently — acceptable
  for v1 but should emit `audio.overflow` telemetry per PLAN-01 §8.1.
- License file still "TBD" in README — non-blocking.
