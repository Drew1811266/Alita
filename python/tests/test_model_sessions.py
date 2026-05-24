from __future__ import annotations

import pytest

from agent_service.model_sessions import ModelSessionRegistry
from agent_service.schemas import AgentModelConfig


def test_model_session_registry_consumes_registered_config_once() -> None:
    registry = ModelSessionRegistry()
    config = AgentModelConfig(
        mode="api",
        provider_id="provider-1",
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1",
        api_key="sk-test",
    )

    session_id = registry.register(config)

    assert registry.consume(session_id) == config
    assert registry.consume(session_id) is None


def test_model_session_registry_rejects_empty_session_id() -> None:
    registry = ModelSessionRegistry()

    with pytest.raises(ValueError, match="model session id is required"):
        registry.consume("")
