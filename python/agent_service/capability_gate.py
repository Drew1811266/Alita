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
    missing_inputs = []
    if decision.requires_files and not message.attachments:
        missing_inputs.append("attachment")

    missing = _missing_tool_candidates(
        decision.tool_candidates,
        available_capabilities,
    )
    if missing_inputs and missing:
        return CapabilityGateResult(
            allowed=False,
            reason="missing required file attachment and route capabilities",
            missing_inputs=missing_inputs,
            missing_capabilities=missing,
            user_message=(
                "请先添加需要处理的文档；当前任务还需要尚未接入的能力："
                + "、".join(missing)
                + "。请补充文档并调整任务目标，或等待该能力接入后再执行。"
            ),
        )

    if missing_inputs:
        return CapabilityGateResult(
            allowed=False,
            reason="missing required file attachment",
            missing_inputs=missing_inputs,
            user_message="请先添加需要处理的文档。",
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
    available = {
        capability.strip()
        for capability in available_capabilities
        if capability.strip()
    }
    missing: list[str] = []
    seen: set[str] = set()
    for tool in tool_candidates:
        normalized = tool.strip()
        if normalized and normalized not in available and normalized not in seen:
            missing.append(normalized)
            seen.add(normalized)
    return missing
