from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

_GATE_TOKEN = object()


class ToolRisk(Enum):
    READ = "read"
    LOCAL_REVERSIBLE = "local_reversible"
    LOCAL_VISIBLE_WRITE = "local_visible_write"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class WindowSnapshot:
    app_id: str
    title: str
    captured_at: datetime


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    value: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def success(cls, value: dict[str, Any] | None = None) -> ToolResult:
        return cls(ok=True, value=value or {})

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, error=error)


@dataclass(frozen=True)
class GatedToolCall:
    call_id: str
    tool: ToolSpec
    arguments: dict[str, Any]
    decision_id: str
    window_at_authorize: WindowSnapshot
    authorized_at: datetime
    expires_at: datetime
    _mint_token: object = field(default=None, repr=False, compare=False)

    def is_fresh(self, now: datetime, current_window: WindowSnapshot) -> bool:
        if now > self.expires_at:
            return False
        if (
            self.tool.risk == ToolRisk.LOCAL_VISIBLE_WRITE
            and current_window.app_id != self.window_at_authorize.app_id
        ):
            return False
        return True


ToolHandler = Callable[[GatedToolCall], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk: ToolRisk
    input_schema: dict[str, Any]
    description: str
    handler: ToolHandler


@dataclass(frozen=True)
class ToolCallRequest:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
