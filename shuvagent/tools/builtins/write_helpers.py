from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable

WriteRunner = Callable[[list[str], float, str | None], str]


def default_write_runner(args: list[str], timeout: float, stdin: str | None) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        input=stdin,
        capture_output=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def text_summary(text: str) -> dict[str, object]:
    return {
        "text_len": len(text),
        "text_sha256_prefix": hashlib.sha256(text.encode()).hexdigest()[:12],
    }


def text_argument(arguments: dict[str, object]) -> str | None:
    text = arguments.get("text")
    if not isinstance(text, str) or text == "":
        return None
    return text


def paste_shortcut(runner: WriteRunner, timeout: float) -> None:
    runner(["wtype", "-M", "ctrl", "-P", "v", "-p", "v", "-m", "ctrl"], timeout, None)
