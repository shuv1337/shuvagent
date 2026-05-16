from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

from shuvagent import cli


def test_run_command_returns_130_on_keyboard_interrupt(monkeypatch) -> None:
    def raise_keyboard_interrupt(coro: Coroutine[Any, Any, int]) -> int:
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", raise_keyboard_interrupt)

    assert cli.main(["run"]) == 130
