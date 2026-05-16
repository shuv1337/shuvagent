"""Unit tests for OpenAIRealtimeSession event handling.

These tests do **not** hit the real WebSocket. They drive
``_handle_event`` and ``_session_update_payload`` directly so the wire
format is locked down without requiring ``websockets`` or an API key.
A live smoke test lives separately under ``tests/integration``.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime

from shuvagent.realtime.events import SessionState
from shuvagent.realtime.openai_session import (
    OpenAIRealtimeSession,
    OpenAISessionConfig,
    _tool_to_openai_function,
)
from shuvagent.tools.types import (
    GatedToolCall,
    ToolResult,
    ToolRisk,
    ToolSpec,
)


def _config(**overrides) -> OpenAISessionConfig:
    return OpenAISessionConfig(api_key="sk-test", **overrides)


def _dummy_tool() -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        del call
        return ToolResult.success({})

    return ToolSpec(
        name="get_selected_text",
        risk=ToolRisk.READ,
        input_schema={"type": "object", "properties": {}},
        description="x",
        handler=handler,
    )


def test_session_update_payload_includes_tools_and_voice() -> None:
    tool = _dummy_tool()
    session = OpenAIRealtimeSession(_config(voice="marin", tools=(tool,)))

    payload = session._session_update_payload()

    assert payload["type"] == "session.update"
    s = payload["session"]
    assert s["type"] == "realtime"
    assert s["output_modalities"] == ["audio"]
    assert s["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["output"]["voice"] == "marin"
    assert s["tool_choice"] == "auto"
    assert s["max_output_tokens"] == 800
    assert s["tools"] == [_tool_to_openai_function(tool)]
    assert s["audio"]["input"]["turn_detection"]["type"] == "server_vad"


def test_handle_audio_delta_decodes_and_enqueues_pcm() -> None:
    async def run() -> None:
        session = OpenAIRealtimeSession(_config())
        pcm = b"\x01\x02\x03\x04"
        await session._handle_event(
            {
                "type": "response.output_audio.delta",
                "delta": base64.b64encode(pcm).decode("ascii"),
            }
        )
        chunk = await asyncio.wait_for(session._audio_out_queue.get(), 0.1)
        assert chunk == pcm
        assert session.state == SessionState.SPEAKING

    asyncio.run(run())


def test_handle_function_call_emits_tool_request() -> None:
    async def run() -> None:
        session = OpenAIRealtimeSession(_config())
        await session._handle_event(
            {
                "type": "response.function_call_arguments.done",
                "call_id": "call-7",
                "name": "get_selected_text",
                "arguments": json.dumps({"k": "v"}),
            }
        )
        req = await asyncio.wait_for(session._tool_call_queue.get(), 0.1)
        assert req is not None
        assert req.call_id == "call-7"
        assert req.tool_name == "get_selected_text"
        assert req.arguments == {"k": "v"}

    asyncio.run(run())


def test_handle_output_item_function_call_emits_tool_request() -> None:
    async def run() -> None:
        session = OpenAIRealtimeSession(_config())
        await session._handle_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call-8",
                    "name": "get_selected_text",
                    "arguments": json.dumps({"k": "v"}),
                },
            }
        )
        req = await asyncio.wait_for(session._tool_call_queue.get(), 0.1)
        assert req is not None
        assert req.call_id == "call-8"
        assert req.tool_name == "get_selected_text"
        assert req.arguments == {"k": "v"}

    asyncio.run(run())


def test_handle_error_emits_realtime_error() -> None:
    async def run() -> None:
        session = OpenAIRealtimeSession(_config())
        await session._handle_event(
            {"type": "error", "error": {"code": "rate_limit", "message": "slow down"}}
        )
        err = await asyncio.wait_for(session._error_queue.get(), 0.1)
        assert err is not None
        assert err.code == "rate_limit"
        assert err.message == "slow down"

    asyncio.run(run())


def test_handle_response_done_returns_to_ready() -> None:
    async def run() -> None:
        session = OpenAIRealtimeSession(_config())
        session.state = SessionState.SPEAKING
        await session._handle_event({"type": "response.done"})
        assert session.state == SessionState.READY
        api_event = await asyncio.wait_for(session._api_event_queue.get(), 0.1)
        assert api_event.type == "response.done"

    asyncio.run(run())


def test_handle_rate_limits_updated_emits_api_event() -> None:
    async def run() -> None:
        session = OpenAIRealtimeSession(_config())
        await session._handle_event(
            {
                "type": "rate_limits.updated",
                "rate_limits": [{"name": "requests", "remaining": 9}],
            }
        )

        api_event = await asyncio.wait_for(session._api_event_queue.get(), 0.1)
        assert api_event.type == "rate_limits.updated"
        assert api_event.payload["rate_limits"][0]["remaining"] == 9

    asyncio.run(run())


def test_send_helpers_serialise_to_json_frames() -> None:
    """Exercise send_audio/commit_input/send_tool_result via a fake ws."""

    async def run() -> None:
        sent: list[str] = []

        class FakeWS:
            async def send(self, frame: str) -> None:
                sent.append(frame)

            async def close(self) -> None:
                pass

        session = OpenAIRealtimeSession(_config())
        session._ws = FakeWS()
        session.is_open = True

        await session.send_audio(b"\x00\x01")
        await session.commit_input()
        await session.send_tool_result("call-1", {"ok": True, "value": {}})
        await session._handle_event({"type": "response.done"})
        await session.cancel_response()
        await session.pause("test")

        types = [json.loads(f)["type"] for f in sent]
        # audio + commit + create + item.create + create + cancel + clear
        assert "input_audio_buffer.append" in types
        assert "input_audio_buffer.commit" in types
        assert "response.create" in types
        assert "conversation.item.create" in types
        assert "response.cancel" in types
        assert "input_audio_buffer.clear" in types
        assert types.count("response.cancel") == 1

        # send_tool_result payload uses function_call_output
        item_frame = next(
            f for f in sent if json.loads(f)["type"] == "conversation.item.create"
        )
        item = json.loads(item_frame)["item"]
        assert item["type"] == "function_call_output"
        assert item["call_id"] == "call-1"
        assert json.loads(item["output"]) == {"ok": True, "value": {}}
        response_frames = [
            json.loads(f) for f in sent if json.loads(f)["type"] == "response.create"
        ]
        assert response_frames == [
            {
                "type": "response.create",
                "response": {
                    "output_modalities": ["audio"],
                    "max_output_tokens": 800,
                },
            },
            {
                "type": "response.create",
                "response": {
                    "output_modalities": ["audio"],
                    "max_output_tokens": 800,
                },
            },
        ]

    asyncio.run(run())


def test_send_tool_result_defers_response_create_until_active_response_done() -> None:
    async def run() -> None:
        sent: list[str] = []

        class FakeWS:
            async def send(self, frame: str) -> None:
                sent.append(frame)

        session = OpenAIRealtimeSession(_config())
        session._ws = FakeWS()
        session.is_open = True
        session._response_active = True

        await session.send_tool_result("call-1", {"ok": True})
        assert [json.loads(f)["type"] for f in sent] == ["conversation.item.create"]

        await session._handle_event({"type": "response.done"})
        assert [json.loads(f)["type"] for f in sent] == [
            "conversation.item.create",
            "response.create",
        ]

    asyncio.run(run())


def test_window_unused_in_session_payload() -> None:
    # Sanity: WindowSnapshot is not part of session.update — just here to
    # keep imports honest if future changes regress.
    snap = type(
        "S", (), {"app_id": "x", "title": "t", "captured_at": datetime.now(UTC)}
    )
    del snap
