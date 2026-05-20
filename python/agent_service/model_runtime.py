from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_service.model_client import ChatMessage, LlamaCppModelClient
from agent_service.node_output import NodeOutput
from agent_service.prompt_templates import render_prompt_template
from agent_service.task_graph import ModelBinding


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        pass


class ModelRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class SupportedModelRegistry:
    model_refs: frozenset[str]

    @classmethod
    def default(cls) -> "SupportedModelRegistry":
        return cls(
            model_refs=frozenset(
                {
                    "local.content_organizer",
                    "local.report_writer",
                }
            )
        )

    def supports(self, model_ref: str) -> bool:
        return model_ref in self.model_refs


class ModelRuntime:
    def __init__(
        self,
        model_client: ModelClient | None = None,
        supported_models: SupportedModelRegistry | None = None,
    ) -> None:
        self.model_client = model_client or LlamaCppModelClient()
        self.supported_models = supported_models or SupportedModelRegistry.default()

    def run(self, binding: ModelBinding, *, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if not self.supported_models.supports(binding.model_ref):
            raise ModelRuntimeError(f"unsupported model ref: {binding.model_ref}")

        values: dict[str, str] = {}
        for output in inputs.values():
            values.update(output.values)

        messages = render_prompt_template(binding.prompt_template, values)
        content = self.model_client.chat(
            messages,
            temperature=binding.temperature,
            max_tokens=binding.max_tokens,
        )
        return NodeOutput(values={binding.output_key: content})
