from __future__ import annotations

import asyncio
import os

import pytest

from shuvagent.realtime.pipecat_gemini_session import (
    PipecatGeminiRealtimeSession,
    PipecatGeminiSessionConfig,
)


@pytest.mark.integration
def test_live_gemini_pipecat_connects_and_closes() -> None:
    if os.environ.get("SHUVAGENT_RUN_LIVE_GEMINI") != "1":
        pytest.skip("set SHUVAGENT_RUN_LIVE_GEMINI=1 to run live Gemini smoke")
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_API_KEY is required for live Gemini smoke")

    async def run() -> None:
        session = PipecatGeminiRealtimeSession(
            PipecatGeminiSessionConfig(
                api_key=api_key,
                model=os.environ.get(
                    "SHUVAGENT_LIVE_GEMINI_MODEL",
                    "models/gemini-3.1-flash-live-preview",
                ),
                voice=os.environ.get("SHUVAGENT_LIVE_GEMINI_VOICE", "Charon"),
                request_timeout_sec=15.0,
            )
        )
        await session.connect()
        assert session.is_open
        await session.close()
        assert not session.is_open

    asyncio.run(run())
