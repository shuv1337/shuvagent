from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from shuvagent.tools.types import ToolCallRequest, ToolSpec


@dataclass(frozen=True)
class ConfirmationRequest:
    request: ToolCallRequest
    tool: ToolSpec
    reason: str


class ConfirmationProvider(Protocol):
    def confirm(self, request: ConfirmationRequest) -> bool: ...


class DenyAllConfirmationProvider:
    def confirm(self, request: ConfirmationRequest) -> bool:
        del request
        return False
