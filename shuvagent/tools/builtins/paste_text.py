"""``paste_text`` — paste confirmed text into the focused window."""

from __future__ import annotations

from shuvagent.tools.builtins.write_helpers import (
    WriteRunner,
    default_write_runner,
    paste_shortcut,
    text_argument,
    text_summary,
)
from shuvagent.tools.types import (
    GatedToolCall,
    ToolResult,
    ToolRisk,
    ToolSpec,
)

NAME = "paste_text"
DESCRIPTION = (
    "Paste user-confirmed text into the currently focused window. "
    "Requires visible local-write confirmation."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"text": {"type": "string", "minLength": 1}},
    "required": ["text"],
    "additionalProperties": False,
}


def spec(
    *,
    runner: WriteRunner = default_write_runner,
    timeout: float = 0.5,
) -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        text = text_argument(call.arguments)
        if text is None:
            return ToolResult.failure("missing_text")
        runner(["wl-copy"], timeout, text)
        paste_shortcut(runner, timeout)
        return ToolResult.success(
            {
                **text_summary(text),
                "action": "paste_text",
            }
        )

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.LOCAL_VISIBLE_WRITE,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )
