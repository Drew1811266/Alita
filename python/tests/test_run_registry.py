from agent_service.run_registry import RunRegistry


def test_registers_and_cancels_run() -> None:
    registry = RunRegistry()

    token = registry.start("run-1")
    assert token.cancelled is False

    assert registry.cancel("run-1") is True
    assert token.cancelled is True
    assert registry.cancel("missing") is False
