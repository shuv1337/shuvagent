<!-- DRAFT ONLY — not posted to GitHub. Review/edit, then post manually if you agree. -->
## Issue #1 closure-readiness check + automated-gap fixes (2026-05-29)

Ran an independent, adversarial re-audit of all 42 acceptance criteria against
the actual code and test bodies (not the audit doc's claims), plus a fresh
automated verification pass. **No live API spend, no audio session.** This
comment reports status and does **not** claim the issue is closeable.

### Automated surface (all green)

| Check | Exit | Result |
|---|---:|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run mypy` | 0 | Success: no issues found in 31 source files |
| `uv run pytest -q` | 0 | **214 passed, 4 skipped** (was 206; +8 new tests) |
| `uv run shuvagent doctor` | 0 | All 10 checks PASS |
| `uv run shuvagent issue1-qa` | 0 | Preflight PASS |
| `systemd-analyze verify … shuvagent.service` | 0 | Verified clean |

### Re-audit found 5 real coverage gaps behind "verified" claims — now fixed

All were in-scope and automatable (no human/credential needed):

1. **US23 (was high)** — the *bounded* half of "graceful but bounded stop" had
   zero coverage; `handle_stop`'s timeout + force-cancel never ran in any test.
   Added a configurable `stop_timeout_sec` seam + a test that force-cancels a
   session which ignores `stop_event`.
2. **US22 (medium)** — monitor *cancel-on-shutdown* was untested. Added an
   indefinitely-blocking monitor asserting it is cancelled on shutdown.
3. **US18 (medium)** — the explicit-debug raw-text marker was tested only via
   `summarize_user_text` (no production callers). Added tests on the real emit
   path (`to_json_dict` / `JsonLineSink.emit`).
4. **US29 (medium)** — "Maple-compatible" was thin and `JsonLineSink.emit` had
   no tests. Added a full-envelope emit-path test (OTEL ids/timestamp/level/
   session/attributes). *(Note: `telemetry.sink = file|maple` is silently
   ignored today and routes to stdout; live Maple export is out of PRD scope, so
   left as a follow-up, not fixed.)*
5. **US28 (low)** — `agent.session.duration_ms` was emitted but unasserted.
   Added an assertion.

### Gemini gate — code correct; model note corrected; blocker is the key

- `models/gemini-3.1-flash-live-preview` is **correct** for the Pipecat layer;
  code path verified against pipecat-ai 1.2.1; 5 Gemini unit tests pass offline.
- The earlier "Gemini 3.x has no Live API support" note was **stale** — Google
  now documents `gemini-3.1-flash-live-preview` as a Live preview model. Docs
  updated; fallbacks recorded (`…2.5-flash-native-audio-preview-12-2025`).
- **Blocker is credential + a live run only:** `GOOGLE_API_KEY` is absent.

### Remaining gates — require human sign-off (not closeable from automation)

- [ ] Spoken microphone input via `shuvagent run` + `control start`
- [ ] Audible model speech on the default speaker
- [ ] Spoken selected-text Q&A with real `wl-paste --primary` text
- [ ] Re-confirm `control stop` interrupts active speech on the real audio path
- [ ] Gemini Live session with a real `GOOGLE_API_KEY` (`SHUVAGENT_RUN_LIVE_GEMINI=1`)

### Not closeable yet

Per `docs/live-validation-checklist.md` ("do not close from automated tests
alone"): this stays open pending the human voice/hardware gates above and a live
Gemini run. The 5 automated fixes are in the working tree pending review/commit.
No secrets, transcripts, or raw text are included here.
