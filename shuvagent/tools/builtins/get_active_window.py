"""``get_active_window`` — return the currently focused window."""

from __future__ import annotations

from shuvagent.tools.types import (
    GatedToolCall,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from shuvagent.window import Runner, default_runner, get_active_window

NAME = "get_active_window"
DESCRIPTION = (
    "Return the currently focused window's app_id and title. "
    "Useful for the model to ground its responses in context."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def spec(
    *,
    runner: Runner = default_runner,
    timeout: float = 0.5,
) -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        del call
        snapshot = get_active_window(runner=runner, timeout=timeout)
        return ToolResult.success(
            {
                "app_id": snapshot.app_id,
                "title": snapshot.title,
                "captured_at": snapshot.captured_at.isoformat(),
            }
        )

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )
