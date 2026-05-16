import asyncio

from shuvagent import cli
from shuvagent.audio.runtime import audio_runtime_error
from shuvagent.cli import _SessionRunner, _start_decision
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
