from __future__ import annotations

from shuvagent.tools.confirmation import (
    ConfirmationRequest,
    DenyAllConfirmationProvider,
)
from shuvagent.tools.types import (
    GatedToolCall,
    ToolCallRequest,
    ToolResult,
    ToolRisk,
    ToolSpec,
)


def test_confirmation_deny_all_provider_returns_false() -> None:
    request = make_confirmation(ToolRisk.LOCAL_VISIBLE_WRITE)

    assert DenyAllConfirmationProvider().confirm(request) is False


def test_confirmation_mock_interactive_provider_allows() -> None:
    request = make_confirmation(ToolRisk.LOCAL_VISIBLE_WRITE)
    provider = AllowConfirmationProvider()

    assert provider.confirm(request) is True
    assert provider.requests == [request]


def test_confirmation_request_constructs_from_tool_call_request_and_spec() -> None:
    tool_call = ToolCallRequest("call-1", "paste_text", {"text": "<redacted>"})
    tool = make_tool(ToolRisk.LOCAL_VISIBLE_WRITE)

    request = ConfirmationRequest(
        request=tool_call,
        tool=tool,
        reason=f"{tool.risk.value}_requires_confirmation",
    )

    assert request.request is tool_call
    assert request.tool is tool
    assert request.reason == "local_visible_write_requires_confirmation"


def test_confirmation_request_visible_write_carries_reason() -> None:
    request = make_confirmation(ToolRisk.LOCAL_VISIBLE_WRITE)

    assert request.tool.risk is ToolRisk.LOCAL_VISIBLE_WRITE
    assert request.reason == "local_visible_write_requires_confirmation"


def make_confirmation(risk: ToolRisk) -> ConfirmationRequest:
    tool = make_tool(risk)
    return ConfirmationRequest(
        request=ToolCallRequest("call-1", tool.name, {"text": "<redacted>"}),
        tool=tool,
        reason=f"{risk.value}_requires_confirmation",
    )


def make_tool(risk: ToolRisk) -> ToolSpec:
    def handler(call: GatedToolCall) -> ToolResult:
        del call
        return ToolResult.success()

    return ToolSpec(
        name="paste_text",
        risk=risk,
        input_schema={"type": "object"},
        description="Paste redacted text",
        handler=handler,
    )


class AllowConfirmationProvider:
    def __init__(self) -> None:
        self.requests: list[ConfirmationRequest] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.requests.append(request)
        return True
