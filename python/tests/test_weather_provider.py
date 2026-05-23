from __future__ import annotations

from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from agent_service.tool_providers.weather import OpenMeteoWeatherProvider


def test_current_weather_geocodes_location_and_normalizes_forecast_payload() -> None:
    requested_urls: list[str] = []

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        requested_urls.append(url)
        if "geocoding-api.open-meteo.com" in url:
            return (
                b'{"results":[{"name":"Shanghai","country_code":"CN",'
                b'"latitude":31.2304,"longitude":121.4737,'
                b'"timezone":"Asia/Shanghai"}]}'
            )
        if "api.open-meteo.com" in url:
            return (
                b'{"current":{"time":"2026-05-23T15:00",'
                b'"temperature_2m":26.1,"apparent_temperature":27.3,'
                b'"precipitation":0.0,"weather_code":2,'
                b'"wind_speed_10m":12.4}}'
            )
        raise AssertionError(f"unexpected url: {url}")

    provider = OpenMeteoWeatherProvider(transport=transport, timeout=3.0)

    result = provider.current("上海")

    assert result.status == "ok"
    assert result.tool_name == "weather.current"
    assert result.data == {
        "location": "Shanghai",
        "country": "CN",
        "latitude": 31.2304,
        "longitude": 121.4737,
        "temperatureC": 26.1,
        "apparentTemperatureC": 27.3,
        "condition": "局部多云",
        "precipitationMm": 0.0,
        "windSpeedKmh": 12.4,
        "observedAt": "2026-05-23T15:00",
        "timezone": "Asia/Shanghai",
    }
    assert result.sources == [
        {
            "title": "Open-Meteo",
            "url": "https://open-meteo.com/",
            "provider": "open_meteo",
        }
    ]
    assert result.metadata["provider"] == "open_meteo"
    geocode_query = parse_qs(urlparse(requested_urls[0]).query)
    assert geocode_query["name"] == ["上海"]
    assert geocode_query["count"] == ["1"]
    forecast_query = parse_qs(urlparse(requested_urls[1]).query)
    assert forecast_query["latitude"] == ["31.2304"]
    assert forecast_query["longitude"] == ["121.4737"]
    assert forecast_query["timezone"] == ["auto"]


def test_current_weather_returns_failed_when_geocoding_has_no_results() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        return b'{"results":[]}'

    provider = OpenMeteoWeatherProvider(transport=transport)

    result = provider.current("不存在城市")

    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "location_not_found"
    assert result.failure.retryable is False
    assert result.metadata["provider"] == "open_meteo"


def test_current_weather_blocks_private_location_query_before_network_call() -> None:
    called = False

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        nonlocal called
        called = True
        return b"{}"

    provider = OpenMeteoWeatherProvider(transport=transport)

    result = provider.current(r"C:\Users\Drew\private-city-file.txt")

    assert called is False
    assert result.status == "blocked"
    assert result.failure is not None
    assert result.failure.kind == "privacy_blocked"
    assert result.failure.retryable is False
    assert result.failure.provider == "open_meteo"


def test_current_weather_maps_network_error_to_retryable_failure() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        raise URLError("tls handshake timed out")

    provider = OpenMeteoWeatherProvider(transport=transport)

    result = provider.current("上海")

    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "network_error"
    assert result.failure.retryable is True
    assert "tls handshake" not in result.failure.message.lower()


def test_current_weather_maps_malformed_geocoding_payload_to_failure() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        return b'{"results":[{"name":"Shanghai","country_code":"CN"}]}'

    result = OpenMeteoWeatherProvider(transport=transport).current("上海")

    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "network_error"
    assert result.failure.retryable is True
    assert "latitude" not in result.failure.message.lower()


def test_current_weather_maps_malformed_forecast_payload_to_failure() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        if "geocoding-api.open-meteo.com" in url:
            return (
                b'{"results":[{"name":"Shanghai","country_code":"CN",'
                b'"latitude":31.2304,"longitude":121.4737,'
                b'"timezone":"Asia/Shanghai"}]}'
            )
        return b'{"current":"bad"}'

    result = OpenMeteoWeatherProvider(transport=transport).current("上海")

    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "network_error"
    assert result.failure.retryable is True


def test_current_weather_maps_missing_current_payload_to_failure() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        if "geocoding-api.open-meteo.com" in url:
            return (
                b'{"results":[{"name":"Shanghai","country_code":"CN",'
                b'"latitude":31.2304,"longitude":121.4737,'
                b'"timezone":"Asia/Shanghai"}]}'
            )
        return b'{"error":true,"reason":"bad request"}'

    result = OpenMeteoWeatherProvider(transport=transport).current("上海")

    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "network_error"
    assert result.failure.retryable is True
    assert "bad request" not in result.failure.message.lower()


def test_forecast_uses_forecast_tool_name() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        if "geocoding-api.open-meteo.com" in url:
            return (
                b'{"results":[{"name":"Shanghai","country_code":"CN",'
                b'"latitude":31.2304,"longitude":121.4737,'
                b'"timezone":"Asia/Shanghai"}]}'
            )
        return (
            b'{"current":{"time":"2026-05-23T15:00",'
            b'"temperature_2m":26.1,"apparent_temperature":27.3,'
            b'"precipitation":0.0,"weather_code":2,'
            b'"wind_speed_10m":12.4}}'
        )

    result = OpenMeteoWeatherProvider(transport=transport).forecast("上海")

    assert result.status == "ok"
    assert result.tool_name == "weather.forecast"
