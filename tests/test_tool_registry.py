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


def test_tool_registry_register_and_specs_returns_copy() -> None:
    tool = make_tool("get_selected_text", ToolRisk.READ)
    registry = ToolRegistry(window_snapshot=window("app"))

    registry.register(tool)
    specs = registry.specs()
    specs.clear()

    assert registry.specs() == {tool.name: tool}


def test_tool_registry_execute_with_valid_mint_token() -> None:
    tool = make_tool("get_selected_text", ToolRisk.READ)
    registry = ToolRegistry(window_snapshot=window("app"))
    registry.register(tool)
    call = authorize(tool, window_snapshot=window("app"))

    result = registry.execute(call)

    assert result == ToolResult.success({"called": tool.name, "args": {"limit": 1}})


def test_tool_registry_execute_rejects_invalid_mint_token() -> None:
    tool = make_tool("get_selected_text", ToolRisk.READ)
    registry = ToolRegistry(window_snapshot=window("app"))
    registry.register(tool)
    forged = GatedToolCall(
        call_id="call-1",
        tool=tool,
        arguments={},
        decision_id="forged",
        window_at_authorize=window("app")(),
        authorized_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(seconds=15),
    )

    with pytest.raises(SecurityError, match="not minted"):
        registry.execute(forged)


def test_tool_registry_execute_expired_call_returns_failure_and_audits() -> None:
    events: list[tuple[str, str]] = []
    tool = make_tool("paste_text", ToolRisk.LOCAL_VISIBLE_WRITE)
    registry = ToolRegistry(
        window_snapshot=window("app"),
        audit_sink=lambda event, call: events.append((event, call.call_id)),
    )
    registry.register(tool)
    call = authorize(
        tool,
        window_snapshot=window("app"),
        confirmation=AllowConfirmation(),
        ttl_sec=-1,
    )

    result = registry.execute(call)

    assert result == ToolResult.failure("confirmation_expired")
    assert events == [("tool.expired", "call-1")]


def test_tool_registry_execute_unregistered_tool_returns_failure() -> None:
    tool = make_tool("get_selected_text", ToolRisk.READ)
    registry = ToolRegistry(window_snapshot=window("app"))
    call = authorize(tool, window_snapshot=window("app"))

    result = registry.execute(call)

    assert result == ToolResult.failure("tool_not_registered")


def test_tool_registry_execute_audits_success() -> None:
    events: list[tuple[str, str]] = []
    tool = make_tool("get_clipboard_text", ToolRisk.READ)
    registry = ToolRegistry(
        window_snapshot=window("app"),
        audit_sink=lambda event, call: events.append((event, call.tool.name)),
    )
    registry.register(tool)
    call = authorize(tool, window_snapshot=window("app"))

    assert registry.execute(call).ok
    assert events == [("tool.executed", tool.name)]


def test_tool_registry_execute_focus_change_invalidates_visible_write() -> None:
    events: list[str] = []
    tool = make_tool("paste_text", ToolRisk.LOCAL_VISIBLE_WRITE)
    registry = ToolRegistry(
        window_snapshot=window("different-app"),
        audit_sink=lambda event, call: events.append(f"{event}:{call.tool.name}"),
    )
    registry.register(tool)
    call = authorize(
        tool,
        window_snapshot=window("original-app"),
        confirmation=AllowConfirmation(),
    )

    result = registry.execute(call)

    assert result == ToolResult.failure("confirmation_expired")
    assert events == ["tool.expired:paste_text"]


def authorize(
    tool: ToolSpec,
    *,
    window_snapshot,
    confirmation: ConfirmationProvider | None = None,
    ttl_sec: int = 15,
) -> GatedToolCall:
    gate = PermissionGate(
        {tool.name: tool},
        window_snapshot=window_snapshot,
        confirmation=confirmation,
        ttl_sec=ttl_sec,
    )
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, {"limit": 1}))
    assert decision.call is not None
    return decision.call


def make_tool(name: str, risk: ToolRisk) -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        return ToolResult.success({"called": call.tool.name, "args": call.arguments})

    return ToolSpec(
        name=name,
        risk=risk,
        input_schema={"type": "object"},
        description=f"{name} tool",
        handler=handler,
    )


def window(app_id: str):
    def snapshot() -> WindowSnapshot:
        return WindowSnapshot(
            app_id=app_id,
            title="Window",
            captured_at=datetime.now(UTC),
        )

    return snapshot


class AllowConfirmation:
    def confirm(self, request: ConfirmationRequest) -> bool:
        del request
        return True
