from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from shuvagent.telemetry.schema import TelemetryEvent

PCM_SAMPLE_RATE = 24000
PCM_SAMPLE_WIDTH_BYTES = 2


@dataclass(frozen=True)
class AudioChunk:
    pcm16: bytes
    sample_rate: int = PCM_SAMPLE_RATE

    def validate(self) -> None:
        if self.sample_rate != PCM_SAMPLE_RATE:
            raise ValueError("audio sample_rate must be 24000")
        if len(self.pcm16) % PCM_SAMPLE_WIDTH_BYTES != 0:
            raise ValueError("pcm16 audio must contain whole 16-bit samples")


@dataclass
class CaptureResult:
    chunks: list[AudioChunk] = field(default_factory=list)
    events: list[TelemetryEvent] = field(default_factory=list)


class InMemoryAudioCapture:
    def __init__(self, chunks: Iterable[bytes], *, sample_rate: int = PCM_SAMPLE_RATE):
        self._chunks = list(chunks)
        self._sample_rate = sample_rate

    def capture_once(self) -> CaptureResult:
        result = CaptureResult()
        result.events.append(TelemetryEvent(event="audio.capture_start"))
        for raw in self._chunks:
            chunk = AudioChunk(raw, sample_rate=self._sample_rate)
            chunk.validate()
            result.chunks.append(chunk)
        result.events.append(
            TelemetryEvent(
                event="audio.capture_stop",
                attributes={"chunk_count": len(result.chunks)},
            )
        )
        return result


class SoundDeviceAudioCapture:
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

        return sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            device=None if self.device == "default" else self.device,
        )
