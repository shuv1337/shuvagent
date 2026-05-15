from __future__ import annotations

import json

from shuvagent.window import get_active_window


def test_get_active_window_parses_hyprctl_json() -> None:
    def runner(args: list[str], timeout: float) -> str:
        assert args == ["hyprctl", "activewindow", "-j"]
        return json.dumps({"class": "firefox", "title": "AGENTS.md - shuvagent"})

    snap = get_active_window(runner=runner)

    assert snap.app_id == "firefox"
    assert snap.title == "AGENTS.md - shuvagent"


def test_get_active_window_returns_unknown_on_missing_binary() -> None:
    def runner(args: list[str], timeout: float) -> str:
        raise FileNotFoundError("hyprctl missing")

    snap = get_active_window(runner=runner)

    assert snap.app_id == "unknown"
    assert snap.title == ""


def test_get_active_window_returns_unknown_on_bad_json() -> None:
    snap = get_active_window(runner=lambda *_: "not json")
    assert snap.app_id == "unknown"
