from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from agent_service.deep_agent_models import (
    PlanDraft,
    PlanStep,
    PlanReview,
    ReasoningDecision,
    ThinkingStatus,
)
from agent_service.model_client import (
    ChatDiagnosticsResponse,
    ChatMessage,
    ModelRuntimeDisabled,
    ModelRuntimeRequestFailed,
)
from agent_service.model_policy import DEEP_REASONING_POLICY, ModelCallPolicy
from agent_service.node_catalog import NodeCatalogBuilder, NodeCatalogSnapshot
from agent_service.node_catalog_resolver import (
    NodeCatalogResolutionError,
    NodeCatalogResolver,
)
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry


LOCAL_PATH_MARKER = "[local_path_removed]"
_LOCAL_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z])(?P<windows>[A-Za-z]:\\(?:[^\\\r\n\"'<>|:*?]+\\)+[^\\\r\n\"'<>|:*?]+"
    r"\.[A-Za-z0-9]{1,16})|"
    r"(?<![A-Za-z])(?P<windows_forward>[A-Za-z]:/(?:[^/\r\n\"'<>|:*?]+/)+[^/\r\n\"'<>|:*?]+"
    r"\.[A-Za-z0-9]{1,16})|"
    r"(?P<unix>/(?:Users|home|tmp)/(?:[^/\r\n\"'<>|:*?]+/)*[^/\r\n\"'<>|:*?]+"
    r"\.[A-Za-z0-9]{1,16})|"
    r"(?P<home>~/(?:[^/\r\n\"'<>|:*?]+/)*[^/\r\n\"'<>|:*?]+"
    r"\.[A-Za-z0-9]{1,16})|"
    r"(?P<unc>\\\\(?:[^\\\r\n\"'<>|:*?]+\\)+[^\\\r\n\"'<>|:*?]+"
    r"\.[A-Za-z0-9]{1,16})"
)
_LOCAL_PATH_TO_END_PATTERN = re.compile(
    r"(?<![A-Za-z])(?P<windows>[A-Za-z]:[\\/][^\r\n\"'<>|]*)|"
    r"(?P<unix>/(?:Users|home|tmp)/[^\r\n\"'<>|:*?]*)|"
    r"(?P<home>~/[^\r\n\"'<>|:*?]*)|"
    r"(?P<unc>\\\\[^\r\n\"'<>|:*?]*)"
)


class DeepPlanningError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class DeepPlanningModel(Protocol):
    def chat_with_diagnostics(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> ChatDiagnosticsResponse:
        ...


class ReasoningGateEngine:
    def __init__(self, model_client: DeepPlanningModel) -> None:
        self._model_client = model_client

    def decide(
        self,
        message: UserMessage,
        *,
        context_bundle: dict[str, Any],
    ) -> ReasoningDecision:
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are the deep agent reasoning gate. Return strict JSON only. "
                    "Do not include markdown, prose, comments, or code fences."
                ),
            ),
            ChatMessage(
                role="user",
                content=_reasoning_prompt(message, context_bundle=context_bundle),
            ),
        ]

        try:
            response = self._model_client.chat_with_diagnostics(
                messages,
                policy=DEEP_REASONING_POLICY,
            )
        except (ModelRuntimeDisabled, ModelRuntimeRequestFailed) as error:
            raise DeepPlanningError("reasoning_unavailable", str(error)) from error

        try:
            payload = json.loads(response.content)
            return ReasoningDecision.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise DeepPlanningError(
                "invalid_reasoning_json",
                "Reasoning gate returned malformed or schema-invalid JSON.",
            ) from error


@dataclass(frozen=True)
class DeepPlanningResult:
    plan_draft: PlanDraft
    thinking_status: ThinkingStatus
    raw_response: str


class DeepPlanningEngine:
    def __init__(self, model_client: DeepPlanningModel) -> None:
        self._model_client = model_client

    def plan(
        self,
        message: UserMessage,
        *,
        context_bundle: dict[str, Any],
        revision_instructions: list[str] | None = None,
    ) -> DeepPlanningResult:
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are the deep planning engine. Return strict JSON matching "
                    "the PlanDraft schema only. Do not include markdown, prose, "
                    "comments, or code fences."
                ),
            ),
            ChatMessage(
                role="user",
                content=_planning_prompt(
                    message,
                    context_bundle=context_bundle,
                    revision_instructions=revision_instructions,
                ),
            ),
        ]

        try:
            response = self._model_client.chat_with_diagnostics(
                messages,
                policy=DEEP_REASONING_POLICY,
            )
        except (ModelRuntimeDisabled, ModelRuntimeRequestFailed) as error:
            raise DeepPlanningError("deep_planning_unavailable", str(error)) from error

        try:
            payload = json.loads(response.content)
            plan_draft = PlanDraft.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise DeepPlanningError(
                "invalid_plan_json",
                "Deep planning returned malformed or schema-invalid JSON.",
            ) from error

        diagnostics = response.diagnostics
        thinking_status = ThinkingStatus(
            requested=True,
            enforced=True,
            model_policy=DEEP_REASONING_POLICY.profile.value,
            request_payload_had_thinking_params=(
                diagnostics.request_payload_had_thinking_params
            ),
            enable_thinking_sent=diagnostics.enable_thinking_sent,
            preserve_thinking_sent=diagnostics.preserve_thinking_sent,
            fallback_used=diagnostics.fallback_used,
            effective_mode=diagnostics.effective_mode,
            raw_provider_status=diagnostics.raw_provider_status,
        )

        return DeepPlanningResult(
            plan_draft=plan_draft,
            thinking_status=thinking_status,
            raw_response=response.content,
        )


def review_plan(
    draft: PlanDraft,
    *,
    available_capabilities: set[str],
    node_catalog: NodeCatalogSnapshot | None = None,
) -> PlanReview:
    if draft.missing_information:
        missing_inputs = list(draft.missing_information)
        first_missing = missing_inputs[0]
        return PlanReview(
            status="needs_clarification",
            findings=["The plan declares missing information before execution."],
            coverage_findings=["declared_missing_information"],
            missing_inputs=missing_inputs,
            suggested_clarifying_question=f"Please provide: {first_missing}",
            revision_instructions=[
                "Revise the plan after the missing information is supplied."
            ],
        )

    findings: list[str] = []
    coverage_findings: list[str] = []
    revision_instructions: list[str] = []
    unsupported_capabilities: list[str] = []
    catalog = node_catalog or _default_node_catalog()
    effective_available_capabilities = _effective_available_capabilities(
        available_capabilities,
        catalog,
    )
    catalog_resolver = NodeCatalogResolver(catalog)

    if not draft.success_criteria:
        coverage_findings.append("missing_success_criteria")
        findings.append("The plan has no success criteria.")
        revision_instructions.append("Add explicit success criteria for the plan.")

    if not draft.steps:
        coverage_findings.append("missing_steps")
        findings.append("The plan has no executable steps.")
        revision_instructions.append("Add ordered steps with objectives and outputs.")

    if not draft.verification_plan:
        coverage_findings.append("missing_verification_plan")
        findings.append("The plan has no verification plan.")
        revision_instructions.append("Add a verification plan for the full plan.")

    for capability in draft.required_capabilities:
        if capability not in effective_available_capabilities:
            _add_unsupported_capability(
                capability,
                unsupported_capabilities,
                coverage_findings,
            )

    for step in draft.steps:
        if not step.verification_criteria:
            code = f"missing_step_verification_criteria:{step.step_id}"
            coverage_findings.append(code)
            findings.append(
                f"Step {step.step_id} has no verification criteria."
            )
            revision_instructions.append(
                f"Add verification criteria for step {step.step_id}."
            )
        if not step.rationale:
            code = f"missing_step_rationale:{step.step_id}"
            coverage_findings.append(code)
            findings.append(f"Step {step.step_id} has no rationale.")
            revision_instructions.append(f"Add a rationale for step {step.step_id}.")
        if not step.expected_output:
            code = f"missing_step_expected_output:{step.step_id}"
            coverage_findings.append(code)
            findings.append(f"Step {step.step_id} has no expected output.")
            revision_instructions.append(
                f"Add an expected output for step {step.step_id}."
            )
        for capability in step.required_capabilities:
            if capability not in effective_available_capabilities:
                _add_unsupported_capability(
                    capability,
                    unsupported_capabilities,
                    coverage_findings,
                )
        _review_step_catalog_resolution(
            step,
            catalog_resolver,
            unsupported_capabilities,
            coverage_findings,
        )

    if unsupported_capabilities:
        findings.append(
            "The plan requires unsupported capabilities: "
            + ", ".join(unsupported_capabilities)
            + "."
        )
        revision_instructions.append(
            "Revise the plan to use only available capabilities or request support."
        )

    if findings:
        return PlanReview(
            status="invalid",
            findings=findings,
            coverage_findings=coverage_findings,
            unsupported_capabilities=unsupported_capabilities,
            revision_instructions=revision_instructions,
        )

    return PlanReview(status="approved")


def _default_node_catalog() -> NodeCatalogSnapshot:
    return NodeCatalogBuilder(
        tool_registry=ToolRegistry.from_packages_root(default_tool_packages_root()),
    ).build()


def _effective_available_capabilities(
    available_capabilities: set[str],
    catalog: NodeCatalogSnapshot,
) -> set[str]:
    catalog_declared_capabilities = _catalog_declared_capabilities(catalog)
    return (
        set(available_capabilities) - catalog_declared_capabilities
    ) | catalog.available_capabilities()


def _catalog_declared_capabilities(catalog: NodeCatalogSnapshot) -> set[str]:
    capabilities: set[str] = set()
    for node in catalog.nodes:
        capabilities.add(node.node_id)
        capabilities.update(node.capabilities)
    return capabilities


def _review_step_catalog_resolution(
    step: PlanStep,
    catalog_resolver: NodeCatalogResolver,
    unsupported_capabilities: list[str],
    coverage_findings: list[str],
) -> None:
    if not step.required_capabilities:
        return

    try:
        catalog_resolver.resolve(
            required_capabilities=step.required_capabilities,
            preferred_node_ids=step.preferred_node_ids,
        )
    except NodeCatalogResolutionError as error:
        for capability in error.capabilities:
            if capability not in unsupported_capabilities:
                unsupported_capabilities.append(capability)
        code = (
            f"unsupported_capability_set:{step.step_id}:"
            + ",".join(error.capabilities)
        )
        if code not in coverage_findings:
            coverage_findings.append(code)


def _planning_prompt(
    message: UserMessage,
    *,
    context_bundle: dict[str, Any],
    revision_instructions: list[str] | None = None,
) -> str:
    prompt = {
        "taskId": _scrub_paths(message.task_id),
        "user_message": _scrub_paths(message.content),
        "attachment_summaries": _attachment_summaries(message.attachments),
        "context_bundle": _scrub_paths(context_bundle),
        "revision_instructions": _scrub_paths(revision_instructions or []),
        "required_json_keys": [
            "plan_draft_id",
            "task_understanding",
            "success_criteria",
            "inputs",
            "assumptions",
            "missing_information",
            "candidate_strategies",
            "recommended_strategy",
            "steps",
            "required_capabilities",
            "risks",
            "verification_plan",
        ],
        "instructions": [
            "Return only valid JSON for PlanDraft.",
            "Use a non-empty success_criteria list.",
            "Use a non-empty steps list.",
            "Use a non-empty verification_plan list.",
            "Ensure recommended_strategy references a candidate strategyId.",
            "Ensure step depends_on values reference existing step_id values only.",
        ],
    }
    return json.dumps(prompt, ensure_ascii=False, indent=2)


def _reasoning_prompt(
    message: UserMessage,
    *,
    context_bundle: dict[str, Any],
) -> str:
    attachment_summaries = _attachment_summaries(message.attachments)
    prompt = {
        "taskId": _scrub_paths(message.task_id),
        "user_message": _scrub_paths(message.content),
        "attachment_count": len(attachment_summaries),
        "attachment_summaries": attachment_summaries,
        "context_bundle": _scrub_paths(context_bundle),
        "allowed_next_actions": [
            "simple_answer",
            "tool_action",
            "clarification",
            "deep_planning",
        ],
        "instructions": [
            "Classify the task and explain why that path is appropriate.",
            "Return only valid JSON for ReasoningDecision.",
        ],
    }
    return json.dumps(prompt, ensure_ascii=False, indent=2)


def _attachment_summaries(attachments: list[Attachment]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for attachment in attachments:
        summary = {
            "attachment_id": attachment.attachment_id,
            "name": attachment.name,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
        }
        summaries.append(_scrub_paths(summary))
    return summaries


def _scrub_paths(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _scrub_paths(value.model_dump())
    if isinstance(value, dict):
        return {
            key: _scrub_paths(item)
            for key, item in value.items()
            if str(key).lower()
            not in {
                "path",
                "local_path",
                "filepath",
                "file_path",
                "absolute_path",
            }
        }
    if isinstance(value, list):
        return [_scrub_paths(item) for item in value]
    if isinstance(value, str):
        scrubbed = _LOCAL_PATH_PATTERN.sub(LOCAL_PATH_MARKER, value)
        return _LOCAL_PATH_TO_END_PATTERN.sub(LOCAL_PATH_MARKER, scrubbed)
    return value


def _add_unsupported_capability(
    capability: str,
    unsupported_capabilities: list[str],
    coverage_findings: list[str],
) -> None:
    if capability not in unsupported_capabilities:
        unsupported_capabilities.append(capability)
    code = f"unsupported_capability:{capability}"
    if code not in coverage_findings:
        coverage_findings.append(code)
