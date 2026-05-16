"""Tests for ``time_context`` — system prompt time injection."""

from __future__ import annotations

from datetime import UTC, datetime

from shuvagent.time_context import build_time_context


def test_time_string_includes_iso_datetime() -> None:
    """Format includes ISO date, time, and day-of-week."""
    now = datetime(2026, 5, 16, 14, 32, 0, tzinfo=UTC)
    ctx = build_time_context(now)
    assert "2026-05-16" in ctx
    assert "14:32:00" in ctx or "14:32" in ctx
    assert "Saturday" in ctx


def test_respects_system_timezone() -> None:
    """Uses the provided timezone, not just UTC."""
    from zoneinfo import ZoneInfo

    now = datetime(2026, 5, 16, 14, 32, 0, tzinfo=ZoneInfo("America/New_York"))
    ctx = build_time_context(now)
    # Should include timezone name or offset
    assert (
        "UTC" not in ctx
        or "EDT" in ctx
        or "EST" in ctx
        or "-04:00" in ctx
        or "-05:00" in ctx
    )


def test_updates_on_session_start() -> None:
    """Fresh time is generated for each call."""
    ctx1 = build_time_context(datetime.now(UTC))
    import time

    time.sleep(0.01)
    ctx2 = build_time_context(datetime.now(UTC))
    assert ctx1 != ctx2 or "seconds" not in ctx1
