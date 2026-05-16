import asyncio
from types import SimpleNamespace

from shuvagent.realtime.events import SessionState
from shuvagent.realtime.pipecat_gemini_session import (
    PipecatGeminiRealtimeSession,
    PipecatGeminiSessionConfig,
    _tools_to_gemini,
)
from shuvagent.tools.types import GatedToolCall, ToolResult, ToolRisk, ToolSpec


def _dummy_tool() -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        del call
        return ToolResult.success({})

    return ToolSpec(
        name="get_selected_text",
        risk=ToolRisk.READ,
        input_schema={"type": "object", "properties": {}},
        description="Read selected text.",
        handler=handler,
    )


def test_tools_to_gemini_function_declarations() -> None:
    assert _tools_to_gemini((_dummy_tool(),)) == [
        {
            "function_declarations": [
                {
                    "name": "get_selected_text",
                    "description": "Read selected text.",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]
        }
    ]


def test_gemini_service_uses_time_context_and_pipecat_settings() -> None:
    session = PipecatGeminiRealtimeSession(
        PipecatGeminiSessionConfig(
            api_key="google-test",
            model="models/gemini-3.1-flash-live-preview",
            voice="Charon",
            tools=(_dummy_tool(),),
            max_output_tokens=123,
        )
    )

    service = session._build_service()

    assert service._settings.model == "models/gemini-3.1-flash-live-preview"
    assert service._settings.voice == "Charon"
    assert service._settings.max_tokens == 123
    assert "Current time:" in service._settings.system_instruction


def test_gemini_session_surfaces_audio_and_tool_calls() -> None:
    async def run() -> None:
        session = PipecatGeminiRealtimeSession(PipecatGeminiSessionConfig(api_key="x"))
        service = session._build_service()

        await service._handle_session_ready(SimpleNamespace())
        assert session._ready.is_set()

        await service._handle_msg_model_turn(
            SimpleNamespace(
                server_content=SimpleNamespace(
                    model_turn=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                inline_data=SimpleNamespace(data=b"pcm")
                            )
                        ]
                    )
                )
            )
        )
        assert session.state == SessionState.SPEAKING
        assert await asyncio.wait_for(session._audio_out_queue.get(), 0.1) == b"pcm"

        await service._handle_msg_tool_call(
            SimpleNamespace(
                tool_call=SimpleNamespace(
                    function_calls=[
                        SimpleNamespace(
                            id="call-1",
                            name="get_selected_text",
                            args={"max_chars": 100},
                        )
                    ]
                )
            )
        )

        call = await asyncio.wait_for(session._tool_call_queue.get(), 0.1)
        assert call is not None
        assert call.call_id == "call-1"
        assert call.tool_name == "get_selected_text"
        assert call.arguments == {"max_chars": 100}

    asyncio.run(run())


def test_gemini_pause_resume_controls_audio_input() -> None:
    class FakeService:
        def __init__(self) -> None:
            self.pauses: list[bool] = []

        def set_audio_input_paused(self, paused: bool) -> None:
            self.pauses.append(paused)

    async def run() -> None:
        session = PipecatGeminiRealtimeSession(PipecatGeminiSessionConfig(api_key="x"))
        service = FakeService()
        session._service = service
        session.is_open = True

        await session.pause("shuvoice")
        await session.resume("clear")

        assert session.is_paused is False
        assert service.pauses == [True, False]
        assert session.state == SessionState.READY

    asyncio.run(run())


def test_gemini_connect_error_is_not_reported_as_open() -> None:
    async def run() -> None:
        session = PipecatGeminiRealtimeSession(PipecatGeminiSessionConfig(api_key="x"))
        service = session._build_service()
        session.state = SessionState.CONNECTING

        await service.push_error("bad credentials")

        assert session._connect_error == "bad credentials"
        assert session._ready.is_set()

    asyncio.run(run())
