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
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import shuvagent.realtime.openai_session as openai_session_module
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


def test_duplicate_function_call_events_emit_one_tool_request() -> None:
    async def run() -> None:
        session = OpenAIRealtimeSession(_config())
        await session._handle_event(
            {
                "type": "response.function_call_arguments.done",
                "call_id": "call-dup",
                "name": "get_selected_text",
                "arguments": "{}",
            }
        )
        await session._handle_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call-dup",
                    "name": "get_selected_text",
                    "arguments": "{}",
                },
            }
        )

        req = await asyncio.wait_for(session._tool_call_queue.get(), 0.1)
        assert req is not None
        assert req.call_id == "call-dup"
        assert session._tool_call_queue.empty()

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


def test_reconnect_retries_with_backoff_and_replays_session_update(
    monkeypatch,
) -> None:
    async def run() -> None:
        sleeps: list[float] = []
        fake_websockets = FakeWebsockets(failures_before_success=2)

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setitem(
            sys.modules,
            "websockets",
            SimpleNamespace(connect=fake_websockets.connect),
        )
        monkeypatch.setattr(openai_session_module.asyncio, "sleep", fake_sleep)

        session = OpenAIRealtimeSession(_config())
        session.is_open = True

        assert await session._reconnect_with_backoff(RuntimeError("closed"))

        assert sleeps == [1.0, 2.0, 4.0]
        assert fake_websockets.attempts == 3
        assert session.is_open
        assert session.state == SessionState.READY
        assert len(fake_websockets.connections) == 1
        sent = [json.loads(frame) for frame in fake_websockets.connections[0].sent]
        assert sent[0]["type"] == "session.update"

        events = [await session._api_event_queue.get() for _ in range(4)]
        assert [event.type for event in events] == [
            "agent.session.reconnect_attempt",
            "agent.session.reconnect_attempt",
            "agent.session.reconnect_attempt",
            "agent.session.reconnect_succeeded",
        ]
        assert [event.payload for event in events[:3]] == [
            {"attempt": 1, "delay_ms": 1000},
            {"attempt": 2, "delay_ms": 2000},
            {"attempt": 3, "delay_ms": 4000},
        ]
        assert events[-1].payload == {"attempt": 3}

    asyncio.run(run())


def test_reconnect_failure_emits_failed_event_and_closes(
    monkeypatch,
) -> None:
    async def run() -> None:
        fake_websockets = FakeWebsockets(failures_before_success=99)

        async def fake_sleep(delay: float) -> None:
            del delay

        monkeypatch.setitem(
            sys.modules,
            "websockets",
            SimpleNamespace(connect=fake_websockets.connect),
        )
        monkeypatch.setattr(openai_session_module.asyncio, "sleep", fake_sleep)

        session = OpenAIRealtimeSession(_config())
        session.is_open = True

        assert not await session._reconnect_with_backoff(RuntimeError("closed"))

        assert fake_websockets.attempts == 3
        assert not session.is_open
        assert session.state == SessionState.CLOSED
        events = [await session._api_event_queue.get() for _ in range(4)]
        assert [event.type for event in events] == [
            "agent.session.reconnect_attempt",
            "agent.session.reconnect_attempt",
            "agent.session.reconnect_attempt",
            "agent.session.reconnect_failed",
        ]
        assert events[-1].payload["attempts"] == 3
        assert "connect failed" in str(events[-1].payload["error"])

    asyncio.run(run())


def test_window_unused_in_session_payload() -> None:
    # Sanity: WindowSnapshot is not part of session.update — just here to
    # keep imports honest if future changes regress.
    snap = type(
        "S", (), {"app_id": "x", "title": "t", "captured_at": datetime.now(UTC)}
    )
    del snap


class FakeWebsockets:
    def __init__(self, *, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.attempts = 0
        self.connections: list[FakeWebSocket] = []

    async def connect(
        self,
        url: str,
        *,
        additional_headers: list[tuple[str, str]],
    ) -> FakeWebSocket:
        assert url.endswith("?model=gpt-realtime-2")
        assert additional_headers == [("Authorization", "Bearer sk-test")]
        self.attempts += 1
        if self.attempts <= self.failures_before_success:
            raise RuntimeError(f"connect failed {self.attempts}")
        ws = FakeWebSocket()
        self.connections.append(ws)
        return ws


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send(self, frame: str) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        self.closed = True
