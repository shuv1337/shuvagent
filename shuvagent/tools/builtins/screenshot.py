"""``screenshot`` — capture screen region and OCR the text."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from shuvagent.tools.types import GatedToolCall, ToolResult, ToolRisk, ToolSpec

NAME = "screenshot"
DESCRIPTION = (
    "Capture a selected screen region and OCR the text. "
    "Use when the user asks about what's on their screen but no text is selected."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def spec(
    *,
    grim_runner: Callable[[list[str], float], bytes] | None = None,
    slurp_runner: Callable[[list[str], float], str] | None = None,
    tesseract_runner: Callable[[list[str], float], str] | None = None,
) -> ToolSpec:
    run_grim = grim_runner or _run_bytes
    run_slurp = slurp_runner or _default_slurp_runner()
    run_tesseract = tesseract_runner or _run_text

    def handler(call: GatedToolCall) -> ToolResult:
        del call
        if grim_runner is None and shutil.which("grim") is None:
            return ToolResult.failure("screenshot tool unavailable: grim not found")
        if tesseract_runner is None and shutil.which("tesseract") is None:
            return ToolResult.failure("OCR unavailable: tesseract not found")

        grim_args = ["grim", "-"]
        if run_slurp is not None:
            try:
                geometry = run_slurp(["slurp"], 10.0).strip()
            except FileNotFoundError:
                geometry = ""
            except Exception:
                geometry = ""
            if geometry:
                grim_args = ["grim", "-g", geometry, "-"]

        try:
            image = run_grim(grim_args, 10.0)
        except Exception as exc:
            return ToolResult.failure(f"screenshot tool unavailable: {exc}")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(image)
            image_path = Path(handle.name)
        try:
            text = run_tesseract(["tesseract", str(image_path), "stdout"], 10.0)
        except Exception as exc:
            return ToolResult.failure(f"OCR unavailable: {exc}")
        finally:
            image_path.unlink(missing_ok=True)
        return ToolResult.success({"text": text.strip(), "reply_text": text.strip()})

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )


def _run_bytes(args: list[str], timeout: float) -> bytes:
    return subprocess.run(
        args,
        check=True,
        timeout=timeout,
        capture_output=True,
    ).stdout


def _run_text(args: list[str], timeout: float) -> str:
    return subprocess.run(
        args,
        check=True,
        timeout=timeout,
        text=True,
        capture_output=True,
    ).stdout


def _default_slurp_runner() -> Callable[[list[str], float], str] | None:
    if shutil.which("slurp") is None:
        return None
    return _run_text
