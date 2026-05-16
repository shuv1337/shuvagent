from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from shuvagent.realtime.events import RealtimeApiEvent, RealtimeError, SessionState
from shuvagent.time_context import build_time_context
from shuvagent.tools.types import ToolCallRequest, ToolSpec

GEMINI_INSTRUCTIONS = (
    "You are a desktop voice assistant. Be concise. "
    "Use the available read-only tools to ground answers in what is "
    "on the user's screen. Do not invent context; call a tool if you need it."
)


@dataclass(frozen=True)
class PipecatGeminiSessionConfig:
    api_key: str
    model: str = "models/gemini-3.1-flash-live-preview"
    voice: str = "Charon"
    instructions: str = GEMINI_INSTRUCTIONS
    tools: tuple[ToolSpec, ...] = ()
    max_output_tokens: int = 800
    request_timeout_sec: float = 10.0
    input_sample_rate: int = 24000


@dataclass
class PipecatGeminiRealtimeSession:
    """RealtimeAgentSession backed by Pipecat's Gemini Live service."""

    config: PipecatGeminiSessionConfig
    state: SessionState = SessionState.CLOSED
    is_open: bool = False
    is_paused: bool = False

    _service: Any = field(default=None, init=False, repr=False)
    _ready: asyncio.Event = field(init=False, repr=False)
    _audio_out_queue: asyncio.Queue[bytes | None] = field(init=False, repr=False)
    _tool_call_queue: asyncio.Queue[ToolCallRequest | None] = field(
        init=False, repr=False
    )
    _error_queue: asyncio.Queue[RealtimeError | None] = field(init=False, repr=False)
    _api_event_queue: asyncio.Queue[RealtimeApiEvent | None] = field(
        init=False, repr=False
    )
    _tool_names_by_call_id: dict[str, str] = field(default_factory=dict, init=False)
    _connect_error: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._ready = asyncio.Event()
        self._audio_out_queue = asyncio.Queue()
        self._tool_call_queue = asyncio.Queue()
        self._error_queue = asyncio.Queue()
        self._api_event_queue = asyncio.Queue()
        self.audio_out = _iter_queue(self._audio_out_queue)
        self.tool_calls = _iter_queue(self._tool_call_queue)
        self.errors = _iter_queue(self._error_queue)
        self.api_events = _iter_queue(self._api_event_queue)

    async def connect(self) -> None:
        self.state = SessionState.CONNECTING
        self._service = self._build_service()
        await self._service._connect()
        try:
            await asyncio.wait_for(
                self._ready.wait(),
                timeout=self.config.request_timeout_sec,
            )
        except TimeoutError as exc:
            await self.close()
            raise RuntimeError("Gemini Live session did not become ready") from exc
        if self._connect_error is not None:
            error = self._connect_error
            await self.close()
            raise RuntimeError(f"Gemini Live session failed to connect: {error}")
        self.is_open = True
        self.state = SessionState.READY

    async def send_audio(self, pcm16: bytes) -> None:
        self._require_open()
        if self.is_paused:
            return
        from pipecat.frames.frames import InputAudioRawFrame

        await self._service._send_user_audio(
            InputAudioRawFrame(
                audio=pcm16,
                sample_rate=self.config.input_sample_rate,
                num_channels=1,
            )
        )
        self.state = SessionState.LISTENING

    async def commit_input(self) -> None:
        self._require_open()
        session = getattr(self._service, "_session", None)
        if session is not None:
            await session.send_client_content(turn_complete=True)

    async def send_tool_result(
        self,
        call_id: str,
        result: dict[str, object],
    ) -> None:
        self._require_open()
        tool_name = self._tool_names_by_call_id.get(call_id, "tool_call_result")
        await self._service._tool_result(call_id, tool_name, result)

    async def cancel_response(self) -> None:
        if not self.is_open:
            return
        self._service.set_audio_input_paused(True)
        self._service.set_audio_input_paused(False)

    async def pause(self, reason: str) -> None:
        del reason
        self.is_paused = True
        if self._service is not None:
            self._service.set_audio_input_paused(True)
        self.state = SessionState.PAUSED

    async def resume(self, reason: str) -> None:
        del reason
        self.is_paused = False
        if self._service is not None:
            self._service.set_audio_input_paused(False)
        if self.is_open:
            self.state = SessionState.READY

    async def close(self) -> None:
        self.is_open = False
        self.state = SessionState.CLOSED
        if self._service is not None:
            await self._service._disconnect()
            self._service = None
        await self._audio_out_queue.put(None)
        await self._tool_call_queue.put(None)
        await self._error_queue.put(None)
        await self._api_event_queue.put(None)

    def _require_open(self) -> None:
        if not self.is_open or self._service is None:
            raise RuntimeError("session is closed")

    def _build_service(self) -> Any:
        try:
            from pipecat.services.google.gemini_live.llm import (
                GeminiLiveLLMService,
                GeminiModalities,
            )
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "Gemini provider requires 'pipecat-ai[google]'. "
                'Install with: uv add "pipecat-ai[google]"'
            ) from exc

        outer = self

        class ShuvGeminiLiveService(GeminiLiveLLMService):
            def create_task(
                self,
                coroutine: Any,
                name: str | None = None,
            ) -> asyncio.Task[Any]:
                del name
                return asyncio.create_task(coroutine)

            async def cancel_task(
                self,
                task: asyncio.Task[Any],
                timeout: float | None = 1.0,
            ) -> None:
                task.cancel()
                try:
                    if timeout is None:
                        await task
                    else:
                        await asyncio.wait_for(task, timeout=timeout)
                except (asyncio.CancelledError, TimeoutError):
                    pass

            async def push_error(
                self,
                error_msg: str,
                exception: Exception | None = None,
                fatal: bool = False,
            ) -> None:
                del exception, fatal
                if outer.state == SessionState.CONNECTING and not outer.is_open:
                    outer._connect_error = error_msg
                await outer._error_queue.put(RealtimeError("gemini_error", error_msg))
                outer._ready.set()

            async def push_frame(self, *args: Any, **kwargs: Any) -> None:
                del args, kwargs

            async def _handle_session_ready(self, session: Any) -> None:
                await super()._handle_session_ready(session)
                if getattr(self, "_context", None) is None:
                    self._ready_for_realtime_input = True
                outer._ready.set()

            async def _handle_msg_model_turn(self, msg: Any) -> None:
                server_content = getattr(msg, "server_content", None)
                model_turn = getattr(server_content, "model_turn", None)
                parts = getattr(model_turn, "parts", None) or []
                for part in parts:
                    inline_data = getattr(part, "inline_data", None)
                    audio = getattr(inline_data, "data", None)
                    if audio:
                        outer.state = SessionState.SPEAKING
                        await outer._audio_out_queue.put(audio)

            async def _handle_msg_tool_call(self, message: Any) -> None:
                tool_call = getattr(message, "tool_call", None)
                function_calls = getattr(tool_call, "function_calls", None) or []
                for function_call in function_calls:
                    call_id = str(getattr(function_call, "id", "") or "")
                    if not call_id:
                        call_id = f"gemini-call-{len(outer._tool_names_by_call_id) + 1}"
                    name = str(getattr(function_call, "name", "") or "")
                    args = getattr(function_call, "args", {}) or {}
                    if name:
                        outer._tool_names_by_call_id[call_id] = name
                        await outer._tool_call_queue.put(
                            ToolCallRequest(
                                call_id=call_id,
                                tool_name=name,
                                arguments=dict(args),
                            )
                        )

            async def _handle_msg_turn_complete(self, message: Any) -> None:
                outer.state = SessionState.READY
                usage = getattr(message, "usage_metadata", None)
                if usage is not None:
                    await outer._api_event_queue.put(
                        RealtimeApiEvent(
                            "response.done",
                            {"response": {"usage": _usage_payload(usage)}},
                        )
                    )

        return ShuvGeminiLiveService(
            api_key=self.config.api_key,
            settings=ShuvGeminiLiveService.Settings(
                model=self.config.model,
                voice=self.config.voice,
                modalities=GeminiModalities.AUDIO,
                max_tokens=self.config.max_output_tokens,
                system_instruction=(
                    f"{self.config.instructions}\n\n{build_time_context()}"
                ),
            ),
            tools=_tools_to_gemini(self.config.tools),
            inference_on_context_initialization=False,
        )


def _tools_to_gemini(tools: tuple[ToolSpec, ...]) -> list[dict[str, object]]:
    if not tools:
        return []
    return [
        {
            "function_declarations": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
            ]
        }
        for tool in tools
    ]


def _usage_payload(usage: Any) -> dict[str, int]:
    return {
        "input_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(usage, "response_token_count", 0) or 0),
        "total_tokens": int(getattr(usage, "total_token_count", 0) or 0),
    }


async def _iter_queue[T](queue: asyncio.Queue[T | None]) -> AsyncIterator[T]:
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
