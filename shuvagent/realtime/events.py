from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
class ScriptedTurn:
    user_audio: bytes
    tool_call: ToolCallRequest | None = None
    audio_response: bytes = b""
