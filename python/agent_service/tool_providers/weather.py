from __future__ import annotations

from collections.abc import Callable
import json
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agent_service.privacy import sanitize_for_web_search
from agent_service.tool_result import ToolFailure, ToolResult, ToolStatus


JsonTransport = Callable[[str, float, dict[str, str]], bytes]


class WeatherProvider(Protocol):
    def current(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
        ...

    def forecast(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
        ...


class OpenMeteoWeatherProvider:
    name = "open_meteo"

    def __init__(
        self,
        *,
        transport: JsonTransport | None = None,
        timeout: float = 8.0,
    ) -> None:
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    def current(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
        return self._weather(location, tool_name="weather.current", locale=locale)

    def forecast(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
        return self._weather(location, tool_name="weather.forecast", locale=locale)

    def _weather(self, location: str, *, tool_name: str, locale: str) -> ToolResult:
        guard = sanitize_for_web_search(location)
        if guard.blocked:
            return _failure_result(
                tool_name,
                "blocked",
                "privacy_blocked",
                "天气查询包含本地路径或私密内容，请只提供城市名称。",
                retryable=False,
                removed_categories=guard.removedCategories,
            )

        try:
            place = self._geocode(guard.sanitizedText, locale=locale)
            if place is None:
                return _failure_result(
                    tool_name,
                    "failed",
                    "location_not_found",
                    "没有找到这个城市，请换一个更明确的城市名称。",
                    retryable=False,
                )
            forecast = self._forecast(place)
            current = _current_payload(forecast)
            return ToolResult(
                tool_name=tool_name,
                status="ok",
                data={
                    "location": str(place["name"]),
                    "country": str(place.get("country_code") or ""),
                    "latitude": float(place["latitude"]),
                    "longitude": float(place["longitude"]),
                    "temperatureC": _float_or_none(current.get("temperature_2m")),
                    "apparentTemperatureC": _float_or_none(
                        current.get("apparent_temperature")
                    ),
                    "condition": _weather_code_label(current.get("weather_code")),
                    "precipitationMm": _float_or_none(current.get("precipitation")),
                    "windSpeedKmh": _float_or_none(current.get("wind_speed_10m")),
                    "observedAt": str(current.get("time") or ""),
                    "timezone": str(place.get("timezone") or ""),
                },
                sources=[_open_meteo_source()],
                metadata={"provider": self.name, "query": guard.sanitizedText},
            )
        except (TimeoutError, socket.timeout):
            return _failure_result(
                tool_name,
                "failed",
                "timeout",
                "天气服务请求超时，请稍后重试。",
                retryable=True,
            )
        except json.JSONDecodeError:
            return _failure_result(
                tool_name,
                "failed",
                "network_error",
                "天气服务暂时不可用。",
                retryable=True,
            )
        except (
            HTTPError,
            URLError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ):
            return _failure_result(
                tool_name,
                "failed",
                "network_error",
                "天气服务暂时不可用。",
                retryable=True,
            )

    def _geocode(self, location: str, *, locale: str) -> dict[str, Any] | None:
        language = "zh" if locale.lower().startswith("zh") else "en"
        url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
            {
                "name": location,
                "count": "1",
                "language": language,
                "format": "json",
            }
        )
        payload = _loads(self._transport(url, self._timeout, _headers()))
        results = payload.get("results") or []
        if not results:
            return None
        if not isinstance(results, list):
            raise ValueError("expected geocoding results list")
        return _geocode_result(results[0])

    def _forecast(self, place: dict[str, Any]) -> dict[str, Any]:
        url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
            {
                "latitude": str(place["latitude"]),
                "longitude": str(place["longitude"]),
                "current": ",".join(
                    [
                        "temperature_2m",
                        "apparent_temperature",
                        "precipitation",
                        "weather_code",
                        "wind_speed_10m",
                    ]
                ),
                "timezone": "auto",
            }
        )
        return _loads(self._transport(url, self._timeout, _headers()))


def _urllib_transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _loads(body: bytes) -> dict[str, Any]:
    payload = json.loads(body.decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError("expected object payload")
    return payload


def _headers() -> dict[str, str]:
    return {"User-Agent": "Alita/0.27 weather-tool"}


def _geocode_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected geocoding result object")

    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("expected geocoding result name")

    latitude = _float_or_none(value.get("latitude"))
    longitude = _float_or_none(value.get("longitude"))
    if latitude is None or longitude is None:
        raise ValueError("expected geocoding coordinates")

    return {
        **value,
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
    }


def _current_payload(forecast: dict[str, Any]) -> dict[str, Any]:
    current = forecast.get("current")
    if not isinstance(current, dict) or not current:
        raise ValueError("expected current weather object")
    return current


def _failure_result(
    tool_name: str,
    status: ToolStatus,
    kind: str,
    message: str,
    *,
    retryable: bool,
    removed_categories: list[str] | None = None,
) -> ToolResult:
    metadata: dict[str, Any] = {"provider": OpenMeteoWeatherProvider.name}
    if removed_categories is not None:
        metadata["removedCategories"] = removed_categories
    return ToolResult(
        tool_name=tool_name,
        status=status,
        failure=ToolFailure(
            kind=kind,
            message=message,
            retryable=retryable,
            provider=OpenMeteoWeatherProvider.name,
        ),
        metadata=metadata,
    )


def _open_meteo_source() -> dict[str, str]:
    return {
        "title": "Open-Meteo",
        "url": "https://open-meteo.com/",
        "provider": OpenMeteoWeatherProvider.name,
    }


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _weather_code_label(value: Any) -> str:
    labels = {
        0: "晴",
        1: "大致晴朗",
        2: "局部多云",
        3: "阴",
        45: "雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "中等毛毛雨",
        55: "大毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        80: "小阵雨",
        81: "中等阵雨",
        82: "强阵雨",
        95: "雷暴",
    }
    try:
        return labels.get(int(value), "未知")
    except (TypeError, ValueError):
        return "未知"
