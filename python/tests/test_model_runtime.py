from __future__ import annotations

import pytest

from agent_service.model_client import ChatMessage
from agent_service.model_runtime import (
    ModelRuntime,
    ModelRuntimeError,
    SupportedModelRegistry,
)
from agent_service.node_output import NodeOutput
from agent_service.task_graph import ModelBinding


class FakeModelClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.messages: list[list[ChatMessage]] = []
        self.temperatures: list[float] = []
        self.max_tokens: list[int] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        self.messages.append(messages)
        self.temperatures.append(temperature)
        self.max_tokens.append(max_tokens)
        return self.reply


def test_model_runtime_runs_content_organizer_binding() -> None:
    model_client = FakeModelClient("outline text")
    runtime = ModelRuntime(model_client=model_client)
    binding = ModelBinding(
        model_ref="local.content_organizer",
        purpose="organize_document_content",
        prompt_template="document.content_organizer.zh.v1",
        output_key="outline",
        max_tokens=1024,
    )

    output = runtime.run(
        binding,
        inputs={"document-parse": NodeOutput(values={"text": "document body"})},
    )

    assert output == NodeOutput(values={"outline": "outline text"})
    assert model_client.messages[0][1] == ChatMessage(
        role="user",
        content="document body",
    )
    assert model_client.temperatures == [0.2]
    assert model_client.max_tokens == [1024]


def test_model_runtime_runs_report_writer_with_custom_token_limit() -> None:
    model_client = FakeModelClient("report text")
    runtime = ModelRuntime(model_client=model_client)
    binding = ModelBinding(
        model_ref="local.report_writer",
        purpose="write_document_report",
        prompt_template="document.report_writer.zh.v1",
        output_key="report",
        max_tokens=1536,
    )

    output = runtime.run(
        binding,
        inputs={"document-parse": NodeOutput(values={"text": "document body"})},
    )

    assert output == NodeOutput(values={"report": "report text"})
    assert model_client.max_tokens == [1536]


def test_model_runtime_rejects_unsupported_model_ref() -> None:
    model_client = FakeModelClient("unused")
    runtime = ModelRuntime(model_client=model_client)
    binding = ModelBinding(
        model_ref="remote.unsupported",
        purpose="organize_document_content",
        prompt_template="document.content_organizer.zh.v1",
        output_key="outline",
    )

    with pytest.raises(ModelRuntimeError, match="unsupported model ref"):
        runtime.run(
            binding,
            inputs={"document-parse": NodeOutput(values={"text": "document body"})},
        )

    assert model_client.messages == []


def test_supported_model_registry_knows_document_models() -> None:
    registry = SupportedModelRegistry.default()

    assert registry.supports("local.content_organizer")
    assert registry.supports("local.report_writer")
    assert not registry.supports("remote.unsupported")
