from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from shuvagent.realtime.session import RealtimeAgentSession
from shuvagent.telemetry.schema import TelemetryEvent
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, ToolResult

AudioStream = AsyncIterator[bytes]
PlaybackSink = Callable[[bytes], Awaitable[None]]
EventSink = Callable[[TelemetryEvent], None]


@dataclass
class ConversationResult:
    audio_out: list[bytes] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    events: list[TelemetryEvent] = field(default_factory=list)


class ConversationApp:
    def __init__(
        self,
        *,
        session: RealtimeAgentSession,
        registry: ToolRegistry,
        gate: PermissionGate,
    ) -> None:
        self._session = session
        self._registry = registry
        self._gate = gate

    async def run_once(self, audio: bytes) -> ConversationResult:
        result = ConversationResult()
        result.events.append(TelemetryEvent(event="agent.session.start_requested"))
        await self._session.connect()
        result.events.append(TelemetryEvent(event="agent.session.connected"))

        audio_task = asyncio.create_task(self._collect_audio(result))
        tool_task = asyncio.create_task(self._handle_one_tool_call(result))
        try:
            await self._session.send_audio(audio)
            await self._session.commit_input()
            await tool_task
            await asyncio.sleep(0)
        finally:
            await self._session.close()
            await audio_task

        result.events.append(TelemetryEvent(event="agent.session.stopped"))
        return result

    async def _collect_audio(self, result: ConversationResult) -> None:
        async for chunk in self._session.audio_out:
            result.audio_out.append(chunk)

    async def _handle_one_tool_call(self, result: ConversationResult) -> None:
        request = await _anext(self._session.tool_calls)
        if request is None:
            return
        tool_result = self._execute_tool_call(request)
        result.tool_results.append(tool_result)
        await self._session.send_tool_result(
            request.call_id,
            _tool_result_payload(tool_result),
        )

    def _execute_tool_call(self, request: ToolCallRequest) -> ToolResult:
        decision = self._gate.authorize(request)
        if not decision.allowed or decision.call is None:
            return ToolResult.failure(decision.reason or "tool_denied")
        return self._registry.execute(decision.call)

    # ------------------------------------------------------------------
    # Streaming entrypoint (M1.6 wiring)
    # ------------------------------------------------------------------
    async def run_streaming(
        self,
        *,
        audio_in: AudioStream,
        playback: PlaybackSink,
        stop_event: asyncio.Event,
        event_sink: EventSink | None = None,
    ) -> None:
        """Drive a live conversation session until ``stop_event`` is set.

        ``audio_in`` yields PCM16 24kHz mic chunks. ``playback`` is
        awaited with each PCM16 output chunk from the model. The loop
        is cooperative — close the session by setting ``stop_event``.
        """
        emit = event_sink or (lambda _ev: None)
        emit(TelemetryEvent(event="agent.session.start_requested"))
        await self._session.connect()
        emit(TelemetryEvent(event="agent.session.connected"))

        audio_out_task = asyncio.create_task(
            self._stream_audio_out(playback, emit)
        )
        tool_task = asyncio.create_task(self._stream_tool_calls(emit))
        send_task = asyncio.create_task(
            self._stream_audio_in(audio_in, stop_event, emit)
        )
        stop_task = asyncio.create_task(stop_event.wait())

        try:
            done, _ = await asyncio.wait(
                {send_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            del done
        finally:
            stop_event.set()
            for task in (send_task, audio_out_task, tool_task, stop_task):
                task.cancel()
            await asyncio.gather(
                send_task,
                audio_out_task,
                tool_task,
                stop_task,
                return_exceptions=True,
            )
            await self._session.close()
            emit(TelemetryEvent(event="agent.session.stopped"))

    async def _stream_audio_in(
        self,
        audio_in: AudioStream,
        stop_event: asyncio.Event,
        emit: EventSink,
    ) -> None:
        del emit
        async for chunk in audio_in:
            if stop_event.is_set():
                return
            await self._session.send_audio(chunk)

    async def _stream_audio_out(
        self, playback: PlaybackSink, emit: EventSink
    ) -> None:
        del emit
        async for chunk in self._session.audio_out:
            await playback(chunk)

    async def _stream_tool_calls(self, emit: EventSink) -> None:
        async for request in self._session.tool_calls:
            emit(
                TelemetryEvent(
                    event="tool.requested",
                    attributes={"tool": request.tool_name},
                )
            )
            tool_result = self._execute_tool_call(request)
            emit(
                TelemetryEvent(
                    event="tool.executed"
                    if tool_result.ok
                    else "tool.failed",
                    attributes={
                        "tool": request.tool_name,
                        "ok": tool_result.ok,
                        "error": tool_result.error,
                    },
                )
            )
            await self._session.send_tool_result(
                request.call_id,
                _tool_result_payload(tool_result),
            )


async def _anext(iterator):
    try:
        return await anext(iterator)
    except StopAsyncIteration:
        return None


def _tool_result_payload(result: ToolResult) -> dict[str, object]:
    if result.ok:
        return {"ok": True, "value": result.value or {}}
    return {"ok": False, "error": result.error or "tool_failed"}
