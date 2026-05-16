from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from shuvagent.realtime.session import RealtimeAgentSession
from shuvagent.telemetry.schema import TelemetryEvent
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, ToolResult
from shuvagent.usage import UsageTracker, parse_rate_limits, parse_realtime_usage

AudioStream = AsyncIterator[bytes]
PlaybackSink = Callable[[bytes], Awaitable[None]]
EventSink = Callable[[TelemetryEvent], None]
MonitorFactory = Callable[[], Awaitable[None]]


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
        session_monitors: Iterable[MonitorFactory] = (),
        usage_tracker: UsageTracker | None = None,
    ) -> None:
        """Drive a live conversation session until ``stop_event`` is set.

        ``audio_in`` yields PCM16 24kHz mic chunks. ``playback`` is
        awaited with each PCM16 output chunk from the model. The loop
        is cooperative — close the session by setting ``stop_event``.
        """
        emit = event_sink or (lambda _ev: None)
        emit(TelemetryEvent(event="agent.session.start_requested"))
        start_time = time.monotonic()
        await self._session.connect()
        emit(TelemetryEvent(event="agent.session.connected"))

        monitor_tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(_await_monitor(monitor()))
            for monitor in session_monitors
        ]
        audio_out_task = asyncio.create_task(
            self._stream_audio_out(playback, emit, session_start_time=start_time)
        )
        tool_task = asyncio.create_task(self._stream_tool_calls(emit))
        error_task = asyncio.create_task(self._stream_errors(emit, stop_event))
        api_event_task = asyncio.create_task(
            self._stream_api_events(emit, stop_event, usage_tracker)
        )
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
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            emit(
                TelemetryEvent(
                    event="agent.session.duration_ms",
                    attributes={"duration_ms": duration_ms},
                )
            )
            if usage_tracker is not None:
                emit(
                    TelemetryEvent(
                        event="realtime.usage.summary",
                        attributes=usage_tracker.snapshot(),
                    )
                )
            tasks = (
                send_task,
                audio_out_task,
                tool_task,
                error_task,
                api_event_task,
                stop_task,
                *monitor_tasks,
            )
            for task in tasks:
                task.cancel()
            await asyncio.gather(
                send_task,
                audio_out_task,
                tool_task,
                error_task,
                api_event_task,
                stop_task,
                *monitor_tasks,
                return_exceptions=True,
            )
            await self._cancel_response_best_effort(emit)
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
        self,
        playback: PlaybackSink,
        emit: EventSink,
        *,
        session_start_time: float,
    ) -> None:
        first_audio = True
        async for chunk in self._session.audio_out:
            if first_audio:
                first_audio = False
                emit(
                    TelemetryEvent(
                        event="realtime.first_audio_response_latency_ms",
                        attributes={
                            "latency_ms": round(
                                (time.monotonic() - session_start_time) * 1000, 2
                            )
                        },
                    )
                )
            try:
                await playback(chunk)
            except Exception as exc:
                emit(
                    TelemetryEvent(
                        event="audio.playback_error",
                        level="error",
                        attributes={
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                        },
                    )
                )
                raise
            emit(
                TelemetryEvent(
                    event="audio.playback_chunk",
                    attributes={"chunk_bytes": len(chunk)},
                )
            )

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
                    event="tool.executed" if tool_result.ok else "tool.failed",
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

    async def _stream_errors(
        self,
        emit: EventSink,
        stop_event: asyncio.Event,
    ) -> None:
        async for error in self._session.errors:
            if error.code == "response_cancel_not_active":
                emit(
                    TelemetryEvent(
                        event="realtime.cancel_ignored",
                        attributes={"code": error.code},
                    )
                )
                continue
            emit(
                TelemetryEvent(
                    event="realtime.error",
                    level="error",
                    attributes={"code": error.code, "message": error.message},
                )
            )
            if error.code in {"rate_limit", "rate_limit_exceeded"}:
                emit(
                    TelemetryEvent(
                        event="realtime.rate_limit",
                        level="warning",
                        attributes={"code": error.code, "message": error.message},
                    )
                )
            stop_event.set()

    async def _stream_api_events(
        self,
        emit: EventSink,
        stop_event: asyncio.Event,
        usage_tracker: UsageTracker | None,
    ) -> None:
        async for event in self._session.api_events:
            if event.type in {
                "agent.session.reconnect_attempt",
                "agent.session.reconnect_succeeded",
                "agent.session.reconnect_failed",
            }:
                emit(TelemetryEvent(event=event.type, attributes=event.payload))
                if event.type == "agent.session.reconnect_failed":
                    stop_event.set()
                continue
            if event.type == "rate_limits.updated":
                for limit in parse_rate_limits(event.payload):
                    emit(
                        TelemetryEvent(
                            event="realtime.rate_limit",
                            attributes={
                                "name": limit.name,
                                "remaining": limit.remaining,
                                "reset_seconds": limit.reset_seconds,
                            },
                        )
                    )
                continue
            if usage_tracker is None:
                continue
            usage = parse_realtime_usage(event.payload)
            if usage is None:
                continue
            decision = usage_tracker.record_usage(usage)
            emit(
                TelemetryEvent(
                    event="realtime.usage",
                    attributes=usage_tracker.snapshot(),
                )
            )
            if decision.should_stop:
                emit(
                    TelemetryEvent(
                        event="agent.session.interrupted",
                        level="warning",
                        attributes={
                            "reason": decision.reason,
                            **usage_tracker.snapshot(),
                        },
                    )
                )
                stop_event.set()

    async def _cancel_response_best_effort(self, emit: EventSink) -> None:
        try:
            await self._session.cancel_response()
            emit(TelemetryEvent(event="realtime.response_cancel_requested"))
        except Exception:
            emit(
                TelemetryEvent(
                    event="realtime.response_cancel_failed",
                    level="warning",
                )
            )
            pass


async def _await_monitor(awaitable: Awaitable[None]) -> None:
    await awaitable


async def _anext[T](iterator: AsyncIterator[T]) -> T | None:
    try:
        return await anext(iterator)
    except StopAsyncIteration:
        return None


def _tool_result_payload(result: ToolResult) -> dict[str, object]:
    if result.ok:
        return {"ok": True, "value": result.value or {}}
    return {"ok": False, "error": result.error or "tool_failed"}
