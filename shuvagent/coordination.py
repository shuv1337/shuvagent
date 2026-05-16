from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

Runner = Callable[[list[str], float], str]
ArbitrationEventSink = Callable[[str, str], None]


class ShuVoiceStatusUnavailable(RuntimeError):
    """Raised when ShuVoice exists but status cannot be read reliably."""


@dataclass(frozen=True)
class ShuVoiceStatus:
    state: str

    @property
    def is_recording(self) -> bool:
        return "recording" in self.state

    @property
    def is_tts_active(self) -> bool:
        return "tts" in self.state or "speaking" in self.state


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str

    @classmethod
    def allow(cls, reason: str) -> Decision:
        return cls(True, reason)

    @classmethod
    def deny(cls, reason: str) -> Decision:
        return cls(False, reason)


class PausableSession(Protocol):
    @property
    def is_open(self) -> bool: ...

    @property
    def is_paused(self) -> bool: ...

    async def pause(self, reason: str) -> None: ...

    async def resume(self, reason: str) -> None: ...


def default_runner(args: list[str], timeout: float) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def shuvoice_status(
    *,
    runner: Runner = default_runner,
    timeout: float = 0.5,
) -> ShuVoiceStatus | None:
    try:
        output = runner(["shuvoice", "control", "status"], timeout)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        raise ShuVoiceStatusUnavailable("shuvoice-status-timeout") from exc
    except subprocess.CalledProcessError as exc:
        raise ShuVoiceStatusUnavailable("shuvoice-status-error") from exc
    state = _parse_status(output)
    if state is None:
        return None
    return ShuVoiceStatus(state=state)


def shuvoice_tts_stop(
    *,
    runner: Runner = default_runner,
    timeout: float = 0.5,
) -> bool:
    try:
        runner(["shuvoice", "control", "tts_stop"], timeout)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return False
    return True


def can_start_agent_session(
    *,
    runner: Runner = default_runner,
    timeout: float = 0.5,
    control_path: Path | None = None,
) -> Decision:
    del control_path
    try:
        status = shuvoice_status(runner=runner, timeout=timeout)
    except ShuVoiceStatusUnavailable as exc:
        return Decision.deny(str(exc))
    if status is None:
        return Decision.allow("shuvoice-not-running")
    if status.is_recording:
        return Decision.deny("shuvoice-recording")
    if status.is_tts_active:
        shuvoice_tts_stop(runner=runner, timeout=timeout)
        return Decision.allow("shuvoice-tts-stopped")
    return Decision.allow("shuvoice-idle")


async def monitor_shuvoice(
    session: PausableSession,
    *,
    runner: Runner = default_runner,
    interval_sec: float = 1.0,
    timeout: float = 0.5,
    event_sink: ArbitrationEventSink | None = None,
) -> None:
    while session.is_open:
        status = shuvoice_status(runner=runner, timeout=timeout)
        if status and status.is_recording and not session.is_paused:
            reason = "shuvoice-took-mic"
            await session.pause(reason)
            if event_sink is not None:
                event_sink("pause", reason)
        elif (not status or not status.is_recording) and session.is_paused:
            reason = "shuvoice-released-mic"
            await session.resume(reason)
            if event_sink is not None:
                event_sink("resume", reason)
        await asyncio.sleep(interval_sec)


def _parse_status(output: str) -> str | None:
    text = output.strip()
    if not text:
        return None
    if text.startswith("OK "):
        text = text[3:]
    return text.split()[0].lower()
