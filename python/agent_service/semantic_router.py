from __future__ import annotations

import inspect
import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from agent_service.model_client import ChatMessage as ModelChatMessage
from agent_service.model_policy import ModelCallPolicy, ModelCallProfile
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

SEMANTIC_ROUTER_MAX_TOKENS = 32
SEMANTIC_ROUTER_TIMEOUT_SECONDS = 5.0
SEMANTIC_ROUTER_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.FAST_CHAT,
    temperature=0.0,
    max_tokens=SEMANTIC_ROUTER_MAX_TOKENS,
    thinking="off",
    preserve_thinking=False,
    stream=False,
)
ROUTE_CODE_TO_ROUTE: dict[str, SemanticRoute] = {
    "A": "response_only",
    "B": "local_answer",
    "C": "simple_tool_answer",
    "D": "web_answer",
    "E": "graph_feedback",
    "F": "clarification_required",
    "G": "deep_planning",
    "H": "research_planning",
}


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
            message=message,
            language=_infer_language(message.content),
            reason="semantic router model unavailable",
            current_graph=current_graph,
            pending_choice=pending_choice,
        )

    messages = build_semantic_router_messages(
        message,
        current_graph=current_graph,
        pending_choice=pending_choice,
        available_capabilities=available_capabilities,
    )
    try:
        response = _chat_semantic_router(model_client, messages)
    except Exception:
        return _router_unavailable_decision(
            message=message,
            language=_infer_language(message.content),
            reason="semantic router failed",
            current_graph=current_graph,
            pending_choice=pending_choice,
        )

    try:
        route_code_decision = _route_code_decision(response, message)
        if route_code_decision is not None:
            return route_code_decision
        return parse_semantic_route_response(response)
    except Exception as first_error:
        try:
            repair_response = _chat_semantic_router(
                model_client,
                _repair_messages(
                    str(first_error),
                    response,
                ),
            )
            return parse_semantic_route_response(repair_response)
        except Exception:
            return _router_unavailable_decision(
                message=message,
                language=_infer_language(message.content),
                reason="semantic router failed",
                current_graph=current_graph,
                pending_choice=pending_choice,
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
                "meaning and runtime context, not keywords. Return exactly one "
                "plain route code and nothing else. Codes: A=response_only, "
                "B=local_answer, C=simple_tool_answer, D=web_answer, "
                "E=graph_feedback, F=clarification_required, G=deep_planning, "
                "H=research_planning. Complexity meanings: simple, bounded_tool, "
                "multi_step, research. The primary distinction is the user's "
                "desired outcome. If the user wants an answer, choose A/B/C/D/H "
                "as appropriate. If the user wants Alita to produce or change "
                "an artifact, choose G/H. Short social turns, greetings, thanks, "
                "identity questions, and casual conversation are A=response_only. "
                "Choose D=web_answer only for factual/current-information questions "
                "where an answer is the deliverable; never choose D when the "
                "user asks for a script, file, document, workflow, or executable "
                "task as the deliverable. If the user asks Alita to "
                "create, write, modify, build, execute, generate, or produce a "
                "script, file, document, workflow, or other deliverable, choose "
                "G=deep_planning even when web knowledge could help. Choose "
                "H=research_planning only when the requested deliverable is a "
                "research workflow, comparison, sourced report, or synthesis. "
                "Examples: 你好 -> A; Python 如何统计 CSV 行数？ -> B; "
                "帮我创建一个 Python 脚本，统计 CSV 文件的行数。 -> G; "
                "联网调研电脑配件价格并输出配置报告 -> H. "
                "Do not ask for clarification just because the message is not a "
                "task. Never include local paths."
            ),
        ),
        ModelChatMessage(role="user", content=json.dumps(envelope, ensure_ascii=False)),
    ]


def _chat_semantic_router(
    model_client: SemanticRouterModelClient,
    messages: list[ModelChatMessage],
) -> str:
    kwargs: dict[str, Any] = {
        "temperature": 0.0,
        "max_tokens": SEMANTIC_ROUTER_MAX_TOKENS,
        "policy": SEMANTIC_ROUTER_POLICY,
    }
    if _chat_accepts_timeout_seconds(model_client):
        kwargs["timeout_seconds"] = SEMANTIC_ROUTER_TIMEOUT_SECONDS
    return model_client.chat(messages, **kwargs)


def _chat_accepts_timeout_seconds(model_client: SemanticRouterModelClient) -> bool:
    try:
        signature = inspect.signature(model_client.chat)
    except (TypeError, ValueError):
        return False
    return "timeout_seconds" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _route_code_decision(
    response: str,
    message: UserMessage,
) -> SemanticRouteDecision | None:
    code = response.strip().strip("`'\".。 \r\n\t").upper()
    if code not in ROUTE_CODE_TO_ROUTE:
        return None

    route = ROUTE_CODE_TO_ROUTE[code]
    language = _infer_language(message.content)
    return SemanticRouteDecision(
        route=route,
        intent="route_code",
        complexity=_complexity_for_route(route),
        requires_graph=route in {"graph_feedback", "deep_planning", "research_planning"},
        requires_tools=route
        in {
            "simple_tool_answer",
            "web_answer",
            "deep_planning",
            "research_planning",
        },
        requires_web=route in {"web_answer", "research_planning"},
        requires_files=bool(message.attachments),
        requires_clarification=route == "clarification_required",
        language=language,
        confidence=0.9,
        context_used=["current_message", "route_code"],
        missing_inputs=(["clarification"] if route == "clarification_required" else []),
        required_capabilities=[],
        tool_candidates=[],
        reason=_route_code_reason(route, language=language),
        clarification_prompt=(
            _default_clarification_prompt(language)
            if route == "clarification_required"
            else None
        ),
    )


def _complexity_for_route(route: SemanticRoute) -> SemanticComplexity:
    if route in {"simple_tool_answer", "web_answer"}:
        return "bounded_tool"
    if route == "research_planning":
        return "research"
    if route in {"graph_feedback", "deep_planning"}:
        return "multi_step"
    return "simple"


def _route_code_reason(route: SemanticRoute, *, language: str) -> str:
    if language == "zh":
        return f"模型快速路由为 {route}。"
    return f"Model fast-routed to {route}."


def _default_clarification_prompt(language: str) -> str:
    if language == "zh":
        return "请补充你的目标或约束，我再继续。"
    return "Please add the goal or constraints before I continue."


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
    message: UserMessage | None = None,
    language: str,
    reason: str,
    current_graph: RunGraph | None = None,
    pending_choice: dict[str, Any] | None = None,
) -> SemanticRouteDecision:
    if (
        message is not None
        and message.content.strip()
        and not message.attachments
        and current_graph is None
        and pending_choice is None
    ):
        return SemanticRouteDecision(
            route="response_only",
            intent="router_unavailable_response_fallback",
            complexity="simple",
            requires_graph=False,
            requires_tools=False,
            requires_web=False,
            requires_files=False,
            requires_clarification=False,
            language=language,
            confidence=0.0,
            context_used=["current_message", "router_fallback"],
            missing_inputs=[],
            required_capabilities=[],
            tool_candidates=[],
            reason=reason,
            clarification_prompt=None,
        )

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
