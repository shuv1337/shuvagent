# shuvagent Next Steps - Issue #1 Live Gate Prompt

Use this prompt only when a future agent/operator has access to the target
Linux/Hyprland desktop and the required live credentials. Do not restart the
completed implementation tasks from the original bootstrap plan.

## Current State

- `main` contains the issue #1 hardening work through the Pipecat/Gemini
  provider slice.
- OpenAI remains the default realtime provider.
- Gemini Live is opt-in with:
  - `realtime.provider = "gemini"`
  - `api_key_env = "GOOGLE_API_KEY"`
  - `model = "models/gemini-3.1-flash-live-preview"`
- The local `~/.config/shuvagent/local.dev` last checked in this run contained
  `OPENAI_API_KEY` only, not `GOOGLE_API_KEY`.
- Public Google docs checked during implementation did not prove
  `models/gemini-3.1-flash-live-preview`; treat that model as unverified until
  the target account passes the opt-in live smoke.

## Validation Baseline

Last full local validation on the pushed checkout:

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

Expected current result:

- `ruff`: pass
- `mypy`: pass over 31 strict source files
- `pytest`: `206 passed, 4 skipped, 1 warning`

The skipped tests are opt-in paid/live smokes unless their flags and
credentials are set.

## Remaining Issue #1 Closure Gates

Run:

```bash
uv run shuvagent issue1-qa
```

Issue #1 must stay open until all of these have fresh safe evidence:

- Spoken microphone input through `uv run shuvagent run` +
  `uv run shuvagent control start`.
- Audible model speech through the default speaker.
- Spoken selected-text Q&A using real `wl-paste --primary` selected text.
- Gemini Live/Pipecat session with `GOOGLE_API_KEY` using
  `models/gemini-3.1-flash-live-preview`.

Record only safe evidence: control outputs, telemetry event names, structured
reasons, and whether audio was heard. Do not record transcripts, raw selected
text, clipboard contents, or API keys.

## Gemini/Pipecat Live Smoke

After adding `GOOGLE_API_KEY` to the environment:

```bash
GOOGLE_API_KEY=... SHUVAGENT_RUN_LIVE_GEMINI=1 \
  uv run pytest tests/integration/test_live_gemini.py -q
```

If the requested Gemini 3.1 live model is unavailable for the account, keep the
issue open and record the safe error category without printing the key.

## Reference Docs

- `docs/live-validation-checklist.md`
- `docs/issue-1-completion-audit.md`
- `HANDOFF.md`
