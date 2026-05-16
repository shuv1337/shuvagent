# PLAN-01: Bootstrap shuvagent + first usable slice

> **Status:** draft for review
> **Parent:** [`PLAN-42` (shuvoice repo)](../shuvoice/PLAN-42-desktop-agent-gpt-realtime-2.md)
> **Author:** Claude (handoff to implementer)
> **Reviewers:** human, `shuvoice` maintainer
> **Last updated:** 2026-05-12

## TL;DR

Stand up `shuvagent` as a standalone Python app with **read-only conversational
voice** as the first usable slice. End state of this plan:

- `shuvagent` package installable via `uv pip install -e .`
- `shuvagent run` opens a GPT-Realtime-2 WebSocket session triggered by a
  Hyprland bind
- Speaks back via local audio playback using the **Marin** voice by default
  (configurable; defaults to a non-Cedar/Marin voice if instruction-following
  is detected as flaky)
- Can answer questions about **selected text** (read-only tool) without
  modifying the desktop
- Refuses to start while ShuVoice is actively recording (mic arbitration)
- Structured JSON logs compatible with Maple Ingest from day one
- Permission gate exists, default-denies all write tools, type-enforced
- Zero changes to ShuVoice — except one optional 4-line PR adding a
  `version` verb to its control socket (filed separately, agent works
  without it via fallback)

This plan **stops at read-only**. Write tools (`paste_text`, `replace_selected_text`)
are intentionally out of scope and ship in **PLAN-02**. This is the cheapest
slice that proves the loop end-to-end and forces every safety boundary into
existence before any write tool can land.

---

## Context: gaps from the PLAN-42 review

The visual review of PLAN-42 surfaced six items that needed concrete answers
before implementation. This plan resolves them:

| Gap (from PLAN-42 review) | Resolution in PLAN-01 |
|---|---|
| Mic arbitration mechanism unspecified | §4 — ShuVoice always wins, poll-based detection |
| "Tool handler not directly callable" enforced only by review | §6 — `GatedToolCall` type, runtime assertion |
| MCP vs hosted vs local tools open | §6 — local-only in v1; MCP deferred to PLAN-03+ |
| M5 extraction trigger undefined | Out of scope for PLAN-01; will define in PLAN-N |
| Telemetry backend choice deferred | §8 — Maple-compatible structured logs from day one |
| ShuVoice control protocol has no version | §11 — separate 4-line PR, optional |
| Voice selection unspecified | §7 — default `marin`, configurable, fallback to `verse` |
| Activation pattern (PTT vs toggle vs session) | §3 — session-based with explicit start/stop binds |

---

## 1. Repo layout

```
shuvagent/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── PLAN-01-bootstrap-and-first-slice.md     # this file
├── packaging/
│   └── systemd/user/shuvagent.service       # optional, M-late
├── examples/
│   ├── config.toml
│   ├── hyprland-bind.conf                   # snippet to drop into hypr config
│   └── local.dev.example
├── shuvagent/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                               # argparse entrypoint
│   ├── app.py                               # main loop, ties everything together
│   ├── config.py                            # dataclass + TOML loader
│   ├── env_loader.py                        # mirrors shuvoice/env_loader.py
│   ├── control.py                           # local Unix socket: start/stop/status/mute/unmute
│   ├── coordination.py                      # ShuVoice mic-arbitration logic
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── capture.py                       # mic capture (24kHz PCM16)
│   │   └── playback.py                      # speaker playback (24kHz PCM16)
│   ├── realtime/
│   │   ├── __init__.py
│   │   ├── session.py                       # RealtimeAgentSession (real WS)
│   │   ├── fake.py                          # in-memory test double
│   │   └── events.py                        # event dataclasses
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── types.py                         # GatedToolCall, ToolSpec, ToolRisk
│   │   ├── registry.py                      # ToolRegistry
│   │   ├── policy.py                        # PermissionGate
│   │   ├── confirmation.py                  # Confirmation lifecycle
│   │   └── builtins/
│   │       ├── __init__.py
│   │       ├── get_selected_text.py
│   │       ├── get_clipboard_text.py
│   │       ├── get_active_window.py
│   │       └── get_shuvoice_status.py
│   ├── overlay.py                           # status indicator (M-late; CLI status first)
│   ├── selection.py                         # wl-paste wrapper (mirror of shuvoice)
│   ├── window.py                            # active-window snapshot via hyprctl
│   └── telemetry/
│       ├── __init__.py
│       ├── schema.py                        # event dataclasses
│       ├── redact.py                        # secret + selected-text redactors
│       └── sink.py                          # JSON stdout sink (Maple-compatible)
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_env_loader.py
    ├── test_control_socket.py
    ├── test_coordination.py
    ├── test_redaction.py
    ├── test_tool_policy.py
    ├── test_tool_registry.py
    ├── test_confirmation.py
    ├── test_realtime_session_fake.py
    ├── test_audio_capture.py
    ├── test_selection.py
    ├── test_window.py
    └── integration/
        └── test_session_loop_with_fake.py
```

---

## 2. Milestones inside this plan

PLAN-01 spans what PLAN-42 calls **M0 + M1 + M2 + read-only half of M3**.
Compressed because the gaps are pre-resolved and the file layout is
committed.

| MS | Title | Exit gate |
|----|-------|-----------|
| **1.0** | Skeleton | `uv run shuvagent --help` works; pyproject installable |
| **1.1** | Config + env + control socket | `shuvagent start` ACK round-trips through socket |
| **1.2** | Coordination layer | Refuses to start while ShuVoice is recording; integration test passes |
| **1.3** | Permission gate + tool registry | Default-deny test passes; `GatedToolCall` type prevents bypass |
| **1.4** | Realtime session (fake) | Full conversation runs against `FakeRealtimeSession` |
| **1.5** | Audio capture + playback | 24kHz PCM round-trip; underrun/overflow telemetry |
| **1.6** | Realtime session (live) | Opt-in smoke against real API; logs show first-audio latency |
| **1.7** | Read-only tools | Selected-text Q&A works end-to-end |
| **1.8** | Telemetry rollup | One JSON line per lifecycle event; redaction tests pass |

Stop here. PLAN-02 picks up write tools.

---

## 3. Activation pattern

**Session-based** with two Hyprland binds:

```conf
# examples/hyprland-bind.conf — drop into ~/.config/hypr/agent.conf
bind = SUPER ALT, A, exec, shuvagent control start
bind = SUPER ALT, X, exec, shuvagent control stop
```

Rationale:

- Push-to-talk would collide with ShuVoice's Right-Control PTT.
- Toggle-to-talk creates ambiguity about whether the mic is currently
  hot. Sessions are explicit: you start one, you have a conversation,
  you end it.
- A session may last seconds or minutes; the agent shows a status
  indicator (CLI text in M1.x, overlay later) so the user always knows
  state.

`stop` is also wired to **immediately interrupt** any model speech via
`response.cancel`. The same bind handles "stop talking" — there is no
separate barge-in bind in v1.

---

## 4. Coordination with ShuVoice

The single arbitration rule is **ShuVoice always wins**.

### 4.1 On agent session start

```python
# shuvagent/coordination.py
def can_start_agent_session(control_path: Path = SHUVOICE_CONTROL) -> Decision:
    status = shuvoice_status(control_path, timeout=2.0)
    if status is None:
        # ShuVoice not running — agent free to start
        return Decision.allow(reason="shuvoice-not-running")
    if status.is_recording:
        return Decision.deny(reason="shuvoice-recording")
    if status.is_tts_active:
        shuvoice_tts_stop(control_path)  # silence ShuVoice TTS
        return Decision.allow(reason="shuvoice-tts-stopped")
    return Decision.allow(reason="shuvoice-idle")
```

`shuvoice_status` parses the response of `shuvoice control status`. If
ShuVoice is not running (socket missing → `RuntimeError`), agent
proceeds.

### 4.2 During an active session

A background poller runs every **1.0s** while the agent session is
open:

```python
# shuvagent/coordination.py
async def monitor_shuvoice(session: RealtimeAgentSession,
                           interval_sec: float = 1.0):
    while session.is_open:
        status = shuvoice_status(...)
        if status and status.is_recording:
            session.pause("shuvoice-took-mic")
        await asyncio.sleep(interval_sec)
```

`session.pause` does:

1. Send `input_audio_buffer.clear` to OpenAI
2. Stop local mic capture (release the device)
3. Cancel any in-flight `response`
4. Emit `agent.session.paused` telemetry event

When the next poll sees ShuVoice idle again, the session resumes mic
capture but does **not** auto-restart a conversation turn — the user
must speak to continue.

### 4.3 Why polling, not events

ShuVoice's control socket has no push-notification mechanism. A polling
loop is simple and gives the agent a worst-case 1s reaction time before
both processes contend for the mic. Acceptable for v1; revisit if ShuVoice
adds an event stream.

### 4.4 Tests

`tests/test_coordination.py` uses a fake Unix socket that responds with
configurable `status` payloads. Test cases:

- `test_allows_when_shuvoice_idle`
- `test_denies_when_shuvoice_recording`
- `test_allows_after_stopping_shuvoice_tts`
- `test_allows_when_shuvoice_not_running`
- `test_pauses_mid_session_when_shuvoice_starts_recording`
- `test_resumes_mic_after_shuvoice_releases`

---

## 5. Config + env

### 5.1 `~/.config/shuvagent/config.toml`

```toml
config_version = 1

[realtime]
model = "gpt-realtime-2"
api_key_env = "OPENAI_API_KEY"
voice = "marin"                          # see §7 for voice choice + fallback
reasoning_effort = "low"                 # low | medium | high
session_max_duration_sec = 300           # hard cap, see §10
request_timeout_sec = 10.0

[audio]
capture_sample_rate = 24000              # locked by OpenAI Realtime
playback_sample_rate = 24000
capture_device = "default"               # PipeWire/PortAudio device hint
playback_device = "default"

[control]
socket = ""                              # empty = XDG_RUNTIME_DIR/shuvagent/control.sock

[coordination]
shuvoice_status_poll_sec = 1.0
shuvoice_control_timeout_sec = 2.0

[ui]
show_overlay = false                     # M-late; CLI status in v1
overlay_position = "top-center"

[telemetry]
sink = "stdout"                          # stdout | file | maple (maple = future)
file_path = ""                           # if sink=file
debug_log_raw_text = false               # if true, logs raw selected/clipboard text — DANGEROUS

[privacy]
log_session_audio_duration = true        # length only, never content
log_token_counts = true
```

`api_key_env` follows the same pattern as ShuVoice's
`openai_realtime_api_key_env` — the value of the env var is the API key;
the config stores only the **name** of the env var. Never persist the
key itself.

### 5.2 `~/.config/shuvagent/local.dev`

Same format as ShuVoice's `local.dev`. Supports `KEY=value` and
`export KEY=value`. Existing process env wins by default.

```text
OPENAI_API_KEY=sk-...
```

`shuvagent/env_loader.py` is a copy of ShuVoice's `env_loader.py`
adjusted for path. Plan to deduplicate via shared package in M5 (per
PLAN-42); not now.

---

## 6. Permission gate and tool registry

This is the safety-critical core. The architecture below makes "model
handler calls tool handler directly" a **type error**, not a code-review
issue.

### 6.1 Types — `shuvagent/tools/types.py`

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

class ToolRisk(Enum):
    READ = "read"                        # no confirmation after setup
    LOCAL_REVERSIBLE = "local_reversible"
    LOCAL_VISIBLE_WRITE = "local_visible_write"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"          # not implemented in v1

@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk: ToolRisk
    input_schema: dict[str, Any]
    description: str
    handler: Callable[["GatedToolCall"], "ToolResult"]

@dataclass(frozen=True)
class WindowSnapshot:
    app_id: str
    title: str
    captured_at: datetime

@dataclass(frozen=True)
class GatedToolCall:
    """A tool call that has passed the policy gate.

    Only PermissionGate.authorize() may construct this. Handlers accept
    only GatedToolCall — there is no way to invoke a handler with a raw
    tool-call dict.
    """
    call_id: str
    tool: ToolSpec
    arguments: dict[str, Any]
    decision_id: str
    window_at_authorize: WindowSnapshot
    authorized_at: datetime
    expires_at: datetime
    # Private constructor sentinel
    _mint_token: object = field(repr=False)

    def is_fresh(self, now: datetime, current_window: WindowSnapshot) -> bool:
        if now > self.expires_at:
            return False
        if (self.tool.risk == ToolRisk.LOCAL_VISIBLE_WRITE
                and current_window.app_id != self.window_at_authorize.app_id):
            return False
        return True
```

### 6.2 The mint token trick

`_mint_token` is a module-private sentinel. Any external code that tries
to construct `GatedToolCall(...)` directly will pass `_mint_token=None`
and the `PermissionGate` runtime check rejects it. Combined with `mypy
--strict` (or `ty` once it stabilizes), this catches the bypass at type
check time **and** at runtime.

```python
# shuvagent/tools/policy.py
_GATE_TOKEN = object()

class PermissionGate:
    def authorize(self, request: ToolCallRequest) -> Decision:
        # ... policy logic ...
        if granted:
            call = GatedToolCall(
                call_id=request.call_id,
                tool=request.tool,
                arguments=request.arguments,
                decision_id=str(uuid4()),
                window_at_authorize=self.window.snapshot(),
                authorized_at=now(),
                expires_at=now() + timedelta(seconds=15),
                _mint_token=_GATE_TOKEN,
            )
            return Decision.allow(call)
        return Decision.deny(reason=...)
```

```python
# shuvagent/tools/registry.py
class ToolRegistry:
    def execute(self, call: GatedToolCall) -> ToolResult:
        if call._mint_token is not _GATE_TOKEN:
            raise SecurityError("GatedToolCall not minted by PermissionGate")
        if not call.is_fresh(now(), self.window.snapshot()):
            self.emit_audit("tool.expired", call)
            return ToolResult.error("confirmation_expired")
        self.emit_audit("tool.executed", call)
        return call.tool.handler(call)
```

### 6.3 Read-only tools shipped in v1

Each ships as a separate file under `shuvagent/tools/builtins/`:

| Tool | Risk | Implementation |
|------|------|----------------|
| `get_selected_text` | READ | Wraps `shuvagent/selection.py` (mirror of ShuVoice's helper); returns `{text_len, hash}` in non-debug mode |
| `get_clipboard_text` | READ | Same as above, but `wl-paste` without `--primary` |
| `get_active_window` | READ | `hyprctl activewindow -j` parsed into `WindowSnapshot` |
| `get_shuvoice_status` | READ | Runs `shuvoice control status`, parses |

**Important:** Read tools still emit audit events, but the audit
payload omits the raw text — only length, hash prefix, and source.
The **model** receives the full text (that's the whole point), but
logs/telemetry do not.

### 6.4 Write tools — deferred from PLAN-01

`paste_text`, `replace_selected_text`, `copy_to_clipboard`, `stop_speaking`,
`speak_text` are explicitly **out of scope for PLAN-01**. They land in
PLAN-02 after the gate has been exercised by read tools in production
for at least one week.

Implementation note, 2026-05-16: the first PLAN-02 local write specs now exist
as explicit opt-in builtins: `paste_text`, `replace_selected_text`, and
`copy_to_clipboard`. They are covered by confirmation/focus-invalidation tests,
but they are intentionally not registered in the default live read-only tool set
until an interactive confirmation provider is available.

### 6.5 Tool-policy tests (mandatory before merging registry)

```
tests/test_tool_policy.py:
  - test_unknown_tool_denied
  - test_read_tool_allowed_after_setup
  - test_write_tool_requires_confirmation     # uses a fake LOCAL_VISIBLE_WRITE tool
  - test_write_tool_expired_confirmation_returns_error
  - test_write_tool_focus_change_invalidates
  - test_gated_tool_call_cannot_be_constructed_without_gate
  - test_model_handler_cannot_bypass_gate     # negative test: tries to fake _mint_token
```

---

## 7. Voice selection

Realtime API as of GPT-Realtime-2 GA supports **10 voices**:

- Realtime-exclusive: `cedar`, `marin`
- Shared with TTS API: `alloy`, `ash`, `ballad`, `coral`, `echo`,
  `sage`, `shimmer`, `verse`

Known issue from upstream: **Cedar and Marin reportedly ignore
realtime-agent instructions more often than older voices**
([openai-agents-python#1746](https://github.com/openai/openai-agents-python/issues/1746)).

### Decision

- **Default:** `marin` (newer, more humanlike)
- **Fallback (config-overridable):** `verse` (older, instruction-obedient)
- Config validation rejects any voice outside the 10-voice allowlist —
  reject `fable`/`onyx`/`nova` even though they exist in the TTS API,
  to prevent silent OpenAI 400 errors at session start.

```python
# shuvagent/config.py
REALTIME_VOICES = frozenset({
    "cedar", "marin", "alloy", "ash", "ballad",
    "coral", "echo", "sage", "shimmer", "verse",
})

def validate(self):
    if self.realtime.voice not in REALTIME_VOICES:
        raise ValueError(
            f"realtime.voice={self.realtime.voice!r} not in allowlist {sorted(REALTIME_VOICES)}"
        )
```

Voice cannot be changed mid-session per OpenAI docs; reload session to
change.

---

## 8. Telemetry

Maple-compatible structured JSON from day one. Schema lives in
`shuvagent/telemetry/schema.py`.

### 8.1 Event taxonomy

| Domain | Events |
|--------|--------|
| `app.lifecycle` | `start`, `ready`, `stop`, `crash`, `config_loaded` |
| `agent.session` | `start_requested`, `connected`, `ready`, `paused`, `resumed`, `interrupted`, `stopped`, `reconnect_attempt`, `reconnect_succeeded`, `failed` |
| `audio` | `capture_start`, `capture_stop`, `playback_start`, `playback_stop`, `underrun`, `overflow`, `device_error` |
| `realtime` | `ws_connect_latency_ms`, `first_audio_response_latency_ms`, `error_event`, `close`, `rate_limit` |
| `tool` | `requested`, `denied`, `confirmation_shown`, `approved`, `canceled`, `expired`, `executed`, `failed` |
| `coordination` | `shuvoice_status_polled`, `paused_for_shuvoice`, `resumed_after_shuvoice` |
| `cost` | `audio_input_tokens`, `audio_output_tokens`, `text_tokens`, `session_duration_sec` |

### 8.2 Common envelope (Maple-compatible)

```json
{
  "timestamp": "2026-05-12T18:01:23.456Z",
  "level": "info",
  "service": "shuvagent",
  "service.version": "0.1.0",
  "event": "agent.session.started",
  "session_id": "01HX...ULID",
  "trace_id": "...",
  "span_id": "...",
  "attributes": {
    "voice": "marin",
    "model": "gpt-realtime-2",
    "reasoning_effort": "low"
  }
}
```

Field names align with OTLP resource attribute conventions
(`service.name`, `service.version`) so they map directly when Maple
integration lands later.

### 8.3 Redaction rules

`shuvagent/telemetry/redact.py`:

- **API keys.** Any string matching `r"\b(sk-[A-Za-z0-9_-]{20,})"` →
  `"[REDACTED-API-KEY]"`. Tests cover OpenAI and Anthropic shapes.
- **Selected/clipboard text.** Tool audit events use `{text_len: int,
  text_sha256_prefix: str}` instead of raw text. Length + hash prefix
  gives forensic capability without exposing content.
- **Pasted text** (PLAN-02 territory but reserved here): same shape.
- **`debug_log_raw_text = true`** in config opts into raw-text logging
  with a startup warning logged every session and an `attribute`
  `privacy.raw_text_logging=true` on every event — so it's auditable
  later that this was on.

### 8.4 Tests (mandatory)

```
tests/test_redaction.py:
  - test_redacts_openai_key_in_message
  - test_redacts_openai_key_in_nested_dict
  - test_selected_text_replaced_with_len_and_hash
  - test_debug_flag_disables_redaction_but_marks_event
  - test_event_envelope_matches_otel_schema
```

---

## 9. RealtimeAgentSession

The session abstraction targets `wss://api.openai.com/v1/realtime` (note:
**no `?intent=transcription`** parameter — that's ShuVoice's URL).

### 9.1 Public surface

```python
# shuvagent/realtime/session.py
class RealtimeAgentSession(Protocol):
    async def connect(self) -> None: ...
    async def send_audio(self, pcm16: bytes) -> None: ...
    async def commit_input(self) -> None: ...
    async def cancel_response(self) -> None: ...
    async def close(self) -> None: ...

    # Event stream
    audio_out: AsyncIterator[bytes]              # 24kHz PCM16
    tool_calls: AsyncIterator[ToolCallRequest]
    errors: AsyncIterator[RealtimeError]
    state: SessionState                          # connecting | ready | speaking | listening | closed

    is_open: bool
```

### 9.2 Initial `session.update` payload

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "model": "gpt-realtime-2",
    "output_modalities": ["audio"],
    "instructions": "You are a desktop voice assistant. Be concise. ...",
    "audio": {
      "input": {
        "format": {"type": "audio/pcm", "rate": 24000},
        "transcription": {"model": "gpt-4o-mini-transcribe"},
        "turn_detection": {"type": "server_vad", "create_response": true, "interrupt_response": true}
      },
      "output": {
        "format": {"type": "audio/pcm", "rate": 24000},
        "voice": "marin"
      }
    },
    "tools": [
      {"type": "function", "name": "get_selected_text", "description": "...", "parameters": {...}},
      // ... other read tools ...
    ],
    "tool_choice": "auto",
    "max_output_tokens": 800
  }
}
```

`reasoning_effort` is configurable; OpenAI's docs as of GA support
`low | medium | high`. Default `low` for latency.

### 9.3 FakeRealtimeSession

`shuvagent/realtime/fake.py` is a test double that:

- Implements the same `Protocol`
- Emits scripted events in response to inputs
- Used by `tests/integration/test_session_loop_with_fake.py` to exercise
  the full app loop without hitting the API

This is what makes the entire stack testable without `OPENAI_API_KEY`.

### 9.4 Live smoke (gated)

```
tests/integration/test_live_realtime.py:
  pytest.skip if not os.environ.get("OPENAI_API_KEY")
  - opens a 5-second session
  - confirms first_audio_response_latency_ms < 3000
  - asserts no rate-limit error
  - logs cost: should be < $0.05 per run
```

Disabled by default in CI; runs locally before each release.

---

## 10. Cost / runtime safety

GPT-Realtime-2 audio output is **$64 per 1M output tokens**. A runaway
session is the biggest cost risk.

- **Hard session duration cap:** `realtime.session_max_duration_sec = 300`
  (5 min). On expiry, send `response.cancel`, close socket, emit
  `agent.session.stopped` with `reason="duration_cap"`. User must
  re-bind `start` to continue.
- **Token-budget kill-switch (M1.6):** if cumulative `audio_output_tokens`
  for a session exceeds `realtime.output_token_cap` (default 800), session
  closes immediately. The same value is also sent as Realtime
  `max_output_tokens` for each response. Configurable in
  `~/.config/shuvagent/config.toml`.
- **Rate-limit handling:** OpenAI rate-limit error events surface as
  `realtime.rate_limit` telemetry; session closes; user notified via
  CLI / overlay.

---

## 11. Optional ShuVoice PR — `version` verb

Out of scope for this repo but worth filing in parallel:

```python
# shuvoice/control.py — proposed 4-line diff
VALID_COMMANDS = {
    "start", "stop", "toggle", "status", "ping", "metrics",
    "debug_status", "version",          # ← add
    "tts_speak", "tts_pause", ...
}

# in ControlServer._handle_command:
if command == "version":
    return f"OK {shuvoice.__version__}"
```

`shuvagent/coordination.py` will call `shuvoice control version` if
present; if the response is `ERROR unknown command: version` it falls
back to "unknown version, proceed anyway" so the agent works against
older ShuVoice installs.

If the shuvoice maintainer rejects this, agent still works — there's
just no version-skew visibility.

---

## 12. First-run UX

```
$ shuvagent run
[shuvagent] Loaded config from ~/.config/shuvagent/config.toml
[shuvagent] Loaded 1 env var from ~/.config/shuvagent/local.dev
[shuvagent] Control socket: /run/user/1000/shuvagent/control.sock
[shuvagent] ShuVoice detected at /run/user/1000/shuvoice/control.sock (status=idle)
[shuvagent] Ready. Bind SUPER+ALT+A to start a session.

$ shuvagent control status
OK idle

# user presses SUPER+ALT+A
$ shuvagent control start
OK started session=01HX...

# ... voice conversation happens ...

$ shuvagent control stop
OK stopped (duration=14.2s, tokens_in=312, tokens_out=580)
```

`shuvagent run` is the long-running foreground process (use systemd
user unit when running headlessly). `shuvagent control <verb>` is the
short-lived CLI client.

---

## 13. Validation strategy

Per PLAN-42's validation rubric:

### 13.1 Automated (CI)

- All unit tests in `tests/test_*.py`
- Integration test against `FakeRealtimeSession`
- Mypy `--strict` on `shuvagent/tools/` (mandatory; non-strict elsewhere
  in v1)
- Ruff lint + format check

### 13.2 Manual QA checklist

Before tagging v0.1.0:

- [ ] Session starts from Hyprland bind
- [ ] Speech is heard through default speaker at expected volume
- [ ] Asking about selected text returns sensible answer
- [ ] Interrupt (SUPER+ALT+X) stops speech within 500ms
- [ ] Starting agent while ShuVoice is recording → clear error
- [ ] Starting ShuVoice PTT mid-agent-session → agent pauses, status
      reflects "paused-for-shuvoice"
- [ ] Releasing ShuVoice PTT → agent mic resumes
- [ ] 5-minute session cap fires correctly
- [ ] No raw selected text in `journalctl --user -u shuvagent`
- [ ] Config validation rejects voice `"fable"` with helpful message
- [ ] First-audio latency < 3s on home network

### 13.3 Opt-in live smoke

`OPENAI_API_KEY=sk-... pytest tests/integration/test_live_realtime.py`

Should pass in < 30s. Logs total cost.

---

## 14. Non-goals (this plan)

Explicit list of what PLAN-01 will **not** ship:

- Write tools (`paste_text`, `replace_selected_text`, `copy_to_clipboard`,
  `stop_speaking`, `speak_text`) — PLAN-02
- Persistent memory / conversation history — deferred indefinitely until
  product decision
- Overlay UI — CLI status only in v1; overlay in PLAN-02 or later
- MCP tool integration — PLAN-03+
- OpenAI hosted tools (search, computer-use) — PLAN-03+
- Browser automation (shuvgeist bridge) — PLAN-04+
- Maple Ingest live integration — schema-compatible from day one; HTTP
  export is a follow-up
- Shared `shuvdesktop-core` package — PLAN-N after duplication is
  proven (PLAN-42 M5)
- Always-listening wake word
- WebRTC transport — WebSocket only in v1

---

## 15. Open questions for reviewers

Numbered so reviewers can reference them.

1. **Default voice.** Is `marin` the right default given known
   instruction-following weakness, or should we ship `verse` and let
   power users opt into `marin`/`cedar`?
2. **Coordination polling interval.** 1.0s feels right. Anyone want
   500ms / 2.0s with reasoning?
3. **Session duration cap.** 5 min default. Too short? Too long?
4. **Mypy strictness.** Strict only on `tools/` initially, or
   strict-everywhere from day one?
5. **`local.dev` env loader.** Mirror ShuVoice's now (and dedupe later),
   or extract a tiny shared package immediately?
6. **`shuvoice control version` verb.** Will the shuvoice maintainer
   accept the 4-line PR? If not, is "unknown version" silently OK?
7. **CLI status command output.** Plain text "OK idle" / "OK active …"
   vs JSON? ShuVoice uses plain text; consistency vs structured.
8. **Audit-event sink.** Stdout JSON only in v1, or also a rolling file
   at `~/.local/share/shuvagent/audit.log`?

---

## 16. Approval gate

This plan should not move to implementation until:

- [ ] Reviewer ✅ — voice / model / coordination decisions (§3–7)
- [ ] Reviewer ✅ — telemetry shape (§8) matches Maple expectations
- [ ] Reviewer ✅ — `GatedToolCall` type-level enforcement (§6.2) is the
      right shape
- [ ] Reviewer ✅ — session duration + token caps (§10) acceptable
- [ ] shuvoice maintainer ✅ — `version` verb PR accepted or rejected
      (§11)
- [ ] All open questions §15 closed or punted with explicit reasoning

After approval, implementation starts at Milestone 1.0 and proceeds
strictly in order. Each milestone ends with the exit gate in §2 — no
skipping ahead.
