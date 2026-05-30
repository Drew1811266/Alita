from __future__ import annotations

import json
from time import monotonic
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from agent_service.model_client import ChatMessage
from agent_service.model_tool_adapter import (
    build_model_tool_invocation,
    safe_observation_payload,
)
from agent_service.model_policy import ModelCallPolicy
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import (
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


class ReActModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        raise NotImplementedError


class ReActPolicy(BaseModel):
    enabled: bool = False
    max_steps: int = 4
    max_tool_calls: int = 3
    max_runtime_ms: int = 30000
    allowed_tool_ids: list[str] = Field(default_factory=list)
    allowed_permissions: list[str] = Field(default_factory=list)
    stop_on_first_success: bool = True


class ReActAction(BaseModel):
    kind: Literal["final", "tool"]
    text: str | None = None
    tool_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


class ReActObservation(BaseModel):
    tool_id: str
    ok: bool
    values: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None


class ReActResult(BaseModel):
    ok: bool
    text: str
    tool_call_count: int
    observations: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None


class ReActController:
    def __init__(
        self,
        *,
        model_client: ReActModelClient,
        gateway: UnifiedToolGateway,
    ) -> None:
        self.model_client = model_client
        self.gateway = gateway

    def run(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[UnifiedToolDefinition],
        base_invocation: UnifiedToolInvocation,
        policy: ReActPolicy,
        model_policy: ModelCallPolicy | None = None,
    ) -> ReActResult:
        if not policy.enabled:
            return ReActResult(
                ok=False,
                text="",
                tool_call_count=0,
                error_code="react_disabled",
            )

        started_at = monotonic()
        tool_call_count = 0
        observations: list[ReActObservation] = []
        current_messages = list(messages)
        tools_by_id = {tool.id: tool for tool in tools}

        for step_index in range(max(policy.max_steps, 0)):
            if _elapsed_ms(started_at) > policy.max_runtime_ms:
                return _failed_result(
                    "runtime_budget_exceeded",
                    tool_call_count=tool_call_count,
                    observations=observations,
                )

            raw_action = self.model_client.chat(
                current_messages,
                policy=model_policy,
            )
            action = _parse_action(raw_action)
            if action is None or not _valid_action_shape(action):
                return _failed_result(
                    "malformed_action",
                    tool_call_count=tool_call_count,
                    observations=observations,
                )

            if action.kind == "final":
                return ReActResult(
                    ok=True,
                    text=action.text or "",
                    tool_call_count=tool_call_count,
                    observations=_dump_observations(observations),
                )

            if tool_call_count >= policy.max_tool_calls:
                return _failed_result(
                    "tool_budget_exceeded",
                    tool_call_count=tool_call_count,
                    observations=observations,
                )

            tool_id = action.tool_id or ""
            tool = tools_by_id.get(tool_id)
            if tool is None or tool_id not in set(policy.allowed_tool_ids):
                return _failed_result(
                    "tool_not_allowed",
                    tool_call_count=tool_call_count,
                    observations=observations,
                )
            if policy.allowed_permissions and not set(tool.permissions).issubset(
                set(policy.allowed_permissions)
            ):
                return _failed_result(
                    "permission_not_allowed",
                    tool_call_count=tool_call_count,
                    observations=observations,
                )

            invocation = _tool_invocation(
                base_invocation=base_invocation,
                tool=tool,
                arguments=action.arguments,
                tool_call_index=tool_call_count + 1,
            )
            result = self.gateway.call_tool(invocation)
            tool_call_count += 1
            observation = _safe_observation(invocation, result)
            observations.append(observation)
            current_messages.extend(
                [
                    ChatMessage(role="assistant", content=raw_action),
                    ChatMessage(
                        role="user",
                        content=(
                            "Observation: "
                            + json.dumps(
                                observation.model_dump(mode="json"),
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                        ),
                    ),
                ]
            )
            if policy.stop_on_first_success and result.ok:
                continue

            if _elapsed_ms(started_at) > policy.max_runtime_ms:
                return _failed_result(
                    "runtime_budget_exceeded",
                    tool_call_count=tool_call_count,
                    observations=observations,
                )

        return _failed_result(
            "step_budget_exceeded",
            tool_call_count=tool_call_count,
            observations=observations,
        )


def _parse_action(raw: str) -> ReActAction | None:
    try:
        return ReActAction.model_validate_json(raw)
    except ValidationError:
        return None


def _valid_action_shape(action: ReActAction) -> bool:
    if action.kind == "final":
        return action.text is not None
    return bool(action.tool_id)


def _tool_invocation(
    *,
    base_invocation: UnifiedToolInvocation,
    tool: UnifiedToolDefinition,
    arguments: dict[str, Any],
    tool_call_index: int,
) -> UnifiedToolInvocation:
    return build_model_tool_invocation(
        base_invocation=base_invocation,
        invocation_id=f"{base_invocation.invocation_id}-react-{tool_call_index}",
        tool=tool,
        arguments=arguments,
    )


def _safe_observation(
    invocation: UnifiedToolInvocation,
    result: UnifiedToolResult,
) -> ReActObservation:
    payload = safe_observation_payload(invocation, result)
    return ReActObservation(
        tool_id=str(payload["toolId"]),
        ok=bool(payload["ok"]),
        values=dict(payload["values"]),
        artifacts=[str(artifact) for artifact in payload["artifacts"]],
        error_code=(
            str(payload["errorCode"])
            if payload["errorCode"] is not None
            else None
        ),
    )


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)


def _dump_observations(observations: list[ReActObservation]) -> list[dict[str, Any]]:
    return [observation.model_dump(mode="json") for observation in observations]


def _failed_result(
    error_code: str,
    *,
    tool_call_count: int,
    observations: list[ReActObservation],
) -> ReActResult:
    return ReActResult(
        ok=False,
        text="",
        tool_call_count=tool_call_count,
        observations=_dump_observations(observations),
        error_code=error_code,
    )
