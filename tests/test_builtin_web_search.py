"""Tests for the ``web_search`` builtin tool.

The tool is already implemented (ported from jarvis). These tests exercise
the full cascade via a fake HTTP client so no network calls are made.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

from shuvagent.tools.builtins.web_search import SearchConfig, _is_public_url
from shuvagent.tools.builtins.web_search import spec as web_search_spec
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
    ) -> None:
        self.status_code = status_code
        self.content = content
        self._json = json_data

    def json(self) -> dict[str, Any]:
        return self._json or {}


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
    brave_search_api_key: str = "",
    wikipedia_fallback_enabled: bool = True,
    enabled: bool = True,
) -> ToolResult:
    config = SearchConfig(
        enabled=enabled,
        brave_search_api_key=brave_search_api_key,
        wikipedia_fallback_enabled=wikipedia_fallback_enabled,
    )
    tool = web_search_spec(http_client=http_client, config=config)
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, arguments))
    assert decision.allowed and decision.call is not None
    return registry.execute(decision.call)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ddg_instant_answer_returns_quick_result() -> None:
    """When DDG instant API returns an Abstract, the tool surfaces it."""
    http = FakeHTTPClient(
        responses=[
            FakeResponse(
                json_data={
                    "Abstract": "Python is a programming language.",
                    "Heading": "Python",
                    "AbstractURL": "https://python.org",
                }
            ),
        ]
    )
    result = _execute(
        {"search_query": "what is python"},
        http_client=http,
    )
    assert result.ok
    assert result.value is not None
    assert result.value["provider"] == "duckduckgo_instant"
    assert result.value["query"] == "what is python"
    assert len(result.value["results"]) == 1
    assert "Python is a programming language" in result.value["results"][0]["snippet"]


def test_ddg_bot_challenge_emits_honest_block() -> None:
    """When DDG serves a bot-challenge page, the tool fails with
    'search_blocked' instead of confabulating results."""
    http = FakeHTTPClient(
        responses=[
            FakeResponse(json_data={}),  # instant empty
            FakeResponse(
                status_code=400,
                content=b'<div class="anomaly-modal">...</div>',
            ),  # DDG HTML blocked
            FakeResponse(json_data=[[], [], []]),  # Wikipedia opensearch empty
        ]
    )
    result = _execute(
        {"search_query": "latest news"},
        http_client=http,
    )
    assert not result.ok
    assert result.error == "search_blocked"


def test_brave_fallback_when_ddg_blocked() -> None:
    """When DDG is blocked and no instant answer exists, Brave Search
    (opt-in, keyed) is tried next."""
    http = FakeHTTPClient(
        responses=[
            FakeResponse(json_data={}),  # DDG instant empty
            FakeResponse(
                status_code=400,
                content=b"anomaly.js",
            ),  # DDG blocked
            FakeResponse(
                json_data={
                    "web": {
                        "results": [
                            {"title": "Python Language", "url": "https://python.org"}
                        ]
                    }
                }
            ),  # Brave success
            FakeResponse(
                content=b"<html><body>Python is great.</body></html>",
            ),  # Page fetch
        ]
    )
    result = _execute(
        {"search_query": "python language"},
        http_client=http,
        brave_search_api_key="test-key",
    )
    assert result.ok
    assert result.value["provider"] == "brave"
    assert result.value["query"] == "python language"
    assert len(result.value["results"]) >= 1


def test_wikipedia_fallback_last_resort() -> None:
    """When DDG and Brave both fail, Wikipedia (zero-config) is the
    final fallback."""
    # No brave_search_api_key set, so Brave is skipped entirely.
    http = FakeHTTPClient(
        responses=[
            FakeResponse(json_data={}),  # DDG instant empty
            FakeResponse(status_code=400, content=b"anomaly.js"),  # DDG blocked
            FakeResponse(
                json_data=[[], ["Python (programming language)"], []]
            ),  # Wiki opensearch
            FakeResponse(
                json_data={
                    "title": "Python (programming language)",
                    "extract": "Python is a high-level programming language.",
                    "content_urls": {
                        "desktop": {"page": "https://en.wikipedia.org/wiki/Python"}
                    },
                }
            ),  # Wiki summary
        ]
    )
    result = _execute(
        {"search_query": "python programming language"},
        http_client=http,
    )
    assert result.ok
    assert result.value["provider"] == "wikipedia"
    assert len(result.value["results"]) == 1
    assert (
        "Python is a high-level programming language"
        in result.value["results"][0]["snippet"]
    )


def test_disabled_in_config_returns_error() -> None:
    """When ``enabled = false`` the tool returns 'web_search_disabled'."""
    http = FakeHTTPClient(responses=[])
    result = _execute(
        {"search_query": "anything"},
        http_client=http,
        enabled=False,
    )
    assert not result.ok
    assert result.error == "web_search_disabled"


def test_ssrf_rejects_private_ip() -> None:
    assert not _is_public_url("http://127.0.0.1")
    assert not _is_public_url("http://10.0.0.1")
    assert not _is_public_url("http://192.168.1.10")
    assert not _is_public_url("http://169.254.169.254")


def test_zero_query_token_overlap_rejects_boilerplate() -> None:
    http = FakeHTTPClient(
        responses=[
            FakeResponse(json_data={}),
            FakeResponse(
                content=(b'<a href="https://example.com/page">Result</a>'),
            ),
            FakeResponse(
                content=b"<html><body>Accept cookies privacy banner</body></html>"
            ),
            FakeResponse(json_data=[[], [], []]),
        ]
    )

    result = _execute({"search_query": "python language"}, http_client=http)

    assert not result.ok
    assert result.error == "no_search_results"


def test_parallel_cascade_respects_wall_clock_cap() -> None:
    class SlowPageClient(FakeHTTPClient):
        def __init__(self) -> None:
            super().__init__(responses=[])
            self._lock = threading.Lock()

        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            with self._lock:
                self.requests.append((url, kwargs))
            if "api.duckduckgo.com" in url:
                return FakeResponse(json_data={})
            if "duckduckgo.com/html" in url:
                return FakeResponse(
                    content=(
                        b'<a href="https://example.com/a">A</a>'
                        b'<a href="https://example.com/b">B</a>'
                        b'<a href="https://example.com/c">C</a>'
                    )
                )
            if "wikipedia" in url:
                return FakeResponse(json_data=[[], [], []])
            time.sleep(0.25)
            return FakeResponse(content=b"<html><body>python language</body></html>")

    http = SlowPageClient()
    started = time.monotonic()
    result = _execute({"search_query": "python language"}, http_client=http)
    elapsed = time.monotonic() - started

    assert result.ok
    assert elapsed < 0.6


def test_missing_query_returns_error() -> None:
    """Empty or missing search_query returns a failure."""
    http = FakeHTTPClient(responses=[])
    result = _execute(
        {},
        http_client=http,
    )
    assert not result.ok
    assert result.error == "missing_query"


def test_timeout_returns_error() -> None:
    """When every request times out, the tool returns 'search_timeout'."""
    http = FakeHTTPClient(
        responses=[],
        side_effect=TimeoutError("request timed out"),
    )
    result = _execute(
        {"search_query": "test"},
        http_client=http,
    )
    assert not result.ok
    assert result.error == "search_timeout"
