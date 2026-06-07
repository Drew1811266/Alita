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
from agent_service.model_policy import (
    DEEP_REASONING_POLICY,
    ModelCallPolicy,
    ModelCallProfile,
)
from agent_service.node_catalog import NodeCatalogBuilder, NodeCatalogSnapshot
from agent_service.node_catalog_resolver import (
    NodeCatalogResolutionError,
    NodeCatalogResolver,
)
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry


LOCAL_PATH_MARKER = "[local_path_removed]"
_PLANNING_REQUIRED_JSON_KEYS = list(PlanDraft.model_fields)
_PLANNING_FIELD_CONTRACT = {
    "plan_draft_id": "Stable non-empty id for this draft.",
    "task_understanding": "One concise sentence summarizing the user's task.",
    "success_criteria": "Non-empty array of measurable success criteria strings.",
    "inputs": "Array of objects, not strings. Each object should describe an input with keys such as kind, description, source, or required.",
    "assumptions": "Array of assumption strings; use an empty array if none.",
    "missing_information": "Array of missing-information strings; use an empty array if none.",
    "candidate_strategies": "Array of objects with exactly strategyId, summary, and tradeoffs. Use summary, not description.",
    "recommended_strategy": "strategyId value from candidate_strategies.",
    "steps": (
        "Non-empty array of objects with step_id, title, objective, rationale, "
        "inputs, required_capabilities, preferred_node_ids, expected_output, "
        "verification_criteria, and depends_on. Do not use description."
    ),
    "required_capabilities": "Array of capability strings needed by the full plan.",
    "risks": "Array of risk strings; use an empty array if none.",
    "verification_plan": "Non-empty array of verification step strings.",
}
_PLANNING_EXAMPLE_RESPONSE = {
    "plan_draft_id": "plan-example",
    "task_understanding": "User wants information gathered, analyzed, and written into a deliverable document.",
    "success_criteria": [
        "The final deliverable directly answers the user's request.",
        "The output includes source-aware analysis and a clear recommendation.",
    ],
    "inputs": [
        {
            "kind": "user_request",
            "description": "Original user instructions and constraints.",
            "source": "user_message",
            "required": True,
        }
    ],
    "assumptions": ["Available nodes can perform the required synthesis and document output."],
    "missing_information": [],
    "candidate_strategies": [
        {
            "strategyId": "strategy-balanced",
            "summary": "Use a compact research, synthesis, and document-generation workflow.",
            "tradeoffs": ["Efficient and direct, but may need revision if sources are unavailable."],
        }
    ],
    "recommended_strategy": "strategy-balanced",
    "steps": [
        {
            "step_id": "step-research",
            "title": "Gather Inputs",
            "objective": "Collect and normalize the information needed for analysis.",
            "rationale": "The final document needs structured source material before synthesis.",
            "inputs": ["user_request"],
            "required_capabilities": ["model.reasoning"],
            "preferred_node_ids": ["model.reasoning"],
            "expected_output": "Structured notes for synthesis.",
            "verification_criteria": ["Notes cover the user's required decision factors."],
            "depends_on": [],
        },
        {
            "step_id": "step-write",
            "title": "Write Deliverable",
            "objective": "Create the final document content.",
            "rationale": "The user requested a written deliverable, not only a chat answer.",
            "inputs": ["step-research"],
            "required_capabilities": ["document.write"],
            "preferred_node_ids": [],
            "expected_output": "A complete draft document.",
            "verification_criteria": ["The document satisfies every success criterion."],
            "depends_on": ["step-research"],
        },
    ],
    "required_capabilities": ["model.reasoning", "document.write"],
    "risks": ["Required source material may be incomplete or unavailable."],
    "verification_plan": ["Validate the plan graph and inspect the final document."],
}
_REASONING_REQUIRED_JSON_KEYS = list(ReasoningDecision.model_fields)
_REASONING_FIELD_CONTRACT = {
    "task_id": "Copy taskId exactly.",
    "task_understanding": "One concise sentence summarizing the user's task.",
    "intent": "Short task category, for example chat, task, web_complex_research_flow, or document_generation.",
    "complexity": "One of: simple, bounded_tool, graph_task.",
    "why_this_path": "Brief reason for choosing next_action. Put explanatory reasoning here, not in a reasoning field.",
    "confidence": "Number from 0.0 to 1.0.",
    "needs_clarification": "Boolean indicating whether the user must provide more information before progress is possible.",
    "required_capabilities": "Array of capability strings needed for the task; use an empty array if none are required.",
    "next_action": "One of allowed_next_actions. Use next_action, not action.",
}
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_WEB_RESEARCH_PATTERN = re.compile(
    r"(上网|联网|网上|网页|网络检索|搜索|搜集|检索|查询|查找|浏览|最新|实时|当前|今天|近期|"
    r"市场行情|价格|报价|电商|web|internet|online|search|browse|look up|latest|"
    r"current|today|recent|price|prices|market)",
    re.IGNORECASE,
)
DEEP_PLANNING_TIMEOUT_SECONDS = 180.0
PLAN_DRAFT_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.DEEP_REASONING,
    temperature=0.0,
    max_tokens=2048,
    thinking="off",
    preserve_thinking=False,
    stream=False,
)
_WEB_SEARCH_NODE_ID = "web.search.parallel"
_WEB_FETCH_NODE_ID = "web.fetch.sources"
_WEB_RESEARCH_NODE_IDS = {_WEB_SEARCH_NODE_ID, _WEB_FETCH_NODE_ID}
_WEB_RESEARCH_CAPABILITIES = {
    "web.search",
    "web.search.parallel",
    "web_search",
    "research.web_search",
    "web.fetch",
    "web.fetch.sources",
    "source.fetch",
    "research.source_fetch",
}
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
        timeout_seconds: float | None = None,
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
                policy=PLAN_DRAFT_POLICY,
                timeout_seconds=DEEP_PLANNING_TIMEOUT_SECONDS,
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
            requested=PLAN_DRAFT_POLICY.thinking != "off",
            enforced=PLAN_DRAFT_POLICY.thinking != "off",
            model_policy=PLAN_DRAFT_POLICY.profile.value,
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
    message: UserMessage | None = None,
) -> PlanReview:
    catalog = node_catalog or _default_node_catalog()
    effective_available_capabilities = _effective_available_capabilities(
        available_capabilities,
        catalog,
    )
    catalog_resolver = NodeCatalogResolver(catalog)
    web_research_findings = _web_research_review_findings(
        draft,
        message=message,
        effective_available_capabilities=effective_available_capabilities,
    )
    findings: list[str] = []
    coverage_findings: list[str] = []
    revision_instructions: list[str] = []
    unsupported_capabilities: list[str] = []

    for capability in draft.required_capabilities:
        if capability not in effective_available_capabilities:
            _add_unsupported_capability(
                capability,
                unsupported_capabilities,
                coverage_findings,
            )

    for step in draft.steps:
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
            revision_instructions,
        )

    if draft.missing_information:
        missing_inputs = list(draft.missing_information)
        first_missing = missing_inputs[0]
        findings = [
            "The plan declares missing information before execution.",
            *findings,
        ]
        coverage_findings = [
            "declared_missing_information",
            *coverage_findings,
        ]
        revision_instructions = [
            "Revise the plan after the missing information is supplied.",
            *revision_instructions,
        ]
        if web_research_findings is not None:
            findings.append(web_research_findings["finding"])
            coverage_findings.append(web_research_findings["coverage_finding"])
            revision_instructions.append(web_research_findings["revision_instruction"])
        if unsupported_capabilities:
            findings.append(
                "The plan requires unsupported capabilities: "
                + ", ".join(unsupported_capabilities)
                + "."
            )
            revision_instructions.append(
                "Revise the plan to use only available capabilities or request support."
            )
        return PlanReview(
            status="needs_clarification",
            findings=findings,
            coverage_findings=coverage_findings,
            missing_inputs=missing_inputs,
            unsupported_capabilities=unsupported_capabilities,
            suggested_clarifying_question=f"请补充：{first_missing}",
            revision_instructions=revision_instructions,
        )

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
    if web_research_findings is not None:
        findings.append(web_research_findings["finding"])
        coverage_findings.append(web_research_findings["coverage_finding"])
        revision_instructions.append(web_research_findings["revision_instruction"])

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
    revision_instructions: list[str],
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
        _add_capability_set_revision_instruction(
            step,
            capabilities=error.capabilities,
            revision_instructions=revision_instructions,
        )
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
        "conversation_history": _conversation_history_summaries(message),
        "attachment_summaries": _attachment_summaries(message.attachments),
        "context_bundle": _scrub_paths(context_bundle),
        "revision_instructions": _scrub_paths(revision_instructions or []),
        "response_language": _response_language_for_message(message),
        "web_research_requirement": _web_research_requirement_for_message(message),
        "required_json_keys": _PLANNING_REQUIRED_JSON_KEYS,
        "field_contract": _PLANNING_FIELD_CONTRACT,
        "example_response": _PLANNING_EXAMPLE_RESPONSE,
        "instructions": [
            "Return exactly one JSON object matching required_json_keys and field_contract.",
            "Do not include any top-level keys except required_json_keys.",
            "For every user-visible string value, use response_language; when response_language is zh-Hans, use natural 简体中文.",
            "For inputs, return objects, not strings.",
            "For candidate_strategies, use strategyId, summary, and tradeoffs; do not use description.",
            "For each step, include every field listed in field_contract.steps; do not use description.",
            "Use a non-empty success_criteria list.",
            "Use a non-empty steps list.",
            "Use a non-empty verification_plan list.",
            "Ensure recommended_strategy references a candidate strategyId.",
            "Ensure step depends_on values reference existing step_id values only.",
            (
                "For each step, set preferred_node_ids to node_id values from "
                "context_bundle.available_nodes when an available node directly "
                "matches a step; leave it empty when no available node directly "
                "matches."
            ),
            (
                "Do not name nodes outside context_bundle.available_nodes in "
                "preferred_node_ids."
            ),
            (
                "Use required_capabilities only from context_bundle.available_tools "
                "or context_bundle.available_nodes. Do not use unavailable "
                "capabilities even if they appear in examples."
            ),
            (
                "Each plan step resolves to one catalog node. If a workflow needs "
                "multiple tools or nodes, split them into sequential steps instead "
                "of combining their capabilities in one step."
            ),
            (
                "If web_research_requirement.required is true, include an early "
                "web search step with required_capabilities containing only "
                "web.search and preferred_node_ids containing web.search.parallel. "
                "If source pages must be read or verified, add a separate following "
                "fetch step with required_capabilities containing only web.fetch "
                "and preferred_node_ids containing web.fetch.sources."
            ),
            (
                "Do not claim that real-time web access or web retrieval is "
                "unavailable when web.search.parallel appears in "
                "context_bundle.available_nodes."
            ),
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
        "conversation_history": _conversation_history_summaries(message),
        "attachment_count": len(attachment_summaries),
        "attachment_summaries": attachment_summaries,
        "context_bundle": _scrub_paths(context_bundle),
        "response_language": _response_language_for_message(message),
        "allowed_next_actions": [
            "simple_answer",
            "tool_action",
            "clarification",
            "deep_planning",
        ],
        "required_json_keys": _REASONING_REQUIRED_JSON_KEYS,
        "field_contract": _REASONING_FIELD_CONTRACT,
        "example_response": {
            "task_id": _scrub_paths(message.task_id),
            "task_understanding": "User wants current PC component research, a roughly 10000 RMB build recommendation, and a written analysis document.",
            "intent": "web_complex_research_flow",
            "complexity": "graph_task",
            "why_this_path": "The request needs research, comparison, synthesis, and document generation, so it should be planned as a multi-step graph.",
            "confidence": 0.9,
            "needs_clarification": False,
            "required_capabilities": [
                "model.reasoning",
                "research.synthesize",
                "document.write",
            ],
            "next_action": "deep_planning",
        },
        "instructions": [
            "Return exactly one JSON object matching required_json_keys and field_contract.",
            "Do not include any top-level keys except required_json_keys.",
            "Do not include classification, reasoning, action, parameters, markdown, comments, or code fences.",
            "For every user-visible string value, use response_language; when response_language is zh-Hans, use natural 简体中文.",
            "Classify the task and explain why that path is appropriate in why_this_path.",
            "Set next_action to one of allowed_next_actions.",
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


def _conversation_history_summaries(message: UserMessage) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for turn in message.conversation_history[-12:]:
        content = turn.content.strip()
        if not content:
            continue
        summaries.append(
            {
                "role": turn.role,
                "content": _scrub_paths(content),
            }
        )
    return summaries


def _response_language_for_message(message: UserMessage) -> str:
    history_text = "\n".join(turn.content for turn in message.conversation_history)
    text = f"{history_text}\n{message.content}"
    return "zh-Hans" if _CJK_PATTERN.search(text) else "match_user_language"


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


def _web_research_requirement_for_message(message: UserMessage) -> dict[str, Any]:
    required = _message_needs_web_research(message)
    return {
        "required": required,
        "required_node_ids": (
            [_WEB_SEARCH_NODE_ID, _WEB_FETCH_NODE_ID] if required else []
        ),
        "required_capabilities": ["web.search", "web.fetch"] if required else [],
        "reason": (
            "The user asks for web/current/external market information."
            if required
            else ""
        ),
    }


def _web_research_review_findings(
    draft: PlanDraft,
    *,
    message: UserMessage | None,
    effective_available_capabilities: set[str],
) -> dict[str, str] | None:
    if message is None or not _message_needs_web_research(message):
        return None
    if _WEB_SEARCH_NODE_ID not in effective_available_capabilities:
        return None
    if _plan_has_web_research_step(draft):
        return None
    return {
        "finding": (
            "The user requested web/current external research, but no plan step "
            f"uses {_WEB_SEARCH_NODE_ID}."
        ),
        "coverage_finding": "missing_web_search_step",
        "revision_instruction": (
            "Add an early web research step with required_capabilities including "
            f"web.search and preferred_node_ids including {_WEB_SEARCH_NODE_ID}; "
            f"use {_WEB_FETCH_NODE_ID} when source pages must be read before synthesis."
        ),
    }


def _message_needs_web_research(message: UserMessage) -> bool:
    return bool(_WEB_RESEARCH_PATTERN.search(_message_text_for_intent(message)))


def _message_text_for_intent(message: UserMessage) -> str:
    history = " ".join(
        str(turn.content)
        for turn in message.conversation_history
        if str(turn.content).strip()
    )
    return f"{history} {message.content}"


def _plan_has_web_research_step(draft: PlanDraft) -> bool:
    for step in draft.steps:
        node_ids = {str(node_id) for node_id in step.preferred_node_ids}
        capabilities = {str(capability) for capability in step.required_capabilities}
        if node_ids & _WEB_RESEARCH_NODE_IDS:
            return True
        if capabilities & _WEB_RESEARCH_CAPABILITIES:
            return True
    return False


def _add_capability_set_revision_instruction(
    step: PlanStep,
    *,
    capabilities: list[str],
    revision_instructions: list[str],
) -> None:
    capability_set = set(capabilities)
    if {"web.search", "web.fetch"} <= capability_set:
        revision_instructions.append(
            f"Split step {step.step_id} into separate catalog-node steps: one "
            f"web.search step using {_WEB_SEARCH_NODE_ID}, followed by one "
            f"web.fetch step using {_WEB_FETCH_NODE_ID} when source pages must be read."
        )
    if "document.write_markdown" in capability_set:
        revision_instructions.append(
            f"Replace unsupported document.write_markdown in step {step.step_id} "
            "with available document output nodes, such as document.render.typst_pdf "
            "for PDF rendering and output.final_response for final delivery."
        )


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
