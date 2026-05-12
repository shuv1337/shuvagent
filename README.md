# shuvagent

A desktop voice-agent app for Linux/Hyprland built on OpenAI's
**GPT-Realtime-2** API.

**Status:** pre-implementation. Plan under review.

- Product-shape doc (parent):
  [`PLAN-42` in shuvoice repo](../shuvoice/PLAN-42-desktop-agent-gpt-realtime-2.md)
- First implementation plan: [`PLAN-01-bootstrap-and-first-slice.md`](./PLAN-01-bootstrap-and-first-slice.md)
- Operating rules: [`AGENTS.md`](./AGENTS.md)

## Relationship to ShuVoice

ShuVoice (`~/repos/shuvoice`) owns push-to-talk dictation. `shuvagent`
owns conversational voice + desktop tool calls. They run as separate
user processes with separate sockets and configs. ShuVoice always wins
mic contention.

## Why a separate app?

ShuVoice's existing `OpenAIRealtimeBackend` opens a
`?intent=transcription` WebSocket — it's a one-way data path,
structurally not a conversational agent session. Bolting bidirectional
audio + tool calls onto an ASR backend would tangle two products in
one process. `PLAN-42` rejects that approach; this repo is the
alternative.

## License

MIT (TBD — single-file license to be added before first release).
