from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from shuvagent.realtime.session import RealtimeAgentSession
from shuvagent.telemetry.schema import TelemetryEvent
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, ToolResult


@dataclass
class ConversationResult:
    audio_out: list[bytes] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    events: list[TelemetryEvent] = field(default_factory=list)


class ConversationApp:
    def __init__(
        self,
        *,
        session: RealtimeAgentSession,
        registry: ToolRegistry,
        gate: PermissionGate,
    ) -> None:
        self._session = session
        self._registry = registry
        self._gate = gate

    async def run_once(self, audio: bytes) -> ConversationResult:
        result = ConversationResult()
        result.events.append(TelemetryEvent(event="agent.session.start_requested"))
        await self._session.connect()
        result.events.append(TelemetryEvent(event="agent.session.connected"))

        audio_task = asyncio.create_task(self._collect_audio(result))
        tool_task = asyncio.create_task(self._handle_one_tool_call(result))
        try:
            await self._session.send_audio(audio)
            await self._session.commit_input()
            await tool_task
            await asyncio.sleep(0)
        finally:
            await self._session.close()
            await audio_task

        result.events.append(TelemetryEvent(event="agent.session.stopped"))
        return result

    async def _collect_audio(self, result: ConversationResult) -> None:
        async for chunk in self._session.audio_out:
            result.audio_out.append(chunk)

    async def _handle_one_tool_call(self, result: ConversationResult) -> None:
        request = await _anext(self._session.tool_calls)
        if request is None:
            return
        tool_result = self._execute_tool_call(request)
        result.tool_results.append(tool_result)
        await self._session.send_tool_result(
            request.call_id,
            _tool_result_payload(tool_result),
        )

    def _execute_tool_call(self, request: ToolCallRequest) -> ToolResult:
        decision = self._gate.authorize(request)
        if not decision.allowed or decision.call is None:
            return ToolResult.failure(decision.reason or "tool_denied")
        return self._registry.execute(decision.call)


async def _anext(iterator):
    try:
        return await anext(iterator)
    except StopAsyncIteration:
        return None


def _tool_result_payload(result: ToolResult) -> dict[str, object]:
    if result.ok:
        return {"ok": True, "value": result.value or {}}
    return {"ok": False, "error": result.error or "tool_failed"}
