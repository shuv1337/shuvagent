"""Live OpenAI GPT-Realtime-2 session over WebSocket.

Implements the :class:`shuvagent.realtime.session.RealtimeAgentSession`
Protocol against ``wss://api.openai.com/v1/realtime``.

Wire format (subset used here):

* Outbound — ``session.update``, ``input_audio_buffer.append``,
  ``input_audio_buffer.commit``, ``conversation.item.create``
  (function-call result), ``response.cancel``.
* Inbound — ``response.audio.delta`` (b64 PCM16), ``response.done``,
  ``response.function_call_arguments.done``, ``error``, anything else
  is ignored at this level (transcripts will be surfaced in a later
  milestone).

This module is **gated behind ``OPENAI_API_KEY``**. It does not import
``websockets`` at module load — the dependency is lazy-imported inside
:meth:`OpenAIRealtimeSession.connect`, so the unit tests for the
Protocol shape and event parsing can run without the optional dep.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from shuvagent.realtime.events import RealtimeError, SessionState
from shuvagent.tools.types import ToolCallRequest, ToolSpec

REALTIME_URL = "wss://api.openai.com/v1/realtime"


@dataclass(frozen=True)
class OpenAISessionConfig:
    """Configuration for an :class:`OpenAIRealtimeSession`."""

    api_key: str
    model: str = "gpt-realtime-2"
    voice: str = "marin"
    instructions: str = (
        "You are a desktop voice assistant. Be concise. "
        "Use the available read-only tools to ground answers in what is "
        "on the user's screen. Do not invent context — call a tool if "
        "you need it."
    )
    reasoning_effort: str = "low"
    tools: tuple[ToolSpec, ...] = ()
    request_timeout_sec: float = 10.0
    # Optional URL override (tests / staging).
    url: str = REALTIME_URL


@dataclass
class OpenAIRealtimeSession:
    """WebSocket-backed implementation of :class:`RealtimeAgentSession`.

    Typical lifecycle::

        session = OpenAIRealtimeSession(OpenAISessionConfig(api_key=...))
        await session.connect()
        await session.send_audio(pcm_chunk)
        await session.commit_input()
        async for chunk in session.audio_out:
            playback.play(chunk)
        await session.close()
    """

    config: OpenAISessionConfig
    state: SessionState = SessionState.CLOSED
    is_open: bool = False
    is_paused: bool = False

    _ws: Any = field(default=None, init=False, repr=False)
    _audio_out_queue: asyncio.Queue[bytes | None] = field(init=False, repr=False)
    _tool_call_queue: asyncio.Queue[ToolCallRequest | None] = field(
        init=False, repr=False
    )
    _error_queue: asyncio.Queue[RealtimeError | None] = field(init=False, repr=False)
    _reader_task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._audio_out_queue = asyncio.Queue()
        self._tool_call_queue = asyncio.Queue()
        self._error_queue = asyncio.Queue()
        self.audio_out = _iter_queue(self._audio_out_queue)
        self.tool_calls = _iter_queue(self._tool_call_queue)
        self.errors = _iter_queue(self._error_queue)

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        self.state = SessionState.CONNECTING
        try:
            import websockets  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "OpenAIRealtimeSession requires the 'websockets' package. "
                "Install with: uv pip install websockets"
            ) from exc

        url = f"{self.config.url}?model={self.config.model}"
        headers = [
            ("Authorization", f"Bearer {self.config.api_key}"),
            ("OpenAI-Beta", "realtime=v1"),
        ]
        self._ws = await asyncio.wait_for(
            websockets.connect(url, additional_headers=headers),
            timeout=self.config.request_timeout_sec,
        )
        await self._ws.send(json.dumps(self._session_update_payload()))
        self.is_open = True
        self.state = SessionState.READY
        self._reader_task = asyncio.create_task(self._read_loop())

    async def send_audio(self, pcm16: bytes) -> None:
        self._require_open()
        payload = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm16).decode("ascii"),
        }
        await self._ws.send(json.dumps(payload))
        self.state = SessionState.LISTENING

    async def commit_input(self) -> None:
        self._require_open()
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def send_tool_result(
        self,
        call_id: str,
        result: dict[str, object],
    ) -> None:
        self._require_open()
        payload = {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result),
            },
        }
        await self._ws.send(json.dumps(payload))
        # Ask the model to continue speaking with the tool result.
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def cancel_response(self) -> None:
        if not self.is_open or self._ws is None:
            return
        await self._ws.send(json.dumps({"type": "response.cancel"}))

    async def pause(self, reason: str) -> None:
        del reason
        self.is_paused = True
        if self.is_open and self._ws is not None:
            await self._ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
            await self._ws.send(json.dumps({"type": "response.cancel"}))
        self.state = SessionState.PAUSED

    async def resume(self, reason: str) -> None:
        del reason
        self.is_paused = False
        if self.is_open:
            self.state = SessionState.READY

    async def close(self) -> None:
        self.is_open = False
        self.state = SessionState.CLOSED
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # pragma: no cover - close best-effort
                pass
            self._ws = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        await self._audio_out_queue.put(None)
        await self._tool_call_queue.put(None)
        await self._error_queue.put(None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _require_open(self) -> None:
        if not self.is_open or self._ws is None:
            raise RuntimeError("session is closed")

    def _session_update_payload(self) -> dict[str, Any]:
        return {
            "type": "session.update",
            "session": {
                "model": self.config.model,
                "voice": self.config.voice,
                "modalities": ["audio", "text"],
                "instructions": self.config.instructions,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
                "turn_detection": {
                    "type": "server_vad",
                    "create_response": True,
                    "interrupt_response": True,
                },
                "tools": [_tool_to_openai_function(t) for t in self.config.tools],
                "tool_choice": "auto",
            },
        }

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    # Realtime API uses text frames; ignore stray binary.
                    continue
                await self._handle_event(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - network failure
            await self._error_queue.put(
                RealtimeError("ws_read_error", str(exc))
            )

    async def _handle_event(self, event: Mapping[str, Any]) -> None:
        etype = event.get("type", "")
        if etype == "response.audio.delta":
            audio_b64 = event.get("delta") or event.get("audio") or ""
            if isinstance(audio_b64, str) and audio_b64:
                self.state = SessionState.SPEAKING
                await self._audio_out_queue.put(base64.b64decode(audio_b64))
            return
        if etype == "response.function_call_arguments.done":
            call_id = str(event.get("call_id") or event.get("id") or "")
            name = str(event.get("name") or "")
            args_raw = event.get("arguments") or "{}"
            try:
                arguments = json.loads(args_raw) if isinstance(args_raw, str) else {}
            except json.JSONDecodeError:
                arguments = {}
            if call_id and name:
                await self._tool_call_queue.put(
                    ToolCallRequest(
                        call_id=call_id,
                        tool_name=name,
                        arguments=arguments,
                    )
                )
            return
        if etype == "response.done":
            self.state = SessionState.READY
            return
        if etype == "error":
            err = event.get("error", {})
            if isinstance(err, Mapping):
                code = str(err.get("code") or "error")
                message = str(err.get("message") or "")
            else:
                code, message = "error", str(err)
            await self._error_queue.put(RealtimeError(code, message))
            return
        # Other events (transcripts, session lifecycle, rate-limits) are
        # silently ignored at this milestone; surfaced in later plans.


def _tool_to_openai_function(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }


async def _iter_queue(queue: asyncio.Queue) -> AsyncIterator:
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
