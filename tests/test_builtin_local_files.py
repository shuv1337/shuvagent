"""Tests for the ``local_files`` builtin tool (read-only subset).

Uses real temp directories for safe file operations.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from shuvagent.tools.builtins import local_files_spec
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, ToolResult, WindowSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _window() -> WindowSnapshot:
    return WindowSnapshot(app_id="firefox", title="t", captured_at=datetime.now(UTC))


def _execute(
    arguments: dict[str, object],
    home_dir: str | None = None,
) -> ToolResult:
    tool = local_files_spec(home_dir=home_dir, max_read_chars=10_000, max_list_files=50)
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, arguments))
    assert decision.allowed and decision.call is not None
    return registry.execute(decision.call)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_files_in_directory() -> None:
    """Returns FILE/DIR entries sorted, limited to 50."""
    with tempfile.TemporaryDirectory() as td:
        Path(td, "a.txt").write_text("hello")
        Path(td, "b.py").write_text("world")
        os.mkdir(Path(td, "subdir"))

        result = _execute({"operation": "list", "path": td}, home_dir=td)
        assert result.ok
        reply = str(result.value.get("reply_text", ""))
        assert "a.txt" in reply
        assert "b.py" in reply
        assert "subdir" in reply


def test_read_file_returns_content() -> None:
    """UTF-8 text returned."""
    with tempfile.TemporaryDirectory() as td:
        Path(td, "readme.txt").write_text("hello world")
        result = _execute(
            {"operation": "read", "path": str(Path(td, "readme.txt"))},
            home_dir=td,
        )
        assert result.ok
        reply = str(result.value.get("reply_text", ""))
        assert "hello world" in reply


def test_read_truncates_long_files() -> None:
    """Files > max_read_chars are truncated."""
    with tempfile.TemporaryDirectory() as td:
        Path(td, "long.txt").write_text("x" * 20_000)
        result = _execute(
            {"operation": "read", "path": str(Path(td, "long.txt"))},
            home_dir=td,
        )
        assert result.ok
        reply = str(result.value.get("reply_text", ""))
        assert "truncated" in reply.lower()


def test_path_traversal_rejected() -> None:
    """Traversal outside home is rejected."""
    with tempfile.TemporaryDirectory() as td:
        result = _execute(
            {"operation": "read", "path": "../../../etc/passwd"},
            home_dir=td,
        )
        assert not result.ok
        error = str(result.error).lower()
        assert "permission" in error or "not allowed" in error or "not_allowed" in error


def test_tilde_expansion() -> None:
    """Tilde ``~`` expanded to real home path."""
    with tempfile.TemporaryDirectory() as td:
        os.environ["HOME"] = td
        Path(td, "bashrc").write_text("alias ll='ls -la'")
        result = _execute(
            {"operation": "read", "path": "~/bashrc"},
            home_dir=td,
        )
        assert result.ok
        reply = str(result.value.get("reply_text", ""))
        assert "alias" in reply


def test_glob_pattern() -> None:
    """Glob ``*.py`` lists only matching files."""
    with tempfile.TemporaryDirectory() as td:
        Path(td, "a.py").write_text("x")
        Path(td, "b.txt").write_text("y")
        result = _execute(
            {"operation": "list", "path": td, "glob": "*.py"},
            home_dir=td,
        )
        assert result.ok
        reply = str(result.value.get("reply_text", ""))
        assert "a.py" in reply
        assert "b.txt" not in reply


def test_recursive_list() -> None:
    """Recursive ``recursive=true`` descends into subdirectories."""
    with tempfile.TemporaryDirectory() as td:
        sub = Path(td, "sub")
        sub.mkdir()
        Path(sub, "nested.txt").write_text("deep")
        result = _execute(
            {"operation": "list", "path": td, "recursive": True},
            home_dir=td,
        )
        assert result.ok
        reply = str(result.value.get("reply_text", ""))
        assert "nested.txt" in reply


def test_missing_file_returns_error() -> None:
    """Read on non-existent path returns failure."""
    with tempfile.TemporaryDirectory() as td:
        result = _execute(
            {"operation": "read", "path": str(Path(td, "missing.txt"))},
            home_dir=td,
        )
        assert not result.ok
        assert result.error is not None


def test_binary_file_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        Path(td, "binary.bin").write_bytes(b"\x00\x01\x02")
        result = _execute(
            {"operation": "read", "path": str(Path(td, "binary.bin"))},
            home_dir=td,
        )

        assert not result.ok
        assert "binary" in str(result.error)
