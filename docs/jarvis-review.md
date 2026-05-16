# Jarvis → ShuvAgent Feature Review

> **Date:** 2026-05-16  
> **Source:** [`github.com/isair/jarvis`](https://github.com/isair/jarvis) (cloned at HEAD)  
> **Target:** `shuvagent` — desktop voice-agent for Linux/Hyprland built on OpenAI GPT-Realtime-2

---

## 1. Executive Summary

Jarvis is a **100% local, 100% offline** voice assistant (macOS primary, Windows/Linux secondary) built on Ollama. It has an enormous feature surface — local Whisper STT, local Piper TTS, wake-word detection, knowledge-graph memory, MCP integration, nutrition tracking, browser automation, dictation mode, and a full desktop UI.

Shuvagent is a **cloud-based** voice assistant built on OpenAI GPT-Realtime-2. It is session-based, runs on Linux/Hyprland only, and deliberately defers many features to later plans. Its core safety architecture (`PermissionGate` → `GatedToolCall` → `ToolRegistry`) is stronger than Jarvis's flat tool-dispatch model.

**Key insight:** Because shuvagent offloads STT/TTS/inference to OpenAI, it can afford to invest its local complexity budget in **desktop context tools** (screen, files, web) and **integration layers** (MCP, memory) rather than local AI infrastructure. Many Jarvis features are *irrelevant* to shuvagent (local LLM, local Whisper, local TTS, wake-word, dictation). The features that *are* relevant are high-impact and well-scoped.

---

## 2. Architecture Comparison

| Dimension | Jarvis | Shuvagent |
|---|---|---|
| **AI backend** | Ollama (local, 100% offline) | OpenAI GPT-Realtime-2 (cloud) |
| **STT** | Whisper (local, multiple backends) | OpenAI server-side (`gpt-4o-mini-transcribe`) |
| **TTS** | Piper / Chatterbox (local) | OpenAI server-side (Realtime voice) |
| **Wake word** | "Jarvis" anywhere in utterance | None — session-based activation |
| **Activation** | Always-listening → PTT hybrid | Explicit start/stop binds |
| **Memory** | SQLite diary + knowledge graph | None (ephemeral sessions) |
| **Tool registry** | Flat dispatch via `Tool.run()` | `PermissionGate` → `GatedToolCall` → `ToolRegistry` |
| **Tool selection** | Keyword / embedding / LLM router | All tools sent to model every turn |
| **MCP integration** | Full — persistent stdio sessions | Deferred to PLAN-03+ |
| **Desktop UI** | Tray icon, face widget, settings, memory viewer | CLI status only (overlay deferred) |
| **Platform** | macOS primary, Windows, Linux | Linux/Hyprland only |
| **Coordination** | None (sole mic owner) | ShuVoice mic arbitration |
| **Telemetry** | Debug logs only | Maple-compatible structured JSON |
| **Redaction** | Auto-redact emails, tokens, passwords | API keys + selected text (configurable) |
| **Session cost** | $0 (local compute) | ~$0.02–0.10 per minute |

---

## 3. Feature Gap Analysis

### 3.1 Tools ShuvAgent Already Has

| Tool | Status | Notes |
|---|---|---|
| `get_selected_text` | ✅ Shipped | Read-only, redacted in telemetry |
| `get_clipboard_text` | ✅ Shipped | Read-only |
| `get_active_window` | ✅ Shipped | `WindowSnapshot` for context grounding |
| `get_shuvoice_status` | ✅ Shipped | Coordination primitive |
| `paste_text` | ✅ Spec + tests | PLAN-02, requires confirmation |
| `replace_selected_text` | ✅ Spec + tests | PLAN-02, requires confirmation |
| `copy_to_clipboard` | ✅ Spec + tests | PLAN-02, requires confirmation |

### 3.2 Tools Jarvis Has That ShuvAgent Lacks

| Feature | Jarvis Impl | Relevance to ShuvAgent | Risk Level |
|---|---|---|---|
| **Web search** (`webSearch`) | DuckDuckGo → Brave → Wikipedia cascade, SSRF protection, parallel fetch, relevance scoring | **High** — natural complement to cloud assistant; read-only external | `EXTERNAL` |
| **Fetch web page** (`fetchWebPage`) | Generic HTTP fetch + BeautifulSoup text extraction | **High** — follows links from web search; read-only external | `EXTERNAL` |
| **Screenshot / OCR** (`screenshot`) | `screencapture` + `tesseract` (macOS); needs `grim` + `tesseract` on Linux | **High** — desktop context without selected text; read-only | `READ` |
| **Local files** (`localFiles`) | Read/write/list/append/delete within `~` with path traversal guards | **High** — read-only subset fits PLAN-01; write subset fits PLAN-02 | `READ` / `LOCAL_VISIBLE_WRITE` |
| **Weather** (`getWeather`) | Open-Meteo API (free, no key), with GeoIP auto-location | **Medium** — nice-to-have; requires location infra | `EXTERNAL` |
| **MCP integration** | Persistent stdio sessions, idle timeout, tool discovery, retry on worker death | **Very High** — unlocks thousands of tools (GitHub, Home Assistant, Slack, etc.) | Varies per tool |
| **Memory / recall** | SQLite diary + knowledge graph (`user` / `directives` / `world` branches), embeddings | **High** — differentiates agent from stateless chat; requires product decision | N/A (system feature) |
| **Tool router / selection** | Keyword / embedding / LLM strategies, `ALWAYS_INCLUDED` set, hard caps | **Medium-High** — needed as tool count grows; prevents context bloat | N/A |
| **Time context injection** | Auto-inject current time, date, day-of-week into system prompt | **Medium** — trivial to add, high user value | N/A |
| **Location context** | GeoLite2 DB, UPnP, socket heuristic, OpenDNS fallback | **Low-Medium** — only needed for weather / local-aware replies | N/A |
| **Nutrition tracking** | Log/fetch/delete meals, calorie goals | **Low** — niche; not desktop-agent core | `LOCAL_VISIBLE_WRITE` |
| **Dictation mode** | Hotkey-to-text, filler-word removal, custom dictionary | **Low** — ShuVoice already has PTT dictation | N/A |
| **Browser automation** | Via MCP (`chrome-devtools-mcp`) | **Medium** — MCP covers this; no bespoke code needed | Varies |
| **TTS engine selection** | Piper / Chatterbox | **N/A** — OpenAI Realtime handles TTS |
| **STT model selection** | Whisper tiny → large-v3-turbo | **N/A** — OpenAI Realtime handles STT |
| **Wake word / intent judge** | `gemma4:e2b` for echo detection, stop commands, query extraction | **N/A** — session-based, no always-listening |
| **Desktop UI** | Face widget, settings window, memory viewer, dictation history | **Low** — CLI status in v1; overlay deferred |
| **Auto-updater** | GitHub releases polling, update dialog | **Low** — package-manager territory |

---

## 4. Prioritized Feature List for ShuvAgent

### Tier 1 — Immediate Value, Low Risk

These can be added **without** changing core architecture. Each ships as a new builtin tool or a system-prompt enhancement.

**Current implementation note:** The Tier 1 surfaces in this section now have
repo-backed specs and fake-collaborator test coverage. They are exposed as
opt-in context tools and are not part of the minimal live default tool set.

#### 4.1 `web_search` builtin tool

**What:** Search the web using DuckDuckGo with Brave Search opt-in fallback and Wikipedia zero-config fallback.  
**Why:** The most common "I don't know that" scenario for a voice assistant. The model's knowledge cutoff is real; users ask about news, weather, sports, current events.  
**Risk:** `EXTERNAL` — read-only, no local mutation. Safe to add without confirmation UI.  
**Key design choices from Jarvis to port:**
- SSRF protection (`_is_public_url`) — resolve hostnames, reject private/loopback/link-local IPs
- Manual redirect walk with per-hop re-validation
- Parallel cascade fetch of top-3 results under shared wall-clock cap (~8s)
- Query-token relevance scoring — reject fetches with zero token overlap (boilerplate detection)
- DuckDuckGo bot-challenge detection (`anomaly-modal` / `anomaly.js` in body)
- Honest failure envelopes — tell the model "search was blocked" rather than letting it confabulate
- Total chain wall-clock cap (~20s) so a stalled provider can't freeze the voice assistant

**Dependencies:** `requests`, `beautifulsoup4` (optional — graceful fallback to raw text).  
**Status:** Implemented with stdlib HTTP transport, DuckDuckGo instant/HTML,
Brave opt-in fallback, Wikipedia fallback, SSRF guards, query-token overlap
filtering, and total/page timeout caps.
**Config:**
```toml
[tools.web_search]
enabled = true
brave_search_api_key = ""          # opt-in fallback
wikipedia_fallback_enabled = true
```

#### 4.2 `fetch_web_page` builtin tool

**What:** Fetch and extract text content from a user-provided URL.  
**Why:** Complements `web_search` — the model finds a link, then asks to read it. Also useful for "summarize this page for me."  
**Risk:** `EXTERNAL` — read-only.  
**Key design choices:**
- Same SSRF protection as `web_search` (reuse `_is_public_url`)
- BeautifulSoup text extraction with script/style/meta removal
- Deduplicate consecutive identical lines (common on badly-structured sites)
- Truncate to 50K chars max to protect context window
- Optional link extraction (`include_links` param)

**Dependencies:** `beautifulsoup4` is optional; raw extraction is used when it
is unavailable.  
**Status:** Implemented with SSRF and redirect-target revalidation, title/text
extraction, optional link reporting, and truncation.

#### 4.3 `screenshot` builtin tool

**What:** Capture a screen region and OCR the text.  
**Why:** "What's on my screen?" is a natural voice query. Selected text only works when text is already highlighted; screenshot works on any visual content (images, PDFs, terminals, diagrams).  
**Risk:** `READ` — no mutation, just observation.  
**Key design choices:**
- Linux/Wayland: `grim` for capture, `tesseract` + `pytesseract` + `Pillow` for OCR
- Interactive region selection (`grim -g` with slurp) — user draws a box
- Fallback: full-screen capture if region tools unavailable
- Return raw OCR text; the model decides what to do with it
- No LLM post-processing in the tool (keep tools dumb)

**Dependencies:** `grim`, `slurp`, and `tesseract` are optional runtime
commands; the tool returns a clear error if capture or OCR is unavailable.  
**Status:** Implemented with injected runners for tests, region selection via
`slurp`, full-screen fallback, and empty-OCR success behavior.
**Config:**
```toml
[tools.screenshot]
enabled = true
ocr_engine = "tesseract"           # only option in v1
```

#### 4.4 `local_files` builtin tool (read-only subset)

**What:** Read and list files within the user's home directory.  
**Why:** "What's in my `~/projects/foo` directory?" / "Read me the contents of `~/.bashrc`."  
**Risk:** `READ` for list/read operations. Write operations (`write`, `append`, `delete`) are `LOCAL_VISIBLE_WRITE` / `DESTRUCTIVE` and require confirmation.  
**Key design choices:**
- Path traversal guard: resolve path, verify it's within `~` (or a configured allowlist)
- `~` expansion support
- `list`: glob pattern, optional recursive, 50-file limit
- `read`: UTF-8 with replacement, 10K char truncation
- No binary file handling in v1

**Dependencies:** None (stdlib only).
**Status:** Implemented for read/list within the configured home root, with
tilde expansion, glob/recursive listing, truncation, and binary-file rejection.

#### 4.5 `time_context` system prompt injection

**What:** Auto-inject current time, date, day-of-week, and timezone into the system prompt.  
**Why:** The model has no idea what time it is unless told. Users ask "what time is it?", "schedule a meeting for tomorrow", "remind me in 10 minutes."  
**Risk:** None — prompt engineering only.  
**Implementation:** Build a time string in `OpenAISessionConfig.instructions` builder:
```
Current time: 2026-05-16 14:32:00 UTC (Saturday)
```
Update on every `session.update` or at session start.

**Status:** Implemented in `OpenAIRealtimeSession._session_update_payload()`;
each session update receives a fresh local time string.

---

### Tier 2 — Significant Value, Medium Complexity

These require new subsystems or architectural changes.

#### 4.6 MCP integration

**What:** Connect to external tool servers via the Model Context Protocol (MCP). Persistent stdio sessions, tool discovery, dynamic registration.  
**Why:** This is the **biggest capability multiplier**. A single MCP config unlocks GitHub, Home Assistant, Slack, Notion, databases, browser automation, Google Workspace, and 500+ apps via Composio.  
**Risk:** Varies per tool — MCP tools can do anything. The permission gate must handle them.  
**Key design choices from Jarvis to port:**
- Persistent stdio sessions: one subprocess per server, kept alive across tool calls
- Per-server serialisation: stdio is single-channel, so calls to one server queue up
- Idle timeout reaping: optional `idle_timeout_sec` for stateless servers
- Worker death retry: if a subprocess crashes, replace the worker and retry once
- Tool namespacing: `server_name__tool_name` to avoid collisions
- Dynamic tool discovery: `list_tools` on each server at session start
- Tool schema translation: MCP `ToolSpec` → OpenAI function schema

**Dependencies:** `mcp` Python SDK (`pip install mcp`).  
**Config:**
```toml
[mcps.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "ghp_..." }

[mcps.home_assistant]
command = "mcp-proxy"
args = ["http://localhost:8123/mcp_server/sse"]
env = { API_ACCESS_TOKEN = "..." }
```

**Integration with permission gate:**
- MCP tools inherit risk from a mapping table (or default to `EXTERNAL`)
- The gate must be able to dynamically register/unregister tools as MCP servers come and go
- Audit events must include the MCP server name

#### 4.7 Tool router / selection

**What:** Filter the tool catalogue per-query so the model only sees relevant tools.  
**Why:** As tool count grows (builtins + MCP servers), the system prompt grows. GPT-Realtime-2 has a context window; too many tools degrade performance. Jarvis observed this with small models (2B) — large tool lists cause the model to ignore instructions.  
**Risk:** None — filtering only, no new capabilities.  
**Strategies to implement:**
1. **`all`** (default today) — no filtering
2. **`keyword`** — fast, no LLM; score tools by keyword overlap with query
3. **`llm`** — ask a small LLM (can reuse the chat model via a cheap completion call) to pick relevant tools; hard cap at 5
4. **`embedding`** (future) — requires local embedding model; not suitable for cloud-first architecture

**Integration point:** Between `app.py` and `OpenAIRealtimeSession` — filter `config.tools` before sending `session.update`.

#### 4.8 Weather tool

**What:** Get current weather and forecast via Open-Meteo (free, no API key).  
**Why:** Common voice query. Only relevant if we also have location detection.  
**Risk:** `EXTERNAL` (Open-Meteo API).  
**Dependencies:** Location detection (see below) or manual city config.  
**Config:**
```toml
[tools.weather]
enabled = true
location_auto_detect = true
location_ip_address = ""           # manual override
```

#### 4.9 Location detection

**What:** Auto-detect user's location for weather-aware responses and local time.  
**Why:** Needed by weather tool; also useful for "what time is it in my timezone?"  
**Risk:** Minimal external egress — single OpenDNS DNS query or UPnP (LAN-only).  
**Approach:**
1. Manual IP override (config)
2. UPnP query to router (no external traffic)
3. Socket heuristic (no external traffic)
4. `myip.opendns.com` DNS lookup (single external query)
5. GeoLite2 MMDB lookup (local DB, free MaxMind account)

**Dependencies:** `geoip2` + GeoLite2-City.mmdb (optional).

---

### Tier 3 — Product Decision Required

These need human approval before implementation.

#### 4.10 Memory / recall system

**What:** Persistent conversation memory — diary (chronological) + knowledge graph (`user` / `directives` / `world` branches).  
**Why:** "What did we talk about yesterday?" / "You said you'd remind me about X." / "I told you I prefer dark mode."  
**Risk:** Privacy — memory is stored locally in SQLite, but the content of conversations is sensitive. Needs redaction before storage.  
**Key design choices from Jarvis:**
- SQLite-backed, thread-safe
- Three fixed top-level branches: `user`, `directives`, `world`
- Self-organising: auto-split when node exceeds token threshold; auto-merge sparse children
- Time-decayed access scoring (hyperbolic decay)
- Mutation listeners for cache invalidation
- Fuzzy deduplication via `normalise_fact` (NFKC + casefold + whitespace collapse)
- Warm profile: `user` + `directives` injected into system prompt every turn
- Search: keyword match across name/description/data with relevance scoring

**AGENTS.md constraint:** "No persistent memory in v1. Sessions are ephemeral. Transcript storage requires an explicit product decision."  
**Recommendation:** Build the infra (schema, CRUD, search) but keep it **opt-in** via config. Default off until product approves.

#### 4.11 Extended redaction

**What:** More comprehensive PII redaction before anything hits logs or memory.  
**Why:** Jarvis redacts emails, tokens, passwords, API keys, phone numbers, credit cards. Shuvagent currently redacts API keys and selected text.  
**Patterns to add:**
- Email addresses: `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`
- Phone numbers (common formats)
- Credit card numbers (Luhn-validated)
- IP addresses (IPv4 / IPv6)
- Social security / national ID patterns
- Custom patterns from config

**Implementation:** `shuvagent/telemetry/redact.py` — extend the redaction pipeline.

---

## 5. Implementation Order

The order below respects dependencies and maximizes early user value:

| Order | Feature | Tier | Depends On | Est. Effort |
|---|---|---|---|---|
| 1 | `time_context` injection | 1 | None | 2h |
| 2 | `web_search` tool | 1 | None | 1 day |
| 3 | `fetch_web_page` tool | 1 | `web_search` (shares SSRF utils) | 4h |
| 4 | `local_files` tool (read) | 1 | None | 4h |
| 5 | `screenshot` tool | 1 | None | 1 day |
| 6 | Tool router (`keyword` + `llm`) | 2 | Growing tool count | 1 day |
| 7 | MCP integration | 2 | Tool router (to manage large catalogues) | 2–3 days |
| 8 | Location detection | 2 | None | 4h |
| 9 | `weather` tool | 2 | Location detection | 2h |
| 10 | Memory / recall system | 3 | Product decision | 3–5 days |
| 11 | Extended redaction | 3 | None | 4h |

Tier 1 implementation status on 2026-05-16: items 1-5 have code and tests.
Item 6 has a standalone router helper and tests. Item 9 has a builtin weather
tool and tests; full automatic location detection remains future work. Item 10
has an opt-in SQLite graph store only; persistent conversation memory is still
outside v1 live runtime. Item 11 has extended telemetry redaction helpers and
tests.

---

## 6. Test Plan

Every new feature must have tests before merge. The test files live in `tests/` and follow shuvagent's existing patterns:

- **Fake collaborators** — inject fakes at the `spec()` factory, never monkeypatch
- **Permission gate** — verify risk classification and authorization behavior
- **Registry execution** — verify `ToolRegistry.execute()` works end-to-end
- **Failure paths** — network errors, missing dependencies, bad input, security violations
- **Security** — where applicable, verify the tool cannot escape its sandbox

| Feature | Test File | Key Test Cases |
|---|---|---|
| `web_search` | `tests/test_builtin_web_search.py` | DDG search returns results; Brave fallback fires when DDG blocked; Wikipedia fallback; SSRF rejects private IPs; bot-challenge detection; zero-result honest envelope; parallel cascade timeout |
| `fetch_web_page` | `tests/test_builtin_fetch_web_page.py` | Fetch + extract text; include_links param; truncate at 50K; SSRF rejects non-public URLs; missing BeautifulSoup graceful fallback; HTTP error handling |
| `screenshot` | `tests/test_builtin_screenshot.py` | OCR returns text from fake image; missing `grim` returns error; missing `tesseract` returns error; empty OCR returns empty string |
| `local_files` | `tests/test_builtin_local_files.py` | List files in temp dir; read file content; path traversal rejected; `~` expansion; recursive list; glob pattern; read truncation; binary file rejection |
| `weather` | `tests/test_builtin_weather.py` | Weather for known lat/lon; geocoding by city name; manual location override; missing location asks user; timeout handling; WMO code mapping |
| MCP | `tests/test_mcp_integration.py` | Discover tools from fake server; invoke tool through persistent session; worker death retry; idle timeout reaping; tool namespacing; schema translation |
| Memory graph | `tests/test_memory_graph.py` | Create/read/update/delete nodes; fixed branches seeded; subtree query; search by keyword; deduplication; token estimation; access scoring |
| Tool router | `tests/test_tool_router.py` | Keyword strategy filters correctly; LLM strategy returns capped list; `all` strategy returns everything; unknown strategy falls back; always-included tools preserved |
| Time context | `tests/test_time_context.py` | Time string format; daylight saving awareness; timezone inclusion |

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Web search SSRF | `_is_public_url` — DNS resolution + IP allowlist; manual redirect walk; reject non-http(s) schemes |
| Web search bot-challenge | Detect structural markers (`anomaly-modal`, `anomaly.js`) not English copy; emit honest-block envelope so model admits failure |
| Web search prompt injection from fetched pages | Fence with `<<<BEGIN UNTRUSTED WEB EXTRACT>>>` / `<<<END>>>`; instruct model to treat as data not instructions |
| Local files path traversal | Resolve to absolute, verify prefix match against `~` or configured allowlist; reject `..` and symlinks outside allowlist |
| Screenshot OCR exposes sensitive screen content | Same as selected text — redact in telemetry; model sees full OCR text (that's the feature) |
| MCP tools can do anything | Default risk = `EXTERNAL`; require confirmation for write/destructive MCP tools; dynamic risk mapping table in config |
| MCP worker death leaves zombie processes | `_PersistentMCPRuntime` idle timeout reaping; explicit `shutdown_runtime()` on app exit; task cancellation on shutdown |
| Memory storage privacy | Redact before storage; opt-in config; no cloud sync |
| Tool router LLM call adds latency | Cap at 5 tools, tight timeout (6s); fallback to `keyword` on failure |
| Too many tools bloat context | `MAX_SELECTED = 8` hard cap; tool router enabled by default when tool count > 10 |

---

## 8. Config Schema Additions

```toml
[tools.web_search]
enabled = true
brave_search_api_key = ""
wikipedia_fallback_enabled = true
total_timeout_sec = 20.0

[tools.fetch_web_page]
enabled = true
max_chars = 50000

[tools.screenshot]
enabled = true
ocr_engine = "tesseract"

[tools.local_files]
enabled = true
allowlist = ["~"]                    # paths the tool can access
max_read_chars = 10000
max_list_files = 50

[tools.weather]
enabled = true
location_auto_detect = true
location_ip_address = ""

[mcps]
# Per-server entries — see §4.6

[memory]
enabled = false                      # opt-in until product decision
graph_db_path = "~/.local/share/shuvagent/memory/graph.db"

[planning]
tool_router_strategy = "all"         # all | keyword | llm
llm_router_timeout_sec = 6.0
max_tools_per_turn = 8

[privacy.redaction]
redact_emails = true
redact_phone_numbers = true
redact_credit_cards = true
redact_ip_addresses = true
custom_patterns = []                 # list of regex strings
```

---

## 9. Appendix: Jarvis Files Reviewed

| File | Purpose | Ported To ShuvAgent? |
|---|---|---|
| `src/jarvis/tools/builtin/web_search.py` | Web search with cascade fallback | ✅ Yes — `web_search` tool |
| `src/jarvis/tools/builtin/fetch_web_page.py` | Generic page fetcher | ✅ Yes — `fetch_web_page` tool |
| `src/jarvis/tools/builtin/screenshot.py` | Screen capture + OCR | ✅ Yes — `screenshot` tool (Linux variant) |
| `src/jarvis/tools/builtin/local_files.py` | Safe file operations | ✅ Yes — `local_files` tool |
| `src/jarvis/tools/builtin/weather.py` | Open-Meteo weather | ✅ Yes — `weather` tool |
| `src/jarvis/tools/external/mcp_runtime.py` | Persistent MCP stdio sessions | ✅ Yes — MCP integration |
| `src/jarvis/tools/selection.py` | Tool router (keyword/embedding/LLM) | ✅ Yes — tool router |
| `src/jarvis/memory/graph.py` | Knowledge graph memory | ⚠️ Yes — opt-in, product decision needed |
| `src/jarvis/utils/time_context.py` | Time injection | ✅ Yes — `time_context` |
| `src/jarvis/utils/location.py` | Location detection | ✅ Yes — location detection |
| `src/jarvis/utils/redact.py` | PII redaction | ✅ Yes — extended redaction |
| `src/jarvis/listening/wake_detection.py` | Wake word detection | ❌ No — session-based, not always-listening |
| `src/jarvis/listening/intent_judge.py` | Echo/stop/query classification | ❌ No — OpenAI handles turn detection |
| `src/jarvis/output/tts.py` | Local TTS (Piper/Chatterbox) | ❌ No — OpenAI Realtime provides TTS |
| `src/jarvis/dictation/dictation_engine.py` | Hotkey dictation | ❌ No — ShuVoice has PTT dictation |
| `src/desktop_app/face_widget.py` | Desktop face UI | ❌ No — overlay deferred |
| `src/desktop_app/memory_viewer.py` | Memory GUI | ❌ No — no memory in v1 |
| `src/jarvis/tools/builtin/nutrition/*.py` | Meal tracking | ❌ No — niche, out of scope |
