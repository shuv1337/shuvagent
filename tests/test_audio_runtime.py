import asyncio

from shuvagent.audio.runtime import (
    AudioRuntimeError,
    audio_runtime_error,
    enqueue_audio_chunk,
    report_audio_status,
)
from shuvagent.telemetry.schema import TelemetryEvent


def test_enqueue_audio_chunk_reports_overflow_without_audio_content() -> None:
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    events: list[TelemetryEvent] = []

    enqueue_audio_chunk(queue, b"first", events.append)
    enqueue_audio_chunk(queue, b"private audio bytes", events.append)

    assert queue.get_nowait() == b"first"
    assert len(events) == 1
    assert events[0].event == "audio.capture_overflow"
    assert events[0].attributes == {"dropped_chunk_count": 1}


def test_report_audio_status_is_content_free() -> None:
    events: list[TelemetryEvent] = []

    report_audio_status(events.append, "input overflow")

    assert events[0].event == "audio.capture_status"
    assert events[0].level == "warning"
    assert events[0].attributes == {"status": "input overflow"}


def test_audio_runtime_error_uses_stable_code() -> None:
    err = audio_runtime_error("audio_capture_device_error", ValueError("bad device"))

    assert isinstance(err, AudioRuntimeError)
    assert err.code == "audio_capture_device_error"
    assert err.safe_message == "bad device"
    assert str(err) == "audio_capture_device_error: bad device"
