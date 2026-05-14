from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

API_KEY_RE = re.compile(r"\b((?:sk|sk-proj|anthropic)-[A-Za-z0-9_-]{20,})")


def redact_value(value: Any, *, debug_log_raw_text: bool = False) -> Any:
    if isinstance(value, str):
        if debug_log_raw_text:
            return value
        return API_KEY_RE.sub("[REDACTED-API-KEY]", value)
    if isinstance(value, Mapping):
        return {
            key: redact_value(val, debug_log_raw_text=debug_log_raw_text)
            for key, val in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [
            redact_value(item, debug_log_raw_text=debug_log_raw_text) for item in value
        ]
    return value


def summarize_user_text(
    text: str, *, debug_log_raw_text: bool = False
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "text_len": len(text),
        "text_sha256_prefix": hashlib.sha256(text.encode()).hexdigest()[:12],
    }
    if debug_log_raw_text:
        summary["text"] = text
        summary["privacy.raw_text_logging"] = True
    return summary
