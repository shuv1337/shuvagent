"""Opt-in live smoke test for OpenAI Realtime.

This test is intentionally disabled unless both:

* ``OPENAI_API_KEY`` is present, and
* ``SHUVAGENT_RUN_LIVE_REALTIME=1`` is set.

That avoids surprising CI/local runs with network calls or paid API
usage. It verifies that a Realtime WebSocket session can open and close
with the configured model/voice/tool schema and can complete a synthetic
selected-text tool round trip. Manual QA still covers real microphone
input and speaker playback.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from contextlib import suppress

import pytest

from shuvagent.config import RealtimeConfig
from shuvagent.realtime.events import SessionState
from shuvagent.realtime.openai_session import OpenAIRealtimeSession, OpenAISessionConfig
from shuvagent.tools.builtins import default_read_only_tools
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest
from shuvagent.window import get_active_window


def _live_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is not set")
    if os.environ.get("SHUVAGENT_RUN_LIVE_REALTIME") != "1":
        pytest.skip("set SHUVAGENT_RUN_LIVE_REALTIME=1 to run paid live smoke")
    return api_key


@pytest.mark.integration
def test_live_realtime_session_opens_and_closes() -> None:
    api_key = _live_api_key()
    async def run() -> None:
        cfg = RealtimeConfig()
        session = OpenAIRealtimeSession(
            OpenAISessionConfig(
                api_key=api_key,
                model=cfg.model,
                voice=cfg.voice,
                reasoning_effort=cfg.reasoning_effort,
                tools=tuple(default_read_only_tools()),
                max_output_tokens=cfg.output_token_cap,
                request_timeout_sec=cfg.request_timeout_sec,
            )
        )
        await session.connect()
        try:
            assert session.is_open
            assert session.state is SessionState.READY
            try:
                error = await asyncio.wait_for(anext(session.errors), timeout=1.0)
            except TimeoutError:
                error = None
            assert error is None
        finally:
            await session.close()
        assert not session.is_open
        assert session.state is SessionState.CLOSED

    asyncio.run(run())


@pytest.mark.integration
def test_live_realtime_selected_text_tool_round_trip() -> None:
    api_key = _live_api_key()
    if shutil.which("wl-copy") is None:
        pytest.skip("wl-copy is not available")
    if shutil.which("wl-paste") is None:
        pytest.skip("wl-paste is not available")
    selected_text = "shuvagent synthetic selected text for issue one"
    subprocess.run(
        ["wl-copy", "--primary"],
        input=selected_text,
        text=True,
        check=True,
    )

    async def run() -> None:
        cfg = RealtimeConfig()
        tools = tuple(default_read_only_tools())
        session = OpenAIRealtimeSession(
            OpenAISessionConfig(
                api_key=api_key,
                model=cfg.model,
                voice=cfg.voice,
                reasoning_effort=cfg.reasoning_effort,
                tools=tools,
                max_output_tokens=cfg.output_token_cap,
                request_timeout_sec=cfg.request_timeout_sec,
            )
        )
        seen: dict[str, int | bool | list[str]] = {
            "tool_called": False,
            "tool_result_len": 0,
            "audio_chunks": 0,
            "audio_bytes": 0,
            "response_done": 0,
            "errors": [],
        }

        async def tool_worker() -> None:
            async for req in session.tool_calls:
                seen["tool_called"] = True
                window = get_active_window()
                registry = ToolRegistry(window_snapshot=lambda window=window: window)
                for spec in tools:
                    registry.register(spec)
                gate = PermissionGate(
                    registry.specs(),
                    window_snapshot=lambda window=window: window,
                )
                decision = gate.authorize(
                    ToolCallRequest(req.call_id, req.tool_name, req.arguments)
                )
                assert decision.allowed and decision.call is not None
                result = registry.execute(decision.call)
                assert result.ok, result.error
                seen["tool_result_len"] = int((result.value or {}).get("text_len", 0))
                await session.send_tool_result(req.call_id, result.value or {})

        async def audio_worker() -> None:
            async for chunk in session.audio_out:
                seen["audio_chunks"] = int(seen["audio_chunks"]) + 1
                seen["audio_bytes"] = int(seen["audio_bytes"]) + len(chunk)

        async def api_worker() -> None:
            async for event in session.api_events:
                if event.type == "response.done":
                    seen["response_done"] = int(seen["response_done"]) + 1

        async def error_worker() -> None:
            async for err in session.errors:
                errors = seen["errors"]
                assert isinstance(errors, list)
                errors.append(f"{err.code}:{err.message}")

        await session.connect()
        workers: tuple[Callable[[], Awaitable[None]], ...] = (
            tool_worker,
            audio_worker,
            api_worker,
            error_worker,
        )
        tasks = [asyncio.create_task(worker()) for worker in workers]
        try:
            await asyncio.sleep(1.0)
            assert session._ws is not None
            await session._ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Briefly explain the selected text.",
                                }
                            ],
                        },
                    }
                )
            )
            await session._ws.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {
                            "output_modalities": ["audio"],
                            "max_output_tokens": 200,
                            "tool_choice": {
                                "type": "function",
                                "name": "get_selected_text",
                            },
                        },
                    }
                )
            )
            deadline = asyncio.get_running_loop().time() + 35
            while asyncio.get_running_loop().time() < deadline:
                assert seen["errors"] == []
                if (
                    seen["tool_called"]
                    and int(seen["tool_result_len"]) == len(selected_text)
                    and int(seen["audio_chunks"]) > 0
                    and int(seen["audio_bytes"]) > 0
                    and int(seen["response_done"]) >= 2
                ):
                    break
                await asyncio.sleep(0.1)
        finally:
            await session.close()
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

        assert seen["tool_called"] is True
        assert seen["tool_result_len"] == len(selected_text)
        assert int(seen["audio_chunks"]) > 0
        assert int(seen["audio_bytes"]) > 0
        assert int(seen["response_done"]) >= 2
        assert seen["errors"] == []

    asyncio.run(run())


@pytest.mark.integration
def test_live_realtime_default_read_only_tool_round_trip() -> None:
    api_key = _live_api_key()
    if shutil.which("wl-copy") is None:
        pytest.skip("wl-copy is not available")
    if shutil.which("wl-paste") is None:
        pytest.skip("wl-paste is not available")
    if shutil.which("hyprctl") is None:
        pytest.skip("hyprctl is not available")
    if shutil.which("shuvoice") is None:
        pytest.skip("shuvoice is not available")

    selected_text = "shuvagent synthetic selected text for full tool round"
    clipboard_text = "shuvagent synthetic clipboard text for full tool round"
    subprocess.run(
        ["wl-copy", "--primary"],
        input=selected_text,
        text=True,
        check=True,
    )
    subprocess.run(["wl-copy"], input=clipboard_text, text=True, check=True)

    async def run() -> None:
        cfg = RealtimeConfig()
        tools = tuple(default_read_only_tools())
        tool_names = [tool.name for tool in tools]
        session = OpenAIRealtimeSession(
            OpenAISessionConfig(
                api_key=api_key,
                model=cfg.model,
                voice=cfg.voice,
                reasoning_effort=cfg.reasoning_effort,
                tools=tools,
                max_output_tokens=cfg.output_token_cap,
                request_timeout_sec=cfg.request_timeout_sec,
            )
        )
        seen: dict[str, object] = {
            "tool_names": [],
            "tool_result_lengths": {},
            "audio_chunks": 0,
            "audio_bytes": 0,
            "response_done": 0,
            "errors": [],
        }

        async def tool_worker() -> None:
            async for req in session.tool_calls:
                called_names = seen["tool_names"]
                assert isinstance(called_names, list)
                called_names.append(req.tool_name)
                window = get_active_window()
                registry = ToolRegistry(window_snapshot=lambda window=window: window)
                for spec in tools:
                    registry.register(spec)
                gate = PermissionGate(
                    registry.specs(),
                    window_snapshot=lambda window=window: window,
                )
                decision = gate.authorize(
                    ToolCallRequest(req.call_id, req.tool_name, req.arguments)
                )
                assert decision.allowed and decision.call is not None
                result = registry.execute(decision.call)
                assert result.ok, result.error
                value = result.value or {}
                lengths = seen["tool_result_lengths"]
                assert isinstance(lengths, dict)
                if req.tool_name in {"get_selected_text", "get_clipboard_text"}:
                    lengths[req.tool_name] = int(value.get("text_len", 0))
                else:
                    lengths[req.tool_name] = len(value)
                await session.send_tool_result(req.call_id, value)

        async def audio_worker() -> None:
            async for chunk in session.audio_out:
                seen["audio_chunks"] = int(seen["audio_chunks"]) + 1
                seen["audio_bytes"] = int(seen["audio_bytes"]) + len(chunk)

        async def api_worker() -> None:
            async for event in session.api_events:
                if event.type == "response.done":
                    seen["response_done"] = int(seen["response_done"]) + 1

        async def error_worker() -> None:
            async for err in session.errors:
                errors = seen["errors"]
                assert isinstance(errors, list)
                errors.append(f"{err.code}:{err.message}")

        await session.connect()
        workers: tuple[Callable[[], Awaitable[None]], ...] = (
            tool_worker,
            audio_worker,
            api_worker,
            error_worker,
        )
        tasks = [asyncio.create_task(worker()) for worker in workers]
        try:
            await asyncio.sleep(1.0)
            assert session._ws is not None
            for index, tool_name in enumerate(tool_names, start=1):
                await session._ws.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                "text": (
                                    f"Call {tool_name} once, then summarize briefly."
                                ),
                                    }
                                ],
                            },
                        }
                    )
                )
                await session._ws.send(
                    json.dumps(
                        {
                            "type": "response.create",
                            "response": {
                                "output_modalities": ["audio"],
                                "max_output_tokens": 200,
                                "tool_choice": {
                                    "type": "function",
                                    "name": tool_name,
                                },
                            },
                        }
                    )
                )
                deadline = asyncio.get_running_loop().time() + 35
                while asyncio.get_running_loop().time() < deadline:
                    assert seen["errors"] == []
                    called_names = seen["tool_names"]
                    assert isinstance(called_names, list)
                    if (
                        called_names.count(tool_name) == 1
                        and int(seen["response_done"]) >= index * 2
                    ):
                        break
                    await asyncio.sleep(0.1)

            deadline = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < deadline:
                if int(seen["audio_bytes"]) > 0:
                    break
                await asyncio.sleep(0.1)
        finally:
            await session.close()
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

        called_names = seen["tool_names"]
        lengths = seen["tool_result_lengths"]
        assert isinstance(called_names, list)
        assert isinstance(lengths, dict)
        assert called_names == tool_names
        assert lengths["get_selected_text"] == len(selected_text)
        assert lengths["get_clipboard_text"] == len(clipboard_text)
        assert int(lengths["get_active_window"]) > 0
        assert int(lengths["get_shuvoice_status"]) > 0
        assert int(seen["audio_chunks"]) > 0
        assert int(seen["audio_bytes"]) > 0
        assert int(seen["response_done"]) >= len(tool_names) * 2
        assert seen["errors"] == []

    asyncio.run(run())
