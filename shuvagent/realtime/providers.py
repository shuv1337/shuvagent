from __future__ import annotations

from dataclasses import dataclass

from shuvagent.config import RealtimeConfig
from shuvagent.realtime.openai_session import (
    OpenAIRealtimeSession,
    OpenAISessionConfig,
)
from shuvagent.realtime.session import RealtimeAgentSession
from shuvagent.tools.types import ToolSpec

DEFAULT_GEMINI_LIVE_MODEL = "models/gemini-3.1-flash-live-preview"
DEFAULT_GEMINI_LIVE_VOICE = "Charon"


@dataclass(frozen=True)
class RealtimeSessionFactoryConfig:
    realtime: RealtimeConfig
    api_key: str
    tools: tuple[ToolSpec, ...] = ()


def build_realtime_session(
    config: RealtimeSessionFactoryConfig,
) -> RealtimeAgentSession:
    if config.realtime.provider == "openai":
        return OpenAIRealtimeSession(
            OpenAISessionConfig(
                api_key=config.api_key,
                model=config.realtime.model,
                voice=config.realtime.voice,
                reasoning_effort=config.realtime.reasoning_effort,
                tools=config.tools,
                max_output_tokens=config.realtime.output_token_cap,
                request_timeout_sec=config.realtime.request_timeout_sec,
            )
        )
    if config.realtime.provider == "gemini":
        from shuvagent.realtime.pipecat_gemini_session import (
            PipecatGeminiRealtimeSession,
            PipecatGeminiSessionConfig,
        )

        return PipecatGeminiRealtimeSession(
            PipecatGeminiSessionConfig(
                api_key=config.api_key,
                model=_gemini_model(config.realtime),
                voice=_gemini_voice(config.realtime),
                tools=config.tools,
                max_output_tokens=config.realtime.output_token_cap,
                request_timeout_sec=config.realtime.request_timeout_sec,
            )
        )
    raise ValueError(f"unsupported realtime provider: {config.realtime.provider}")


def _gemini_model(config: RealtimeConfig) -> str:
    if config.model == RealtimeConfig().model:
        return DEFAULT_GEMINI_LIVE_MODEL
    return config.model


def _gemini_voice(config: RealtimeConfig) -> str:
    if config.voice == RealtimeConfig().voice:
        return DEFAULT_GEMINI_LIVE_VOICE
    return config.voice
