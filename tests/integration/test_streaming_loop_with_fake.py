"""Integration test: ConversationApp.run_streaming against the fake."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from shuvagent.app import ConversationApp
from shuvagent.realtime.events import ScriptedTurn
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
        played: list[bytes] = []
        events: list[str] = []

        async def playback(chunk: bytes) -> None:
            played.append(chunk)

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
        )

        assert played == [b"spoken"]
        assert session.tool_results == [
            (
                "call-1",
                {"ok": True, "value": {"text_len": 12, "text_sha256_prefix": "abc"}},
            )
        ]
        assert "agent.session.start_requested" in events
        assert "agent.session.connected" in events
        assert "tool.requested" in events
        assert "tool.executed" in events
        assert "agent.session.stopped" in events

    asyncio.run(run())


def _handler(call: GatedToolCall) -> ToolResult:
    del call
    return ToolResult.success({"text_len": 12, "text_sha256_prefix": "abc"})


def _window() -> WindowSnapshot:
    return WindowSnapshot(
        app_id="test-app",
        title="Test",
        captured_at=datetime.now(UTC),
    )
