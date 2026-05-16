# shuvagent Next Steps — Autonomous Execution Prompt

Execute the following 10 tasks for the shuvagent project in order. Each task must be completed, tested, and committed before moving to the next. The project is a Python 3.12 desktop voice agent using `uv`, `pytest`, `ruff`, and `mypy --strict`.

---

## 1. Commit the uncommitted working tree

The working tree has ~1,500 lines of changes across 20 tracked files and 7 new files (all currently uncommitted). This includes the hardening pass, live validation, doctor command, usage tracker, audio runtime, GA API format fixes, and completion audit.

- Run `git diff` to review the full change set.
- Break into 2–4 logical commits or create one atomic commit with a descriptive message covering all major additions.
- Ensure every commit passes `uv run ruff check .`, `uv run mypy`, and `uv run pytest`.
- Push to `origin/main`.

## 2. Add `tests/test_tool_registry.py`

The `ToolRegistry` class in `shuvagent/tools/registry.py` currently has no direct unit tests. PLAN-01 §6.5 lists this as mandatory.

Test coverage needed:
- `register()` adds a tool and `specs()` returns it.
- `execute()` with a valid `GatedToolCall` (proper `_mint_token`) succeeds.
- `execute()` with an invalid `_mint_token` raises `SecurityError`.
- `execute()` with an expired `GatedToolCall` returns `ToolResult.failure("confirmation_expired")`.
- `execute()` with an unregistered tool returns `ToolResult.failure("tool_not_registered")`.
- `execute()` with a stale window focus (for `LOCAL_VISIBLE_WRITE` risk) returns `confirmation_expired`.
- Audit sink is called with the correct event name when a tool is executed or expired.

## 3. Add `tests/test_confirmation.py`

The confirmation lifecycle in `shuvagent/tools/confirmation.py` currently has no direct unit tests. PLAN-01 §6.5 lists this as mandatory.

Test coverage needed:
- `DenyAllConfirmationProvider.confirm()` returns `False` for any `ConfirmationRequest`.
- A mock interactive provider that returns `True` allows the confirmation.
- `ConfirmationRequest` can be constructed from a `ToolCallRequest` and `ToolSpec`.
- A `ConfirmationRequest` with `LOCAL_VISIBLE_WRITE` risk carries the correct reason string.

## 4. Fix mic device release during `session.pause()`

Currently, when `monitor_shuvoice` detects ShuVoice recording and calls `session.pause()`, the OpenAI audio buffer is cleared and the response is cancelled, but the local `sounddevice` input stream in `_mic_stream()` keeps capturing. This contradicts PLAN-01 §4.2 which specifies "Stop local mic capture (release the device)."

Changes needed:
- In `ConversationApp.run_streaming()`, track the mic stream state explicitly.
- On `session.pause()`: stop the `sounddevice` input stream and emit `audio.capture_stop`.
- On `session.resume()`: restart the `sounddevice` input stream and emit `audio.capture_start`.
- Ensure `_stream_audio_in()` handles the stream stopping gracefully without raising.
- Add a test in `tests/test_session_runner.py` or `tests/test_coordination.py` that verifies the mic stream is stopped during pause and restarted on resume.
- Run the full test suite: `uv run pytest`.

## 5. Add WebSocket reconnect with exponential backoff

If the OpenAI Realtime WebSocket drops mid-session (network blip, server restart), the session dies immediately. Add resilient reconnect logic.

Changes needed:
- In `OpenAIRealtimeSession`, add a `reconnect()` method or integrate into `connect()`.
- On unexpected close: wait 1s, 2s, 4s (max 3 attempts) before giving up.
- Emit `agent.session.reconnect_attempt` with `attempt=N` and `delay_ms`.
- On success: emit `agent.session.reconnect_succeeded`.
- On failure after max retries: emit `agent.session.reconnect_failed` and close cleanly.
- Preserve session state (tools, voice) across reconnects by re-sending `session.update`.
- Add tests in `tests/test_openai_session.py` for the retry logic using a mock WebSocket that fails twice then succeeds.
- Ensure the reconnect does not double-count usage tokens.

## 6. Implement write tools (PLAN-02 foundation)

The permission gate (`GatedToolCall`, `PermissionGate`, `ToolRegistry`) is fully built and tested. Add the first write tool to prove the gate works end-to-end.

Start with one tool: `paste_text`.

Changes needed:
- Create `shuvagent/tools/builtins/paste_text.py`.
- Risk: `ToolRisk.LOCAL_VISIBLE_WRITE` (requires confirmation + window focus check).
- Handler: uses `wl-copy` or `xdotool type` to paste text at the current cursor position.
- Add to `shuvagent/tools/builtins/__init__.py`.
- Tests (mandatory per AGENTS.md):
  - `test_paste_text_denied_by_default`
  - `test_paste_text_confirmation_required`
  - `test_paste_text_focus_change_invalidates`
- Run `uv run pytest`.

After `paste_text` works, add `replace_selected_text` and `copy_to_clipboard` in the same pattern.

## 7. Expand `tests/test_cli.py`

Currently `tests/test_cli.py` is only 437 bytes and tests only keyboard-interrupt exit code. Expand to cover the CLI surface.

Test coverage needed:
- `cli.main(["doctor"])` returns `0` when all checks pass and `1` when any check fails.
- `cli.main(["control", "status"])` returns `0`.
- `_start_decision()` denies `control start` when `api_key` is missing.
- `_SessionRunner.handle_start()` creates a task; `handle_stop()` cancels it; `shutdown()` is idempotent.
- `main(["run"])` raises `SystemExit` with code `130` on `KeyboardInterrupt`.
- Use `monkeypatch` to mock `asyncio.run` and control socket operations; do not require real audio or network.

## 8. Add systemd user service

Create `packaging/systemd/user/shuvagent.service` for headless operation.

Requirements:
- `ExecStart=/usr/local/bin/shuvagent run` (or the appropriate path after `uv pip install`).
- `Restart=on-failure`.
- `ExecStopPost=/usr/local/bin/shuvagent control stop` (best-effort cleanup).
- `Environment=XDG_RUNTIME_DIR=%t`.
- Install instructions in README or a new `packaging/README.md`.
- Test by running `systemd-analyze verify packaging/systemd/user/shuvagent.service`.

## 9. Add a simple status indicator

Currently the only way to know session state is to run `shuvagent control status`. Add a lightweight in-process indicator.

Start simple: update the terminal title bar or emit a short status line on state changes.

Changes needed:
- In `_SessionRunner._run_session()`, print `[shuvagent] Session started` / `paused` / `resumed` / `stopped` to stderr.
- On `session.pause()`: print `[shuvagent] Paused — ShuVoice has the mic`.
- On `session.resume()`: print `[shuvagent] Resumed`.
- On duration cap or token cap: print `[shuvagent] Session stopped: <reason>`.
- Ensure these prints go to stderr so they don't interfere with the JSON telemetry on stdout.
- Add tests verifying the prints happen at the right lifecycle points (use `capsys` or `capfd`).

Future iterations can add a tray icon or overlay window, but stderr status is the cheapest meaningful step.

## 10. Add config reload on SIGHUP

Allow changing `voice`, `session_max_duration_sec`, `output_token_cap`, and tool set without restarting the process.

Changes needed:
- In `_run()`, install a `signal.signal(signal.SIGHUP, ...)` handler.
- On SIGHUP: re-read `~/.config/shuvagent/config.toml`, validate it, and emit `app.lifecycle.config_reloaded`.
- If a session is active, apply new safety caps (duration, tokens) immediately. Do not change voice mid-session (document this limitation).
- If the new config is invalid, log an error and keep the old config.
- Add a test in `tests/test_config.py` or `tests/test_session_runner.py` that sends SIGHUP and verifies the config is reloaded.
- Run `uv run pytest`.

---

## Validation Rules

After every task:
- `uv run ruff check .` must pass.
- `uv run mypy` must pass on all 19+ strict source files.
- `uv run pytest` must show 84+ passing, 3 skipped (live smoke).
- New tests must follow the naming convention: `test_<module>_<behavior>`.
- No raw user text, API keys, or selected text in any test output.
- Update `HANDOFF.md` with any new operational knowledge.
