from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from shuvagent import __version__
from shuvagent.telemetry.redact import redact_value


@dataclass(frozen=True)
class TelemetryEvent:
    event: str
    level: str = "info"
    attributes: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    service: str = "shuvagent"
    session_id: str | None = None
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid4().hex[:16])

    def to_json_dict(self, *, debug_log_raw_text: bool = False) -> dict[str, Any]:
        attrs = redact_value(
            self.attributes,
            debug_log_raw_text=debug_log_raw_text,
        )
        if debug_log_raw_text:
            attrs["privacy.raw_text_logging"] = True
        return {
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "level": self.level,
            "service.name": self.service,
            "service.version": __version__,
            "event": self.event,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "attributes": attrs,
        }
