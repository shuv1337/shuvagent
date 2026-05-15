"""``get_selected_text`` — read the X11/Wayland primary selection."""

from __future__ import annotations

from shuvagent.selection import (
    Runner,
    SelectionSnapshot,
    default_runner,
    get_primary_selection,
)
from shuvagent.tools.types import (
    GatedToolCall,
    ToolResult,
    ToolRisk,
    ToolSpec,
)

NAME = "get_selected_text"
DESCRIPTION = (
    "Return the user's currently highlighted text (Wayland primary selection). "
    "Use this when the user asks about 'this', 'the selection', or similar."
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
        snapshot = get_primary_selection(runner=runner, timeout=timeout)
        return _result_from_snapshot(snapshot, source="primary_selection")

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )


def _result_from_snapshot(
    snapshot: SelectionSnapshot | None, *, source: str
) -> ToolResult:
    if snapshot is None:
        return ToolResult.failure("no_selection")
    return ToolResult.success(
        {
            "text": snapshot.text,
            "text_len": snapshot.text_len,
            "text_sha256_prefix": snapshot.text_sha256_prefix,
            "source": source,
        }
    )
