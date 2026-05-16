from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from shuvagent.tools.builtins import (
    copy_to_clipboard_spec,
    default_write_tools,
    paste_text_spec,
    replace_selected_text_spec,
)
from shuvagent.tools.confirmation import ConfirmationProvider, ConfirmationRequest
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, ToolResult, ToolSpec, WindowSnapshot


def test_default_write_tools_lists_plan_02_tools() -> None:
    assert [tool.name for tool in default_write_tools()] == [
        "paste_text",
        "replace_selected_text",
        "copy_to_clipboard",
    ]


def test_paste_text_denied_by_default() -> None:
    tool = paste_text_spec(runner=RecordingWriteRunner().run)
    decision = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
    ).authorize(ToolCallRequest("call-1", tool.name, {"text": "safe"}))

    assert not decision.allowed
    assert decision.reason == "confirmation_required"


def test_paste_text_confirmation_required() -> None:
    confirmation = RecordingConfirmation(allowed=False)
    tool = paste_text_spec(runner=RecordingWriteRunner().run)

    decision = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
        confirmation=confirmation,
    ).authorize(ToolCallRequest("call-1", tool.name, {"text": "safe"}))

    assert not decision.allowed
    assert decision.reason == "confirmation_required"
    assert (
        confirmation.requests[0].reason == "local_visible_write_requires_confirmation"
    )


def test_paste_text_focus_change_invalidates() -> None:
    runner = RecordingWriteRunner()
    tool = paste_text_spec(runner=runner.run)

    result = execute_tool(
        tool,
        arguments={"text": "safe"},
        authorize_window=window("original"),
        execute_window=window("other"),
    )

    assert result == ToolResult.failure("confirmation_expired")
    assert runner.calls == []


def test_paste_text_executes_after_confirmation() -> None:
    runner = RecordingWriteRunner()
    tool = paste_text_spec(runner=runner.run)

    result = execute_tool(tool, arguments={"text": "safe paste"})

    assert result.ok
    assert result.value == {
        "text_len": 10,
        "text_sha256_prefix": result.value["text_sha256_prefix"],
        "action": "paste_text",
    }
    assert len(result.value["text_sha256_prefix"]) == 12
    assert runner.calls == [
        (["wl-copy"], 0.5, "safe paste"),
        (["wtype", "-M", "ctrl", "-P", "v", "-p", "v", "-m", "ctrl"], 0.5, None),
    ]


def test_paste_text_missing_text_fails() -> None:
    runner = RecordingWriteRunner()
    tool = paste_text_spec(runner=runner.run)

    result = execute_tool(tool, arguments={})

    assert result == ToolResult.failure("missing_text")
    assert runner.calls == []


def test_replace_selected_text_denied_by_default() -> None:
    tool = replace_selected_text_spec(runner=RecordingWriteRunner().run)
    decision = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
    ).authorize(ToolCallRequest("call-1", tool.name, {"text": "safe"}))

    assert not decision.allowed
    assert decision.reason == "confirmation_required"


def test_replace_selected_text_confirmation_required() -> None:
    confirmation = RecordingConfirmation(allowed=False)
    tool = replace_selected_text_spec(runner=RecordingWriteRunner().run)

    decision = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
        confirmation=confirmation,
    ).authorize(ToolCallRequest("call-1", tool.name, {"text": "safe"}))

    assert not decision.allowed
    assert decision.reason == "confirmation_required"
    assert (
        confirmation.requests[0].reason == "local_visible_write_requires_confirmation"
    )


def test_replace_selected_text_focus_change_invalidates() -> None:
    runner = RecordingWriteRunner()
    tool = replace_selected_text_spec(runner=runner.run)

    result = execute_tool(
        tool,
        arguments={"text": "safe"},
        authorize_window=window("original"),
        execute_window=window("other"),
    )

    assert result == ToolResult.failure("confirmation_expired")
    assert runner.calls == []


def test_replace_selected_text_executes_after_confirmation() -> None:
    runner = RecordingWriteRunner()
    tool = replace_selected_text_spec(runner=runner.run)

    result = execute_tool(tool, arguments={"text": "safe replace"})

    assert result.ok
    assert result.value is not None
    assert result.value["text_len"] == 12
    assert result.value["action"] == "replace_selected_text"
    assert "safe replace" not in repr(result.value)
    assert runner.calls == [
        (["wl-copy"], 0.5, "safe replace"),
        (["wtype", "-M", "ctrl", "-P", "v", "-p", "v", "-m", "ctrl"], 0.5, None),
    ]


def test_copy_to_clipboard_denied_by_default() -> None:
    tool = copy_to_clipboard_spec(runner=RecordingWriteRunner().run)
    decision = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
    ).authorize(ToolCallRequest("call-1", tool.name, {"text": "safe"}))

    assert not decision.allowed
    assert decision.reason == "confirmation_required"


def test_copy_to_clipboard_confirmation_required() -> None:
    confirmation = RecordingConfirmation(allowed=False)
    tool = copy_to_clipboard_spec(runner=RecordingWriteRunner().run)

    decision = PermissionGate(
        {tool.name: tool},
        window_snapshot=window("app"),
        confirmation=confirmation,
    ).authorize(ToolCallRequest("call-1", tool.name, {"text": "safe"}))

    assert not decision.allowed
    assert decision.reason == "confirmation_required"
    assert confirmation.requests[0].reason == "local_reversible_requires_confirmation"


def test_copy_to_clipboard_executes_after_confirmation() -> None:
    runner = RecordingWriteRunner()
    tool = copy_to_clipboard_spec(runner=runner.run)

    result = execute_tool(tool, arguments={"text": "safe clipboard"})

    assert result.ok
    assert result.value is not None
    assert result.value["text_len"] == 14
    assert result.value["action"] == "copy_to_clipboard"
    assert "safe clipboard" not in repr(result.value)
    assert runner.calls == [(["wl-copy"], 0.5, "safe clipboard")]


def execute_tool(
    tool: ToolSpec,
    *,
    arguments: dict[str, object],
    authorize_window: Callable[[], WindowSnapshot] | None = None,
    execute_window: Callable[[], WindowSnapshot] | None = None,
) -> ToolResult:
    authorize_snapshot = authorize_window or window("app")
    execute_snapshot = execute_window or authorize_snapshot
    registry = ToolRegistry(window_snapshot=execute_snapshot)
    registry.register(tool)
    gate = PermissionGate(
        registry.specs(),
        window_snapshot=authorize_snapshot,
        confirmation=RecordingConfirmation(allowed=True),
    )
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, arguments))
    assert decision.call is not None
    return registry.execute(decision.call)


def window(app_id: str) -> Callable[[], WindowSnapshot]:
    def snapshot() -> WindowSnapshot:
        return WindowSnapshot(
            app_id=app_id, title="Window", captured_at=datetime.now(UTC)
        )

    return snapshot


class RecordingConfirmation(ConfirmationProvider):
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.requests: list[ConfirmationRequest] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.requests.append(request)
        return self.allowed


class RecordingWriteRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], float, str | None]] = []

    def run(self, args: list[str], timeout: float, stdin: str | None) -> str:
        self.calls.append((args, timeout, stdin))
        return ""
