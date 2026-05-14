import asyncio

from shuvagent.realtime.events import RealtimeError, ScriptedTurn, SessionState
from shuvagent.realtime.fake import FakeRealtimeSession
from shuvagent.tools.types import ToolCallRequest


def test_fake_realtime_session_emits_scripted_tool_and_audio() -> None:
    async def run() -> None:
        tool_call = ToolCallRequest(
            call_id="call-1",
            tool_name="get_selected_text",
            arguments={},
        )
        session = FakeRealtimeSession(
            [
                ScriptedTurn(
                    user_audio=b"question-audio",
                    tool_call=tool_call,
                    audio_response=b"answer-audio",
                )
            ]
        )

        await session.connect()
        await session.send_audio(b"question-audio")
        await session.commit_input()

        assert await anext(session.tool_calls) == tool_call
        assert await anext(session.audio_out) == b"answer-audio"
        assert session.state == SessionState.SPEAKING

        await session.close()
        assert not session.is_open

    asyncio.run(run())


def test_fake_realtime_session_reports_unexpected_audio() -> None:
    async def run() -> None:
        session = FakeRealtimeSession([ScriptedTurn(user_audio=b"expected")])

        await session.connect()
        await session.send_audio(b"actual")
        await session.commit_input()

        error = await anext(session.errors)
        assert error == RealtimeError(
            code="unexpected_audio",
            message="scripted audio did not match",
        )

        await session.close()

    asyncio.run(run())
