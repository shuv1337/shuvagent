from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shuvagent.tools.confirmation import ConfirmationProvider, ConfirmationRequest
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import SecurityError, ToolRegistry
from shuvagent.tools.types import (
    GatedToolCall,
    ToolCallRequest,
    ToolResult,
    ToolRisk,
    ToolSpec,
    WindowSnapshot,
)


def test_unknown_tool_denied() -> None:
    gate = PermissionGate({}, window_snapshot=window("app"))

    decision = gate.authorize(ToolCallRequest("1", "missing", {}))

    assert not decision.allowed
    assert decision.reason == "unknown_tool"


def test_read_tool_allowed_after_setup_and_executes() -> None:
    tool = make_tool("get_selected_text", ToolRisk.READ)
    registry = ToolRegistry(window_snapshot=window("app"))
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=window("app"))

    decision = gate.authorize(ToolCallRequest("1", tool.name, {"x": 1}))
    assert decision.allowed
    assert decision.call is not None

    result = registry.execute(decision.call)

    assert result == ToolResult.success({"called": tool.name})


def test_write_tool_requires_confirmation() -> None:
    tool = make_tool("paste_text", ToolRisk.LOCAL_VISIBLE_WRITE)
    gate = PermissionGate({tool.name: tool}, window_snapshot=window("app"))

    decision = gate.authorize(ToolCallRequest("1", tool.name, {}))

    assert not decision.allowed
    assert decision.reason == "confirmation_required"


def test_write_tool_allowed_after_confirmation() -> None:
    tool = make_tool("paste_text", ToolRisk.LOCAL_VISIBLE_WRITE)
    gate = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
        confirmation=AllowConfirmation(),
    )

    decision = gate.authorize(ToolCallRequest("1", tool.name, {}))

    assert decision.allowed


def test_write_tool_expired_confirmation_returns_error() -> None:
    tool = make_tool("paste_text", ToolRisk.LOCAL_VISIBLE_WRITE)
    gate = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
        confirmation=AllowConfirmation(),
        ttl_sec=-1,
    )
    registry = ToolRegistry(window_snapshot=window("app"))
    registry.register(tool)

    decision = gate.authorize(ToolCallRequest("1", tool.name, {}))
    assert decision.call is not None

    assert registry.execute(decision.call) == ToolResult.failure("confirmation_expired")


def test_write_tool_focus_change_invalidates() -> None:
    tool = make_tool("paste_text", ToolRisk.LOCAL_VISIBLE_WRITE)
    gate = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("original"),
        confirmation=AllowConfirmation(),
    )
    registry = ToolRegistry(window_snapshot=window("other"))
    registry.register(tool)

    decision = gate.authorize(ToolCallRequest("1", tool.name, {}))
    assert decision.call is not None

    assert registry.execute(decision.call) == ToolResult.failure("confirmation_expired")


def test_gated_tool_call_cannot_be_constructed_without_gate() -> None:
    tool = make_tool("get_selected_text", ToolRisk.READ)
    forged = GatedToolCall(
        call_id="1",
        tool=tool,
        arguments={},
        decision_id="fake",
        window_at_authorize=window("app")(),
        authorized_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(seconds=15),
    )
    registry = ToolRegistry(window_snapshot=window("app"))
    registry.register(tool)

    with pytest.raises(SecurityError, match="not minted"):
        registry.execute(forged)


def make_tool(name: str, risk: ToolRisk) -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        return ToolResult.success({"called": call.tool.name})

    return ToolSpec(
        name=name,
        risk=risk,
        input_schema={},
        description=f"{name} tool",
        handler=handler,
    )


def window(app_id: str):
    def snapshot() -> WindowSnapshot:
        return WindowSnapshot(
            app_id=app_id,
            title="Title",
            captured_at=datetime.now(UTC),
        )

    return snapshot


class AllowConfirmation(ConfirmationProvider):
    def confirm(self, request: ConfirmationRequest) -> bool:
        del request
        return True
