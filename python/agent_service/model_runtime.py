from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from agent_service.model_client import ChatMessage, LlamaCppModelClient
from agent_service.model_policy import ModelCallPolicy, NODE_REASONING_POLICY
from agent_service.node_output import NodeOutput
from agent_service.prompt_templates import render_prompt_template
from agent_service.runtime_events import utc_now_iso
from agent_service.runtime_trace import RuntimeSpan, next_span_id, trace_id_for_run
from agent_service.task_graph import ModelBinding


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        pass


class ModelRuntimeError(ValueError):
    pass


TraceSpanSink = Callable[[RuntimeSpan], None]


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
        trace_span_sink: TraceSpanSink | None = None,
    ) -> None:
        self.model_client = model_client or LlamaCppModelClient()
        self.supported_models = supported_models or SupportedModelRegistry.default()
        self.trace_span_sink = trace_span_sink
        self._span_counter = 0

    def run(
        self,
        binding: ModelBinding,
        *,
        inputs: dict[str, NodeOutput],
        run_id: str | None = None,
        node_id: str | None = None,
    ) -> NodeOutput:
        if not self.supported_models.supports(binding.model_ref):
            raise ModelRuntimeError(f"unsupported model ref: {binding.model_ref}")

        values: dict[str, str] = {}
        for output in inputs.values():
            values.update(output.values)

        messages = render_prompt_template(binding.prompt_template, values)
        started_at = utc_now_iso()
        start = perf_counter()
        try:
            content = self.model_client.chat(
                messages,
                temperature=binding.temperature,
                max_tokens=binding.max_tokens,
                policy=NODE_REASONING_POLICY,
            )
        except Exception as error:
            self._record_model_span(
                binding=binding,
                run_id=run_id,
                node_id=node_id,
                status="error",
                started_at=started_at,
                duration_ms=int((perf_counter() - start) * 1000),
                error_code=type(error).__name__,
            )
            raise
        self._record_model_span(
            binding=binding,
            run_id=run_id,
            node_id=node_id,
            status="ok",
            started_at=started_at,
            duration_ms=int((perf_counter() - start) * 1000),
            error_code=None,
        )
        return NodeOutput(values={binding.output_key: content})

    def _record_model_span(
        self,
        *,
        binding: ModelBinding,
        run_id: str | None,
        node_id: str | None,
        status: str,
        started_at: str,
        duration_ms: int,
        error_code: str | None,
    ) -> None:
        if self.trace_span_sink is None or run_id is None:
            return
        self._span_counter += 1
        self.trace_span_sink(
            RuntimeSpan(
                trace_id=trace_id_for_run(run_id),
                span_id=next_span_id(self._span_counter),
                parent_span_id=None,
                run_id=run_id,
                node_id=node_id,
                kind="model.call",
                name=binding.model_ref,
                status=status,
                started_at=started_at,
                ended_at=utc_now_iso(),
                duration_ms=duration_ms,
                metadata={
                    "modelRef": binding.model_ref,
                    "purpose": binding.purpose,
                    "promptTemplate": binding.prompt_template,
                    "outputKey": binding.output_key,
                    "policyProfile": NODE_REASONING_POLICY.profile.value,
                    "temperature": binding.temperature,
                    "maxTokens": binding.max_tokens,
                    "errorCode": error_code,
                },
            )
        )
