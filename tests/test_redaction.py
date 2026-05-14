from shuvagent.telemetry.redact import redact_value, summarize_user_text
from shuvagent.telemetry.schema import TelemetryEvent


def test_redacts_openai_key_in_message() -> None:
    redacted = redact_value("token sk-abcdefghijklmnopqrstuvwxyz123456")

    assert redacted == "token [REDACTED-API-KEY]"


def test_redacts_openai_key_in_nested_dict() -> None:
    redacted = redact_value({"nested": ["sk-proj-abcdefghijklmnopqrstuvwxyz123456"]})

    assert redacted == {"nested": ["[REDACTED-API-KEY]"]}


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
