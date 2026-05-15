from __future__ import annotations

import json
from datetime import UTC, datetime

from shuvagent.tools.builtins import (
    get_active_window_spec,
    get_clipboard_text_spec,
    get_selected_text_spec,
    get_shuvoice_status_spec,
)
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, WindowSnapshot


def _window() -> WindowSnapshot:
    return WindowSnapshot(app_id="firefox", title="t", captured_at=datetime.now(UTC))


def _execute(spec) -> dict:
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(spec)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("1", spec.name, {}))
    assert decision.allowed and decision.call is not None
    result = registry.execute(decision.call)
    assert result.ok, result.error
    return result.value or {}


def test_get_selected_text_returns_text_and_redaction_summary() -> None:
    def runner(args: list[str], timeout: float) -> str:
        return "hello there"

    value = _execute(get_selected_text_spec(runner=runner))
    assert value["text"] == "hello there"
    assert value["text_len"] == 11
    assert len(value["text_sha256_prefix"]) == 12
    assert value["source"] == "primary_selection"


def test_get_selected_text_handles_no_selection() -> None:
    def runner(args: list[str], timeout: float) -> str:
        return ""

    spec = get_selected_text_spec(runner=runner)
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(spec)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("1", spec.name, {}))
    assert decision.allowed and decision.call is not None
    result = registry.execute(decision.call)
    assert not result.ok
    assert result.error == "no_selection"


def test_get_clipboard_text_uses_runner_without_primary_flag() -> None:
    captured: dict[str, list[str]] = {}

    def runner(args: list[str], timeout: float) -> str:
        captured["args"] = args
        return "clip"

    value = _execute(get_clipboard_text_spec(runner=runner))
    assert value["text"] == "clip"
    assert value["source"] == "clipboard"
    assert "--primary" not in captured["args"]


def test_get_active_window_returns_app_id_and_title() -> None:
    def runner(args: list[str], timeout: float) -> str:
        return json.dumps({"class": "alacritty", "title": "shell"})

    value = _execute(get_active_window_spec(runner=runner))
    assert value["app_id"] == "alacritty"
    assert value["title"] == "shell"


def test_get_shuvoice_status_reports_running_when_runner_responds() -> None:
    def runner(args: list[str], timeout: float) -> str:
        assert args == ["shuvoice", "control", "status"]
        return "OK recording"

    value = _execute(get_shuvoice_status_spec(runner=runner))
    assert value["running"] is True
    assert value["state"] == "recording"
    assert value["is_recording"] is True


def test_get_shuvoice_status_reports_not_running_when_runner_fails() -> None:
    def runner(args: list[str], timeout: float) -> str:
        raise FileNotFoundError("shuvoice missing")

    value = _execute(get_shuvoice_status_spec(runner=runner))
    assert value["running"] is False
    assert value["state"] is None
