# Issue #1 Closure-Readiness Report

Issue: **PRD: Live validation and production hardening for the read-only voice slice**
(<https://github.com/shuv1337/shuvagent/issues/1>, state: OPEN, label: `ready-for-human`)

Produced: 2026-05-29 by an automated audit + adversarial-verification workflow
(`issue1-closure-drive`, 21 agents). This report distinguishes what automation
has actually proven from what still requires human/hardware sign-off or a
credential. **It does not close the issue and nothing here was committed,
pushed, or posted to GitHub.**

## Verdict

The **automated acceptance surface is complete and clean.** An independent,
adversarial re-audit of all 42 acceptance criteria initially found **5 genuine
test-coverage gaps** that the prior audit doc had marked "verified." All 5 were
**in-scope, automatable (no human / hardware / credential needed), and are now
closed** in this working tree with new tests. The remaining work is inherently
**human/hardware** (4 voice gates) plus one **credential** gate (Gemini live),
which no agent can satisfy.

| Category | Count | Closeable by an agent? |
|---|---:|---|
| Verified by automation | 29 → **34** of 42 | already done |
| Automatable gaps found by re-audit | 5 | **fixed in this tree** |
| Human / hardware sign-off gates | 4 | no — needs a person at the desktop |
| Credential / provider gates | 3 (OpenAI live, Gemini live × model+key) | no — needs keys |

## Fresh automated evidence (this run, no live API spend, no audio session)

| Check | Exit | Result |
|---|---:|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run mypy` | 0 | Success: no issues found in 31 source files |
| `uv run pytest -q` | 0 | **214 passed, 4 skipped** (was 206; +8 new tests) |
| `uv run shuvagent doctor` | 0 | All 10 checks PASS |
| `uv run shuvagent issue1-qa` | 0 | Preflight PASS; lists the human gates |
| `systemd-analyze verify … shuvagent.service` | 0 | Verified clean, no warnings |

The 4 pytest skips are the by-default-skipped live OpenAI/Gemini smokes
(`SHUVAGENT_RUN_LIVE_*` unset) — expected. One benign `DeprecationWarning`
(pipecat imports `audioop`) — not a failure.

Credential presence (names only, no values): `OPENAI_API_KEY` present in
`~/.config/shuvagent/local.dev`; **`GOOGLE_API_KEY` absent** from both the env
and the local.dev file.

## Gaps found by adversarial re-audit — now CLOSED

Each was a real coverage hole behind a "verified" claim. Fixes are test-only
except US23, which adds a small, justified testability seam.

1. **US23 — graceful-but-bounded stop (was: high).** The *bounded* guarantee —
   `handle_stop()`'s `wait_for(timeout=…)` + force-cancel fallback
   (`cli.py`) — had **zero** coverage; every existing fake `_run_session`
   returned promptly so the timeout path never ran.
   - Fix: `_SessionRunner.__init__` now takes `stop_timeout_sec` (default 5.0).
     New `tests/test_cli.py::test_session_runner_stop_is_bounded_and_force_cancels_stuck_session`
     drives a session that ignores `stop_event` and asserts `handle_stop`
     returns within bound and force-cancels the stuck task.

2. **US22 — monitor cancel-on-shutdown (was: medium).** "Started after connect"
   was tested, but "cancelled on shutdown" was not (the one monitor test
   returned naturally).
   - Fix: new
     `tests/integration/test_streaming_loop_with_fake.py::test_run_streaming_cancels_blocking_monitor_on_shutdown`
     wires an indefinitely-blocking monitor and asserts it is started and then
     receives `CancelledError` on shutdown.

3. **US18 — raw-text logging requires explicit debug flag (was: medium /
   overstated).** Default-off gating was verified, but the "reveals-and-marks"
   half was only tested against `summarize_user_text()`, which has **no
   production callers**. The real emit path
   (`TelemetryEvent.to_json_dict(debug_log_raw_text=True)`) was untested.
   - Fix: new tests in `tests/test_redaction.py` drive both `to_json_dict(...)`
     and `JsonLineSink.emit(...)` with the flag on/off, asserting un-redacted
     attributes **and** the `privacy.raw_text_logging` marker only under debug.

4. **US29 — Maple-compatible structured JSON events (was: medium /
   overstated).** The envelope test asserted only 2 fields and `JsonLineSink.emit`
   had **zero** test references.
   - Fix: new
     `tests/test_redaction.py::test_json_line_sink_emit_serializes_full_maple_compatible_envelope`
     validates the full OTEL/Maple-compatible envelope through the real emit
     path (timestamp `…Z`, level, `service.name`/`service.version`, event,
     32-char `trace_id`, 16-char `span_id`, `session_id`, attributes), plus an
     emit-path redaction test. *Scope note below.*

5. **US28 — session duration telemetry (was: low).** `agent.session.duration_ms`
   was emitted but never asserted.
   - Fix: new
     `tests/integration/test_streaming_loop_with_fake.py::test_run_streaming_emits_session_duration_ms`
     asserts it is emitted exactly once with a numeric `duration_ms`.

### Scope note on US29 / the `telemetry.sink` option

`config.py` accepts `telemetry.sink ∈ {stdout, file, maple}`, but `cli.py`
**always** constructs a stdout `JsonLineSink` — so `file` and `maple` are
silently ignored today. Per the PRD, **live Maple Ingest export is explicitly
out of scope** ("the schema should remain compatible, but live export is not
part of this PRD"). The correct, in-scope action is therefore to *prove the
emitted JSON is Maple-compatible* (done, via the emit-path envelope test) and
**not** to add a network sink. The unhonored `file`/`maple` routing is recorded
here as a minor, out-of-scope follow-up rather than fixed.

## Remaining human / hardware gates (cannot be automated)

These require a person at the target Linux/Hyprland desktop with mic + speakers.
No automated test opens the real PortAudio capture/playback device.

- [ ] **Spoken microphone input** via `shuvagent run` + `control start` (US8/US1/US2).
- [ ] **Audible model speech** confirmed on the default speaker (US9).
- [ ] **Spoken selected-text Q&A** with real `wl-paste --primary` text (US13).
- [ ] **Re-confirm `control stop` interrupts active speech promptly** on the
  real audio path (already `[x]` from synthetic drills; re-confirm with a human).

## Credential / provider gates

- **OpenAI live Realtime smoke (US19/US20)** — code + skip-by-default verified;
  the gated body passes only with `OPENAI_API_KEY` + `SHUVAGENT_RUN_LIVE_REALTIME=1`.
  Does **not** cover the spoken mic/speaker legs (those are human gates).
- **Gemini Live via Pipecat (US42)** — **code path verified correct** against
  pipecat-ai 1.2.1 (service import, settings fields, overridden methods,
  24 kHz audio, tool routing, `missing_api_key:GOOGLE_API_KEY` denial,
  connect-error not reported as open); all 5 Gemini unit tests pass offline.
  **Blocker is credential + a live run only:** `GOOGLE_API_KEY` is absent.
  - **Model-name correction (doc fix applied):** the prior note that "Gemini 3
    Flash preview has no Live API support" is **stale**. Google now documents
    `gemini-3.1-flash-live-preview` as a supported (preview) Live API model, and
    the Pipecat layer expects the `models/` prefix, so
    `models/gemini-3.1-flash-live-preview` is correct. Documented fallbacks:
    `models/gemini-2.5-flash-native-audio-preview-12-2025` or stable
    `models/gemini-live-2.5-flash-native-audio`. Updated in
    `docs/live-validation-checklist.md` and `docs/issue-1-completion-audit.md`.

## What changed in this working tree (uncommitted — for your review)

- `shuvagent/cli.py` — `_SessionRunner` gains `stop_timeout_sec` (testability seam for US23).
- `tests/test_cli.py` — US23 bounded-stop test.
- `tests/integration/test_streaming_loop_with_fake.py` — US22 + US28 tests.
- `tests/test_redaction.py` — US18 emit-path + US29 full-envelope/emit tests.
- `docs/live-validation-checklist.md`, `docs/issue-1-completion-audit.md` — Gemini model-name correction.

## Bottom line

Everything an agent can complete for issue #1 is complete: the automated surface
is clean (214 passed), the 5 real coverage gaps are closed, and the stale Gemini
note is corrected. Closing the issue now depends only on **human voice/hardware
sign-off** (4 gates) and a **live Gemini run with a real `GOOGLE_API_KEY`** —
per the project's standing "do not close from automated tests alone" rule. See
the runbook in the draft comment / `docs/live-validation-checklist.md`.
