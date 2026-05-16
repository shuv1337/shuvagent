from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from shuvagent.realtime.events import (
    RealtimeApiEvent,
    RealtimeError,
    ScriptedTurn,
    SessionState,
)
from shuvagent.tools.types import ToolCallRequest


class FakeRealtimeSession:
    def __init__(self, turns: Iterable[ScriptedTurn]) -> None:
        self._turns = list(turns)
        self._audio_out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._tool_call_queue: asyncio.Queue[ToolCallRequest | None] = asyncio.Queue()
        self._error_queue: asyncio.Queue[RealtimeError | None] = asyncio.Queue()
        self._api_event_queue: asyncio.Queue[RealtimeApiEvent | None] = asyncio.Queue()
        self._pending_audio = bytearray()
        self._next_turn = 0
        self.tool_results: list[tuple[str, dict[str, object]]] = []
        self.sent_audio: list[bytes] = []
        self.cancel_count = 0
        self.fail_cancel_response = False
        self.state = SessionState.CLOSED
        self.is_open = False
        self.is_paused = False
        self.audio_out = self._iter_queue(self._audio_out_queue)
        self.tool_calls = self._iter_queue(self._tool_call_queue)
        self.errors = self._iter_queue(self._error_queue)
        self.api_events = self._iter_queue(self._api_event_queue)

    async def connect(self) -> None:
        self.state = SessionState.READY
        self.is_open = True

    async def send_audio(self, pcm16: bytes) -> None:
        if not self.is_open:
            raise RuntimeError("session is closed")
        self._pending_audio.extend(pcm16)
        self.sent_audio.append(pcm16)
        self.state = SessionState.LISTENING

    async def commit_input(self) -> None:
        if not self.is_open:
            raise RuntimeError("session is closed")
        if self._next_turn >= len(self._turns):
            await self._error_queue.put(RealtimeError("script_exhausted", "no turn"))
            return

        turn = self._turns[self._next_turn]
        self._next_turn += 1
        if bytes(self._pending_audio) != turn.user_audio:
            await self._error_queue.put(
                RealtimeError("unexpected_audio", "scripted audio did not match")
            )
            self._pending_audio.clear()
            return

        self._pending_audio.clear()
        if turn.tool_call is not None:
            await self._tool_call_queue.put(turn.tool_call)
        if turn.audio_response:
            self.state = SessionState.SPEAKING
            await self._audio_out_queue.put(turn.audio_response)

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        self.tool_results.append((call_id, result))

    async def cancel_response(self) -> None:
        self.cancel_count += 1
        if self.fail_cancel_response:
            raise RuntimeError("cancel failed")

    async def close(self) -> None:
        self.state = SessionState.CLOSED
        self.is_open = False
        await self._audio_out_queue.put(None)
        await self._tool_call_queue.put(None)
        await self._error_queue.put(None)
        await self._api_event_queue.put(None)

    async def emit_api_event(self, event: RealtimeApiEvent) -> None:
        await self._api_event_queue.put(event)

    async def emit_error(self, error: RealtimeError) -> None:
        await self._error_queue.put(error)

    async def pause(self, reason: str) -> None:
        del reason
        self.is_paused = True
        self.state = SessionState.PAUSED

    async def resume(self, reason: str) -> None:
        del reason
        self.is_paused = False
        self.state = SessionState.READY

    async def _iter_queue(self, queue: asyncio.Queue) -> AsyncIterator:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
