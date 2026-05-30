from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

from agent_service.schemas import UserMessage


ToolRouteStatus = Literal["ready", "missing_input"]
ToolName = Literal["weather.current", "weather.forecast"]


@dataclass(frozen=True)
class ToolRoute:
    tool_name: ToolName
    status: ToolRouteStatus
    arguments: dict[str, str] = field(default_factory=dict)
    missing_inputs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", dict(self.arguments))
        object.__setattr__(self, "missing_inputs", list(self.missing_inputs))


def route_tool_for_message(message: UserMessage) -> ToolRoute | None:
    content = message.content.strip()
    if not content:
        return None
    if _is_chinese_non_weather_temperature_query(content):
        return None

    location = _extract_location(content)
    if _is_english_content(content):
        if not location:
            if _has_english_location_candidate(content):
                return None
            if not _is_english_direct_weather_question(content):
                return None
    else:
        if not _is_weather_question(content):
            return None
        if (
            location
            and _is_chinese_temperature_only_question(content)
            and not _is_allowed_chinese_temperature_location(location)
        ):
            return None

    tool_name: ToolName = (
        "weather.forecast"
        if _contains_any(content, _FORECAST_MARKERS)
        else "weather.current"
    )
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


def _is_weather_question(content: str) -> bool:
    if not _contains_any(content, _WEATHER_MARKERS):
        return False
    return _contains_any(content, _TIME_MARKERS) or _contains_any(
        content,
        _QUESTION_MARKERS,
    )


def _extract_location(content: str) -> str | None:
    normalized = content.strip()
    for pattern in _CHINESE_LOCATION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return _clean_location(match.group("location"))

    for pattern in _ENGLISH_LOCATION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return _clean_location(match.group("location"))

    return None


def _has_english_location_candidate(content: str) -> bool:
    normalized = content.strip()
    return any(pattern.search(normalized) for pattern in _ENGLISH_LOCATION_PATTERNS)


def _clean_location(location: str) -> str | None:
    cleaned = location.strip(" \t\r\n,，.。?？!！")
    cleaned = _strip_trailing_english_modifier_phrases(cleaned)
    cleaned = _strip_trailing_english_time_tokens(cleaned)
    if (
        not cleaned
        or cleaned in _TIME_MARKERS
        or cleaned in _LOCATION_STOPWORDS
        or any(verb in cleaned for verb in _REQUEST_VERB_STOPWORDS)
        or _is_rejected_english_location(cleaned)
    ):
        return None
    return cleaned


def _is_english_content(content: str) -> bool:
    return re.search(r"[\u4e00-\u9fff]", content) is None


def _is_chinese_non_weather_temperature_query(content: str) -> bool:
    return _contains_any(content, _CHINESE_TEMPERATURE_MARKERS) and _contains_any(
        content,
        _CHINESE_NON_WEATHER_TEMPERATURE_TERMS,
    )


def _is_chinese_temperature_only_question(content: str) -> bool:
    return _contains_any(content, _CHINESE_TEMPERATURE_MARKERS) and not _contains_any(
        content,
        _CHINESE_EXPLICIT_WEATHER_MARKERS,
    )


def _is_allowed_chinese_temperature_location(location: str) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", location):
        return False
    return not _contains_any(location, _CHINESE_NON_LOCATION_TEMPERATURE_TERMS)


def _is_english_direct_weather_question(content: str) -> bool:
    if _contains_any(content, _ENGLISH_GENERIC_QUERY_MARKERS):
        return False

    normalized = content.lower()
    return any(
        re.search(pattern, normalized) is not None
        for pattern in _ENGLISH_DIRECT_WEATHER_PATTERNS
    )


def _is_rejected_english_location(location: str) -> bool:
    normalized = location.lower()
    if normalized.startswith(("a ", "an ", "the ")):
        return True
    if " " in location and "," not in location and location == normalized:
        return True
    return any(
        _contains_keyword(normalized, blocked)
        for blocked in _ENGLISH_NON_LOCATION_TERMS
    )


def _strip_trailing_english_modifier_phrases(location: str) -> str:
    cleaned = location
    for pattern in _ENGLISH_TRAILING_MODIFIER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _strip_trailing_english_time_tokens(location: str) -> str:
    tokens = location.split()
    while tokens and tokens[-1].lower() in _ENGLISH_TRAILING_TIME_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _contains_any(content: str, keywords: list[str]) -> bool:
    normalized = content.lower()
    return any(_contains_keyword(normalized, keyword.lower()) for keyword in keywords)


def _contains_keyword(normalized_content: str, normalized_keyword: str) -> bool:
    if normalized_keyword.isascii() and any(
        character.isalpha() for character in normalized_keyword
    ):
        pattern = rf"(?<![a-z0-9_]){re.escape(normalized_keyword)}(?![a-z0-9_])"
        return re.search(pattern, normalized_content) is not None
    return normalized_keyword in normalized_content


_WEATHER_MARKERS = [
    "天气",
    "气温",
    "温度",
    "多少度",
    "几度",
    "下雨",
    "降雨",
    "会不会下雨",
    "会不会降雨",
    "下雪",
    "降雪",
    "会不会下雪",
    "会不会降雪",
    "weather",
    "temperature",
    "rain",
    "raining",
    "snow",
]

_TIME_MARKERS = [
    "现在",
    "当前",
    "今天",
    "今晚",
    "明天",
    "后天",
    "本周",
    "today",
    "tonight",
    "now",
    "current",
    "currently",
    "tomorrow",
    "forecast",
]

_FORECAST_MARKERS = [
    "明天",
    "后天",
    "预报",
    "会不会下雨",
    "会不会降雨",
    "会不会下雪",
    "会不会降雪",
    "会下雨",
    "会降雨",
    "会下雪",
    "会降雪",
    "tomorrow",
    "forecast",
    "will it rain",
    "will it snow",
    "will rain",
    "will snow",
    "this afternoon",
    "this evening",
    "this morning",
    "this weekend",
]

_QUESTION_MARKERS = [
    "?",
    "？",
    "吗",
    "么",
    "多少",
    "几",
    "怎么样",
    "what",
    "how",
    "will",
    "is it",
]

_CHINESE_TIME_PATTERN = r"(?:现在|当前|今天|今晚|明天|后天|本周)"
_CHINESE_WEATHER_PATTERN = (
    r"(?:会不会下雨|会不会降雨|会不会下雪|会不会降雪|"
    r"会下雨|会降雨|会下雪|会降雪|"
    r"天气|气温|温度|多少度|几度|下雨|降雨|下雪|降雪)"
)
_CHINESE_LOCATION = r"(?P<location>[\u4e00-\u9fff]{2,12}?)"
_CHINESE_REQUEST_PREFIX_PATTERN = (
    r"(?:(?:麻烦帮我查一下|帮我查一下|帮我看一下|请查一下|"
    r"我想知道|想知道|我想查询|我想查一下|我想查|"
    r"告诉我|查一下|看一下|请问|麻烦|帮我|请)\s*)?"
)

_CHINESE_LOCATION_PATTERNS = [
    re.compile(
        rf"(?:^|[，,。！？\s]){_CHINESE_REQUEST_PREFIX_PATTERN}"
        rf"{_CHINESE_TIME_PATTERN}"
        rf"{_CHINESE_LOCATION}"
        rf"(?:市|省|县|区)?(?:的)?"
        rf"{_CHINESE_WEATHER_PATTERN}"
    ),
    re.compile(
        rf"(?:^|[，,。！？\s]){_CHINESE_REQUEST_PREFIX_PATTERN}"
        rf"{_CHINESE_LOCATION}"
        rf"(?:市|省|县|区)?(?:的)?"
        rf"{_CHINESE_TIME_PATTERN}(?:的)?"
        rf"{_CHINESE_WEATHER_PATTERN}"
    ),
    re.compile(
        rf"(?:^|[，,。！？\s]){_CHINESE_REQUEST_PREFIX_PATTERN}"
        rf"{_CHINESE_LOCATION}"
        rf"(?:市|省|县|区)?(?:的)?"
        rf"{_CHINESE_WEATHER_PATTERN}"
    ),
]

_ENGLISH_LOCATION_PATTERNS = [
    re.compile(
        r"\b(?:what(?:'s| is)|how(?:'s| is))\s+the\s+weather\s+"
        r"(?:in|for|at)\s+"
        r"(?P<location>[A-Za-z][A-Za-z .'-]{1,60}?)"
        r"(?=\s+(?:right\s+now|today|tonight|tomorrow|now|currently)\b|[?.!]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bweather\s+like\s+"
        r"(?:in|for|at)\s+"
        r"(?P<location>[A-Za-z][A-Za-z .'-]{1,60})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:weather|rain|snow)\s+forecast\s+"
        r"(?:in|for|at)\s+"
        r"(?P<location>[A-Za-z][A-Za-z .'-]{1,60})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:weather|rain|snow)\s+"
        r"(?:in|for|at)\s+"
        r"(?P<location>[A-Za-z][A-Za-z .'-]{1,60}?)\s+"
        r"(?:today|tonight|tomorrow|now|currently)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwill it (?:rain|snow)\s+"
        r"(?:in|at)\s+"
        r"(?P<location>[A-Za-z][A-Za-z .'-]{1,60})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bin\s+(?P<location>[A-Za-z][A-Za-z .'-]{1,60})\s+"
        r"(?:today|tonight|tomorrow|now|currently)?\s*"
        r"(?:weather|temperature|forecast|rain|snow)",
        re.IGNORECASE,
    ),
]

_ENGLISH_TRAILING_TIME_TOKENS = {
    "today",
    "tonight",
    "tomorrow",
    "now",
    "currently",
}

_ENGLISH_TRAILING_MODIFIER_PATTERNS = [
    r"\s+in\s+(?:fahrenheit|celsius)$",
    r"\s+right\s+now$",
    r"\s+this\s+(?:afternoon|evening|morning|weekend)$",
]

_ENGLISH_DIRECT_WEATHER_PATTERNS = [
    r"\b(?:what(?:'s| is)|how(?:'s| is))\s+the\s+weather\b",
    r"\b(?:today's|tomorrow's|tonight's|current)\s+weather\b",
    r"\bweather\s+(?:today|tomorrow|tonight|now|currently)\b",
    r"\bwill it (?:rain|snow)\b",
    r"\bis it (?:raining|snowing)\b",
]

_ENGLISH_GENERIC_QUERY_MARKERS = [
    "compare",
    "comparison",
    "model",
    "models",
    "gpu",
    "gpus",
    "revenue",
    "release",
]

_ENGLISH_NON_LOCATION_TERMS = {
    "cpu",
    "cpus",
    "gpu",
    "gpus",
    "model",
    "models",
    "revenue",
    "spanish",
    "french",
    "german",
    "sentence",
    "minecraft",
    "gatsby",
    "literature",
    "grammar",
    "language",
    "meaning",
    "pod",
    "pods",
    "starter",
    "refrigerator",
}

_CHINESE_TEMPERATURE_MARKERS = [
    "当前温度",
    "现在温度",
    "温度",
    "多少度",
    "几度",
]

_CHINESE_NON_WEATHER_TEMPERATURE_TERMS = [
    "显卡",
    "gpu",
    "cpu",
    "处理器",
    "烤箱",
    "冰箱",
    "发酵",
    "面团",
    "咖啡",
    "冲泡",
    "水温",
    "股票",
    "市场",
]

_CHINESE_EXPLICIT_WEATHER_MARKERS = [
    "天气",
    "气温",
    "下雨",
    "降雨",
    "会不会下雨",
    "会不会降雨",
    "下雪",
    "降雪",
    "会不会下雪",
    "会不会降雪",
]

_CHINESE_NON_LOCATION_TEMPERATURE_TERMS = [
    "温",
    "水温",
    "咖啡",
    "冲泡",
    "股票",
    "市场",
    "发酵",
    "面团",
    "显卡",
    "处理器",
    "烤箱",
    "冰箱",
]

_LOCATION_STOPWORDS = {
    "今天",
    "今晚",
    "明天",
    "后天",
    "现在",
    "当前",
    "天气",
    "气温",
    "温度",
    "显卡",
    "GPU",
    "CPU",
    "处理器",
    "烤箱",
    "冰箱",
    "发酵",
    "面团",
    "咖啡",
    "冲泡",
    "水温",
    "股票",
    "市场",
}

_REQUEST_VERB_STOPWORDS = {
    "请",
    "请问",
    "请查一下",
    "查一下",
    "看一下",
    "我想知道",
    "想知道",
    "我想查询",
    "我想查一下",
    "我想查",
    "告诉我",
    "帮我",
    "帮我查一下",
    "帮我看一下",
    "麻烦",
    "麻烦帮我查一下",
}
