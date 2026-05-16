# Issue 1 Completion Audit

Issue: `PRD: Live validation and production hardening for read-only voice slice`

Status: source hardening, local validation, live OpenAI Realtime smoke,
foreground/control-socket live smoke, ShuVoice arbitration drills, and the
foreground microphone-path `output_token_cap = 1` drill are complete. The issue
is not release-complete until the remaining human/hardware-driven microphone,
speaker, spoken selected-text Q&A, and active-speech stop acceptance gates pass.

## Local Evidence

| Requirement area | Evidence |
|---|---|
| Foreground process and control socket | `uv run shuvagent run`; `uv run shuvagent status/start/stop`; `tests/test_control_socket.py` |
| Missing API key start denial | `_start_decision()` denies `control start` before a false active session can be reported; `tests/test_session_runner.py`; `tests/test_control_socket.py` |
| Background session cleanup | `ControlServer.finish_session()` returns status to idle when the background session exits; `tests/test_control_socket.py` |
| ShuVoice pre-start denial | `shuvagent/coordination.py`; `tests/test_coordination.py`; live `shuvoice control start` recording drill |
| ShuVoice mid-session pause/resume | `ConversationApp.run_streaming(session_monitors=...)`; `monitor_shuvoice`; `tests/test_coordination.py`; live mid-session recording drill |
| Stop handling is bounded | `_SessionRunner.handle_stop()` waits up to 5 seconds before canceling; `ConversationApp.run_streaming()` sends best-effort `response.cancel` before close and emits `realtime.response_cancel_requested` or `realtime.response_cancel_failed` |
| 24 kHz mic and speaker path | `_mic_stream()` and `_speaker_playback()` use 24 kHz PCM16 sounddevice streams |
| First-audio latency | `realtime.first_audio_response_latency_ms`; `tests/integration/test_streaming_loop_with_fake.py` |
| Duration cap | `_stop_after_duration_cap()`; `tests/test_session_runner.py` |
| Output token cap | Realtime `max_output_tokens` in `session.update` / `response.create`; `shuvagent/usage.py` backstop; `tests/test_openai_session.py`; `tests/test_usage.py`; `tests/integration/test_streaming_loop_with_fake.py`; live foreground/control mic-path cap drill |
| Read-only selected text, clipboard, active window, ShuVoice status tools | `shuvagent/tools/builtins/`; `tests/test_builtin_tools.py` |
| Opt-in PLAN-02 write tools | `paste_text`, `replace_selected_text`, `copy_to_clipboard`; `tests/test_write_tools.py`; not registered in the default live read-only tool set |
| Permission gate remains in tool path | `ConversationApp._execute_tool_call()`; `tests/test_tool_policy.py` |
| Privacy/redaction | `shuvagent/telemetry/redact.py`; `tests/test_redaction.py`; streaming tool telemetry excludes raw tool results; no doctor output renders API keys |
| Opt-in live Realtime smoke | `tests/integration/test_live_realtime.py`; skipped without both API key and explicit flag; passed with credentials and `SHUVAGENT_RUN_LIVE_REALTIME=1`, including the full default read-only tool round |
| Realtime wire format | `tests/test_openai_session.py`; live smoke caught and fixed stale beta header/session payload drift; GA output audio and function-call item events are covered |
| Rate-limit/API error telemetry | `RealtimeApiEvent`; `ConversationApp._stream_api_events()`; `tests/test_openai_session.py`; `tests/test_usage.py` |
| Audio overflow/status/device error telemetry | `shuvagent/audio/runtime.py`; `audio.device_error`; `tests/test_audio_runtime.py`; `tests/test_session_runner.py` |
| Stderr lifecycle status indicator | `_SessionRunner` status writer; `tests/test_cli.py`; `tests/test_session_runner.py` |
| Config reload | SIGHUP handler in `shuvagent.cli`; safety cap mutation; invalid reload preservation; active-session voice deferral; `tests/test_cli.py` |
| Issue #1 live QA helper | `uv run shuvagent issue1-qa`; `shuvagent/live_qa.py`; `tests/test_live_qa.py`; prints remaining closure gates and safe evidence guidance |
| Config validation for voices/safety caps | `AppConfig.validate()`; `tests/test_config.py` |
| Example config schema alignment | `examples/config.toml`; `tests/test_config.py::test_example_config_matches_current_schema` |
| Strict type coverage where stable | `pyproject.toml`; `uv run mypy` over 24 source files, including `shuvagent/app.py`, `shuvagent/cli.py`, `shuvagent/control.py`, and `shuvagent/realtime/openai_session.py` |
| Live prerequisite preflight | `uv run shuvagent doctor`; `tests/test_doctor.py` |
| Manual release checklist | `docs/live-validation-checklist.md` |

## Prompt-To-Artifact Checklist

| Issue requirement | Status | Evidence |
|---|---:|---|
| US1 `shuvagent run` foreground process | verified live | foreground smoke printed socket path and ready state |
| US2 `shuvagent control start` opens live session | verified live | `OK started session=...`; telemetry `agent.session.connected` |
| US3 `shuvagent control stop` stops session | verified live | `OK stopped`; final `OK idle`; cancel telemetry emitted |
| US4 refuse start while ShuVoice records | verified live | `coordination.can_start_agent_session`; `tests/test_coordination.py`; live ShuVoice recording drill returned `ERROR start denied: shuvoice-recording` and shuvagent status stayed `OK idle` |
| US5 pause if ShuVoice records mid-session | verified live | `monitor_shuvoice`; fake tests; live drill emitted `shuvoice.mic_arbitration action=pause reason=shuvoice-took-mic` while status was `OK recording` |
| US6 resume after ShuVoice releases mic | verified live | `monitor_shuvoice`; fake tests; live drill emitted `shuvoice.mic_arbitration action=resume reason=shuvoice-released-mic` after ShuVoice returned to `OK idle` |
| US7 stop ShuVoice TTS before session | verified live | `_SessionRunner._run_session` calls `shuvoice_tts_stop` before constructing the live session and emits `shuvoice.tts_stop_requested`; `tests/test_session_runner.py`; live active-TTS drill saw `OK playing` before start, `shuvoice.tts_stop_requested ok=true` before `agent.session.connected`, and `OK idle` after start |
| US8 stream mic audio at expected sample rate | partial live | `_mic_stream` uses 24 kHz PCM16; `sounddevice.check_input_settings` passed; live `_mic_stream` yielded a non-empty chunk; spoken mic QA pending |
| US9 play model audio through default speaker | partial live | `_speaker_playback`; `sounddevice.check_output_settings` passed; live `_speaker_playback` wrote a 20 ms silent PCM buffer; audible speaker QA pending |
| US10 first-audio latency measured | local/fake verified | `realtime.first_audio_response_latency_ms`; streaming fake tests |
| US11 hard duration cap | verified live | `_stop_after_duration_cap`; `tests/test_session_runner.py`; live 2-second config returned status to idle |
| US12 output token cap | verified live | config validation, Realtime payload tests, usage tests; live foreground/control mic-path drill with `output_token_cap=1` emitted `agent.session.interrupted reason=output_token_cap` |
| US13 selected-text Q&A end-to-end | partial | live synthetic selected-text tool round trip produced model audio bytes; spoken mic-driven Q&A pending |
| US14 clipboard read-only | local/desktop verified | real clipboard helper returned safe summary; write specs are opt-in only and default live registration remains read-only |
| US15 active-window context | desktop verified | real `hyprctl activewindow -j` returned active app/title summary |
| US16 ShuVoice status read-only tool | local/CLI verified | builtin tool tests and live `shuvoice control status` probe returned `OK idle` |
| US17 no raw private text/API keys in logs | live/local verified | redaction tests, tool telemetry regression, doctor output; live foreground run with synthetic selection/clipboard emitted no raw synthetic text |
| US18 raw-text logging requires debug flag | local verified | telemetry sink/redaction tests |
| US19 opt-in live Realtime smoke | verified live | skipped by default; passed only with explicit flag |
| US20 live smoke opens/closes WebSocket | verified live | `tests/integration/test_live_realtime.py` passed with credentials |
| US21 fake-session streaming coverage | local verified | `tests/integration/test_streaming_loop_with_fake.py` |
| US22 monitor tasks start after connect/cancel on shutdown | local verified | streaming fake monitor tests |
| US23 graceful bounded stop handling | live/local verified | live control stop; 5s bounded stop code path |
| US24 audio overflow telemetry | local verified | `shuvagent/audio/runtime.py`; `tests/test_audio_runtime.py` |
| US25 audio device error telemetry | local verified | `AudioRuntimeError`; `tests/test_session_runner.py` |
| US26 Realtime rate-limit telemetry | local verified | `rate_limits.updated` parser/streaming tests |
| US27 token usage telemetry | local verified | usage parser/tracker and streaming tests |
| US28 session duration telemetry | live/local verified | live `agent.session.duration_ms`; fake tests |
| US29 Maple-compatible structured JSON events | local verified | telemetry schema/sink used across emitted events |
| US30 stable safe error codes/messages | local verified | realtime/audio error tests and safe telemetry fields |
| US31 Realtime wire-format tests | live/local verified | GA payload tests plus live smoke caught stale shape |
| US32 config validation for voices/safety caps | local verified | `tests/test_config.py` |
| US33 README/HANDOFF distinguish source/live validation | verified | README, HANDOFF, this audit updated |
| US34 audio runtime isolated | verified | `shuvagent/audio/runtime.py` |
| US35 usage tracker isolated | verified | `shuvagent/usage.py` |
| US36 lifecycle orchestration isolated from CLI parsing | verified | `_SessionRunner`; control tests |
| US37 read-only tools use permission gate | verified | `ConversationApp._execute_tool_call`; policy tests |
| US38 usage/rate-limit fixtures | verified | usage and streaming fake tests |
| US39 mypy coverage expanded where stable | verified | `uv run mypy` over 23 strict source files |
| US40 manual QA checklist | verified artifact | `docs/live-validation-checklist.md`; execution pending |
| Out of scope remains out of scope | verified | no write tools, persistent memory, overlay, MCP, WebRTC, Maple export, or ShuVoice repo edits |

## Current Validation Commands

Last local validation:

```bash
uv run ruff check .
uv run mypy
uv run pytest
uv run shuvagent doctor
SHUVAGENT_RUN_LIVE_REALTIME=1 uv run pytest tests/integration/test_live_realtime.py -q
```

Current result:

- `ruff`: pass.
- `mypy`: pass for 24 strict source files.
- `pytest`: pass with the paid live Realtime tests skipped when the explicit
  flag is absent (`194 passed, 3 skipped` after the Realtime duplicate tool-call
  regression test).
- `doctor`: pass with config, safety caps, `$OPENAI_API_KEY`, `sounddevice`,
  `websockets`, `shuvoice`, `wl-paste`, and `hyprctl`.
- opt-in live Realtime smoke and selected-text tool round trip: pass, not skipped.
- `uv run shuvagent issue1-qa`: pass; prints doctor preflight and the five
  remaining target-desktop closure gates.
- outbound Realtime frames include `max_output_tokens` matching
  `realtime.output_token_cap`.

Current live-smoke evidence:

```bash
SHUVAGENT_RUN_LIVE_REALTIME=1 uv run pytest tests/integration/test_live_realtime.py -q
# ...                                                                      [100%]
# 3 passed in 37.34s
```

`uv run shuvagent doctor` reports all checks passing, including the API key and
desktop helper probes. It does not print the secret value.

Current foreground/control evidence:

```bash
uv run shuvagent control status
# OK idle
uv run shuvagent control start
# OK started session=...
uv run shuvagent control status
# OK active session=...
uv run shuvagent control stop
# OK stopped
uv run shuvagent control status
# OK idle
```

Foreground telemetry emitted `agent.session.connected`,
`agent.session.duration_ms`, `realtime.usage.summary`,
`realtime.response_cancel_requested`, and `agent.session.stopped`. After the
explicit TTS-stop hardening, foreground start also emitted
`shuvoice.tts_stop_requested ok=true` before `agent.session.start_requested` and
`agent.session.connected`.

Current desktop helper evidence with synthetic selection/clipboard content:

```text
selection_present=True, selection_len=47, selection_hash_len=12
clipboard_present=True, clipboard_len=48, clipboard_hash_len=12
active_window_app=com.mitchellh.ghostty, active_window_title_len=18
live_selected_text_round_trip=True, audio_bytes_gt_zero=True, errors=0
sounddevice_input_24khz_pcm16_ok=True
sounddevice_output_24khz_pcm16_ok=True
live_mic_stream_chunk_bytes_gt_zero=True
live_speaker_playback_silent_write_ok=True
shuvoice_status_before_tts_stop=OK idle
shuvoice_tts_stop=OK tts already idle
shuvoice_status_after_tts_stop=OK idle
live_privacy_probe_selection_raw_absent=True
live_privacy_probe_clipboard_raw_absent=True
```

Current live privacy telemetry evidence:

```text
synthetic selected text set: privacy synthetic selected text should not appear
synthetic clipboard text set: privacy synthetic clipboard text should not appear
foreground events observed: shuvoice.tts_stop_requested, agent.session.start_requested,
agent.session.connected, agent.session.interrupted, agent.session.duration_ms,
realtime.usage.summary, realtime.response_cancel_requested, agent.session.stopped
raw synthetic selected text in telemetry: false
raw synthetic clipboard text in telemetry: false
api key in telemetry: false
```

Current missing-key control evidence:

```bash
env -u OPENAI_API_KEY uv run shuvagent --config <temp-config> start
# ERROR start denied: missing_api_key:OPENAI_API_KEY
env -u OPENAI_API_KEY uv run shuvagent --config <temp-config> status
# OK idle
```

Current invalid-connection cleanup evidence:

```bash
OPENAI_API_KEY=sk-test-invalid uv run shuvagent --config <temp-config> start
# OK started session=...
OPENAI_API_KEY=sk-test-invalid uv run shuvagent --config <temp-config> status
# OK idle
```

## Remaining Unverified Live Gates

These are required by issue #1 and cannot be considered complete from local
unit/fake-session evidence or direct API injection alone:

1. Real microphone input and speaker playback on the target Linux/Hyprland
   desktop.
2. Selected-text Q&A end-to-end by spoken microphone prompt with real
   `wl-paste` selected text.
3. Prompt `control stop` behavior during active model speech.

## Additional Live ShuVoice Pre-Start Evidence

Initial attempt exposed a fail-open bug when `shuvoice control status` timed out
under the original 0.5 second timeout. The fix makes status timeouts/errors
deny start and raises the configured ShuVoice control timeout to 2.0 seconds.

Live recording drill after the fix:

```bash
shuvoice control start
# OK started
shuvoice control status
# OK recording
uv run shuvagent --config /tmp/shuvagent-shuvoice-deny3-sIn0.toml control start
# ERROR start denied: shuvoice-recording
uv run shuvagent --config /tmp/shuvagent-shuvoice-deny3-sIn0.toml control status
# OK idle
shuvoice control stop --control-wait-sec 0
# OK stopped
shuvoice control status
# OK idle
```

## Additional Live ShuVoice Mid-Session Evidence

Live mid-session recording drill:

```bash
uv run shuvagent --config /tmp/shuvagent-shuvoice-mid2-WUmn.toml control start
# OK started session=3423329ecd5549c5b2884ebd480c4b66
uv run shuvagent --config /tmp/shuvagent-shuvoice-mid2-WUmn.toml control status
# OK active session=3423329ecd5549c5b2884ebd480c4b66
shuvoice control start
# OK started
shuvoice control status
# OK recording
uv run shuvagent --config /tmp/shuvagent-shuvoice-mid2-WUmn.toml control status
# OK active session=3423329ecd5549c5b2884ebd480c4b66
shuvoice control stop --control-wait-sec 0
# OK stopped
shuvoice control status
# OK idle
uv run shuvagent --config /tmp/shuvagent-shuvoice-mid2-WUmn.toml control status
# OK active session=3423329ecd5549c5b2884ebd480c4b66
uv run shuvagent --config /tmp/shuvagent-shuvoice-mid2-WUmn.toml control stop
# OK stopped
uv run shuvagent --config /tmp/shuvagent-shuvoice-mid2-WUmn.toml control status
# OK idle
```

Foreground telemetry:

```text
shuvoice.mic_arbitration action=pause reason=shuvoice-took-mic
shuvoice.mic_arbitration action=resume reason=shuvoice-released-mic
agent.session.duration_ms
realtime.usage.summary
realtime.response_cancel_requested
agent.session.stopped
```

## Additional Live ShuVoice Active-TTS Evidence

Live active-TTS arbitration drill:

```bash
shuvoice control tts_speak
# OK tts speaking
shuvoice control tts_status
# OK playing
uv run shuvagent --config /tmp/shuvagent-tts-active-iYgE.toml control start
# OK started session=12e05c6aaff54734ade1aeed1f4469e1
shuvoice control tts_status
# OK idle
uv run shuvagent --config /tmp/shuvagent-tts-active-iYgE.toml control status
# OK active session=12e05c6aaff54734ade1aeed1f4469e1
```

Foreground telemetry:

```text
shuvoice.tts_stop_requested ok=true
agent.session.start_requested
agent.session.connected
agent.session.interrupted reason=duration_cap duration_cap_sec=3
agent.session.stopped
```

## Additional Live Duration-Cap Evidence

Temporary config:

```toml
[realtime]
session_max_duration_sec = 2
output_token_cap = 800
```

Control sequence:

```bash
uv run shuvagent --config /tmp/shuvagent-duration-s0n4.toml control status
# OK idle
uv run shuvagent --config /tmp/shuvagent-duration-s0n4.toml control start
# OK started session=71c89d66e75d4644a875ec86e2d4c192
sleep 4
uv run shuvagent --config /tmp/shuvagent-duration-s0n4.toml control status
# OK idle
```

Foreground telemetry:

```text
agent.session.connected
agent.session.interrupted reason=duration_cap duration_cap_sec=2
agent.session.duration_ms duration_ms=2203.18
realtime.usage.summary output_token_cap=800
realtime.response_cancel_requested
agent.session.stopped
```

## Additional Live Output-Token-Cap Evidence

Foreground/control-socket microphone-path drill with `output_token_cap = 1`:

```text
uv run shuvagent --config /tmp/shuvagent-issue1-cap1b-aosk/config.toml control status
# OK idle
uv run shuvagent --config /tmp/shuvagent-issue1-cap1b-aosk/config.toml control start
# OK started session=7ffc9c85dbfe405c8c0d2715aef62fbf
espeak-ng -s 145 'please answer with a few words about this test'
uv run shuvagent --config /tmp/shuvagent-issue1-cap1b-aosk/config.toml control status
# OK active session=7ffc9c85dbfe405c8c0d2715aef62fbf
```

Safe telemetry evidence:

```text
output_token_cap=1
realtime.usage
agent.session.interrupted reason=output_token_cap
agent.session.duration_ms
realtime.usage.summary output_token_cap=1
audio.capture_stop reason=stop
realtime.response_cancel_requested
conversation_already_has_active_response=false
```

The status line also emitted:

```text
[shuvagent] Session stopped: output_token_cap
```

Direct live Realtime accounting drill:

```text
max_output_tokens=1
UsageTracker(output_token_cap=1)
decision_reason=output_token_cap
snapshot={'input_tokens': 54, 'output_tokens': 1, 'total_tokens': 55, 'output_token_cap': 1}
errors=[]
```

Together these verify the live API returns usage data compatible with the
production usage parser/tracker and that the foreground/control-socket mic-path
cap decision fires at the threshold.

## Additional Live Selected-Text Mic-Path Evidence

Synthetic selected-text microphone-path drill after Realtime tool-call dedupe
hardening:

```text
uv run shuvagent --config /tmp/shuvagent-issue1-micpath-jBsh/config.toml control status
# OK idle
uv run shuvagent --config /tmp/shuvagent-issue1-micpath-jBsh/config.toml control start
# OK started session=3b1d3b30b5354de29e139fa6b0bc478f
wl-copy --primary < synthetic safe selected text
espeak-ng -s 145 'what does the selected text mean'
uv run shuvagent --config /tmp/shuvagent-issue1-micpath-jBsh/config.toml control stop
# OK idle
```

Safe telemetry evidence:

```text
agent.session.connected
audio.capture_start
realtime.first_audio_response_latency_ms
tool.requested get_selected_text
tool.executed get_selected_text ok=true
agent.session.interrupted reason=output_token_cap
audio.capture_stop reason=stop
raw synthetic selected text present=false
conversation_already_has_active_response=false
```

This verifies the microphone-path selected-text tool round trip with synthetic
text and no raw selected-text telemetry leakage. The remaining selected-text
gate is specifically human-spoken Q&A with real selected text and audible
answer confirmation.

## Completion Rule

Do not close issue #1 until every remaining unverified live gate above has
concrete evidence from the target desktop. Passing local tests alone is not
sufficient for this PRD because live API, audio hardware, and microphone-path
behavior are explicit acceptance requirements.
