from __future__ import annotations

from agent_service.model_policy import (
    DEEP_REASONING_POLICY,
    FAST_CHAT_POLICY,
    FAST_FACTUAL_POLICY,
    NODE_REASONING_POLICY,
    ModelCallProfile,
    apply_policy_defaults,
    policy_for_agent_intent,
    policy_for_graph_node,
)
from agent_service.schemas import GraphNode


def _node(node_id: str, node_type: str, *, model_ref: str | None = None) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType=node_type,
        displayName=node_id,
        status="waiting",
        inputPorts=[],
        outputPorts=[],
        dependencies=[],
        modelRef=model_ref,
        summary="test node",
        createdBy="agent",
        artifactRefs=[],
        retryCount=0,
        position={"x": 0, "y": 0},
    )


def test_policy_for_chat_intents_uses_fast_chat() -> None:
    assert policy_for_agent_intent("chat").profile == ModelCallProfile.FAST_CHAT
    assert (
        policy_for_agent_intent("local_inquiry").profile
        == ModelCallProfile.FAST_CHAT
    )


def test_policy_for_simple_web_intents_uses_fast_factual() -> None:
    assert (
        policy_for_agent_intent("web_simple_inquiry").profile
        == ModelCallProfile.FAST_FACTUAL
    )
    assert (
        policy_for_agent_intent("web_complex_choice").profile
        == ModelCallProfile.FAST_FACTUAL
    )


def test_policy_for_task_and_research_intents_uses_deep_reasoning() -> None:
    assert policy_for_agent_intent("task").profile == ModelCallProfile.DEEP_REASONING
    assert (
        policy_for_agent_intent("web_complex_research_flow").profile
        == ModelCallProfile.DEEP_REASONING
    )


def test_policy_for_research_report_synthesis_node_uses_deep_reasoning() -> None:
    policy = policy_for_graph_node(
        _node(
            "research-report-synthesis",
            "model",
            model_ref="research-report-synthesizer",
        ),
        graph_metadata={"kind": "research"},
    )

    assert policy.profile == ModelCallProfile.DEEP_REASONING


def test_policy_for_normal_model_node_uses_node_reasoning() -> None:
    policy = policy_for_graph_node(
        _node(
            "content-organize",
            "model",
            model_ref="local-content-organizer",
        ),
    )

    assert policy.profile == ModelCallProfile.NODE_REASONING


def test_policy_for_non_model_fallback_node_uses_fast_chat() -> None:
    policy = policy_for_graph_node(_node("final-output", "output"))

    assert policy.profile == ModelCallProfile.FAST_CHAT


def test_apply_policy_defaults_preserves_explicit_overrides_and_profile() -> None:
    resolved = apply_policy_defaults(
        NODE_REASONING_POLICY,
        temperature=0.4,
        max_tokens=2048,
        stream=True,
    )

    assert resolved.policy.profile == ModelCallProfile.NODE_REASONING
    assert resolved.temperature == 0.4
    assert resolved.max_tokens == 2048
    assert resolved.stream is True


def test_policy_defaults_are_backend_agnostic() -> None:
    resolved = apply_policy_defaults(FAST_CHAT_POLICY)

    assert not hasattr(FAST_CHAT_POLICY, "extra_body")
    assert not hasattr(resolved, "extra_body")


def test_policy_constants_have_expected_profiles() -> None:
    assert FAST_CHAT_POLICY.profile == ModelCallProfile.FAST_CHAT
    assert FAST_FACTUAL_POLICY.profile == ModelCallProfile.FAST_FACTUAL
    assert DEEP_REASONING_POLICY.profile == ModelCallProfile.DEEP_REASONING
    assert NODE_REASONING_POLICY.profile == ModelCallProfile.NODE_REASONING
