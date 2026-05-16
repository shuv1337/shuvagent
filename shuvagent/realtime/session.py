from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from shuvagent.realtime.events import RealtimeApiEvent, RealtimeError, SessionState
from shuvagent.tools.types import ToolCallRequest


class RealtimeAgentSession(Protocol):
    audio_out: AsyncIterator[bytes]
    tool_calls: AsyncIterator[ToolCallRequest]
    errors: AsyncIterator[RealtimeError]
    api_events: AsyncIterator[RealtimeApiEvent]
    state: SessionState
    is_open: bool
    is_paused: bool

    async def connect(self) -> None: ...

    async def send_audio(self, pcm16: bytes) -> None: ...

    async def commit_input(self) -> None: ...

    async def send_tool_result(
        self,
        call_id: str,
        result: dict[str, object],
    ) -> None: ...

    async def cancel_response(self) -> None: ...

    async def pause(self, reason: str) -> None: ...

    async def resume(self, reason: str) -> None: ...

    async def close(self) -> None: ...
