"""Opt-in live smoke test for OpenAI Realtime.

This test is intentionally disabled unless both:

* ``OPENAI_API_KEY`` is present, and
* ``SHUVAGENT_RUN_LIVE_REALTIME=1`` is set.

That avoids surprising CI/local runs with network calls or paid API
usage. It only verifies that a Realtime WebSocket session can open and
close with the configured model/voice/tool schema; manual QA still
covers real microphone input and spoken audio output.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from shuvagent.config import RealtimeConfig
from shuvagent.realtime.events import SessionState
from shuvagent.realtime.openai_session import OpenAIRealtimeSession, OpenAISessionConfig
from shuvagent.tools.builtins import default_read_only_tools


@pytest.mark.integration
def test_live_realtime_session_opens_and_closes() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is not set")
    if os.environ.get("SHUVAGENT_RUN_LIVE_REALTIME") != "1":
        pytest.skip("set SHUVAGENT_RUN_LIVE_REALTIME=1 to run paid live smoke")

    async def run() -> None:
        cfg = RealtimeConfig()
        session = OpenAIRealtimeSession(
            OpenAISessionConfig(
                api_key=api_key,
                model=cfg.model,
                voice=cfg.voice,
                reasoning_effort=cfg.reasoning_effort,
                tools=tuple(default_read_only_tools()),
                request_timeout_sec=cfg.request_timeout_sec,
            )
        )
        await session.connect()
        try:
            assert session.is_open
            assert session.state is SessionState.READY
        finally:
            await session.close()
        assert not session.is_open
        assert session.state is SessionState.CLOSED

    asyncio.run(run())
