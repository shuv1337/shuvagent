from shuvagent.config import RealtimeConfig
from shuvagent.realtime.openai_session import OpenAIRealtimeSession
from shuvagent.realtime.pipecat_gemini_session import PipecatGeminiRealtimeSession
from shuvagent.realtime.providers import (
    DEFAULT_GEMINI_LIVE_MODEL,
    DEFAULT_GEMINI_LIVE_VOICE,
    RealtimeSessionFactoryConfig,
    build_realtime_session,
)


def test_build_realtime_session_defaults_to_openai() -> None:
    session = build_realtime_session(
        RealtimeSessionFactoryConfig(
            realtime=RealtimeConfig(),
            api_key="sk-test",
        )
    )

    assert isinstance(session, OpenAIRealtimeSession)
    assert session.config.model == "gpt-realtime-2"
    assert session.config.voice == "marin"


def test_build_realtime_session_supports_gemini_defaults() -> None:
    session = build_realtime_session(
        RealtimeSessionFactoryConfig(
            realtime=RealtimeConfig(provider="gemini", api_key_env="GOOGLE_API_KEY"),
            api_key="google-test",
        )
    )

    assert isinstance(session, PipecatGeminiRealtimeSession)
    assert session.config.model == DEFAULT_GEMINI_LIVE_MODEL
    assert session.config.voice == DEFAULT_GEMINI_LIVE_VOICE


def test_build_realtime_session_preserves_explicit_gemini_model_and_voice() -> None:
    session = build_realtime_session(
        RealtimeSessionFactoryConfig(
            realtime=RealtimeConfig(
                provider="gemini",
                api_key_env="GOOGLE_API_KEY",
                model="models/gemini-2.5-flash-native-audio-preview-12-2025",
                voice="Puck",
            ),
            api_key="google-test",
        )
    )

    assert isinstance(session, PipecatGeminiRealtimeSession)
    assert (
        session.config.model
        == "models/gemini-2.5-flash-native-audio-preview-12-2025"
    )
    assert session.config.voice == "Puck"
