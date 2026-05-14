from __future__ import annotations

from dataclasses import dataclass, field

from shuvagent.audio.capture import PCM_SAMPLE_RATE, AudioChunk
from shuvagent.telemetry.schema import TelemetryEvent


@dataclass
class PlaybackResult:
    played: list[AudioChunk] = field(default_factory=list)
    events: list[TelemetryEvent] = field(default_factory=list)


class InMemoryAudioPlayback:
    def __init__(self) -> None:
        self.played: list[AudioChunk] = []

    def play(self, chunks: list[AudioChunk]) -> PlaybackResult:
        result = PlaybackResult()
        result.events.append(TelemetryEvent(event="audio.playback_start"))
        if not chunks:
            result.events.append(TelemetryEvent(event="audio.underrun"))
        for chunk in chunks:
            chunk.validate()
            self.played.append(chunk)
            result.played.append(chunk)
        result.events.append(
            TelemetryEvent(
                event="audio.playback_stop",
                attributes={"chunk_count": len(result.played)},
            )
        )
        return result


class SoundDeviceAudioPlayback:
    def __init__(
        self,
        *,
        device: str = "default",
        sample_rate: int = PCM_SAMPLE_RATE,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate

    def open_stream(self):
        if self.sample_rate != PCM_SAMPLE_RATE:
            raise ValueError("audio sample_rate must be 24000")
        import sounddevice as sd

        return sd.RawOutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            device=None if self.device == "default" else self.device,
        )
