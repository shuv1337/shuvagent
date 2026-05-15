"""``get_clipboard_text`` — read the regular Wayland clipboard."""

from __future__ import annotations

from shuvagent.selection import Runner, default_runner, get_clipboard
from shuvagent.tools.builtins.get_selected_text import _result_from_snapshot
from shuvagent.tools.types import (
    GatedToolCall,
    ToolResult,
    ToolRisk,
    ToolSpec,
)

NAME = "get_clipboard_text"
DESCRIPTION = (
    "Return the contents of the user's regular (Ctrl+C) clipboard. "
    "Use only when the user explicitly refers to clipboard contents."
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
        snapshot = get_clipboard(runner=runner, timeout=timeout)
        return _result_from_snapshot(snapshot, source="clipboard")

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )
