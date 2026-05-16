from __future__ import annotations

import asyncio
from collections.abc import Callable

from shuvagent.telemetry.schema import TelemetryEvent

AudioEventSink = Callable[[TelemetryEvent], None]


class AudioRuntimeError(RuntimeError):
    def __init__(self, code: str, cause: Exception) -> None:
        self.code = code
        self.safe_message = str(cause)
        super().__init__(f"{code}: {self.safe_message}")


def report_audio_status(
    event_sink: AudioEventSink,
    status: object,
) -> None:
    event_sink(
        TelemetryEvent(
            event="audio.capture_status",
            level="warning",
            attributes={"status": str(status)},
        )
    )


def enqueue_audio_chunk(
    queue: asyncio.Queue[bytes],
    chunk: bytes,
    event_sink: AudioEventSink,
) -> None:
    try:
        queue.put_nowait(chunk)
    except asyncio.QueueFull:
        event_sink(
            TelemetryEvent(
                event="audio.capture_overflow",
                level="warning",
                attributes={"dropped_chunk_count": 1},
            )
        )


def audio_runtime_error(code: str, exc: Exception) -> AudioRuntimeError:
    return AudioRuntimeError(code, exc)
