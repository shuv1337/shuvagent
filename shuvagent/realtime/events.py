from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from shuvagent.tools.types import ToolCallRequest


class SessionState(Enum):
    CONNECTING = "connecting"
    READY = "ready"
    LISTENING = "listening"
    SPEAKING = "speaking"
    PAUSED = "paused"
    CLOSED = "closed"


@dataclass(frozen=True)
class RealtimeError:
    code: str
    message: str


@dataclass(frozen=True)
class RealtimeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class RealtimeRateLimit:
    name: str
    remaining: int | None = None
    reset_seconds: float | None = None


@dataclass(frozen=True)
class RealtimeApiEvent:
    type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ScriptedTurn:
    user_audio: bytes
    tool_call: ToolCallRequest | None = None
    audio_response: bytes = b""
