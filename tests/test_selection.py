from __future__ import annotations

import subprocess

import pytest

from shuvagent.selection import (
    SelectionSnapshot,
    get_clipboard,
    get_primary_selection,
)


def test_snapshot_summary_fields_are_derived() -> None:
    snap = SelectionSnapshot(text="hello world")
    assert snap.text_len == 11
    assert len(snap.text_sha256_prefix) == 12
    assert snap.text_sha256_prefix == snap.text_sha256_prefix  # deterministic


def test_get_primary_selection_returns_snapshot() -> None:
    def runner(args: list[str], timeout: float) -> str:
        assert args[0] == "wl-paste"
        assert "--primary" in args
        return "selected text"

    snap = get_primary_selection(runner=runner)

    assert snap is not None
    assert snap.text == "selected text"
    assert snap.text_len == len("selected text")


def test_get_clipboard_uses_no_primary_flag() -> None:
    captured: dict[str, list[str]] = {}

    def runner(args: list[str], timeout: float) -> str:
        captured["args"] = args
        return "clip\n"

    snap = get_clipboard(runner=runner)

    assert snap is not None
    assert snap.text == "clip"
    assert "--primary" not in captured["args"]


@pytest.mark.parametrize(
    "exc",
    [FileNotFoundError(), subprocess.TimeoutExpired("wl-paste", 0.1)],
)
def test_get_primary_selection_returns_none_on_failure(exc: Exception) -> None:
    def runner(args: list[str], timeout: float) -> str:
        raise exc

    assert get_primary_selection(runner=runner) is None


def test_get_primary_selection_returns_none_on_empty_output() -> None:
    assert get_primary_selection(runner=lambda *_: "\n") is None
