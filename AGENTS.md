# AGENTS.md — shuvagent

> Single source of truth for AI coding agents working in this repo.
> Read first before changing architecture, tools, or runtime behavior.

## What this repo is

`shuvagent` is a desktop voice-agent app for Linux/Hyprland built on
**OpenAI's GPT-Realtime-2 API** (full-duplex voice + tool calls).

It is the implementation of the product shape proposed in
[`shuvoice/PLAN-42-desktop-agent-gpt-realtime-2.md`](../shuvoice/PLAN-42-desktop-agent-gpt-realtime-2.md)
— **a separate app from ShuVoice**, not an in-tree feature.

The first concrete implementation plan lives in
[`PLAN-01-bootstrap-and-first-slice.md`](./PLAN-01-bootstrap-and-first-slice.md).

## Hard constraints

These are non-negotiable. Violations should be flagged as bugs.

1. **Never modify ShuVoice from this repo.** Talk to it only via its
   existing control socket (`shuvoice control <verb>`) or by reading
   public files. If a tiny ShuVoice change is genuinely required (e.g.,
   adding `version` to `VALID_COMMANDS`), open a separate PR against
   `~/repos/shuvoice` and explain the dependency in this repo's plan
   doc.
2. **Default-deny permission gate.** Every tool call routes through
   `ToolRegistry → PermissionGate → optional Confirmation → handler →
   audit event`. A model event handler **must not** call a tool handler
   directly. This is enforced at the type level via `GatedToolCall`
   (see `shuvagent/tools/types.py` once it exists).
3. **No raw user text in logs by default.** Selected text, clipboard
   contents, transcripts, pasted text, and API keys must never appear
   in logs or telemetry unless an explicit debug flag is set.
4. **Stay out of `shuvoice.service`.** `shuvagent` runs as its own user
   process / user systemd unit. Separate socket
   (`$XDG_RUNTIME_DIR/shuvagent/control.sock`), separate config
   (`~/.config/shuvagent/config.toml`).
5. **No persistent memory in v1.** Sessions are ephemeral. Transcript
   storage requires an explicit product decision.

## Tech stack (locked for v1)

| Component | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Matches ShuVoice; mature `websockets`/`pyaudio` ecosystem |
| Package mgmt | `uv` | Same as ShuVoice |
| Realtime transport | WebSocket | Trusted local backend; standard API key in env |
| Audio | PipeWire via `sounddevice` | Matches ShuVoice's PortAudio path |
| Config | TOML via stdlib `tomllib` | Same as ShuVoice |
| Tests | `pytest` | Same as ShuVoice |
| Lint/format | `ruff` | Same as ShuVoice |

WebRTC is deferred until UI is browser/webview-heavy.

## Runtime layout

```
~/.config/shuvagent/config.toml        # user config
~/.config/shuvagent/local.dev          # KEY=value env (OPENAI_API_KEY etc.)
$XDG_RUNTIME_DIR/shuvagent/control.sock # local control IPC
~/.local/share/shuvagent/               # logs, telemetry buffers (gitignored)
```

## Coordination with ShuVoice

ShuVoice owns the mic during PTT bursts; `shuvagent` owns the mic
during agent sessions. Concrete rule:

- **ShuVoice always wins.** On agent session start, agent calls
  `shuvoice control status`. If status reports `recording`, agent
  refuses to start and surfaces an error toast.
- During an active agent session, if ShuVoice's mic becomes active
  (detected via periodic `shuvoice control status` poll, every 1s),
  agent pauses its session (`response.cancel` + close input audio
  buffer) until ShuVoice releases the mic.
- Agent calls `shuvoice control tts_stop` on its own session start so
  the two voices don't talk over each other.
- These rules live in `shuvagent/coordination.py` and are tested via
  a fake ShuVoice control socket.

## Useful ShuVoice surfaces (read-only, used via subprocess)

| Command | Purpose |
|---|---|
| `shuvoice control status` | Is ShuVoice idle / recording / processing / tts? |
| `shuvoice control tts_stop` | Stop ShuVoice TTS so agent can speak |
| `shuvoice control debug_status` | Full diagnostic dump (JSON) |

Do **not** call internal ShuVoice Python modules. If you need them,
add a CLI surface to ShuVoice in a separate PR.

## Test discipline

- Every new tool: `test_<tool>_denied_by_default`,
  `test_<tool>_confirmation_required`, `test_<tool>_cancellation`,
  `test_<tool>_focus_change_invalidates`.
- Every IPC command: round-trip test through a fake socket.
- Every redaction helper: tests with secret-like and selected-text
  inputs.
- Live OpenAI Realtime smoke gated by `OPENAI_API_KEY` env (skipped
  in CI unless explicitly enabled).

## Telemetry contract

Structured JSON logs from day one. Schema lives in
`shuvagent/telemetry/schema.py`. Field names match Maple Ingest's
OTLP resource/attribute conventions so logs can be exported later
without rewrites.

## When to update this file

- New hard constraint discovered
- Tech stack change
- Coordination rule with ShuVoice changes
- New service path / runtime layout entry

Don't dump implementation notes here — they belong in the plan doc
(`PLAN-NN-*.md`) or in module docstrings.
