from __future__ import annotations

import asyncio
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


def test_full_conversation_runs_against_fake_realtime_session() -> None:
    async def run() -> None:
        request = ToolCallRequest(
            call_id="call-1",
            tool_name="get_selected_text",
            arguments={},
        )
        session = FakeRealtimeSession(
            [
                ScriptedTurn(
                    user_audio=b"selected-text-question",
                    tool_call=request,
                    audio_response=b"spoken-answer",
                )
            ]
        )
        registry = ToolRegistry(window_snapshot=window)
        registry.register(
            ToolSpec(
                name="get_selected_text",
                risk=ToolRisk.READ,
                input_schema={},
                description="Return selected text metadata",
                handler=selected_text_handler,
            )
        )
        gate = PermissionGate(registry.specs(), window_snapshot=window)
        app = ConversationApp(session=session, registry=registry, gate=gate)

        result = await app.run_once(b"selected-text-question")

        assert result.audio_out == [b"spoken-answer"]
        assert result.tool_results == [
            ToolResult.success({"text_len": 12, "text_sha256_prefix": "abc123"})
        ]
        assert session.tool_results == [
            (
                "call-1",
                {
                    "ok": True,
                    "value": {"text_len": 12, "text_sha256_prefix": "abc123"},
                },
            )
        ]
        assert [event.event for event in result.events] == [
            "agent.session.start_requested",
            "agent.session.connected",
            "agent.session.stopped",
        ]

    asyncio.run(run())


def selected_text_handler(call: GatedToolCall) -> ToolResult:
    assert call.tool.name == "get_selected_text"
    return ToolResult.success({"text_len": 12, "text_sha256_prefix": "abc123"})


def window() -> WindowSnapshot:
    return WindowSnapshot(
        app_id="test-app",
        title="Test",
        captured_at=datetime.now(UTC),
    )
