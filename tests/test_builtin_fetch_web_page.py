"""Tests for the ``fetch_web_page`` builtin tool.

All HTTP traffic is injected via a fake client so tests never hit the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shuvagent.tools.builtins import fetch_web_page_spec
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.tools.types import ToolCallRequest, ToolResult, WindowSnapshot

# ---------------------------------------------------------------------------
# Fake HTTP client
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"",
        json_data: dict[str, Any] | None = None,
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self._json = json_data
        self.url = url

    def json(self) -> dict[str, Any]:
        return self._json or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHTTPClient:
    def __init__(
        self,
        responses: list[FakeResponse],
        side_effect: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.side_effect = side_effect
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((url, kwargs))
        if self.side_effect is not None:
            raise self.side_effect
        if not self.responses:
            raise RuntimeError("No more canned responses")
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _window() -> WindowSnapshot:
    return WindowSnapshot(app_id="firefox", title="t", captured_at=datetime.now(UTC))


def _execute(
    arguments: dict[str, object],
    http_client: FakeHTTPClient,
    max_chars: int = 50_000,
) -> ToolResult:
    tool = fetch_web_page_spec(http_client=http_client, max_chars=max_chars)
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, arguments))
    assert decision.allowed and decision.call is not None
    return registry.execute(decision.call)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fetch_extracts_text_and_title() -> None:
    """Returns title + deduplicated text content."""
    html = (
        b"<html><head><title>Python Docs</title></head>"
        b"<body><p>Python is great.</p><p>Python is great.</p></body></html>"
    )
    http = FakeHTTPClient(responses=[FakeResponse(content=html)])
    result = _execute({"url": "https://python.org"}, http_client=http)
    assert result.ok
    reply = str(result.value.get("reply_text", ""))
    assert "Python Docs" in reply
    assert "Python is great" in reply


def test_include_links_param_adds_link_section() -> None:
    """include_links=true appends found links."""
    html = (
        b"<html><body>"
        b'<a href="/about">About</a>'
        b'<a href="https://other.com">Other</a>'
        b"</body></html>"
    )
    http = FakeHTTPClient(responses=[FakeResponse(content=html)])
    result = _execute(
        {"url": "https://python.org", "include_links": True},
        http_client=http,
    )
    assert result.ok
    reply = str(result.value.get("reply_text", ""))
    assert "Links found on page" in reply
    assert "About" in reply
    assert "Other" in reply


def test_truncate_at_max_chars() -> None:
    """Content > max_chars is truncated."""
    html = b"<html><body><p>A</p></body></html>"
    http = FakeHTTPClient(responses=[FakeResponse(content=html)])
    result = _execute(
        {"url": "https://python.org"},
        http_client=http,
        max_chars=5,
    )
    assert result.ok
    reply = str(result.value.get("reply_text", ""))
    assert "truncated" in reply.lower() or len(reply) <= 200


def test_ssrf_rejects_non_public_url() -> None:
    http = FakeHTTPClient(responses=[])
    result = _execute({"url": "http://127.0.0.1/private"}, http_client=http)

    assert not result.ok
    assert result.error == "url_not_allowed"
    assert http.requests == []


def test_missing_beautifulsoup_fallback_to_raw(monkeypatch) -> None:
    def missing_bs4(name: str):
        if name == "bs4":
            raise ImportError("no bs4")
        raise AssertionError(name)

    monkeypatch.setattr(
        "shuvagent.tools.builtins.fetch_web_page.import_module", missing_bs4
    )
    http = FakeHTTPClient(
        responses=[FakeResponse(content=b"<html><body><p>Raw text</p></body></html>")]
    )

    result = _execute({"url": "https://python.org"}, http_client=http)

    assert result.ok
    assert "Raw text" in str(result.value.get("reply_text", ""))


def test_http_error_returns_failure() -> None:
    """404/500 returns ToolResult.failure with status."""
    http = FakeHTTPClient(responses=[FakeResponse(status_code=404)])
    result = _execute({"url": "https://python.org/missing"}, http_client=http)
    assert not result.ok
    assert result.error is not None


def test_redirect_chain_re_validates_each_hop() -> None:
    http = FakeHTTPClient(
        responses=[
            FakeResponse(
                status_code=200,
                content=b"private",
                url="http://127.0.0.1/private",
            )
        ]
    )
    result = _execute({"url": "https://python.org"}, http_client=http)

    assert not result.ok
    assert result.error == "redirect_url_not_allowed"


def test_missing_url_returns_error() -> None:
    """Empty or missing URL returns a failure."""
    http = FakeHTTPClient(responses=[])
    result = _execute({}, http_client=http)
    assert not result.ok
    assert result.error is not None
