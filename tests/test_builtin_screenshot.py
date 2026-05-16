"""Tests for the ``screenshot`` builtin tool.

Grim + slurp + tesseract are all faked via injected runners.
"""

from __future__ import annotations

from datetime import UTC, datetime

from shuvagent.tools.builtins import screenshot_spec
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, ToolResult, WindowSnapshot

# ---------------------------------------------------------------------------
# Fake runners
# ---------------------------------------------------------------------------


class RecordingGrimRunner:
    def __init__(self, returncode: int = 0, png_bytes: bytes = b"fake_png") -> None:
        self.returncode = returncode
        self.png_bytes = png_bytes
        self.calls: list[tuple[list[str], float]] = []

    def run(self, args: list[str], timeout: float) -> bytes:
        self.calls.append((args, timeout))
        if self.returncode != 0:
            raise RuntimeError(f"grim failed with code {self.returncode}")
        return self.png_bytes


class RecordingSlurpRunner:
    def __init__(self, geometry: str = "0,0 100x100") -> None:
        self.geometry = geometry
        self.calls: list[tuple[list[str], float]] = []

    def run(self, args: list[str], timeout: float) -> str:
        self.calls.append((args, timeout))
        return self.geometry


class RecordingTesseractRunner:
    def __init__(self, text: str = "hello world") -> None:
        self.text = text
        self.calls: list[tuple[list[str], float]] = []

    def run(self, args: list[str], timeout: float) -> str:
        self.calls.append((args, timeout))
        return self.text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _window() -> WindowSnapshot:
    return WindowSnapshot(app_id="firefox", title="t", captured_at=datetime.now(UTC))


def _execute(
    grim_runner: RecordingGrimRunner,
    slurp_runner: RecordingSlurpRunner | None = None,
    tesseract_runner: RecordingTesseractRunner | None = None,
) -> ToolResult:
    tool = screenshot_spec(
        grim_runner=grim_runner.run if grim_runner else None,
        slurp_runner=slurp_runner.run if slurp_runner else None,
        tesseract_runner=tesseract_runner.run if tesseract_runner else None,
    )
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, {}))
    assert decision.allowed and decision.call is not None
    return registry.execute(decision.call)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ocr_returns_text_from_captured_region() -> None:
    """Fake image → fake tesseract → text returned in ToolResult."""
    grim = RecordingGrimRunner(returncode=0, png_bytes=b"fake_png")
    slurp = RecordingSlurpRunner(geometry="10,20 300x200")
    tess = RecordingTesseractRunner(text="Hello from the screen!")

    result = _execute(grim_runner=grim, slurp_runner=slurp, tesseract_runner=tess)
    assert result.ok
    assert result.value is not None
    assert result.value.get("text") == "Hello from the screen!"
    # grim should have been called with the slurp geometry
    assert any("-g" in str(c[0]) or "10,20" in str(c[0]) for c in grim.calls)


def test_missing_grim_returns_error() -> None:
    """grim not in PATH → tool returns 'screenshot tool unavailable'."""
    grim = RecordingGrimRunner(returncode=1)
    tess = RecordingTesseractRunner(text="")
    result = _execute(grim_runner=grim, tesseract_runner=tess)
    assert not result.ok
    assert (
        "grim" in str(result.error).lower() or "screenshot" in str(result.error).lower()
    )


def test_missing_tesseract_returns_error() -> None:
    """tesseract not in PATH → tool returns 'OCR unavailable'."""
    grim = RecordingGrimRunner(returncode=0, png_bytes=b"fake_png")

    # Simulate missing tesseract by having it raise
    def broken_tess(args, timeout):
        raise FileNotFoundError("tesseract")

    tool = screenshot_spec(
        grim_runner=grim.run,
        tesseract_runner=broken_tess,
    )
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, {}))
    assert decision.allowed and decision.call is not None
    result = registry.execute(decision.call)
    assert not result.ok
    assert (
        "tesseract" in str(result.error).lower() or "ocr" in str(result.error).lower()
    )


def test_empty_ocr_returns_empty_string() -> None:
    """Blank image returns empty string (not error)."""
    grim = RecordingGrimRunner(returncode=0, png_bytes=b"fake_png")
    tess = RecordingTesseractRunner(text="")
    result = _execute(grim_runner=grim, tesseract_runner=tess)
    assert result.ok
    assert result.value is not None
    assert result.value.get("text") == ""


def test_fullscreen_fallback_when_slurp_missing() -> None:
    """No slurp → capture full screen instead of region."""
    grim = RecordingGrimRunner(returncode=0, png_bytes=b"fake_png")
    tess = RecordingTesseractRunner(text="fullscreen capture")

    tool = screenshot_spec(
        grim_runner=grim.run,
        slurp_runner=None,  # no region selection
        tesseract_runner=tess.run,
    )
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, {}))
    assert decision.allowed and decision.call is not None
    result = registry.execute(decision.call)
    assert result.ok
    assert result.value.get("text") == "fullscreen capture"
    # grim should NOT have -g (geometry) flag
    assert not any("-g" in str(c[0]) for c in grim.calls)
