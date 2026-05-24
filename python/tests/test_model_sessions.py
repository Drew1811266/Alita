from __future__ import annotations

import pytest

from agent_service.model_sessions import ModelSessionRegistry
from agent_service.schemas import AgentModelConfig


class MutableClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def set(self, now: float) -> None:
        self.now = now


def model_config(api_key: str = "sk-test") -> AgentModelConfig:
    return AgentModelConfig(
        mode="api",
        provider_id="provider-1",
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1",
        api_key=api_key,
    )


def test_model_session_registry_consumes_registered_config_once() -> None:
    registry = ModelSessionRegistry()
    config = model_config()

    session_id = registry.register(config)

    assert registry.consume(session_id) == config
    assert registry.consume(session_id) is None


def test_model_session_registry_rejects_empty_session_id() -> None:
    registry = ModelSessionRegistry()

    with pytest.raises(ValueError, match="model session id is required"):
        registry.consume("")


def test_model_session_registry_does_not_return_expired_config() -> None:
    clock = MutableClock()
    registry = ModelSessionRegistry(ttl_seconds=10, clock=clock)
    session_id = registry.register(model_config())

    clock.advance(11)

    assert registry.consume(session_id) is None


def test_model_session_registry_register_purges_abandoned_expired_entries() -> None:
    clock = MutableClock()
    registry = ModelSessionRegistry(ttl_seconds=10, clock=clock)
    expired_config = model_config(api_key="sk-expired")
    active_config = model_config(api_key="sk-active")
    expired_session_id = registry.register(expired_config)

    clock.advance(11)
    active_session_id = registry.register(active_config)

    # Move the injected clock back so consume cannot be the operation that
    # expires the old session; register must have purged it already.
    clock.set(0)

    assert registry.consume(expired_session_id) is None
    assert registry.consume(active_session_id) == active_config
