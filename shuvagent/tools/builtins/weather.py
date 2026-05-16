"""``weather`` — current weather and forecast via Open-Meteo."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from shuvagent.tools.types import GatedToolCall, ToolResult, ToolRisk, ToolSpec

NAME = "weather"
DESCRIPTION = (
    "Get current weather and forecast. Auto-detects location or uses configured city. "
    "Call with empty arguments to use detected location."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "location": {
            "type": "string",
            "description": (
                "OPTIONAL. City name. If omitted, uses auto-detected location."
            ),
        }
    },
    "required": [],
    "additionalProperties": False,
}


class UrllibHttpClient:
    def get(self, url: str, **kwargs: Any) -> Any:
        timeout = float(kwargs.get("timeout", 10.0))
        with urlopen(Request(url), timeout=timeout) as response:
            return _JsonResponse(response.status, response.read())


class _JsonResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self._content = content

    def json(self) -> dict[str, Any]:
        import json

        data = json.loads(self._content.decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}


def spec(
    *,
    http_client: Any | None = None,
    location_provider: Any | None = None,
) -> ToolSpec:
    http = http_client or UrllibHttpClient()

    def handler(call: GatedToolCall) -> ToolResult:
        location_arg = call.arguments.get("location")
        try:
            if isinstance(location_arg, str) and location_arg.strip():
                location = _geocode(location_arg.strip(), http)
                if location is None:
                    return ToolResult.failure("location_not_found")
            else:
                location = (
                    location_provider.get_location()
                    if location_provider is not None
                    else None
                )
                if location is None:
                    return ToolResult.failure("please tell me which city")
            weather = _fetch_weather(location, http)
        except TimeoutError:
            return ToolResult.failure("weather service timeout")
        except Exception as exc:
            return ToolResult.failure(f"weather service unavailable: {exc}")

        current = weather.get("current", {})
        temp = current.get("temperature_2m")
        code = int(current.get("weather_code", -1))
        condition = _wmo_description(code)
        name = str(
            location.get("display_name")
            or location.get("name")
            or location.get("city")
            or "that location"
        )
        return ToolResult.success(
            {
                "reply_text": f"Current weather for {name}: {temp}°C, {condition}.",
                "temperature_2m": temp,
                "condition": condition,
                "location": location,
            }
        )

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )


def _geocode(location: str, http: Any) -> dict[str, Any] | None:
    response = http.get(
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={quote(location)}&count=1&language=en&format=json",
        timeout=10.0,
    )
    data = response.json()
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    return {
        "latitude": first.get("latitude"),
        "longitude": first.get("longitude"),
        "display_name": first.get("name") or location,
    }


def _fetch_weather(location: dict[str, Any], http: Any) -> dict[str, Any]:
    lat = location.get("latitude")
    lon = location.get("longitude")
    response = http.get(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,weather_code"
        "&hourly=temperature_2m,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min",
        timeout=10.0,
    )
    data = response.json()
    return data if isinstance(data, dict) else {}


def _wmo_description(code: int) -> str:
    return {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        80: "Rain showers",
        81: "Rain showers",
        82: "Violent rain showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Thunderstorm with hail",
    }.get(code, "Unknown conditions")
