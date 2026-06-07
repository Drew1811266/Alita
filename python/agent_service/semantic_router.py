from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from agent_service.model_client import ChatMessage as ModelChatMessage
from agent_service.model_policy import ModelCallPolicy
from agent_service.schemas import RunGraph, UserMessage


SemanticRoute = Literal[
    "response_only",
    "local_answer",
    "simple_tool_answer",
    "web_answer",
    "graph_feedback",
    "clarification_required",
    "deep_planning",
    "research_planning",
]

SemanticComplexity = Literal["simple", "bounded_tool", "multi_step", "research"]

LOCAL_PATH_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"\b[a-z]:[\\/](?:[^\\/:\r\n,;<>\"|?*]+[\\/])+[^\\/\s:\r\n,;<>\"|?*]+"
    r"|"
    r"/(?:[^/\r\n,;<>\"|?*]+/){2,}[^/\s\r\n,;<>\"|?*]+"
    r")"
)

LOCAL_PATH_FRAGMENT_PATTERNS = (
    re.compile(r"(?i)Software Project[\\/]Alita"),
    re.compile(r"(?i)(?<![A-Za-z0-9])agent_service(?![A-Za-z0-9])"),
)

SEMANTIC_ROUTER_MAX_TOKENS = 2048


class SemanticRouterModelClient(Protocol):
    def chat(
        self,
        messages: list[ModelChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        raise NotImplementedError


class SemanticRouteDecision(BaseModel):
    route: SemanticRoute
    intent: str
    complexity: SemanticComplexity
    requires_graph: bool = Field(alias="requiresGraph")
    requires_tools: bool = Field(alias="requiresTools")
    requires_web: bool = Field(alias="requiresWeb")
    requires_files: bool = Field(alias="requiresFiles")
    requires_clarification: bool = Field(alias="requiresClarification")
    language: str
    confidence: float = Field(ge=0.0, le=1.0)
    context_used: list[str] = Field(default_factory=list, alias="contextUsed")
    missing_inputs: list[str] = Field(default_factory=list, alias="missingInputs")
    required_capabilities: list[str] = Field(
        default_factory=list,
        alias="requiredCapabilities",
    )
    tool_candidates: list[str] = Field(default_factory=list, alias="toolCandidates")
    reason: str
    clarification_prompt: str | None = Field(
        default=None,
        alias="clarificationPrompt",
    )

    model_config = {"populate_by_name": True}

    def to_payload(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "intent": _safe_text(self.intent),
            "complexity": self.complexity,
            "requiresGraph": self.requires_graph,
            "requiresTools": self.requires_tools,
            "requiresWeb": self.requires_web,
            "requiresFiles": self.requires_files,
            "requiresClarification": self.requires_clarification,
            "language": _safe_text(self.language),
            "confidence": self.confidence,
            "contextUsed": [_safe_text(item) for item in self.context_used],
            "missingInputs": [_safe_text(item) for item in self.missing_inputs],
            "requiredCapabilities": [
                _safe_capability(item) for item in self.required_capabilities
            ],
            "toolCandidates": [
                _safe_capability(item) for item in self.tool_candidates
            ],
            "reason": _safe_text(self.reason),
            "clarificationPrompt": (
                _safe_text(self.clarification_prompt)
                if self.clarification_prompt is not None
                else None
            ),
        }


def parse_semantic_route_response(response: str) -> SemanticRouteDecision:
    raw = json.loads(_extract_json_object(response))
    if not isinstance(raw, dict):
        raise ValueError("semantic router response must be a JSON object")
    return SemanticRouteDecision.model_validate(_scrub_route_payload(raw))


def route_semantically(
    message: UserMessage,
    *,
    model_client: SemanticRouterModelClient | None,
    current_graph: RunGraph | None = None,
    pending_choice: dict[str, Any] | None = None,
    available_capabilities: list[str] | None = None,
) -> SemanticRouteDecision:
    if model_client is None:
        return _router_unavailable_decision(
            language=_infer_language(message.content),
            reason="semantic router model unavailable",
        )

    messages = build_semantic_router_messages(
        message,
        current_graph=current_graph,
        pending_choice=pending_choice,
        available_capabilities=available_capabilities,
    )
    try:
        response = model_client.chat(
            messages,
            temperature=0.0,
            max_tokens=SEMANTIC_ROUTER_MAX_TOKENS,
        )
        return parse_semantic_route_response(response)
    except Exception as first_error:
        try:
            repair_response = model_client.chat(
                _repair_messages(
                    str(first_error),
                    response if "response" in locals() else "",
                ),
                temperature=0.0,
                max_tokens=SEMANTIC_ROUTER_MAX_TOKENS,
            )
            return parse_semantic_route_response(repair_response)
        except Exception:
            return _router_unavailable_decision(
                language=_infer_language(message.content),
                reason="semantic router failed",
            )


def build_semantic_router_messages(
    message: UserMessage,
    *,
    current_graph: RunGraph | None = None,
    pending_choice: dict[str, Any] | None = None,
    available_capabilities: list[str] | None = None,
) -> list[ModelChatMessage]:
    envelope = {
        "currentMessage": _safe_text(message.content.strip()),
        "conversationHistory": [
            {
                "role": turn.role,
                "content": _safe_text(turn.content),
            }
            for turn in message.conversation_history[-5:]
        ],
        "attachments": [
            {
                "name": _safe_text(attachment.name),
                "mimeType": attachment.mime_type,
                "sizeBytes": attachment.size_bytes,
            }
            for attachment in message.attachments
        ],
        "currentGraph": _graph_summary(current_graph),
        "pendingChoice": _pending_choice_summary(pending_choice),
        "availableCapabilities": [
            _safe_capability(capability) for capability in available_capabilities or []
        ],
    }
    return [
        ModelChatMessage(
            role="system",
            content=(
                "You are Alita's Semantic Router. Decide the user's route from "
                "meaning and runtime context, not keywords. Return only JSON with "
                "route, intent, complexity, requiresGraph, requiresTools, "
                "requiresWeb, requiresFiles, requiresClarification, language, "
                "confidence, contextUsed, missingInputs, requiredCapabilities, "
                "toolCandidates, reason, clarificationPrompt. Use the user's "
                "language for reason and clarificationPrompt. Allowed route values: "
                "response_only, local_answer, simple_tool_answer, web_answer, "
                "graph_feedback, clarification_required, deep_planning, "
                "research_planning. Allowed complexity values: simple, bounded_tool, "
                "multi_step, research. Never include local paths."
            ),
        ),
        ModelChatMessage(role="user", content=json.dumps(envelope, ensure_ascii=False)),
    ]


def _repair_messages(error: str, invalid_response: str) -> list[ModelChatMessage]:
    return [
        ModelChatMessage(
            role="system",
            content=(
                "Repair this invalid Semantic Router response. Return only one "
                "valid JSON object matching the Semantic Router schema. Do not "
                "include markdown, commentary, or local paths.\n"
                f"Error: {_safe_text(error)}\n"
                f"Invalid response: {_safe_text(invalid_response)}"
            ),
        )
    ]


def _router_unavailable_decision(
    *,
    language: str,
    reason: str,
) -> SemanticRouteDecision:
    is_zh = language == "zh"
    return SemanticRouteDecision(
        route="clarification_required",
        intent="router_unavailable",
        complexity="simple",
        requires_graph=False,
        requires_tools=False,
        requires_web=False,
        requires_files=False,
        requires_clarification=True,
        language=language,
        confidence=0.0,
        context_used=["current_message"],
        missing_inputs=["router_decision"],
        required_capabilities=["model.semantic_router"],
        tool_candidates=[],
        reason=reason,
        clarification_prompt=(
            "我需要确认你的目标后才能继续。你想让我直接回答、使用工具、联网研究，还是制定多步骤计划？"
            if is_zh
            else (
                "I need to confirm your goal before continuing. Do you want a "
                "direct answer, tool use, web research, or a multi-step plan?"
            )
        ),
    )


def _infer_language(content: str) -> str:
    return "zh" if re.search(r"[\u3400-\u9fff]", content) else "en"


def _graph_summary(current_graph: RunGraph | None) -> dict[str, Any] | None:
    if current_graph is None:
        return None
    return {
        "graphId": _safe_text(current_graph.graphId),
        "nodeCount": len(current_graph.nodes),
        "edgeCount": len(current_graph.edges),
        "nodes": [
            {
                "nodeId": _safe_text(node.nodeId),
                "nodeType": _safe_text(node.nodeType),
                "displayName": _safe_text(node.displayName),
                "status": _safe_text(node.status),
            }
            for node in current_graph.nodes[:12]
        ],
    }


def _pending_choice_summary(pending_choice: dict[str, Any] | None) -> dict[str, Any] | None:
    if not pending_choice:
        return None
    return {
        "kind": _safe_text(str(pending_choice.get("kind") or "")),
        "runId": _safe_text(str(pending_choice.get("runId") or "")),
        "threadId": _safe_text(str(pending_choice.get("threadId") or "")),
    }


def _extract_json_object(response: str) -> str:
    start = response.find("{")
    end = response.rfind("}")
    if start < 0 or end < start:
        raise ValueError("semantic router response did not contain a JSON object")
    return response[start : end + 1]


def _safe_text(value: str) -> str:
    scrubbed = LOCAL_PATH_PATTERN.sub("[local_path]", value)
    for pattern in LOCAL_PATH_FRAGMENT_PATTERNS:
        scrubbed = pattern.sub("[local_path_fragment]", scrubbed)
    return scrubbed


def _safe_capability(value: str) -> str:
    if LOCAL_PATH_PATTERN.search(value):
        return _safe_text(value)
    if re.search(r"(?i)Software Project[\\/]+Alita", value):
        return _safe_text(value)
    if "\\" in value or "/" in value:
        return _safe_text(value)
    return value


def _scrub_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_payload(item) for key, item in value.items()}
    return value


def _scrub_route_payload(value: dict[str, Any]) -> dict[str, Any]:
    scrubbed = _scrub_payload(value)
    for key in (
        "requiredCapabilities",
        "required_capabilities",
        "toolCandidates",
        "tool_candidates",
    ):
        if key in value and isinstance(value[key], list):
            scrubbed[key] = [_safe_capability(str(item)) for item in value[key]]
    return scrubbed
