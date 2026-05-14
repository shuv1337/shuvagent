from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from shuvagent.tools.confirmation import (
    ConfirmationProvider,
    ConfirmationRequest,
    DenyAllConfirmationProvider,
)
from shuvagent.tools.types import (
    _GATE_TOKEN,
    GatedToolCall,
    ToolCallRequest,
    ToolRisk,
    ToolSpec,
    WindowSnapshot,
)


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    call: GatedToolCall | None = None
    reason: str | None = None

    @classmethod
    def allow(cls, call: GatedToolCall) -> AuthorizationDecision:
        return cls(allowed=True, call=call)

    @classmethod
    def deny(cls, reason: str) -> AuthorizationDecision:
        return cls(allowed=False, reason=reason)


class PermissionGate:
    def __init__(
        self,
        tools: Mapping[str, ToolSpec],
        *,
        window_snapshot: Callable[[], WindowSnapshot],
        confirmation: ConfirmationProvider | None = None,
        ttl_sec: int = 15,
    ) -> None:
        self._tools = tools
        self._window_snapshot = window_snapshot
        self._confirmation = confirmation or DenyAllConfirmationProvider()
        self._ttl_sec = ttl_sec

    def authorize(self, request: ToolCallRequest) -> AuthorizationDecision:
        tool = self._tools.get(request.tool_name)
        if tool is None:
            return AuthorizationDecision.deny("unknown_tool")
        if tool.risk is ToolRisk.DESTRUCTIVE:
            return AuthorizationDecision.deny("destructive_tool_not_supported")
        if tool.risk is not ToolRisk.READ:
            confirmation = ConfirmationRequest(
                request=request,
                tool=tool,
                reason=f"{tool.risk.value}_requires_confirmation",
            )
            if not self._confirmation.confirm(confirmation):
                return AuthorizationDecision.deny("confirmation_required")
        now = datetime.now(UTC)
        return AuthorizationDecision.allow(
            GatedToolCall(
                call_id=request.call_id,
                tool=tool,
                arguments=request.arguments,
                decision_id=str(uuid4()),
                window_at_authorize=self._window_snapshot(),
                authorized_at=now,
                expires_at=now + timedelta(seconds=self._ttl_sec),
                _mint_token=_GATE_TOKEN,
            )
        )
