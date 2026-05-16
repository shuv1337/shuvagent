"""``get_shuvoice_status`` — return ShuVoice's current state."""

from __future__ import annotations

from shuvagent.coordination import (
    Runner,
    ShuVoiceStatusUnavailable,
    default_runner,
    shuvoice_status,
)
from shuvagent.tools.types import (
    GatedToolCall,
    ToolResult,
    ToolRisk,
    ToolSpec,
)

NAME = "get_shuvoice_status"
DESCRIPTION = (
    "Return ShuVoice's current state (idle / recording / processing / tts). "
    "Use to explain to the user why the agent paused or refused to start."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def spec(
    *,
    runner: Runner = default_runner,
    timeout: float = 2.0,
) -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        del call
        try:
            status = shuvoice_status(runner=runner, timeout=timeout)
        except ShuVoiceStatusUnavailable:
            return ToolResult.failure("shuvoice_status_unavailable")
        if status is None:
            return ToolResult.success({"running": False, "state": None})
        return ToolResult.success(
            {
                "running": True,
                "state": status.state,
                "is_recording": status.is_recording,
                "is_tts_active": status.is_tts_active,
            }
        )

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )
