from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from agent_service.harness_errors import HarnessError
from agent_service.node_catalog import NodeCatalogSnapshot, NodeDefinition


_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_GENERIC_MODEL_CAPABILITY = "model.reasoning"
_DEFAULT_CAPABILITIES = ["model.reasoning"]


@dataclass(frozen=True)
class NodeCatalogResolution:
    node: NodeDefinition
    matched_capabilities: list[str]
    selection_reason: str


@dataclass(frozen=True)
class NodeCatalogResolutionError(HarnessError):
    capabilities: list[str]


class NodeCatalogResolver:
    def __init__(self, snapshot: NodeCatalogSnapshot) -> None:
        self.snapshot = snapshot

    def resolve(
        self,
        required_capabilities: Iterable[str],
        preferred_node_ids: Iterable[str],
    ) -> NodeCatalogResolution:
        required = _dedupe_non_empty(required_capabilities)
        if not required:
            required = list(_DEFAULT_CAPABILITIES)
        effective_required = _effective_required_capabilities(required)
        preferred = _dedupe_non_empty(preferred_node_ids)
        available_nodes = [
            node
            for node in self.snapshot.nodes
            if node.availability.status == "available"
        ]

        unsupported = [
            capability
            for capability in effective_required
            if not any(
                _node_matches_capability(node, capability)
                for node in available_nodes
            )
        ]
        if unsupported:
            raise NodeCatalogResolutionError(
                code="unsupported_capability",
                message="Unsupported catalog capabilities: "
                + ", ".join(unsupported),
                capabilities=unsupported,
            )

        candidates = [
            (index, node, matched)
            for index, node in enumerate(available_nodes)
            if _node_satisfies_capabilities(node, effective_required)
            if (matched := _matched_capabilities(node, effective_required))
        ]
        if not candidates:
            raise NodeCatalogResolutionError(
                code="unsupported_capability",
                message="Unsupported catalog capability set: "
                + ", ".join(effective_required),
                capabilities=effective_required,
            )

        for preferred_node_id in preferred:
            for _, node, matched in candidates:
                if node.node_id == preferred_node_id:
                    return NodeCatalogResolution(
                        node=node,
                        matched_capabilities=matched,
                        selection_reason=f"preferred_node_id:{preferred_node_id}",
                    )

        _, selected, matched = min(
            candidates,
            key=lambda candidate: (
                -len(candidate[2]),
                -_exact_match_score(candidate[1], candidate[2]),
                _RISK_ORDER[candidate[1].permissions.risk_level],
                candidate[0],
            ),
        )
        return NodeCatalogResolution(
            node=selected,
            matched_capabilities=matched,
            selection_reason=_selection_reason(selected, matched),
        )


def _dedupe_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _effective_required_capabilities(required_capabilities: list[str]) -> list[str]:
    if (
        len(required_capabilities) > 1
        and _GENERIC_MODEL_CAPABILITY in required_capabilities
    ):
        return [
            capability
            for capability in required_capabilities
            if capability != _GENERIC_MODEL_CAPABILITY
        ]
    return list(required_capabilities)


def _node_satisfies_capabilities(
    node: NodeDefinition,
    required_capabilities: list[str],
) -> bool:
    return all(
        _node_matches_capability(node, capability)
        for capability in required_capabilities
    )


def _matched_capabilities(
    node: NodeDefinition,
    required_capabilities: list[str],
) -> list[str]:
    return [
        capability
        for capability in required_capabilities
        if _node_matches_capability(node, capability)
    ]


def _exact_match_score(node: NodeDefinition, matched_capabilities: list[str]) -> int:
    return sum(
        1
        for capability in matched_capabilities
        if capability == node.node_id
    )


def _node_matches_capability(node: NodeDefinition, capability: str) -> bool:
    return capability == node.node_id or capability in node.capabilities


def _selection_reason(node: NodeDefinition, matched: list[str]) -> str:
    for capability in matched:
        if capability == node.node_id:
            return f"matched_node_id:{capability}"
    return "ranked_match:" + ",".join(matched)
