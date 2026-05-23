from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from agent_service.schemas import GraphNode

ThinkingMode = Literal["off", "auto", "deep"]


class ModelCallProfile(str, Enum):
    FAST_CHAT = "fast_chat"
    FAST_FACTUAL = "fast_factual"
    DEEP_REASONING = "deep_reasoning"
    NODE_REASONING = "node_reasoning"


@dataclass(frozen=True)
class ModelCallPolicy:
    profile: ModelCallProfile
    temperature: float
    max_tokens: int
    thinking: ThinkingMode
    preserve_thinking: bool = False
    stream: bool | None = None


@dataclass(frozen=True)
class ResolvedModelCallSettings:
    policy: ModelCallPolicy
    temperature: float
    max_tokens: int
    stream: bool


FAST_CHAT_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.FAST_CHAT,
    temperature=0.3,
    max_tokens=768,
    thinking="off",
    preserve_thinking=False,
    stream=True,
)

FAST_FACTUAL_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.FAST_FACTUAL,
    temperature=0.2,
    max_tokens=1024,
    thinking="auto",
    preserve_thinking=False,
)

DEEP_REASONING_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.DEEP_REASONING,
    temperature=0.2,
    max_tokens=8192,
    thinking="deep",
    preserve_thinking=True,
    stream=False,
)

NODE_REASONING_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.NODE_REASONING,
    temperature=0.2,
    max_tokens=4096,
    thinking="auto",
    preserve_thinking=True,
    stream=False,
)

_FAST_CHAT_INTENTS = {
    "chat",
    "local_inquiry",
}
_FAST_FACTUAL_INTENTS = {
    "web_simple_inquiry",
    "web_complex_choice",
}
_DEEP_REASONING_INTENTS = {
    "task",
    "web_complex_task",
    "web_complex_research_flow",
}
_GRAPH_BUILDING_INTENT_HINTS = {
    "graph",
    "plan",
    "research_flow",
}
_REPORT_SYNTHESIS_HINTS = {
    "report-synthesis",
    "report_synthesis",
    "report-synthesizer",
    "report_synthesizer",
}


def policy_for_agent_intent(intent: str) -> ModelCallPolicy:
    normalized_intent = intent.strip().lower()

    if normalized_intent in _FAST_CHAT_INTENTS:
        return FAST_CHAT_POLICY
    if normalized_intent in _FAST_FACTUAL_INTENTS:
        return FAST_FACTUAL_POLICY
    if normalized_intent in _DEEP_REASONING_INTENTS:
        return DEEP_REASONING_POLICY
    if any(hint in normalized_intent for hint in _GRAPH_BUILDING_INTENT_HINTS):
        return DEEP_REASONING_POLICY

    return FAST_CHAT_POLICY


def policy_for_graph_node(
    node: GraphNode,
    *,
    graph_metadata: dict[str, Any] | None = None,
) -> ModelCallPolicy:
    metadata = graph_metadata or {}
    node_id = node.nodeId.lower()
    model_ref = (node.modelRef or "").lower()
    node_identifiers = f"{node_id} {model_ref}"

    if metadata.get("kind") == "research" and any(
        hint in node_identifiers for hint in _REPORT_SYNTHESIS_HINTS
    ):
        return DEEP_REASONING_POLICY

    if node.nodeType == "model" or bool(node.modelRef):
        return NODE_REASONING_POLICY

    return FAST_CHAT_POLICY


def apply_policy_defaults(
    policy: ModelCallPolicy,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool | None = None,
) -> ResolvedModelCallSettings:
    return ResolvedModelCallSettings(
        policy=policy,
        temperature=policy.temperature if temperature is None else temperature,
        max_tokens=policy.max_tokens if max_tokens is None else max_tokens,
        stream=(
            policy.stream
            if stream is None and policy.stream is not None
            else bool(stream)
        ),
    )
