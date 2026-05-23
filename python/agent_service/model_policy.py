from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal

from agent_service.schemas import GraphNode

ThinkingMode = Literal["off", "auto", "deep"]


class ModelCallProfile(str, Enum):
    FAST_CHAT = "fast_chat"
    FAST_FACTUAL = "fast_factual"
    DEEP_REASONING = "deep_reasoning"
    NODE_REASONING = "node_reasoning"


class ImmutableDict(Mapping[str, Any]):
    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self._values = MappingProxyType(
            {
                key: _freeze_extra_body_value(value)
                for key, value in (values or {}).items()
            },
        )

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False

        return dict(self.items()) == dict(other.items())

    def __repr__(self) -> str:
        return repr(self._values)


def _freeze_extra_body_value(value: Any) -> Any:
    if isinstance(value, ImmutableDict):
        return value
    if isinstance(value, Mapping):
        return ImmutableDict(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_extra_body_value(item) for item in value)

    return value


def _thaw_extra_body_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _thaw_extra_body_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_extra_body_value(item) for item in value]

    return deepcopy(value)


@dataclass(frozen=True)
class ModelCallPolicy:
    profile: ModelCallProfile
    temperature: float
    max_tokens: int
    thinking: ThinkingMode
    preserve_thinking: bool = False
    stream: bool | None = None
    extra_body: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_body", ImmutableDict(self.extra_body))


@dataclass(frozen=True)
class ResolvedModelCallSettings:
    policy: ModelCallPolicy
    temperature: float
    max_tokens: int
    stream: bool
    extra_body: dict[str, Any]


FAST_CHAT_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.FAST_CHAT,
    temperature=0.3,
    max_tokens=768,
    thinking="off",
    preserve_thinking=False,
    stream=True,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
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
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        },
    },
)

NODE_REASONING_POLICY = ModelCallPolicy(
    profile=ModelCallProfile.NODE_REASONING,
    temperature=0.2,
    max_tokens=4096,
    thinking="auto",
    preserve_thinking=True,
    stream=False,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": True,
            "preserve_thinking": True,
        },
    },
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
        extra_body=_thaw_extra_body_value(policy.extra_body),
    )
