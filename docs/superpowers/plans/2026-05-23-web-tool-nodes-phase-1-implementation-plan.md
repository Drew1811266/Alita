# Web Tool Nodes Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stable web tool nodes so weather questions use Open-Meteo directly and general real-time questions use a configurable search provider chain instead of depending only on DuckDuckGo HTML search.

**Architecture:** Keep the current LangGraph intent layer as the broad router. Add a small tool routing layer under `web_simple_inquiry`, then call provider classes that return structured tool results or existing `SearchResponse` objects. Weather bypasses generic search; general web search uses Brave Search when configured and DuckDuckGo HTML as a fallback.

**Tech Stack:** Python 3.12, pytest, dataclasses, urllib, LangGraph, Open-Meteo Geocoding API, Open-Meteo Forecast API, optional Brave Search API.

---

## Scope Boundary

This plan implements the first working slice of the design spec:

- Phase 1 weather tool nodes: `weather.current` and `weather.forecast`.
- Phase 2 search provider chain: `BraveSearchProvider` plus `DuckDuckGoHtmlSearchProvider` fallback.
- Graph integration for simple inquiries and research executor defaults.
- Privacy guard reuse before outbound weather and search calls.

The fetch/scrape provider package and browser automation provider are separate subsystems. They remain outside this Phase 1 plan because the reported failure is simple weather/search reliability, and this slice can be tested and shipped independently.

## Current Code Entry Points

- `python/agent_service/intent.py` classifies words like `today`, `current`, `最新`, `今天`, and `当前` as `InquiryMode.WEB_SIMPLE`.
- `python/agent_service/graph.py` routes `web_simple_inquiry` to `answer_with_web()`.
- `python/agent_service/web_research.py` calls `answer_simple_web_inquiry()` and currently defaults to `DuckDuckGoHtmlSearchProvider()`.
- `python/agent_service/web_search.py` owns the existing `SearchResponse`, `SearchResult`, `SearchFailure`, ranking, source classification, and DuckDuckGo HTML provider.
- `python/agent_service/execution.py` defaults `ResearchFlowExecutor` to `DuckDuckGoHtmlSearchProvider()`.
- `python/agent_service/privacy.py` exposes `sanitize_for_web_search()` and must stay in the outbound tool path.

## File Structure

- Create `python/agent_service/tool_result.py`
  - Shared `ToolResult` and `ToolFailure` dataclasses for non-search tools.
- Create `python/agent_service/tool_router.py`
  - Deterministic mapping from simple inquiry text to concrete tool names and arguments.
- Create `python/agent_service/tool_providers/__init__.py`
  - Marks provider package and exports public provider helpers.
- Create `python/agent_service/tool_providers/weather.py`
  - Open-Meteo geocoding and current/forecast weather provider.
- Create `python/agent_service/tool_providers/web_search.py`
  - Provider chain, optional Brave provider, default provider factory.
- Modify `python/agent_service/web_search.py`
  - Add optional provider metadata to `SearchResponse`; add `name` and `is_configured()` to DuckDuckGo.
- Modify `python/agent_service/web_research.py`
  - Route weather questions before generic search; default search to the provider chain.
- Modify `python/agent_service/graph.py`
  - Thread an optional weather provider through `build_graph()`, `run_agent()`, `stream_agent_events()`, and `answer_with_web()`.
- Modify `python/agent_service/execution.py`
  - Default `ResearchFlowExecutor` search provider to the same provider chain.
- Create `python/tests/test_tool_result.py`
  - Contract tests for `ToolResult` payload conversion.
- Create `python/tests/test_tool_router.py`
  - Weather routing and location extraction tests.
- Create `python/tests/test_weather_provider.py`
  - Open-Meteo response normalization, privacy block, and failure tests.
- Create `python/tests/test_web_provider_chain.py`
  - Provider chain and Brave mapping tests.
- Modify `python/tests/test_web_research.py`
  - Weather answer tests and default provider factory test.
- Modify `python/tests/test_graph.py`
  - End-to-end graph tests for weather path.
- Modify `python/tests/test_execution.py`
  - Research executor default provider chain test.

---

### Task 1: Add Shared Tool Result Contract

**Files:**
- Create: `python/agent_service/tool_result.py`
- Test: `python/tests/test_tool_result.py`

- [ ] **Step 1: Write the failing contract tests**

Create `python/tests/test_tool_result.py`:

```python
from __future__ import annotations

from agent_service.tool_result import ToolFailure, ToolResult


def test_tool_result_payload_includes_status_data_sources_failure_and_metadata() -> None:
    failure = ToolFailure(
        kind="network_error",
        message="Provider was unreachable.",
        retryable=True,
        provider="open_meteo",
    )
    result = ToolResult(
        tool_name="weather.current",
        status="failed",
        data={"location": "上海"},
        sources=[{"title": "Open-Meteo", "url": "https://open-meteo.com/"}],
        failure=failure,
        metadata={"provider": "open_meteo"},
    )

    assert result.to_payload() == {
        "toolName": "weather.current",
        "status": "failed",
        "data": {"location": "上海"},
        "sources": [{"title": "Open-Meteo", "url": "https://open-meteo.com/"}],
        "failure": {
            "kind": "network_error",
            "message": "Provider was unreachable.",
            "retryable": True,
            "provider": "open_meteo",
        },
        "metadata": {"provider": "open_meteo"},
    }


def test_ok_tool_result_payload_omits_failure() -> None:
    result = ToolResult(
        tool_name="weather.current",
        status="ok",
        data={"temperatureC": 22.5},
    )

    assert result.to_payload()["failure"] is None
    assert result.to_payload()["sources"] == []
    assert result.to_payload()["metadata"] == {}
```

- [ ] **Step 2: Run the new tests and verify the expected failure**

Run:

```powershell
python -m pytest python/tests/test_tool_result.py -q
```

Expected: FAIL because `agent_service.tool_result` does not exist.

- [ ] **Step 3: Implement the shared contract**

Create `python/agent_service/tool_result.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ToolStatus = Literal["ok", "failed", "blocked", "not_configured"]


@dataclass(frozen=True)
class ToolFailure:
    kind: str
    message: str
    retryable: bool = False
    provider: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "retryable": self.retryable,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: ToolStatus
    data: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    failure: ToolFailure | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "toolName": self.tool_name,
            "status": self.status,
            "data": dict(self.data),
            "sources": list(self.sources),
            "failure": self.failure.to_payload() if self.failure else None,
            "metadata": dict(self.metadata),
        }
```

- [ ] **Step 4: Run the contract tests**

Run:

```powershell
python -m pytest python/tests/test_tool_result.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add python/agent_service/tool_result.py python/tests/test_tool_result.py
git commit -m "feat: add tool result contract"
```

---

### Task 2: Add Open-Meteo Weather Provider

**Files:**
- Create: `python/agent_service/tool_providers/__init__.py`
- Create: `python/agent_service/tool_providers/weather.py`
- Test: `python/tests/test_weather_provider.py`

- [ ] **Step 1: Write failing weather provider tests**

Create `python/tests/test_weather_provider.py`:

```python
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
```

- [ ] **Step 2: Run the provider tests and verify the expected failure**

Run:

```powershell
python -m pytest python/tests/test_weather_provider.py -q
```

Expected: FAIL because `agent_service.tool_providers.weather` does not exist.

- [ ] **Step 3: Implement the provider package and Open-Meteo provider**

Create `python/agent_service/tool_providers/__init__.py`:

```python
from __future__ import annotations
```

Create `python/agent_service/tool_providers/weather.py`:

```python
from __future__ import annotations

from collections.abc import Callable
import json
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agent_service.privacy import sanitize_for_web_search
from agent_service.tool_result import ToolFailure, ToolResult


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
        except (TimeoutError, socket.timeout):
            return _failure_result(
                tool_name,
                "failed",
                "timeout",
                "天气服务请求超时，请稍后重试。",
                retryable=True,
            )
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            return _failure_result(
                tool_name,
                "failed",
                "network_error",
                "天气服务暂时不可用。",
                retryable=True,
            )

        current = forecast.get("current") or {}
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
        return dict(results[0])

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
    return {"User-Agent": "Alita/0.26 weather-tool"}


def _failure_result(
    tool_name: str,
    status: str,
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
        status=status,  # type: ignore[arg-type]
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
```

- [ ] **Step 4: Run the weather provider tests**

Run:

```powershell
python -m pytest python/tests/test_weather_provider.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add python/agent_service/tool_providers/__init__.py python/agent_service/tool_providers/weather.py python/tests/test_weather_provider.py
git commit -m "feat: add open meteo weather provider"
```

---

### Task 3: Add Tool Router For Weather Questions

**Files:**
- Create: `python/agent_service/tool_router.py`
- Test: `python/tests/test_tool_router.py`

- [ ] **Step 1: Write failing router tests**

Create `python/tests/test_tool_router.py`:

```python
from __future__ import annotations

from agent_service.schemas import UserMessage
from agent_service.tool_router import route_tool_for_message


def test_routes_current_weather_question_to_weather_current() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="今天上海市的天气怎么样？")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "ready"
    assert route.arguments == {"location": "上海"}


def test_routes_forecast_question_to_weather_forecast() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="明天杭州会下雨吗？")
    )

    assert route is not None
    assert route.tool_name == "weather.forecast"
    assert route.status == "ready"
    assert route.arguments == {"location": "杭州"}


def test_routes_temperature_question_without_weather_word() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="北京现在多少度？")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "ready"
    assert route.arguments == {"location": "北京"}


def test_weather_question_without_location_requests_location() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="今天的天气怎么样？")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "missing_input"
    assert route.missing_inputs == ["location"]
    assert route.arguments == {}


def test_non_weather_web_question_has_no_tool_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is the latest Python release?")
    )

    assert route is None
```

- [ ] **Step 2: Run router tests and verify the expected failure**

Run:

```powershell
python -m pytest python/tests/test_tool_router.py -q
```

Expected: FAIL because `agent_service.tool_router` does not exist.

- [ ] **Step 3: Implement deterministic weather routing**

Create `python/agent_service/tool_router.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
import re

from agent_service.schemas import UserMessage


ToolRouteStatus = Literal["ready", "missing_input"]
ToolName = Literal["weather.current", "weather.forecast"]


@dataclass(frozen=True)
class ToolRoute:
    tool_name: ToolName
    status: ToolRouteStatus
    arguments: dict[str, str] = field(default_factory=dict)
    missing_inputs: list[str] = field(default_factory=list)


def route_tool_for_message(message: UserMessage) -> ToolRoute | None:
    content = message.content.strip()
    if not _looks_like_weather_question(content):
        return None

    tool_name: ToolName = (
        "weather.forecast" if _looks_like_forecast(content) else "weather.current"
    )
    location = _extract_location(content)
    if not location:
        return ToolRoute(
            tool_name=tool_name,
            status="missing_input",
            missing_inputs=["location"],
        )
    return ToolRoute(
        tool_name=tool_name,
        status="ready",
        arguments={"location": location},
    )


def _looks_like_weather_question(content: str) -> bool:
    normalized = content.lower()
    weather_markers = (
        "weather",
        "temperature",
        "rain",
        "forecast",
        "天气",
        "气温",
        "温度",
        "多少度",
        "下雨",
        "降雨",
        "风速",
        "湿度",
    )
    time_markers = (
        "today",
        "tomorrow",
        "current",
        "now",
        "今天",
        "明天",
        "现在",
        "当前",
    )
    return any(marker in normalized for marker in weather_markers) and any(
        marker in normalized for marker in time_markers
    )


def _looks_like_forecast(content: str) -> bool:
    normalized = content.lower()
    return any(
        marker in normalized
        for marker in ("tomorrow", "forecast", "明天", "后天", "预报", "会下雨")
    )


def _extract_location(content: str) -> str:
    normalized = content.strip()
    patterns = [
        r"(?:今天|现在|当前|明天|后天)\s*([\u4e00-\u9fff]{2,10})市?(?:的)?(?:天气|气温|温度|会下雨|下雨|降雨|风速|湿度)",
        r"([\u4e00-\u9fff]{2,10})市?(?:今天|现在|当前|明天|后天)(?:的)?(?:天气|气温|温度|会下雨|下雨|降雨|风速|湿度|多少度)",
        r"([\u4e00-\u9fff]{2,10})市?(?:现在|当前)?多少度",
        r"(?:weather|temperature|forecast|rain)\s+(?:in|for)\s+([A-Za-z][A-Za-z .'-]{1,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return _clean_location(match.group(1))
    return ""


def _clean_location(value: str) -> str:
    cleaned = value.strip(" 　,，。.!?？")
    if cleaned.endswith("市"):
        cleaned = cleaned[:-1]
    return cleaned.strip()
```

- [ ] **Step 4: Run router tests**

Run:

```powershell
python -m pytest python/tests/test_tool_router.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add python/agent_service/tool_router.py python/tests/test_tool_router.py
git commit -m "feat: route weather inquiries to tool nodes"
```

---

### Task 4: Wire Weather Tool Into Simple Web Inquiry

**Files:**
- Modify: `python/agent_service/web_research.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_web_research.py`
- Modify: `python/tests/test_graph.py`

- [ ] **Step 1: Add failing web research tests for the weather path**

Append these tests to `python/tests/test_web_research.py`:

```python

class FakeWeatherProvider:
    def __init__(self) -> None:
        self.current_locations: list[str] = []
        self.forecast_locations: list[str] = []

    def current(self, location: str, *, locale: str = "zh-CN"):
        from agent_service.tool_result import ToolResult

        self.current_locations.append(location)
        return ToolResult(
            tool_name="weather.current",
            status="ok",
            data={
                "location": "上海",
                "country": "CN",
                "temperatureC": 26.1,
                "apparentTemperatureC": 27.3,
                "condition": "局部多云",
                "precipitationMm": 0.0,
                "windSpeedKmh": 12.4,
                "observedAt": "2026-05-23T15:00",
                "timezone": "Asia/Shanghai",
            },
            sources=[
                {
                    "title": "Open-Meteo",
                    "url": "https://open-meteo.com/",
                    "provider": "open_meteo",
                }
            ],
            metadata={"provider": "open_meteo"},
        )

    def forecast(self, location: str, *, locale: str = "zh-CN"):
        self.forecast_locations.append(location)
        return self.current(location, locale=locale)


class FailingSearchProvider:
    def search(self, query: str):
        raise AssertionError(f"search should not be called for weather: {query}")


def test_simple_weather_inquiry_uses_weather_provider_without_search() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    weather_provider = FakeWeatherProvider()
    message = UserMessage(task_id="weather", content="今天上海天气怎么样？")

    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=FailingSearchProvider(),
        weather_provider=weather_provider,
    )

    assert event.type == "message.created"
    assert weather_provider.current_locations == ["上海"]
    assert "上海当前天气" in event.payload["message"]["content"]
    assert "26.1°C" in event.payload["message"]["content"]
    assert event.payload["sources"][0]["provider"] == "open_meteo"
    assert event.payload["sourceMetadata"]["toolName"] == "weather.current"


def test_weather_inquiry_without_location_asks_for_city() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    message = UserMessage(task_id="weather", content="今天的天气怎么样？")

    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=FailingSearchProvider(),
        weather_provider=FakeWeatherProvider(),
    )

    assert event.type == "input.required"
    assert event.payload == {
        "prompt": "请告诉我要查询哪个城市的天气。",
        "missing": ["location"],
    }
```

- [ ] **Step 2: Add a failing graph-level weather test**

Append this test to `python/tests/test_graph.py`:

```python

def test_weather_simple_route_uses_weather_provider_without_generic_search() -> None:
    from agent_service.tool_result import ToolResult

    class WeatherProvider:
        def __init__(self) -> None:
            self.locations: list[str] = []

        def current(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
            self.locations.append(location)
            return ToolResult(
                tool_name="weather.current",
                status="ok",
                data={
                    "location": "上海",
                    "temperatureC": 26.1,
                    "apparentTemperatureC": 27.3,
                    "condition": "局部多云",
                    "precipitationMm": 0.0,
                    "windSpeedKmh": 12.4,
                    "observedAt": "2026-05-23T15:00",
                    "timezone": "Asia/Shanghai",
                },
                sources=[{"title": "Open-Meteo", "url": "https://open-meteo.com/"}],
                metadata={"provider": "open_meteo"},
            )

        def forecast(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
            return self.current(location, locale=locale)

    class SearchProvider:
        def search(self, query: str):
            raise AssertionError("generic search should not run for weather")

    weather_provider = WeatherProvider()

    events = run_agent(
        UserMessage(task_id="weather", content="今天上海天气怎么样？"),
        search_provider=SearchProvider(),
        weather_provider=weather_provider,
    )

    assert weather_provider.locations == ["上海"]
    assert events[0].type == "message.created"
    assert "上海当前天气" in events[0].payload["message"]["content"]
```

- [ ] **Step 3: Run the new tests and verify the expected signature failures**

Run:

```powershell
python -m pytest python/tests/test_web_research.py::test_simple_weather_inquiry_uses_weather_provider_without_search python/tests/test_web_research.py::test_weather_inquiry_without_location_asks_for_city python/tests/test_graph.py::test_weather_simple_route_uses_weather_provider_without_generic_search -q
```

Expected: FAIL because `answer_simple_web_inquiry()` and `run_agent()` do not accept `weather_provider`.

- [ ] **Step 4: Modify `web_research.py` imports and function signature**

In `python/agent_service/web_research.py`, add imports:

```python
from agent_service.tool_providers.weather import (
    OpenMeteoWeatherProvider,
    WeatherProvider,
)
from agent_service.tool_router import route_tool_for_message
from agent_service.tool_result import ToolResult
```

Change `answer_simple_web_inquiry()` signature:

```python
def answer_simple_web_inquiry(
    message: UserMessage,
    route_decision: RouteDecision | dict,
    *,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
) -> AgentEvent:
```

At the start of the function, after `del route_decision`, insert:

```python
    tool_route = route_tool_for_message(message)
    if tool_route is not None and tool_route.tool_name.startswith("weather."):
        return _answer_weather_inquiry(
            tool_route,
            weather_provider=weather_provider,
        )
```

Add helper functions in `web_research.py` above `_synthesize_answer()`:

```python
def _answer_weather_inquiry(
    tool_route,
    *,
    weather_provider: WeatherProvider | None,
) -> AgentEvent:
    if tool_route.status == "missing_input":
        return AgentEvent(
            type="input.required",
            payload={
                "prompt": "请告诉我要查询哪个城市的天气。",
                "missing": list(tool_route.missing_inputs),
            },
        )

    provider = weather_provider or OpenMeteoWeatherProvider()
    location = tool_route.arguments["location"]
    if tool_route.tool_name == "weather.forecast":
        result = provider.forecast(location)
    else:
        result = provider.current(location)

    return AgentEvent(
        type="message.created",
        payload={
            "message": _assistant_message(_synthesize_weather_answer(result)),
            "sources": list(result.sources),
            "rejectedSources": [],
            "sourceMetadata": {
                "toolName": result.tool_name,
                "status": result.status,
                "failure": (
                    result.failure.to_payload() if result.failure is not None else None
                ),
                "metadata": dict(result.metadata),
            },
        },
    )


def _synthesize_weather_answer(result: ToolResult) -> str:
    if result.status != "ok":
        if result.failure is not None:
            return f"天气查询失败：{result.failure.message}"
        return "天气查询失败：工具没有返回可用结果。"

    data = result.data
    location = data.get("location") or "该城市"
    temperature = _format_weather_value(data.get("temperatureC"), "°C")
    apparent = _format_weather_value(data.get("apparentTemperatureC"), "°C")
    precipitation = _format_weather_value(data.get("precipitationMm"), " mm")
    wind = _format_weather_value(data.get("windSpeedKmh"), " km/h")
    condition = data.get("condition") or "未知"
    observed_at = data.get("observedAt") or "未知时间"
    return (
        f"{location}当前天气：{condition}，气温 {temperature}，"
        f"体感 {apparent}，降水 {precipitation}，风速 {wind}。"
        f"观测时间：{observed_at}。数据来源：Open-Meteo。"
    )


def _format_weather_value(value: object, unit: str) -> str:
    if value is None or value == "":
        return f"未知{unit.strip()}"
    return f"{value}{unit}"
```

- [ ] **Step 5: Thread weather provider through `graph.py`**

In `python/agent_service/graph.py`, add import:

```python
from agent_service.tool_providers.weather import WeatherProvider
```

Change `build_graph()` signature:

```python
def build_graph(
    model_client: ModelClient | None = None,
    *,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
):
```

Change the `answer_with_web` node registration:

```python
    graph.add_node(
        "answer_with_web",
        lambda state: answer_with_web(
            state,
            search_provider=search_provider,
            weather_provider=weather_provider,
        ),
    )
```

Change `answer_with_web()` signature and call:

```python
def answer_with_web(
    state: AgentState,
    *,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
) -> AgentState:
    return {
        **state,
        "events": [
            answer_simple_web_inquiry(
                state["message"],
                state.get("route_decision", {}),
                search_provider=search_provider,
                weather_provider=weather_provider,
            )
        ],
    }
```

Change `run_agent()` signature:

```python
def run_agent(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
    current_graph: RunGraph | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict | None = None,
) -> list[AgentEvent]:
```

Pass `weather_provider` into `build_graph()`:

```python
    app = build_graph(
        model_client=model_client,
        search_provider=search_provider,
        weather_provider=weather_provider,
        inquiry_choice=inquiry_choice,
    )
```

Change `stream_agent_events()` signature:

```python
def stream_agent_events(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
    current_graph: RunGraph | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict | None = None,
) -> Iterator[AgentEvent]:
```

Pass `weather_provider` into the `run_agent()` call inside `stream_agent_events()`:

```python
        yield from run_agent(
            message,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
            inquiry_choice=inquiry_choice,
        )
```

- [ ] **Step 6: Run targeted weather integration tests**

Run:

```powershell
python -m pytest python/tests/test_web_research.py::test_simple_weather_inquiry_uses_weather_provider_without_search python/tests/test_web_research.py::test_weather_inquiry_without_location_asks_for_city python/tests/test_graph.py::test_weather_simple_route_uses_weather_provider_without_generic_search -q
```

Expected: PASS.

- [ ] **Step 7: Run existing web and graph tests touched by this path**

Run:

```powershell
python -m pytest python/tests/test_web_research.py python/tests/test_graph.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```powershell
git add python/agent_service/web_research.py python/agent_service/graph.py python/tests/test_web_research.py python/tests/test_graph.py
git commit -m "feat: answer weather inquiries with tool provider"
```

---

### Task 5: Add Search Provider Chain And Brave Provider

**Files:**
- Create: `python/agent_service/tool_providers/web_search.py`
- Modify: `python/agent_service/web_search.py`
- Test: `python/tests/test_web_provider_chain.py`
- Modify: `python/tests/test_web_search.py`

- [ ] **Step 1: Write failing provider chain tests**

Create `python/tests/test_web_provider_chain.py`:

```python
from __future__ import annotations

from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from agent_service.tool_providers.web_search import (
    BraveSearchProvider,
    ProviderChainSearchProvider,
)
from agent_service.web_search import SearchFailure, SearchResponse, SearchResult


class FakeProvider:
    def __init__(
        self,
        name: str,
        response: SearchResponse,
        *,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.response = response
        self.configured = configured
        self.queries: list[str] = []

    def is_configured(self) -> bool:
        return self.configured

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        return self.response


def test_chain_skips_unconfigured_provider_and_uses_first_success() -> None:
    skipped = FakeProvider("brave", SearchResponse(results=[]), configured=False)
    success = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="Python Docs",
                    url="https://docs.python.org/",
                    snippet="Official docs.",
                )
            ]
        ),
    )
    chain = ProviderChainSearchProvider([skipped, success])

    response = chain.search("latest Python release")

    assert skipped.queries == []
    assert success.queries == ["latest Python release"]
    assert response.results[0].title == "Python Docs"
    assert response.metadata["provider"] == "duckduckgo"
    assert response.metadata["attempts"] == [
        {"provider": "brave", "status": "not_configured"},
        {"provider": "duckduckgo", "status": "ok"},
    ]


def test_chain_falls_back_after_retryable_failure() -> None:
    failure = FakeProvider(
        "brave",
        SearchResponse(
            results=[],
            failure=SearchFailure(kind="timeout", message="Search timed out."),
        ),
    )
    success = FakeProvider(
        "duckduckgo",
        SearchResponse(
            results=[
                SearchResult(
                    title="LangGraph Docs",
                    url="https://langchain-ai.github.io/langgraph/",
                    snippet="Docs.",
                )
            ]
        ),
    )

    response = ProviderChainSearchProvider([failure, success]).search("LangGraph docs")

    assert failure.queries == ["LangGraph docs"]
    assert success.queries == ["LangGraph docs"]
    assert response.results[0].title == "LangGraph Docs"
    assert response.metadata["attempts"][0] == {
        "provider": "brave",
        "status": "failed",
        "kind": "timeout",
        "message": "Search timed out.",
    }


def test_chain_returns_clear_failure_when_every_provider_fails() -> None:
    chain = ProviderChainSearchProvider(
        [
            FakeProvider("brave", SearchResponse(results=[]), configured=False),
            FakeProvider(
                "duckduckgo",
                SearchResponse(
                    results=[],
                    failure=SearchFailure(
                        kind="network_error",
                        message="Search request failed.",
                    ),
                ),
            ),
        ]
    )

    response = chain.search("today Shanghai weather")

    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "network_error"
    assert response.failure.message == "所有搜索服务暂时不可用。"
    assert response.metadata["attempts"] == [
        {"provider": "brave", "status": "not_configured"},
        {
            "provider": "duckduckgo",
            "status": "failed",
            "kind": "network_error",
            "message": "Search request failed.",
        },
    ]


def test_brave_provider_maps_json_results_and_sanitizes_query() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        seen.append((url, headers))
        return (
            b'{"web":{"results":[{"title":"Python",'
            b'"url":"https://www.python.org/","description":"Official site."}]}}'
        )

    provider = BraveSearchProvider(api_key="test-key", transport=transport)

    response = provider.search(
        r"Search C:\Users\Drew\project\secret.txt latest Python release"
    )

    assert response.failure is None
    assert response.results == [
        SearchResult(
            title="Python",
            url="https://www.python.org/",
            snippet="Official site.",
        )
    ]
    assert response.metadata["provider"] == "brave"
    assert seen[0][1]["X-Subscription-Token"] == "test-key"
    query = parse_qs(urlparse(seen[0][0]).query)["q"][0]
    assert query == "Search [LOCAL_PATH] latest Python release"


def test_brave_provider_returns_not_configured_without_api_key() -> None:
    called = False

    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        nonlocal called
        called = True
        return b"{}"

    provider = BraveSearchProvider(api_key="", transport=transport)

    response = provider.search("latest Python release")

    assert called is False
    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "not_configured"


def test_brave_provider_maps_network_error_without_leaking_transport_details() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        raise URLError("private dns details")

    provider = BraveSearchProvider(api_key="test-key", transport=transport)

    response = provider.search("latest Python release")

    assert response.results == []
    assert response.failure is not None
    assert response.failure.kind == "network_error"
    assert response.failure.message == "Brave Search request failed."
```

- [ ] **Step 2: Add web search metadata test**

Append this test to `python/tests/test_web_search.py`:

```python

def test_duckduckgo_provider_records_provider_metadata() -> None:
    def transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
        return b""

    provider = DuckDuckGoHtmlSearchProvider(transport=transport)

    response = provider.search("LangGraph docs")

    assert provider.name == "duckduckgo"
    assert provider.is_configured() is True
    assert response.metadata == {"provider": "duckduckgo"}
```

- [ ] **Step 3: Run provider chain tests and verify expected failures**

Run:

```powershell
python -m pytest python/tests/test_web_provider_chain.py python/tests/test_web_search.py::test_duckduckgo_provider_records_provider_metadata -q
```

Expected: FAIL because provider chain does not exist and `SearchResponse` has no metadata field.

- [ ] **Step 4: Extend `SearchResponse` and DuckDuckGo metadata**

In `python/agent_service/web_search.py`, change imports:

```python
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol
```

Change `SearchResponse`:

```python
@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult]
    failure: SearchFailure | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Add to `DuckDuckGoHtmlSearchProvider`:

```python
    name = "duckduckgo"

    def is_configured(self) -> bool:
        return True
```

In every `SearchResponse(...)` returned by `DuckDuckGoHtmlSearchProvider.search()`, add `metadata={"provider": self.name}`. The three changed return shapes are:

```python
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="privacy_blocked",
                    message="Search query was blocked by privacy guard.",
                    blocked=True,
                    removedCategories=guard.removedCategories,
                ),
                metadata={"provider": self.name},
            )
```

```python
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="timeout",
                    message="Search request timed out.",
                ),
                metadata={"provider": self.name},
            )
```

```python
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="network_error",
                    message="Search request failed.",
                ),
                metadata={"provider": self.name},
            )
```

The successful return becomes:

```python
        return SearchResponse(
            results=parse_duckduckgo_html_results(
                body.decode("utf-8", errors="replace")
            ),
            metadata={"provider": self.name},
        )
```

- [ ] **Step 5: Implement provider chain and Brave provider**

Create `python/agent_service/tool_providers/web_search.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import os
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agent_service.privacy import sanitize_for_web_search
from agent_service.web_search import (
    DuckDuckGoHtmlSearchProvider,
    SearchFailure,
    SearchProvider,
    SearchResponse,
    SearchResult,
)


SearchTransport = Callable[[str, float, dict[str, str]], bytes]


class ChainProvider(Protocol):
    name: str

    def is_configured(self) -> bool:
        ...

    def search(self, query: str) -> SearchResponse:
        ...


class ProviderChainSearchProvider:
    name = "provider_chain"

    def __init__(self, providers: Sequence[SearchProvider]) -> None:
        self.providers = list(providers)

    def is_configured(self) -> bool:
        return any(_provider_is_configured(provider) for provider in self.providers)

    def search(self, query: str) -> SearchResponse:
        attempts: list[dict[str, str]] = []
        last_failure: SearchFailure | None = None

        for provider in self.providers:
            provider_name = _provider_name(provider)
            if not _provider_is_configured(provider):
                attempts.append({"provider": provider_name, "status": "not_configured"})
                continue

            response = provider.search(query)
            if response.results:
                return SearchResponse(
                    results=response.results,
                    failure=response.failure,
                    metadata={
                        **response.metadata,
                        "provider": provider_name,
                        "attempts": [
                            *attempts,
                            {"provider": provider_name, "status": "ok"},
                        ],
                    },
                )

            if response.failure is not None:
                last_failure = response.failure
                attempts.append(
                    {
                        "provider": provider_name,
                        "status": "failed",
                        "kind": response.failure.kind,
                        "message": response.failure.message,
                    }
                )
                continue

            last_failure = SearchFailure(
                kind="no_results",
                message="Search provider returned no results.",
            )
            attempts.append({"provider": provider_name, "status": "no_results"})

        return SearchResponse(
            results=[],
            failure=SearchFailure(
                kind=last_failure.kind if last_failure else "not_configured",
                message=(
                    "所有搜索服务暂时不可用。"
                    if last_failure is not None
                    else "没有可用的搜索服务，请配置搜索提供方。"
                ),
                blocked=last_failure.blocked if last_failure else False,
                removedCategories=(
                    last_failure.removedCategories if last_failure else None
                ),
            ),
            metadata={"provider": self.name, "attempts": attempts},
        )


class BraveSearchProvider:
    name = "brave"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: SearchTransport | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv(
            "ALITA_BRAVE_SEARCH_API_KEY",
            "",
        )
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> SearchResponse:
        if not self.is_configured():
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="not_configured",
                    message="Brave Search API key is not configured.",
                ),
                metadata={"provider": self.name},
            )

        guard = sanitize_for_web_search(query)
        if guard.blocked:
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="privacy_blocked",
                    message="Search query was blocked by privacy guard.",
                    blocked=True,
                    removedCategories=guard.removedCategories,
                ),
                metadata={"provider": self.name},
            )

        url = "https://api.search.brave.com/res/v1/web/search?" + urlencode(
            {"q": guard.sanitizedText}
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "Alita/0.26 web-search-tool",
            "X-Subscription-Token": self.api_key or "",
        }
        try:
            body = self._transport(url, self._timeout, headers)
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except (TimeoutError, socket.timeout):
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="timeout",
                    message="Brave Search request timed out.",
                ),
                metadata={"provider": self.name},
            )
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            return SearchResponse(
                results=[],
                failure=SearchFailure(
                    kind="network_error",
                    message="Brave Search request failed.",
                ),
                metadata={"provider": self.name},
            )

        return SearchResponse(
            results=_brave_results(payload),
            metadata={"provider": self.name},
        )


def default_search_provider() -> SearchProvider:
    provider_name = os.getenv("ALITA_WEB_SEARCH_PROVIDER", "auto").strip().lower()
    brave = BraveSearchProvider(timeout=_timeout_from_env())
    duckduckgo = DuckDuckGoHtmlSearchProvider(timeout=_timeout_from_env())

    if provider_name == "brave":
        return brave
    if provider_name in {"duckduckgo", "ddg"}:
        return duckduckgo
    return ProviderChainSearchProvider([brave, duckduckgo])


def _urllib_transport(url: str, timeout: float, headers: dict[str, str]) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _brave_results(payload: Any) -> list[SearchResult]:
    if not isinstance(payload, dict):
        return []
    web = payload.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
    if not isinstance(results, list):
        return []

    mapped: list[SearchResult] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("description") or item.get("snippet") or "").strip()
        if title and url:
            mapped.append(SearchResult(title=title, url=url, snippet=snippet))
    return mapped


def _provider_name(provider: SearchProvider) -> str:
    return str(getattr(provider, "name", provider.__class__.__name__))


def _provider_is_configured(provider: SearchProvider) -> bool:
    checker = getattr(provider, "is_configured", None)
    if checker is None:
        return True
    return bool(checker())


def _timeout_from_env() -> float:
    raw = os.getenv("ALITA_WEB_SEARCH_TIMEOUT_SECONDS", "8")
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 8.0
```

- [ ] **Step 6: Run provider chain tests**

Run:

```powershell
python -m pytest python/tests/test_web_provider_chain.py python/tests/test_web_search.py::test_duckduckgo_provider_records_provider_metadata -q
```

Expected: PASS.

- [ ] **Step 7: Run full web search tests**

Run:

```powershell
python -m pytest python/tests/test_web_search.py python/tests/test_web_provider_chain.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

Run:

```powershell
git add python/agent_service/web_search.py python/agent_service/tool_providers/web_search.py python/tests/test_web_search.py python/tests/test_web_provider_chain.py
git commit -m "feat: add web search provider chain"
```

---

### Task 6: Use Provider Chain As The Default Search Runtime

**Files:**
- Modify: `python/agent_service/web_research.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_web_research.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add failing default provider tests for simple inquiry**

Append this test to `python/tests/test_web_research.py`:

```python

def test_simple_web_inquiry_uses_default_search_provider_factory(monkeypatch) -> None:
    import agent_service.web_research as web_research

    provider = FakeSearchProvider(
        [
            SearchResponse(
                results=[
                    SearchResult(
                        title="Python docs",
                        url="https://docs.python.org/3/",
                        snippet="Official release information.",
                    )
                ],
                metadata={"provider": "chain"},
            )
        ]
    )
    monkeypatch.setattr(web_research, "default_search_provider", lambda: provider)

    event = web_research.answer_simple_web_inquiry(
        UserMessage(task_id="simple-web", content="What is the latest Python release?"),
        classify_route(
            UserMessage(
                task_id="simple-web",
                content="What is the latest Python release?",
            )
        ),
    )

    assert provider.queries == ["What is the latest Python release?"]
    assert "Python docs" in event.payload["message"]["content"]
```

- [ ] **Step 2: Add failing research executor default provider test**

Append this test to `python/tests/test_execution.py`:

```python

def test_research_flow_executor_uses_default_search_provider_factory(monkeypatch) -> None:
    import agent_service.execution as execution
    from agent_service.execution import ResearchFlowExecutor
    from agent_service.schemas import RunGraph, RunGraphMode, RunGraphRequest, UserMessage
    from agent_service.web_research import build_research_graph
    from agent_service.web_search import SearchResponse, SearchResult

    class Provider:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str) -> SearchResponse:
            self.queries.append(query)
            return SearchResponse(
                results=[
                    SearchResult(
                        title="Python",
                        url="https://www.python.org/",
                        snippet="Official site.",
                    )
                ]
            )

    provider = Provider()
    monkeypatch.setattr(execution, "default_search_provider", lambda: provider)
    message = UserMessage(
        task_id="research",
        content="Compare current Python packaging tools",
    )
    graph = RunGraph(**build_research_graph(message, {}))
    request = RunGraphRequest(
        task_id="research",
        graph=graph,
        project_path="D:/Software Project/Alita/test.alita",
        mode=RunGraphMode(type="full"),
        attachments=[],
    )

    executor = ResearchFlowExecutor(request)

    output = executor.run(
        "research-parallel-search",
        {
            "research-query-plan": execution.NodeOutput(
                values={
                    "sanitizedQuestion": message.content,
                    "queries": [{"query": message.content, "purpose": "primary"}],
                }
            )
        },
    )

    assert provider.queries == ["Compare current Python packaging tools"]
    assert output.values["results"][0]["title"] == "Python"
```

- [ ] **Step 3: Run default provider tests and verify expected failures**

Run:

```powershell
python -m pytest python/tests/test_web_research.py::test_simple_web_inquiry_uses_default_search_provider_factory python/tests/test_execution.py::test_research_flow_executor_uses_default_search_provider_factory -q
```

Expected: FAIL because `web_research` and `execution` still instantiate `DuckDuckGoHtmlSearchProvider()` directly.

- [ ] **Step 4: Update simple inquiry default provider**

In `python/agent_service/web_research.py`, replace the DuckDuckGo import:

```python
from agent_service.web_search import (
    SearchFailure,
    SearchProvider,
    SearchResult,
    classify_sources,
    rank_sources,
)
```

Add:

```python
from agent_service.tool_providers.web_search import default_search_provider
```

Change:

```python
    provider = search_provider or DuckDuckGoHtmlSearchProvider()
```

to:

```python
    provider = search_provider or default_search_provider()
```

- [ ] **Step 5: Update research executor default provider**

In `python/agent_service/execution.py`, replace the DuckDuckGo import from `agent_service.web_search`:

```python
from agent_service.web_search import (
    SearchFailure,
    SearchProvider,
    SearchResponse,
    SearchResult,
    classify_sources,
    rank_sources,
)
```

Add:

```python
from agent_service.tool_providers.web_search import default_search_provider
```

Change `ResearchFlowExecutor.__init__()`:

```python
        self.search_provider = search_provider or default_search_provider()
```

- [ ] **Step 6: Run targeted default provider tests**

Run:

```powershell
python -m pytest python/tests/test_web_research.py::test_simple_web_inquiry_uses_default_search_provider_factory python/tests/test_execution.py::test_research_flow_executor_uses_default_search_provider_factory -q
```

Expected: PASS.

- [ ] **Step 7: Run full affected test modules**

Run:

```powershell
python -m pytest python/tests/test_web_research.py python/tests/test_execution.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 6**

Run:

```powershell
git add python/agent_service/web_research.py python/agent_service/execution.py python/tests/test_web_research.py python/tests/test_execution.py
git commit -m "feat: use default web search provider chain"
```

---

### Task 7: Final Regression And Manual Weather Smoke Test

**Files:**
- No new files.
- Verify: Python test suite and one live Open-Meteo smoke test.

- [ ] **Step 1: Run all targeted web tool tests**

Run:

```powershell
python -m pytest python/tests/test_tool_result.py python/tests/test_tool_router.py python/tests/test_weather_provider.py python/tests/test_web_provider_chain.py python/tests/test_web_search.py python/tests/test_web_research.py python/tests/test_graph.py python/tests/test_agent_routing_integration.py python/tests/test_execution.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full Python test suite**

Run:

```powershell
python -m pytest python/tests -q
```

Expected: PASS.

- [ ] **Step 3: Run a live weather smoke test**

Run:

```powershell
@'
from agent_service.graph import run_agent
from agent_service.schemas import UserMessage

events = run_agent(UserMessage(task_id="smoke-weather", content="今天上海天气怎么样？"))
for event in events:
    print(event.type)
    print(event.payload.get("message", {}).get("content", ""))
'@ | python -
```

Expected:

```text
message.created
上海当前天气：
```

The exact condition and temperature will vary with Open-Meteo's current data.

- [ ] **Step 4: Run a provider-chain fallback smoke test without API keys**

Run:

```powershell
@'
from agent_service.tool_providers.web_search import default_search_provider, ProviderChainSearchProvider

provider = default_search_provider()
print(type(provider).__name__)
if isinstance(provider, ProviderChainSearchProvider):
    print([getattr(item, "name", type(item).__name__) for item in provider.providers])
'@ | python -
```

Expected:

```text
ProviderChainSearchProvider
['brave', 'duckduckgo']
```

- [ ] **Step 5: Check git status**

Run:

```powershell
git status --short
```

Expected: no uncommitted files created by this task. If test caches appear, remove only generated cache directories that are inside this worktree and then re-run `git status --short`.

---

## Self-Review

- Spec coverage:
  - Weather questions bypass generic search through `route_tool_for_message()` and `OpenMeteoWeatherProvider`.
  - Provider chain supports optional Brave Search and DuckDuckGo fallback.
  - Privacy guard is used before weather location queries and Brave search queries.
  - LangGraph remains the broad router; the new tool router sits under `web_simple_inquiry`.
  - Research executor default search provider changes to the same provider chain.
  - Failure messages are stable and user-facing strings do not expose transport exception details.
  - Fetch/scrape and browser automation are intentionally split from this Phase 1 plan.
- Placeholder scan: passed.
- Type consistency:
  - `WeatherProvider.current()` and `WeatherProvider.forecast()` both return `ToolResult`.
  - `answer_simple_web_inquiry()` accepts `weather_provider: WeatherProvider | None`.
  - `run_agent()`, `stream_agent_events()`, `build_graph()`, and `answer_with_web()` use the same optional `weather_provider` parameter name.
  - `SearchResponse.metadata` is present across DuckDuckGo, Brave, and provider-chain returns.
- Verification commands:
  - Targeted test command is listed in Task 7 Step 1.
  - Full Python suite command is listed in Task 7 Step 2.
  - Live Open-Meteo smoke test is listed in Task 7 Step 3.
