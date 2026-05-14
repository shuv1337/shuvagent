from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from shuvagent.tools.types import (
    _GATE_TOKEN,
    GatedToolCall,
    ToolResult,
    ToolSpec,
    WindowSnapshot,
)


class SecurityError(RuntimeError):
    pass


AuditSink = Callable[[str, GatedToolCall], None]


@dataclass
class ToolRegistry:
    window_snapshot: Callable[[], WindowSnapshot]
    audit_sink: AuditSink | None = None
    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def specs(self) -> dict[str, ToolSpec]:
        return dict(self._tools)

    def execute(self, call: GatedToolCall) -> ToolResult:
        if call._mint_token is not _GATE_TOKEN:
            raise SecurityError("GatedToolCall not minted by PermissionGate")
        if call.tool.name not in self._tools:
            return ToolResult.failure("tool_not_registered")
        if not call.is_fresh(datetime.now(UTC), self.window_snapshot()):
            self._emit("tool.expired", call)
            return ToolResult.failure("confirmation_expired")
        self._emit("tool.executed", call)
        return call.tool.handler(call)

    def _emit(self, event: str, call: GatedToolCall) -> None:
        if self.audit_sink is not None:
            self.audit_sink(event, call)
