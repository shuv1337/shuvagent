import asyncio
import sys
from types import SimpleNamespace

from shuvagent import cli
from shuvagent.audio.runtime import audio_runtime_error
from shuvagent.cli import (
    _CapturePauseController,
    _mic_stream,
    _SessionRunner,
    _start_decision,
)
from shuvagent.config import AppConfig, RealtimeConfig
from shuvagent.telemetry.schema import TelemetryEvent


class MemorySink:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)


def test_duration_cap_sets_stop_event_and_emits_interruption() -> None:
    async def run() -> None:
        sink = MemorySink()
        runner = _SessionRunner(
            config=AppConfig(
                realtime=RealtimeConfig(session_max_duration_sec=1),
            ),
            api_key="sk-test",
            sink=sink,
        )
        stop_event = asyncio.Event()

        await runner._stop_after_duration_cap(stop_event)

        assert stop_event.is_set()
        assert sink.events[-1].event == "agent.session.interrupted"
        assert sink.events[-1].attributes == {
            "reason": "duration_cap",
            "duration_cap_sec": 1,
        }

    asyncio.run(run())


def test_audio_runtime_error_emits_audio_device_error() -> None:
    sink = MemorySink()
    runner = _SessionRunner(
        config=AppConfig(),
        api_key="sk-test",
        sink=sink,
    )

    runner._emit_session_failure(
        audio_runtime_error("audio_capture_device_error", ValueError("bad device"))
    )

    audio_events = [
        event for event in sink.events if event.event == "audio.device_error"
    ]
    assert audio_events
    assert audio_events[-1].attributes == {
        "code": "audio_capture_device_error",
        "message": "bad device",
    }
    assert sink.events[-1].event == "agent.session.failed"


def test_start_decision_denies_missing_api_key() -> None:
    decision = _start_decision(config=AppConfig(), api_key=None)()

    assert not decision.allowed
    assert decision.reason == "missing_api_key:OPENAI_API_KEY"


def test_session_start_requests_shuvoice_tts_stop(monkeypatch) -> None:
    calls: list[float] = []

    def fake_tts_stop(*, timeout: float) -> bool:
        calls.append(timeout)
        return True

    monkeypatch.setattr(cli, "shuvoice_tts_stop", fake_tts_stop)
    sink = MemorySink()
    runner = _SessionRunner(config=AppConfig(), api_key="sk-test", sink=sink)

    runner._stop_shuvoice_tts()

    assert calls == [2.0]
    assert sink.events[-1].event == "shuvoice.tts_stop_requested"
    assert sink.events[-1].attributes == {"ok": True}


def test_shuvoice_arbitration_emits_safe_telemetry() -> None:
    sink = MemorySink()
    runner = _SessionRunner(config=AppConfig(), api_key="sk-test", sink=sink)

    runner._emit_shuvoice_arbitration("pause", "shuvoice-took-mic")

    assert sink.events[-1].event == "shuvoice.mic_arbitration"
    assert sink.events[-1].attributes == {
        "action": "pause",
        "reason": "shuvoice-took-mic",
    }


def test_mic_stream_releases_device_on_pause_and_restarts_on_resume(
    monkeypatch,
) -> None:
    async def run() -> None:
        streams: list[FakeRawInputStream] = []

        def raw_input_stream(**kwargs) -> FakeRawInputStream:
            stream = FakeRawInputStream(kwargs["callback"])
            streams.append(stream)
            return stream

        monkeypatch.setitem(
            sys.modules,
            "sounddevice",
            SimpleNamespace(RawInputStream=raw_input_stream),
        )
        sink = MemorySink()
        stop_event = asyncio.Event()
        pause_controller = _CapturePauseController()
        generator = _mic_stream(
            stop_event,
            AppConfig(),
            sink.emit,
            pause_controller=pause_controller,
        )

        first = await anext(generator)
        assert first == b"chunk-1"
        assert len(streams) == 1
        assert streams[0].started
        assert not streams[0].closed

        await pause_controller.pause()
        pending = asyncio.create_task(anext(generator))
        await asyncio.sleep(0.1)

        assert streams[0].stopped
        assert streams[0].closed
        assert not pending.done()

        await pause_controller.resume()
        second = await asyncio.wait_for(pending, timeout=1.0)

        assert second == b"chunk-2"
        assert len(streams) == 2
        assert streams[1].started

        stop_event.set()
        await generator.aclose()
        assert streams[1].stopped
        assert streams[1].closed
        assert [event.event for event in sink.events] == [
            "audio.capture_start",
            "audio.capture_stop",
            "audio.capture_start",
            "audio.capture_stop",
        ]
        assert [event.attributes.get("reason") for event in sink.events[1::2]] == [
            "pause",
            "stop",
        ]

    asyncio.run(run())


class FakeRawInputStream:
    _next_chunk = 1

    def __init__(self, callback) -> None:
        self._callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True
        chunk = f"chunk-{FakeRawInputStream._next_chunk}".encode()
        FakeRawInputStream._next_chunk += 1
        self._callback(chunk, 480, object(), None)

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True
