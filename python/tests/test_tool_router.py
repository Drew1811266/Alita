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


def test_business_forecast_question_does_not_route_to_weather() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is the revenue forecast for Apple?")
    )

    assert route is None


def test_polite_chinese_weather_prompt_extracts_city_only() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="请查一下今天上海天气")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "ready"
    assert route.arguments == {"location": "上海"}


def test_chinese_will_it_rain_prompt_extracts_city_only() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="今天上海会不会下雨？")
    )

    assert route is not None
    assert route.tool_name == "weather.forecast"
    assert route.arguments == {"location": "上海"}


def test_english_weather_prompt_strips_trailing_time_word() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="weather in San Francisco today")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.arguments == {"location": "San Francisco"}


def test_english_rain_forecast_prompt_strips_trailing_time_word() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="rain forecast for Seattle tomorrow")
    )

    assert route is not None
    assert route.tool_name == "weather.forecast"
    assert route.arguments == {"location": "Seattle"}


def test_polite_chinese_weather_prompt_without_location_requests_location() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="请查一下今天的天气")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "missing_input"
    assert route.missing_inputs == ["location"]
    assert route.arguments == {}


def test_temperature_forecast_for_non_location_entity_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(
            task_id="web",
            content="What is the temperature forecast for Nvidia GPUs?",
        )
    )

    assert route is None


def test_generic_snow_forecast_models_query_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="Compare snow forecast models")
    )

    assert route is None


def test_cpu_operating_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(
            task_id="web",
            content="What is the current safe operating temperature for Ryzen CPUs?",
        )
    )

    assert route is None


def test_sourdough_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(
            task_id="web",
            content="What is the current ideal temperature for sourdough starter?",
        )
    )

    assert route is None


def test_chinese_gpu_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="显卡当前温度多少正常？")
    )

    assert route is None


def test_english_weather_like_prompt_extracts_location() -> None:
    route = route_tool_for_message(
        UserMessage(
            task_id="weather",
            content="What is the weather like in San Francisco?",
        )
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "ready"
    assert route.arguments == {"location": "San Francisco"}


def test_english_will_it_snow_prompt_routes_forecast() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="Will it snow in Boston?")
    )

    assert route is not None
    assert route.tool_name == "weather.forecast"
    assert route.status == "ready"
    assert route.arguments == {"location": "Boston"}


def test_rain_literature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What does rain in literature symbolize?")
    )

    assert route is None


def test_weather_grammar_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is weather in a sentence?")
    )

    assert route is None


def test_minecraft_weather_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="How does weather in Minecraft work?")
    )

    assert route is None


def test_chinese_coffee_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="今天咖啡冲泡温度多少合适？")
    )

    assert route is None


def test_chinese_water_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="今天水温多少度适合游泳？")
    )

    assert route is None


def test_chinese_stock_market_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="今天股票市场温度如何？")
    )

    assert route is None


def test_refrigerator_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(
            task_id="web",
            content="What is the ideal temperature in a refrigerator?",
        )
    )

    assert route is None


def test_kubernetes_temperature_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="temperature in Kubernetes pods")
    )

    assert route is None


def test_sourdough_temperature_in_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(
            task_id="web",
            content="What temperature in sourdough starter is ideal?",
        )
    )

    assert route is None


def test_english_direct_weather_in_city_prompt_extracts_location() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="What is the weather in New York?")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "ready"
    assert route.arguments == {"location": "New York"}


def test_weather_in_spanish_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is the weather in Spanish?")
    )

    assert route is None


def test_weather_in_sentence_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is the weather in a sentence?")
    )

    assert route is None


def test_weather_in_minecraft_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="weather in Minecraft today")
    )

    assert route is None


def test_weather_in_literary_title_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is the weather in The Great Gatsby?")
    )

    assert route is None


def test_weather_in_french_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is the weather in French?")
    )

    assert route is None


def test_weather_in_german_question_does_not_route() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="web", content="What is the weather in German?")
    )

    assert route is None


def test_weather_in_fahrenheit_strips_unit_modifier() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="What's the weather in Paris in Fahrenheit?")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "ready"
    assert route.arguments == {"location": "Paris"}


def test_weather_right_now_strips_time_modifier() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="What's the weather in New York right now?")
    )

    assert route is not None
    assert route.tool_name == "weather.current"
    assert route.status == "ready"
    assert route.arguments == {"location": "New York"}


def test_will_it_rain_this_afternoon_strips_time_modifier_and_routes_forecast() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="Will it rain in Boston this afternoon?")
    )

    assert route is not None
    assert route.tool_name == "weather.forecast"
    assert route.status == "ready"
    assert route.arguments == {"location": "Boston"}


def test_weather_this_weekend_strips_time_modifier_and_routes_forecast() -> None:
    route = route_tool_for_message(
        UserMessage(task_id="weather", content="What's the weather in Paris this weekend?")
    )

    assert route is not None
    assert route.tool_name == "weather.forecast"
    assert route.status == "ready"
    assert route.arguments == {"location": "Paris"}
