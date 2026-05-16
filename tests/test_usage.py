from shuvagent.usage import UsageTracker, parse_rate_limits, parse_realtime_usage


def test_usage_tracker_stops_at_output_token_cap() -> None:
    tracker = UsageTracker(output_token_cap=10)
    usage = parse_realtime_usage(
        {"response": {"usage": {"input_tokens": 3, "output_tokens": 10}}}
    )

    assert usage is not None
    decision = tracker.record_usage(usage)

    assert decision.should_stop
    assert decision.reason == "output_token_cap"
    assert tracker.snapshot()["output_tokens"] == 10


def test_usage_parser_tolerates_missing_and_malformed_usage() -> None:
    assert parse_realtime_usage({}) is None

    usage = parse_realtime_usage(
        {"usage": {"input_tokens": "bad", "output_tokens": "7", "total_tokens": 9}}
    )

    assert usage is not None
    assert usage.input_tokens == 0
    assert usage.output_tokens == 7
    assert usage.total_tokens == 9


def test_rate_limit_parser_returns_safe_fields() -> None:
    limits = parse_rate_limits(
        {
            "rate_limits": [
                {"name": "requests", "remaining": "3", "reset_seconds": "1.5"},
                "invalid",
            ]
        }
    )

    assert len(limits) == 1
    assert limits[0].name == "requests"
    assert limits[0].remaining == 3
    assert limits[0].reset_seconds == 1.5
