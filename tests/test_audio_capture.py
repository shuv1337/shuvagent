import pytest

from shuvagent.audio.capture import AudioChunk, InMemoryAudioCapture


def test_in_memory_capture_returns_24khz_pcm16_chunks() -> None:
    capture = InMemoryAudioCapture([b"\x00\x00\x01\x00"])

    result = capture.capture_once()

    assert result.chunks == [AudioChunk(b"\x00\x00\x01\x00")]
    assert [event.event for event in result.events] == [
        "audio.capture_start",
        "audio.capture_stop",
    ]


def test_capture_rejects_non_24khz_audio() -> None:
    capture = InMemoryAudioCapture([b"\x00\x00"], sample_rate=48000)

    with pytest.raises(ValueError, match="24000"):
        capture.capture_once()


def test_capture_rejects_partial_pcm16_sample() -> None:
    capture = InMemoryAudioCapture([b"\x00"])

    with pytest.raises(ValueError, match="16-bit"):
        capture.capture_once()
