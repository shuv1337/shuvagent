# shuvagent Project Review — 2026-05-16

## Executive Summary

**shuvagent is in excellent shape.** The uncommitted working tree represents a
significant hardening pass beyond what PLAN-01 originally specified. All core
milestones are functionally complete, the test suite is healthy (84 passing),
ruff and mypy are clean, and the codebase has been live-validated against the
actual OpenAI Realtime API, PipeWire audio, ShuVoice arbitration, and Hyprland
desktop helpers.

**The single most important next step: commit this work.** There are ~1,500 lines
of uncommitted changes across 20 tracked files plus 7 new files. This represents
the bulk of the project's real-world functionality and should be preserved
immediately.

---

## Current State Snapshot

### Committed vs Uncommitted

| Category | Committed (origin/main) | Uncommitted (working tree) |
|---|---|---|
| **Core loop** | Skeleton, fake session, basic audio | Streaming lifecycle, error handling, API event streaming, response ordering |
| **CLI** | `--help`, `run`, `control start/stop/status` | `doctor` command, start-decision gate, bounded stop, keyboard interrupt |
| **Safety** | Permission gate, default deny | Usage tracker, rate-limit parser, duration cap, token cap, audio runtime errors |
| **Coordination** | Polling, pause/resume | TTS-stop on session start, fail-closed on timeout |
| **Realtime wire** | Beta API format | GA API format (`audio/pcm`, `output_modalities`, no beta header) |
| **Tests** | Unit tests for core modules | Live smoke, streaming fake, session runner, doctor, audio runtime, usage |
| **Docs** | PLAN-01, HANDOFF, README | Completion audit, live validation checklist, expanded HANDOFF |

### Test Health

```
84 passed, 3 skipped in 1.68s
```

- **3 skipped:** `test_live_realtime_session_opens_and_closes`,
  `test_live_realtime_selected_text_tool_round_trip`,
  `test_live_realtime_default_read_only_tool_round_trip` — all gated by
  `SHUVAGENT_RUN_LIVE_REALTIME=1` and `OPENAI_API_KEY`. Expected.
- **Lint:** `ruff check .` — clean
- **Types:** `mypy` over 19 strict source files — clean

### Live Validation Status

Per `docs/issue-1-completion-audit.md`, the following have been verified on the
target Linux/Hyprland desktop:

| Gate | Status |
|---|---|
| Foreground process + control socket round-trip | ✅ Live verified |
| Missing API key denies start | ✅ Live verified |
| Session cleanup on finish | ✅ Live verified |
| ShuVoice pre-start denial | ✅ Live verified |
| ShuVoice mid-session pause/resume | ✅ Live verified |
| ShuVoice TTS arbitration | ✅ Live verified |
| Duration cap (2-second test) | ✅ Live verified |
| Output token cap (direct API drill) | ✅ Live verified |
| Selected-text tool round trip | ✅ Live verified (synthetic) |
| Real microphone + speaker | ⚠️ Partial — hardware path tested, spoken Q&A pending |
| Interrupt during active speech | ⚠️ Pending |
| Full token-cap stop via control socket | ⚠️ Pending |

---

## What's Strong

1. **Safety architecture is real.** The `GatedToolCall` mint-token pattern,
   `PermissionGate` default-deny, and audit-sink integration are not just
   designed—they're wired into the live streaming loop and tested.

2. **Realtime wire format is current.** The GA API shape (nested `audio`
   object, `output_modalities`, no `OpenAI-Beta` header) was caught and fixed
   during live smoke testing. The response-ordering logic
   (`_response_active`, `_response_after_active_done`) correctly handles the
   function-call timing quirk in the GA API.

3. **Telemetry is production-ready.** Every lifecycle event, error, rate
   limit, usage snapshot, and audio status is emitted as structured JSON with
   Maple-compatible field names. Redaction is tested and enforced.

4. **Coordination with ShuVoice is fail-closed.** Timeouts deny start rather
   than allow it. Mid-session polling pauses and resumes correctly. TTS is
   stopped before the agent speaks.

5. **`doctor` is a genuinely useful addition.** Not in the original plan but
   exactly what a Linux audio/desktop project needs: preflight checks for
   config, API key, Python deps, desktop helpers, and safety caps.

---

## Gaps and Risks

### 1. Missing Tests (mentioned in PLAN-01 as mandatory)

| Missing test file | What it should cover | Risk if absent |
|---|---|---|
| `tests/test_confirmation.py` | `DenyAllConfirmationProvider`, future interactive confirmation | Low — currently no interactive confirmation flow |
| `tests/test_tool_registry.py` | `ToolRegistry.register`, `ToolRegistry.specs`, audit sink | Low-Medium — `execute` is tested via `test_tool_policy.py` and integration tests, but `register`/`specs` paths are uncovered |

### 2. Real-World Gaps

| Gap | Impact | Suggested priority |
|---|---|---|
| No `systemd/user/shuvagent.service` | Cannot run headless at login | Medium — add for v0.1.0 release |
| No overlay/status UI beyond CLI | User doesn't know session state without typing `status` | Medium — a simple terminal title-bar or tray indicator |
| No config reload | Must restart process to change voice/caps | Low — acceptable for v0.1.0 |
| No WebSocket reconnect | One drop kills the session | Medium — add exponential backoff reconnect |
| `test_cli.py` is only 437 bytes | Only tests keyboard-interrupt exit code | Low — expand to cover doctor, control verbs, missing-key paths |

### 3. Code-Level Observations

**Audio pause doesn't release the device.**
`ConversationApp.run_streaming()` starts the mic stream when the session
begins and keeps it running until `stop_event` fires. `monitor_shuvoice`
calling `session.pause()` clears the OpenAI buffer and cancels the response,
but the local `sounddevice` stream continues capturing. This means:

- Mic is still open while ShuVoice is recording (two processes holding the
  device — depends on PipeWire mixing policy)
- Audio is being captured but dropped on the floor

The PLAN-01 §4.2 specification says: "Stop local mic capture (release the
device)." The current implementation doesn't do this. It's a privacy and
resource issue worth fixing.

**Response cancellation idempotency.**
`cancel_response()` sets `_response_active = False` locally, but the server
may still send `response.done` later. This is harmless (double-set to False),
but in `_stream_errors`, `response_cancel_not_active` is treated as a
non-fatal warning rather than an expected idempotent result. This is correct
but the comment could be clearer.

**Token cap only tracks output.**
`UsageTracker` only monitors `output_tokens`. The cost risk is output-biased
($64/M output vs $4/M input), so this is the right priority. A future
`input_token_cap` would be nice for completeness but isn't urgent.

---

## Recommended Next Steps

### Immediate (this week)

1. **Commit the working tree.** All 20 modified files + 7 new files. This is
   ~1,500 lines of hardening, live validation, and critical fixes. It should
   not sit uncommitted.

2. **Add `test_tool_registry.py`.** Test `register`, `specs`, `execute` with
   mint-token validation, audit sink invocation, and `tool_not_registered`
   error path.

3. **Add `test_confirmation.py`.** Test `DenyAllConfirmationProvider`,
   `ConfirmationRequest` construction, and a mock interactive provider that
   returns `True`.

### Short-term (next 2–4 weeks)

4. **Fix mic device release during pause.** When `session.pause()` is called,
   stop the `sounddevice` input stream and restart it on `resume()`. This
   properly implements PLAN-01 §4.2 and respects ShuVoice's mic ownership.

5. **Add WebSocket reconnect with backoff.** If the Realtime connection drops
   (network blip, OpenAI restart), attempt 3 retries with exponential backoff
   before failing the session. Emit `agent.session.reconnect_attempt` and
   `reconnect_succeeded`/`failed` telemetry events (schema already defines
   them).

6. **Write tools (PLAN-02).** The gate is ready. Add:
   - `paste_text` (LOCAL_VISIBLE_WRITE — requires confirmation + focus check)
   - `replace_selected_text` (LOCAL_VISIBLE_WRITE)
   - `copy_to_clipboard` (LOCAL_REVERSIBLE)
   - `speak_text` (LOCAL_REVERSIBLE — TTS via local speaker)

   Each tool needs: handler, `tests/test_<tool>_denied_by_default`,
   `test_<tool>_confirmation_required`, `test_<tool>_focus_change_invalidates`.

7. **Expand `test_cli.py`.** Add tests for:
   - `doctor` command with all check statuses
   - `control start` denied when API key missing
   - `control status` returns correct state strings
   - `_SessionRunner` start/stop/shutdown lifecycle

### Medium-term (next 1–2 months)

8. **Systemd user service.** Create `packaging/systemd/user/shuvagent.service`
   so `systemctl --user enable shuvagent` works. Include `ExecStopPost` for
   cleanup telemetry.

9. **Simple status indicator.** Even a terminal title-bar update or a small
   `curses`/`rich` status panel showing `idle | active | paused | error` with
   session duration would dramatically improve UX.

10. **Config reload (SIGHUP).** Allow changing voice, caps, and tool set
    without restarting the process. Useful for tuning during a session.

11. **MCP tool integration (PLAN-03+).** Once write tools are proven, add an
    MCP client to the `ToolRegistry` so third-party servers can extend
    capabilities without code changes.

12. **Maple Ingest live export.** The telemetry schema is already
    Maple-compatible. Add an HTTP sink that POSTs to `Maple Ingest (:3474)`
    when `telemetry.sink = "maple"` is configured.

---

## Suggested Commit Message

If committing as one atomic unit:

```
feat: live validation and production hardening for read-only voice slice

Adds:
- doctor command for preflight validation
- UsageTracker with output token cap and rate-limit telemetry
- AudioRuntimeError with overflow/status telemetry
- Streaming session lifecycle: error streams, API event streams,
  response ordering, bounded stop, best-effort cancel
- GA Realtime API wire format (audio/pcm, output_modalities)
- ShuVoice TTS arbitration and fail-closed timeout handling
- Session duration cap enforcement
- Control socket cleanup on session finish
- Live smoke tests for OpenAI Realtime API
- Completion audit and live validation checklist

Tests: 84 passing, 3 skipped (gated live smoke)
Lint: ruff clean
Types: mypy clean on 19 strict source files
```

Or, if the user prefers granular commits, break into:
1. `feat: add doctor preflight command`
2. `feat: add usage tracker and rate-limit telemetry`
3. `feat: add audio runtime error handling`
4. `feat: harden streaming session lifecycle`
5. `fix: update to GA Realtime API wire format`
6. `feat: fail-closed ShuVoice coordination and TTS arbitration`
7. `test: add live OpenAI Realtime smoke tests`
8. `docs: add completion audit and live validation checklist`

---

## Final Assessment

**shuvagent is ready to commit and close the read-only slice.** The code is
well-tested, type-safe, lint-clean, and live-validated. The architecture
for write tools, MCP, and Maple export is already in place. The next
phase is about adding capability (write tools, MCP) and polish (systemd,
status UI, reconnect) rather than fixing foundational issues.
