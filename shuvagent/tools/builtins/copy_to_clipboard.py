"""``copy_to_clipboard`` — copy confirmed text to the regular clipboard."""

from __future__ import annotations

from shuvagent.tools.builtins.write_helpers import (
    WriteRunner,
    default_write_runner,
    text_argument,
    text_summary,
)
from shuvagent.tools.types import (
    GatedToolCall,
    ToolResult,
    ToolRisk,
    ToolSpec,
)

NAME = "copy_to_clipboard"
DESCRIPTION = (
    "Copy user-confirmed text to the regular clipboard. "
    "Requires confirmation because it mutates local desktop state."
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
        return ToolResult.success(
            {
                **text_summary(text),
                "action": "copy_to_clipboard",
            }
        )

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.LOCAL_REVERSIBLE,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )
