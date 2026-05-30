import io
import json

from shuvagent import __version__
from shuvagent.telemetry.redact import redact_value, summarize_user_text
from shuvagent.telemetry.schema import TelemetryEvent
from shuvagent.telemetry.sink import JsonLineSink


def test_redacts_openai_key_in_message() -> None:
    redacted = redact_value("token sk-abcdefghijklmnopqrstuvwxyz123456")

    assert redacted == "token [REDACTED-API-KEY]"


def test_redacts_openai_key_in_nested_dict() -> None:
    redacted = redact_value({"nested": ["sk-proj-abcdefghijklmnopqrstuvwxyz123456"]})

    assert redacted == {"nested": ["[REDACTED-API-KEY]"]}


def test_redacts_email_addresses() -> None:
    assert redact_value("mail user@example.com") == "mail [REDACTED-EMAIL]"


def test_redacts_phone_numbers() -> None:
    assert redact_value("call +1-555-123-4567") == "call [REDACTED-PHONE]"


def test_redacts_credit_cards() -> None:
    assert redact_value("card 4111 1111 1111 1111") == "card [REDACTED-CC]"


def test_redacts_ip_addresses() -> None:
    assert redact_value("hosts 192.168.1.1 and ::1") == (
        "hosts [REDACTED-IP] and [REDACTED-IP]"
    )


def test_custom_patterns_from_config() -> None:
    redacted = redact_value("internal ABC-123", custom_patterns=[r"ABC-\d+"])

    assert redacted == "internal [REDACTED-CUSTOM]"


def test_nested_dict_redaction() -> None:
    redacted = redact_value({"user": {"email": "user@example.com"}})

    assert redacted == {"user": {"email": "[REDACTED-EMAIL]"}}


def test_selected_text_replaced_with_len_and_hash() -> None:
    summary = summarize_user_text("secret selected text")

    assert summary["text_len"] == 20
    assert "text" not in summary
    assert len(summary["text_sha256_prefix"]) == 12


def test_debug_flag_disables_text_summary_redaction_but_marks_event() -> None:
    summary = summarize_user_text("secret selected text", debug_log_raw_text=True)

    assert summary["text"] == "secret selected text"
    assert summary["privacy.raw_text_logging"] is True


def test_event_envelope_matches_otel_shape_and_redacts() -> None:
    event = TelemetryEvent(
        event="agent.session.start_requested",
        attributes={"api_key": "sk-abcdefghijklmnopqrstuvwxyz123456"},
    )

    payload = event.to_json_dict()

    assert payload["service.name"] == "shuvagent"
    assert payload["service.version"] == "0.1.0"
    assert payload["attributes"]["api_key"] == "[REDACTED-API-KEY]"


def test_to_json_dict_debug_flag_reveals_raw_text_and_marks_event() -> None:
    """The real emit path (to_json_dict) must un-redact attributes only under
    the explicit debug flag and stamp the privacy marker (US18)."""
    event = TelemetryEvent(
        event="tool.executed",
        attributes={"selected_text": "secret selected text user@example.com"},
    )

    payload = event.to_json_dict(debug_log_raw_text=True)

    assert (
        payload["attributes"]["selected_text"]
        == "secret selected text user@example.com"
    )
    assert payload["attributes"]["privacy.raw_text_logging"] is True


def test_to_json_dict_default_redacts_and_omits_raw_text_marker() -> None:
    """Default (no debug flag) must redact and NOT stamp the marker (US18)."""
    event = TelemetryEvent(
        event="tool.executed",
        attributes={"selected_text": "secret user@example.com"},
    )

    payload = event.to_json_dict()

    assert payload["attributes"]["selected_text"] == "secret [REDACTED-EMAIL]"
    assert "privacy.raw_text_logging" not in payload["attributes"]


def test_json_line_sink_emit_serializes_full_maple_compatible_envelope() -> None:
    """JsonLineSink.emit must serialize the full OTEL/Maple-compatible envelope
    (timestamp, level, service, event, ids, session, attributes) (US29)."""
    stream = io.StringIO()
    sink = JsonLineSink(stream=stream)

    event = TelemetryEvent(
        event="agent.session.connected",
        session_id="sess-1",
        attributes={"k": "v"},
    )
    sink.emit(event)

    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "agent.session.connected"
    assert payload["level"] == "info"
    assert payload["service.name"] == "shuvagent"
    assert payload["service.version"] == __version__
    assert payload["session_id"] == "sess-1"
    assert isinstance(payload["trace_id"], str) and len(payload["trace_id"]) == 32
    assert isinstance(payload["span_id"], str) and len(payload["span_id"]) == 16
    assert payload["timestamp"].endswith("Z")
    assert payload["attributes"] == {"k": "v"}


def test_json_line_sink_default_redacts_secrets_on_emit() -> None:
    """The serialized emit path redacts secrets by default (US17/US29)."""
    stream = io.StringIO()
    sink = JsonLineSink(stream=stream)

    sink.emit(
        TelemetryEvent(
            event="tool.executed",
            attributes={"blob": "key sk-abcdefghijklmnopqrstuvwxyz123456"},
        )
    )

    rendered = stream.getvalue()
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in rendered
    assert "[REDACTED-API-KEY]" in rendered


def test_json_line_sink_debug_flag_emits_raw_text_and_marker() -> None:
    """With debug_log_raw_text=True the sink passes raw text through and marks
    the event so privacy-sensitive diagnostics are auditable (US18)."""
    stream = io.StringIO()
    sink = JsonLineSink(stream=stream, debug_log_raw_text=True)

    sink.emit(
        TelemetryEvent(
            event="tool.executed",
            attributes={"selected_text": "raw private text"},
        )
    )

    payload = json.loads(stream.getvalue().strip())
    assert payload["attributes"]["selected_text"] == "raw private text"
    assert payload["attributes"]["privacy.raw_text_logging"] is True
