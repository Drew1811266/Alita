from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec, TaskType, parse_goal_spec
from agent_service.intent import (
    InquiryMode,
    IntentKind,
    RouteDecision,
    classify_route,
)
from agent_service.model_client import ChatMessage as ModelChatMessage
from agent_service.model_policy import ModelCallPolicy
from agent_service.schemas import UserMessage
from agent_service.tool_router import route_tool_for_message


AgentRouteIntent = Literal[
    "chat",
    "local_inquiry",
    "web_simple_inquiry",
    "web_complex_choice",
    "web_complex_research_flow",
    "task",
    "missing_input",
]
InquiryChoice = Literal["quick_answer", "research_flow"]
RouteSource = Literal["deterministic", "model", "fallback"]

STRUCTURED_ROUTER_ENV = "ALITA_STRUCTURED_ROUTER"
HIGH_CONFIDENCE_THRESHOLD = 0.75
LOW_CONFIDENCE_THRESHOLD = 0.45
LOCAL_PATH_PATTERN = re.compile(
    r"(?i)(?:[a-z]:[\\/](?:[^\\/\s:<>|\"?*]+[\\/]?)+|"
    r"(?:/[\w .@+-]+){2,})"
)


class RouterModelClient(Protocol):
    def chat(
        self,
        messages: list[ModelChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        ...


class RouterV2Decision(BaseModel):
    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: TaskType
    missing_inputs: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    reason: str
    source: RouteSource
    should_clarify: bool = False
    clarification_prompt: str | None = None
    legacy_route: dict[str, Any] = Field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": list(self.missing_inputs),
            "requiredPermissions": list(self.required_permissions),
            "toolCandidates": list(self.tool_candidates),
            "reason": self.reason,
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": self.clarification_prompt,
            "legacyRoute": dict(self.legacy_route),
        }


def structured_router_enabled() -> bool:
    return os.getenv(STRUCTURED_ROUTER_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def deterministic_route(
    message: UserMessage,
    inquiry_choice: InquiryChoice | None = None,
) -> RouterV2Decision:
    decision = classify_route(message)
    goal_spec = parse_goal_spec(message)
    intent = compatible_intent(
        message,
        decision,
        inquiry_choice=inquiry_choice,
        goal_spec=goal_spec,
    )
    legacy_route = effective_legacy_route_payload(decision, intent)
    missing_inputs = _ordered_unique(
        [*decision.missing_inputs, *goal_spec.missing_inputs]
    )
    tool_candidates = _tool_candidates(message)
    task_type = _task_type_for_route(message, intent, goal_spec)
    reason = _safe_reason(decision.reason)

    return RouterV2Decision(
        intent=intent,
        confidence=_confidence_for_route(intent, missing_inputs),
        task_type=task_type,
        missing_inputs=missing_inputs,
        required_permissions=list(goal_spec.permissions_required),
        tool_candidates=tool_candidates,
        reason=reason,
        source="deterministic",
        should_clarify=bool(missing_inputs),
        clarification_prompt=_clarification_prompt(missing_inputs),
        legacy_route=legacy_route,
    )


def route_message(
    message: UserMessage,
    *,
    inquiry_choice: InquiryChoice | None = None,
    model_client: RouterModelClient | None = None,
) -> RouterV2Decision:
    deterministic = deterministic_route(message, inquiry_choice=inquiry_choice)
    if not structured_router_enabled():
        return deterministic
    if _is_protected_fast_path(message, deterministic, inquiry_choice):
        return deterministic
    if model_client is None:
        return _fallback_decision(deterministic, "model router unavailable")

    try:
        response = model_client.chat(
            _build_model_router_messages(message),
            temperature=0.0,
            max_tokens=512,
        )
        model_decision = parse_model_route_response(
            response,
            fallback=deterministic,
        )
    except Exception:
        return _fallback_decision(deterministic, "model router failed")

    if model_decision.confidence < LOW_CONFIDENCE_THRESHOLD:
        return _fallback_decision(deterministic, "model router confidence too low")
    return model_decision


def compatible_intent(
    message: UserMessage,
    decision: RouteDecision,
    *,
    inquiry_choice: InquiryChoice | None = None,
    goal_spec: GoalSpec | None = None,
) -> AgentRouteIntent:
    if (
        goal_spec is not None
        and goal_spec.task_type == "document_processing"
        and not _looks_like_external_web_request(message.content)
    ):
        if goal_spec.missing_inputs:
            return "missing_input"
        return "task"

    if decision.intent.kind == IntentKind.NEED_INPUT:
        return "missing_input"

    if decision.intent.kind == IntentKind.TASK:
        return "task"

    if decision.intent.kind == IntentKind.INQUIRY and decision.inquiry is not None:
        if decision.inquiry.mode == InquiryMode.LOCAL:
            return "local_inquiry"
        if decision.inquiry.mode == InquiryMode.WEB_SIMPLE:
            return "web_simple_inquiry"
        if decision.inquiry.mode == InquiryMode.WEB_COMPLEX:
            if inquiry_choice == "quick_answer":
                return "web_simple_inquiry"
            if inquiry_choice == "research_flow":
                return "web_complex_research_flow"
            return "web_complex_choice"

    return "chat"


def effective_legacy_route_payload(
    decision: RouterV2Decision | RouteDecision,
    intent: AgentRouteIntent | None = None,
) -> dict[str, Any]:
    if isinstance(decision, RouterV2Decision):
        route_decision = dict(decision.legacy_route)
        effective_intent = decision.intent
    else:
        route_decision = decision.to_payload()
        effective_intent = intent or compatible_intent(
            UserMessage(task_id="route", content=""),
            decision,
        )

    if (
        effective_intent == "web_simple_inquiry"
        and route_decision.get("inquiry", {}).get("mode") == InquiryMode.WEB_COMPLEX.value
    ):
        route_decision = {
            **route_decision,
            "inquiry": {
                **route_decision["inquiry"],
                "mode": InquiryMode.WEB_SIMPLE.value,
                "requires_web": True,
            },
        }
    return _scrub_payload(route_decision)


def parse_model_route_response(
    response: str,
    *,
    fallback: RouterV2Decision,
) -> RouterV2Decision:
    try:
        raw = json.loads(_extract_json_object(response))
        if not isinstance(raw, dict):
            raise ValueError("router response must be an object")
        return RouterV2Decision(
            intent=raw.get("intent"),
            confidence=raw.get("confidence"),
            task_type=raw.get("task_type") or raw.get("taskType"),
            missing_inputs=list(raw.get("missing_inputs") or raw.get("missingInputs") or []),
            required_permissions=list(
                raw.get("required_permissions") or raw.get("requiredPermissions") or []
            ),
            tool_candidates=[
                _safe_reason(str(candidate))
                for candidate in (
                    raw.get("tool_candidates") or raw.get("toolCandidates") or []
                )
            ],
            reason=_safe_reason(str(raw.get("reason") or "model router")),
            source="model",
            should_clarify=bool(
                raw.get("should_clarify") or raw.get("shouldClarify") or False
            ),
            clarification_prompt=_safe_optional_text(
                raw.get("clarification_prompt") or raw.get("clarificationPrompt")
            ),
            legacy_route=effective_legacy_route_payload(
                classify_route(UserMessage(task_id="fallback", content="")),
                fallback.intent,
            )
            if not fallback.legacy_route
            else fallback.legacy_route,
        )
    except Exception:
        return _fallback_decision(fallback, "invalid model router response")


def _fallback_decision(
    decision: RouterV2Decision,
    reason: str,
) -> RouterV2Decision:
    return decision.model_copy(
        update={
            "source": "fallback",
            "reason": _safe_reason(f"{decision.reason}; {reason}"),
        }
    )


def _is_protected_fast_path(
    message: UserMessage,
    decision: RouterV2Decision,
    inquiry_choice: InquiryChoice | None,
) -> bool:
    tool_route = route_tool_for_message(message)
    return (
        bool(decision.missing_inputs)
        or bool(tool_route and tool_route.tool_name.startswith("weather."))
        or inquiry_choice is not None
        or decision.task_type == "document_processing"
        or decision.intent == "web_complex_research_flow"
    )


def _build_model_router_messages(message: UserMessage) -> list[ModelChatMessage]:
    content = _safe_reason(message.content.strip() or "continue")
    attachment_names = ", ".join(attachment.name for attachment in message.attachments)
    if attachment_names:
        content = f"{content}\nAttachments: {attachment_names}"
    return [
        ModelChatMessage(
            role="system",
            content=(
                "Return only JSON for Alita routing. Use intent, confidence, "
                "task_type, missing_inputs, required_permissions, tool_candidates, "
                "reason, should_clarify, clarification_prompt. Do not include local paths."
            ),
        ),
        ModelChatMessage(role="user", content=content),
    ]


def _task_type_for_route(
    message: UserMessage,
    intent: AgentRouteIntent,
    goal_spec: GoalSpec,
) -> TaskType:
    if goal_spec.task_type == "document_processing":
        return "document_processing"
    if intent.startswith("web_complex") or intent == "web_simple_inquiry":
        return "research"
    if intent in {"chat", "local_inquiry"}:
        return "chat"
    if intent == "missing_input":
        return goal_spec.task_type

    normalized = message.content.lower()
    if _contains_any(normalized, ["script", "python", "code", "graph.py", "test"]):
        return "code_task"
    if _contains_any(normalized, ["write", "generate", "draft", "文案", "生成"]):
        return "content_creation"
    return goal_spec.task_type if goal_spec.task_type != "chat" else "unknown"


def _confidence_for_route(
    intent: AgentRouteIntent,
    missing_inputs: list[str],
) -> float:
    if missing_inputs:
        return HIGH_CONFIDENCE_THRESHOLD
    if intent == "web_complex_choice":
        return 0.7
    return 0.85


def _tool_candidates(message: UserMessage) -> list[str]:
    tool_route = route_tool_for_message(message)
    if tool_route is None:
        return []
    return [_safe_reason(tool_route.tool_name)]


def _clarification_prompt(missing_inputs: list[str]) -> str | None:
    if "document_file" in missing_inputs:
        return "请把需要处理的文件添加到聊天框里。"
    if "message" in missing_inputs:
        return "请先输入你想让我处理的问题或任务。"
    if missing_inputs:
        return "请补充缺失的信息后我再继续。"
    return None


def _safe_reason(value: str) -> str:
    return LOCAL_PATH_PATTERN.sub("[local_path]", value)


def _safe_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _safe_reason(str(value))


def _scrub_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_reason(value)
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_payload(item) for key, item in value.items()}
    return value


def _extract_json_object(response: str) -> str:
    stripped = response.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    return stripped[start : end + 1]


def _contains_any(content: str, keywords: list[str]) -> bool:
    return any(keyword in content for keyword in keywords)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _looks_like_external_web_request(content: str) -> bool:
    normalized = content.lower()
    return any(
        keyword in normalized
        for keyword in (
            "github",
            "search",
            "website",
            "web site",
            "网站",
            "查询",
            "搜索",
            "热门项目",
            "联网",
        )
    )
