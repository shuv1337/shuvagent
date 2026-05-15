"""Read-only selected-text / clipboard helpers (wl-paste wrapper).

Mirrors ShuVoice's selection helper but exists as a tiny standalone
module here so the agent can be built without taking a dependency on
ShuVoice internals.

The helpers are deliberately read-only and shell out to ``wl-paste``.
They never mutate clipboard state.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

Runner = Callable[[list[str], float], str]


@dataclass(frozen=True)
class SelectionSnapshot:
    """A read-only snapshot of a clipboard / selection.

    ``text`` is the raw text (the model needs it). ``text_len`` and
    ``text_sha256_prefix`` are the redaction-safe summary used in audit
    logs and telemetry — never log ``text`` directly unless
    ``debug_log_raw_text`` is on.
    """

    text: str

    @property
    def text_len(self) -> int:
        return len(self.text)

    @property
    def text_sha256_prefix(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]


def default_runner(args: list[str], timeout: float) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return result.stdout


def get_primary_selection(
    *,
    runner: Runner = default_runner,
    timeout: float = 0.5,
) -> SelectionSnapshot | None:
    """Return the X11/Wayland primary selection (highlighted text)."""
    return _wl_paste(["wl-paste", "--primary", "--no-newline"], runner, timeout)


def get_clipboard(
    *,
    runner: Runner = default_runner,
    timeout: float = 0.5,
) -> SelectionSnapshot | None:
    """Return the regular clipboard contents."""
    return _wl_paste(["wl-paste", "--no-newline"], runner, timeout)


def _wl_paste(
    args: list[str], runner: Runner, timeout: float
) -> SelectionSnapshot | None:
    try:
        output = runner(args, timeout)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None
    if output is None:
        return None
    # wl-paste appends a trailing newline unless --no-newline; strip
    # defensively in case the user runs on a wl-paste that ignored it.
    text = output.rstrip("\n")
    if not text:
        return None
    return SelectionSnapshot(text=text)
