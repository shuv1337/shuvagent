"""Integration test: ConversationApp.run_streaming against the fake."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from shuvagent.app import ConversationApp
from shuvagent.realtime.events import RealtimeApiEvent, RealtimeError, ScriptedTurn
from shuvagent.realtime.fake import FakeRealtimeSession
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import (
    GatedToolCall,
    ToolCallRequest,
    ToolResult,
    ToolRisk,
    ToolSpec,
    WindowSnapshot,
)
from shuvagent.usage import UsageTracker


def test_run_streaming_drives_one_turn_then_stops() -> None:
    async def run() -> None:
        request = ToolCallRequest(
            call_id="call-1",
            tool_name="get_selected_text",
            arguments={},
        )
        session = FakeRealtimeSession(
            [
                ScriptedTurn(
                    user_audio=b"hello",
                    tool_call=request,
                    audio_response=b"spoken",
                )
            ]
        )
        registry = ToolRegistry(window_snapshot=_window)
        registry.register(
            ToolSpec(
                name="get_selected_text",
                risk=ToolRisk.READ,
                input_schema={},
                description="read selection",
                handler=_handler,
            )
        )
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        monitor_ran = asyncio.Event()
        played: list[bytes] = []
        events: list[str] = []

        async def playback(chunk: bytes) -> None:
            played.append(chunk)

        async def monitor() -> None:
            assert session.is_open
            monitor_ran.set()
            await stop_event.wait()

        async def mic_then_commit() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.commit_input()
            # Give the playback task time to drain.
            await asyncio.sleep(0.05)
            stop_event.set()

        await app.run_streaming(
            audio_in=mic_then_commit(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append(ev.event),
            session_monitors=[monitor],
        )

        assert monitor_ran.is_set()
        assert played == [b"spoken"]
        assert session.tool_results == [
            (
                "call-1",
                {"ok": True, "value": {"text_len": 12, "text_sha256_prefix": "abc"}},
            )
        ]
        assert "agent.session.start_requested" in events
        assert "agent.session.connected" in events
        assert "realtime.first_audio_response_latency_ms" in events
        assert "audio.playback_chunk" in events
        assert "tool.requested" in events
        assert "tool.executed" in events
        assert "realtime.response_cancel_requested" in events
        assert "agent.session.stopped" in events
        assert session.cancel_count == 1

    asyncio.run(run())


def test_run_streaming_emits_playback_error() -> None:
    async def run() -> None:
        session = FakeRealtimeSession(
            [ScriptedTurn(user_audio=b"hello", audio_response=b"spoken")]
        )
        registry = ToolRegistry(window_snapshot=_window)
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[tuple[str, dict[str, object]]] = []

        async def playback(chunk: bytes) -> None:
            del chunk
            raise RuntimeError("speaker write failed")

        async def mic() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.commit_input()
            await asyncio.sleep(0.05)
            stop_event.set()

        await app.run_streaming(
            audio_in=mic(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append((ev.event, ev.attributes)),
        )

        assert (
            "audio.playback_error",
            {"error_type": "RuntimeError", "message": "speaker write failed"},
        ) in events
        assert "agent.session.stopped" in [event for event, _ in events]

    asyncio.run(run())


def test_run_streaming_emits_cancel_failure_and_still_stops() -> None:
    async def run() -> None:
        session = FakeRealtimeSession([ScriptedTurn(user_audio=b"hello")])
        session.fail_cancel_response = True
        registry = ToolRegistry(window_snapshot=_window)
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[str] = []

        async def playback(chunk: bytes) -> None:
            del chunk

        async def mic() -> AsyncIterator[bytes]:
            yield b"hello"
            await asyncio.sleep(0.05)
            stop_event.set()

        await app.run_streaming(
            audio_in=mic(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append(ev.event),
        )

        assert session.cancel_count == 1
        assert "realtime.response_cancel_failed" in events
        assert "agent.session.stopped" in events
        assert not session.is_open

    asyncio.run(run())


def test_tool_telemetry_does_not_include_raw_tool_result() -> None:
    async def run() -> None:
        request = ToolCallRequest(
            call_id="call-private",
            tool_name="get_selected_text",
            arguments={},
        )
        session = FakeRealtimeSession(
            [ScriptedTurn(user_audio=b"hello", tool_call=request)]
        )
        registry = ToolRegistry(window_snapshot=_window)
        registry.register(
            ToolSpec(
                name="get_selected_text",
                risk=ToolRisk.READ,
                input_schema={},
                description="read selection",
                handler=_private_text_handler,
            )
        )
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[tuple[str, dict[str, object]]] = []

        async def playback(chunk: bytes) -> None:
            del chunk

        async def mic_then_commit() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.commit_input()
            await asyncio.sleep(0.05)
            stop_event.set()

        await app.run_streaming(
            audio_in=mic_then_commit(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append((ev.event, ev.attributes)),
        )

        assert session.tool_results == [
            ("call-private", {"ok": True, "value": {"text": "private selected text"}})
        ]
        rendered_events = repr(events)
        assert "private selected text" not in rendered_events
        assert (
            "tool.executed",
            {"tool": "get_selected_text", "ok": True, "error": None},
        ) in events

    asyncio.run(run())


def test_run_streaming_stops_on_output_token_cap() -> None:
    async def run() -> None:
        session = FakeRealtimeSession([ScriptedTurn(user_audio=b"hello")])
        registry = ToolRegistry(window_snapshot=_window)
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[tuple[str, dict[str, object]]] = []

        async def playback(chunk: bytes) -> None:
            del chunk

        async def mic() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.emit_api_event(
                RealtimeApiEvent(
                    "response.done",
                    {
                        "response": {
                            "usage": {
                                "input_tokens": 2,
                                "output_tokens": 5,
                                "total_tokens": 7,
                            }
                        }
                    },
                )
            )
            await asyncio.sleep(0.05)

        await app.run_streaming(
            audio_in=mic(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append((ev.event, ev.attributes)),
            usage_tracker=UsageTracker(output_token_cap=5),
        )

        assert any(
            event == "agent.session.interrupted"
            and attrs["reason"] == "output_token_cap"
            for event, attrs in events
        )
        assert any(event == "realtime.usage.summary" for event, _ in events)

    asyncio.run(run())


def test_run_streaming_emits_rate_limit_telemetry() -> None:
    async def run() -> None:
        session = FakeRealtimeSession([ScriptedTurn(user_audio=b"hello")])
        registry = ToolRegistry(window_snapshot=_window)
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[tuple[str, dict[str, object]]] = []

        async def playback(chunk: bytes) -> None:
            del chunk

        async def mic() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.emit_api_event(
                RealtimeApiEvent(
                    "rate_limits.updated",
                    {
                        "rate_limits": [
                            {
                                "name": "requests",
                                "remaining": 2,
                                "reset_seconds": 1.5,
                            }
                        ]
                    },
                )
            )
            await asyncio.sleep(0.05)
            stop_event.set()

        await app.run_streaming(
            audio_in=mic(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append((ev.event, ev.attributes)),
        )

        assert (
            "realtime.rate_limit",
            {"name": "requests", "remaining": 2, "reset_seconds": 1.5},
        ) in events

    asyncio.run(run())


def test_run_streaming_forwards_reconnect_telemetry_and_stops_on_failure() -> None:
    async def run() -> None:
        session = FakeRealtimeSession([ScriptedTurn(user_audio=b"hello")])
        registry = ToolRegistry(window_snapshot=_window)
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[tuple[str, dict[str, object]]] = []

        async def playback(chunk: bytes) -> None:
            del chunk

        async def mic() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.emit_api_event(
                RealtimeApiEvent(
                    "agent.session.reconnect_attempt",
                    {"attempt": 1, "delay_ms": 1000},
                )
            )
            await session.emit_api_event(
                RealtimeApiEvent(
                    "agent.session.reconnect_succeeded",
                    {"attempt": 1},
                )
            )
            await session.emit_api_event(
                RealtimeApiEvent(
                    "agent.session.reconnect_failed",
                    {"attempts": 3, "error": "closed"},
                )
            )
            await asyncio.sleep(0.05)

        await app.run_streaming(
            audio_in=mic(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append((ev.event, ev.attributes)),
        )

        assert (
            "agent.session.reconnect_attempt",
            {"attempt": 1, "delay_ms": 1000},
        ) in events
        assert (
            "agent.session.reconnect_succeeded",
            {"attempt": 1},
        ) in events
        assert (
            "agent.session.reconnect_failed",
            {"attempts": 3, "error": "closed"},
        ) in events
        assert stop_event.is_set()

    asyncio.run(run())


def test_run_streaming_emits_realtime_error_and_stops() -> None:
    async def run() -> None:
        session = FakeRealtimeSession([ScriptedTurn(user_audio=b"hello")])
        registry = ToolRegistry(window_snapshot=_window)
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[tuple[str, dict[str, object]]] = []

        async def playback(chunk: bytes) -> None:
            del chunk

        async def mic() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.emit_error(RealtimeError("rate_limit", "slow down"))
            await asyncio.sleep(0.05)

        await app.run_streaming(
            audio_in=mic(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append((ev.event, ev.attributes)),
        )

        assert stop_event.is_set()
        assert (
            "realtime.error",
            {"code": "rate_limit", "message": "slow down"},
        ) in events
        assert (
            "realtime.rate_limit",
            {"code": "rate_limit", "message": "slow down"},
        ) in events

    asyncio.run(run())


def test_run_streaming_ignores_cancel_not_active_error() -> None:
    async def run() -> None:
        session = FakeRealtimeSession([ScriptedTurn(user_audio=b"hello")])
        registry = ToolRegistry(window_snapshot=_window)
        gate = PermissionGate(registry.specs(), window_snapshot=_window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        stop_event = asyncio.Event()
        events: list[tuple[str, dict[str, object]]] = []

        async def playback(chunk: bytes) -> None:
            del chunk

        async def mic() -> AsyncIterator[bytes]:
            yield b"hello"
            await session.emit_error(
                RealtimeError(
                    "response_cancel_not_active",
                    "Cancellation failed: no active response found",
                )
            )
            await asyncio.sleep(0.05)
            stop_event.set()

        await app.run_streaming(
            audio_in=mic(),
            playback=playback,
            stop_event=stop_event,
            event_sink=lambda ev: events.append((ev.event, ev.attributes)),
        )

        assert (
            "realtime.cancel_ignored",
            {"code": "response_cancel_not_active"},
        ) in events
        assert not any(event == "realtime.error" for event, _ in events)

    asyncio.run(run())


def _handler(call: GatedToolCall) -> ToolResult:
    del call
    return ToolResult.success({"text_len": 12, "text_sha256_prefix": "abc"})


def _private_text_handler(call: GatedToolCall) -> ToolResult:
    del call
    return ToolResult.success({"text": "private selected text"})


def _window() -> WindowSnapshot:
    return WindowSnapshot(
        app_id="test-app",
        title="Test",
        captured_at=datetime.now(UTC),
    )
