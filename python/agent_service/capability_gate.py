from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.schemas import UserMessage
from agent_service.semantic_router import SemanticRouteDecision


class CapabilityGateResult(BaseModel):
    allowed: bool
    reason: str
    missing_capabilities: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    user_message: str = ""


def evaluate_route_capabilities(
    decision: SemanticRouteDecision,
    message: UserMessage,
    *,
    available_capabilities: list[str],
) -> CapabilityGateResult:
    if decision.requires_files and not message.attachments:
        return CapabilityGateResult(
            allowed=False,
            reason="missing required file attachment",
            missing_inputs=["attachment"],
            user_message="请先添加需要处理的文档。",
        )

    missing = _missing_tool_candidates(
        decision.tool_candidates,
        available_capabilities,
    )
    if missing:
        return CapabilityGateResult(
            allowed=False,
            reason="missing route capabilities",
            missing_capabilities=missing,
            user_message=(
                "当前任务需要尚未接入的能力："
                + "、".join(missing)
                + "。请调整任务目标或等待该能力接入后再执行。"
            ),
        )

    return CapabilityGateResult(allowed=True, reason="capabilities available")


def _missing_tool_candidates(
    tool_candidates: list[str],
    available_capabilities: list[str],
) -> list[str]:
    available = set(available_capabilities)
    missing: list[str] = []
    seen: set[str] = set()
    for tool in tool_candidates:
        if tool and tool not in available and tool not in seen:
            missing.append(tool)
            seen.add(tool)
    return missing
