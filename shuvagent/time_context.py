"""Time context injection for the system prompt."""

from __future__ import annotations

from datetime import datetime


def build_time_context(now: datetime | None = None) -> str:
    """Return a human-readable time string for injection into the system prompt.

    Example: "Current time: 2026-05-16 14:32:00 UTC (Saturday)"
    """
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    zone = current.tzname() or current.strftime("%z") or "local"
    offset = current.strftime("%z")
    formatted_offset = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    zone_label = zone if not formatted_offset else f"{zone} ({formatted_offset})"
    return f"Current time: {current:%Y-%m-%d %H:%M:%S} {zone_label} ({current:%A})"
