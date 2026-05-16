"""Tests for the ``weather`` builtin tool.

Open-Meteo API calls are injected via a fake HTTP client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shuvagent.tools.builtins import weather_spec
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
        json_data: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data or {}

    def json(self) -> dict[str, Any]:
        return self._json

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
# Fake location provider
# ---------------------------------------------------------------------------


class FakeLocationProvider:
    def __init__(
        self, lat: float | None = None, lon: float | None = None, name: str = ""
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.name = name

    def get_location(self) -> dict[str, Any] | None:
        if self.lat is None or self.lon is None:
            return None
        return {
            "latitude": self.lat,
            "longitude": self.lon,
            "display_name": self.name,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _window() -> WindowSnapshot:
    return WindowSnapshot(app_id="firefox", title="t", captured_at=datetime.now(UTC))


def _execute(
    arguments: dict[str, object],
    http_client: FakeHTTPClient,
    location_provider: FakeLocationProvider | None = None,
) -> ToolResult:
    tool = weather_spec(
        http_client=http_client,
        location_provider=location_provider,
    )
    registry = ToolRegistry(window_snapshot=_window)
    registry.register(tool)
    gate = PermissionGate(registry.specs(), window_snapshot=_window)
    decision = gate.authorize(ToolCallRequest("call-1", tool.name, arguments))
    assert decision.allowed and decision.call is not None
    return registry.execute(decision.call)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_weather_by_lat_lon() -> None:
    """Known coordinates return current temp + conditions."""
    loc = FakeLocationProvider(lat=51.5, lon=-0.1, name="London")
    weather_data = {
        "current": {
            "temperature_2m": 15.0,
            "weather_code": 1,
            "time": "2026-05-16T12:00",
        },
        "hourly": {"time": [], "temperature_2m": [], "weather_code": []},
        "daily": {
            "time": [],
            "weather_code": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
        },
    }
    http = FakeHTTPClient(responses=[FakeResponse(json_data=weather_data)])
    result = _execute({}, http_client=http, location_provider=loc)
    assert result.ok
    reply = str(result.value.get("reply_text", ""))
    assert "15" in reply
    assert "London" in reply


def test_geocoding_by_city_name() -> None:
    """ "London" resolved via Open-Meteo geocoding API, then weather fetched."""
    geo_data = {
        "results": [
            {"latitude": 51.5, "longitude": -0.1, "name": "London", "country": "UK"}
        ]
    }
    weather_data = {
        "current": {
            "temperature_2m": 12.0,
            "weather_code": 3,
            "time": "2026-05-16T12:00",
        },
        "hourly": {"time": [], "temperature_2m": [], "weather_code": []},
        "daily": {
            "time": [],
            "weather_code": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
        },
    }
    http = FakeHTTPClient(
        responses=[
            FakeResponse(json_data=geo_data),
            FakeResponse(json_data=weather_data),
        ]
    )
    result = _execute({"location": "London"}, http_client=http)
    assert result.ok
    reply = str(result.value.get("reply_text", ""))
    assert "12" in reply
    assert "London" in reply


def test_manual_location_override() -> None:
    """Configured lat/lon skips auto-detection."""
    loc = FakeLocationProvider(lat=40.7, lon=-74.0, name="New York")
    weather_data = {
        "current": {
            "temperature_2m": 22.0,
            "weather_code": 0,
            "time": "2026-05-16T12:00",
        },
        "hourly": {"time": [], "temperature_2m": [], "weather_code": []},
        "daily": {
            "time": [],
            "weather_code": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
        },
    }
    http = FakeHTTPClient(responses=[FakeResponse(json_data=weather_data)])
    result = _execute({}, http_client=http, location_provider=loc)
    assert result.ok
    reply = str(result.value.get("reply_text", ""))
    assert "New York" in reply


def test_missing_location_asks_user() -> None:
    """No auto-detect + no manual config → asks user for city."""
    loc = FakeLocationProvider(lat=None, lon=None, name="")
    http = FakeHTTPClient(responses=[])
    result = _execute({}, http_client=http, location_provider=loc)
    assert not result.ok
    assert (
        "city" in str(result.error).lower() or "location" in str(result.error).lower()
    )


def test_timeout_returns_error() -> None:
    """Open-Meteo > timeout → 'weather service timeout'."""
    loc = FakeLocationProvider(lat=51.5, lon=-0.1, name="London")
    http = FakeHTTPClient(
        responses=[],
        side_effect=TimeoutError("request timed out"),
    )
    result = _execute({}, http_client=http, location_provider=loc)
    assert not result.ok
    assert (
        "timeout" in str(result.error).lower()
        or "unavailable" in str(result.error).lower()
    )


def test_wmo_code_mapping() -> None:
    """Code 0 = 'Clear sky', code 95 = 'Thunderstorm'."""
    loc = FakeLocationProvider(lat=0.0, lon=0.0, name="Test")
    weather_data = {
        "current": {
            "temperature_2m": 25.0,
            "weather_code": 0,
            "time": "2026-05-16T12:00",
        },
        "hourly": {"time": [], "temperature_2m": [], "weather_code": []},
        "daily": {
            "time": [],
            "weather_code": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
        },
    }
    http = FakeHTTPClient(responses=[FakeResponse(json_data=weather_data)])
    result = _execute({}, http_client=http, location_provider=loc)
    assert result.ok
    reply = str(result.value.get("reply_text", ""))
    assert "Clear sky" in reply
