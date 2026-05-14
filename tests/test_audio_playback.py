from shuvagent.audio.capture import InMemoryAudioCapture
from shuvagent.audio.playback import InMemoryAudioPlayback


def test_24khz_pcm_round_trip() -> None:
    captured = InMemoryAudioCapture([b"\x00\x00\x01\x00"]).capture_once()
    playback = InMemoryAudioPlayback()

    result = playback.play(captured.chunks)

    assert result.played == captured.chunks
    assert playback.played == captured.chunks
    assert [event.event for event in result.events] == [
        "audio.playback_start",
        "audio.playback_stop",
    ]


def test_playback_empty_chunks_emits_underrun() -> None:
    playback = InMemoryAudioPlayback()

    result = playback.play([])

    assert [event.event for event in result.events] == [
        "audio.playback_start",
        "audio.underrun",
        "audio.playback_stop",
    ]
