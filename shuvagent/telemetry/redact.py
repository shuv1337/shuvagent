from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Mapping, Sequence
from typing import Any

API_KEY_RE = re.compile(r"\b((?:sk|sk-proj|anthropic)-[A-Za-z0-9_-]{20,})")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\w)"
)
CC_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
IP_RE = re.compile(
    r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])|"
    r"(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(?![\w:])"
)


def redact_value(
    value: Any,
    *,
    debug_log_raw_text: bool = False,
    custom_patterns: Sequence[str] | None = None,
) -> Any:
    if isinstance(value, str):
        if debug_log_raw_text:
            return value
        return _redact_text(value, custom_patterns=custom_patterns)
    if isinstance(value, Mapping):
        return {
            key: redact_value(
                val,
                debug_log_raw_text=debug_log_raw_text,
                custom_patterns=custom_patterns,
            )
            for key, val in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [
            redact_value(
                item,
                debug_log_raw_text=debug_log_raw_text,
                custom_patterns=custom_patterns,
            )
            for item in value
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


def _redact_text(value: str, *, custom_patterns: Sequence[str] | None) -> str:
    redacted = API_KEY_RE.sub("[REDACTED-API-KEY]", value)
    redacted = EMAIL_RE.sub("[REDACTED-EMAIL]", redacted)
    redacted = PHONE_RE.sub("[REDACTED-PHONE]", redacted)
    redacted = CC_RE.sub(_redact_card_match, redacted)
    redacted = IP_RE.sub(_redact_ip_match, redacted)
    for pattern in custom_patterns or ():
        redacted = re.sub(pattern, "[REDACTED-CUSTOM]", redacted)
    return redacted


def _redact_card_match(match: re.Match[str]) -> str:
    candidate = re.sub(r"\D", "", match.group(0))
    if _luhn_valid(candidate):
        return "[REDACTED-CC]"
    return match.group(0)


def _redact_ip_match(match: re.Match[str]) -> str:
    candidate = match.group(0)
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return candidate
    return "[REDACTED-IP]"


def _luhn_valid(number: str) -> bool:
    if len(number) < 13 or len(number) > 19:
        return False
    total = 0
    parity = len(number) % 2
    for index, char in enumerate(number):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
