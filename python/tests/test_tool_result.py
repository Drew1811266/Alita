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
    )

    assert result.to_payload() == {
        "toolName": "weather.current",
        "status": "ok",
        "data": {},
        "sources": [],
        "failure": None,
        "metadata": {},
    }


def test_tool_result_payload_isolated_from_mutable_inputs_and_outputs() -> None:
    data = {"nested": {"temperatureC": 22.5}}
    sources = [{"title": "Open-Meteo", "metadata": {"provider": "open_meteo"}}]
    metadata = {"attempts": [{"provider": "open_meteo"}]}
    result = ToolResult(
        tool_name="weather.current",
        status="ok",
        data=data,
        sources=sources,
        metadata=metadata,
    )

    data["nested"]["temperatureC"] = 99
    sources[0]["metadata"]["provider"] = "mutated"
    metadata["attempts"][0]["provider"] = "mutated"

    payload = result.to_payload()
    assert payload["data"]["nested"]["temperatureC"] == 22.5
    assert payload["sources"][0]["metadata"]["provider"] == "open_meteo"
    assert payload["metadata"]["attempts"][0]["provider"] == "open_meteo"

    payload["data"]["nested"]["temperatureC"] = 100
    payload["sources"][0]["metadata"]["provider"] = "payload-mutated"
    payload["metadata"]["attempts"][0]["provider"] = "payload-mutated"

    second_payload = result.to_payload()
    assert second_payload["data"]["nested"]["temperatureC"] == 22.5
    assert second_payload["sources"][0]["metadata"]["provider"] == "open_meteo"
    assert second_payload["metadata"]["attempts"][0]["provider"] == "open_meteo"
