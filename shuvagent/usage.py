from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shuvagent.realtime.events import RealtimeRateLimit, RealtimeUsage


@dataclass(frozen=True)
class UsageDecision:
    action: str
    reason: str = ""

    @property
    def should_stop(self) -> bool:
        return self.action == "stop"


class UsageTracker:
    def __init__(self, *, output_token_cap: int) -> None:
        if output_token_cap <= 0:
            raise ValueError("output_token_cap must be greater than zero")
        self.output_token_cap = output_token_cap
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    def record_usage(self, usage: RealtimeUsage) -> UsageDecision:
        self.input_tokens = usage.input_tokens
        self.output_tokens = usage.output_tokens
        self.total_tokens = usage.total_tokens
        if self.output_tokens >= self.output_token_cap:
            return UsageDecision("stop", "output_token_cap")
        return UsageDecision("continue")

    def snapshot(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "output_token_cap": self.output_token_cap,
        }


def parse_realtime_usage(payload: dict[str, Any]) -> RealtimeUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        response = payload.get("response")
        if isinstance(response, dict):
            usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    return RealtimeUsage(
        input_tokens=_safe_int(usage.get("input_tokens")),
        output_tokens=_safe_int(usage.get("output_tokens")),
        total_tokens=_safe_int(usage.get("total_tokens")),
    )


def parse_rate_limits(payload: dict[str, Any]) -> list[RealtimeRateLimit]:
    raw_limits = payload.get("rate_limits")
    if not isinstance(raw_limits, list):
        return []
    limits: list[RealtimeRateLimit] = []
    for raw in raw_limits:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "unknown")
        limits.append(
            RealtimeRateLimit(
                name=name,
                remaining=_safe_optional_int(raw.get("remaining")),
                reset_seconds=_safe_optional_float(raw.get("reset_seconds")),
            )
        )
    return limits


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
