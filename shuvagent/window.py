"""Active-window snapshot via ``hyprctl activewindow -j``.

Read-only. Returns a :class:`WindowSnapshot` so the permission gate and
focus-change check have something to bind against.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime

from shuvagent.tools.types import WindowSnapshot

Runner = Callable[[list[str], float], str]


def default_runner(args: list[str], timeout: float) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return result.stdout


def get_active_window(
    *,
    runner: Runner = default_runner,
    timeout: float = 0.5,
) -> WindowSnapshot:
    """Return the currently focused window.

    Falls back to an ``"unknown"`` snapshot if hyprctl is missing or
    fails. The permission gate uses this for focus-change invalidation,
    so we must always return *something*.
    """
    try:
        output = runner(["hyprctl", "activewindow", "-j"], timeout)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
    ):
        return _unknown_window()
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return _unknown_window()
    if not isinstance(data, dict):
        return _unknown_window()
    return WindowSnapshot(
        app_id=str(data.get("class") or "unknown"),
        title=str(data.get("title") or ""),
        captured_at=datetime.now(UTC),
    )


def _unknown_window() -> WindowSnapshot:
    return WindowSnapshot(
        app_id="unknown",
        title="",
        captured_at=datetime.now(UTC),
    )
