from __future__ import annotations

from agent_service.agent_run_state import AgentRunState
from agent_service.goal_spec import GoalSpec
from agent_service.schemas import (
    AgentMessageRequest,
    Attachment,
    GraphNode,
    RunGraph,
    RunGraphRequest,
    RunAttachment,
    RunMode,
    UserMessage,
)


def test_from_message_request_preserves_request_context_without_alias_leaks() -> None:
    graph = _sample_graph()
    request = AgentMessageRequest(
        task_id="task-state",
        content="Research and compare current Python packaging tools",
        attachments=[
            Attachment(
                attachment_id="doc-1",
                name="notes.docx",
                path=r"C:\Users\Drew\Desktop\notes.docx",
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
        inquiry_choice="research_flow",
        current_graph=graph,
        has_run_history=True,
        artifact_refs=["artifact-1"],
        pending_choice={"id": "confirm_overwrite", "kind": "full_replan"},
        model_session_id="model-session-1",
    )

    state = AgentRunState.from_message_request(request)

    assert state.task_id == "task-state"
    assert state.run_id is None
    assert state.message == UserMessage(
        task_id="task-state",
        content="Research and compare current Python packaging tools",
        attachments=list(request.attachments),
        model_session_id="model-session-1",
    )
    assert state.inquiry_choice == "research_flow"
    assert state.current_graph == graph
    assert state.has_run_history is True
    assert state.artifact_refs == ["artifact-1"]
    assert state.pending_choice == {"id": "confirm_overwrite", "kind": "full_replan"}
    assert state.goal_spec is None
    assert state.route_decision is None
    assert state.intent is None
    assert state.project_path is None
    assert state.run_mode is None
    assert state.disabled_tool_ids == []
    assert state.approved_permissions == []


def test_from_message_request_copies_mutable_lists() -> None:
    request = AgentMessageRequest(
        task_id="task-state-copy",
        content="hello",
        attachments=[],
        artifact_refs=["artifact-1"],
    )

    state = AgentRunState.from_message_request(request)
    state.artifact_refs.append("artifact-2")

    assert request.artifactRefs == ["artifact-1"]
    assert state.artifact_refs == ["artifact-1", "artifact-2"]


def test_from_user_message_supports_existing_graph_wrappers() -> None:
    message = UserMessage(task_id="direct-message", content="hello")
    graph = _sample_graph()

    state = AgentRunState.from_user_message(
        message,
        inquiry_choice="quick_answer",
        current_graph=graph,
        has_run_history=True,
        artifact_refs=["artifact-1"],
        pending_choice={"id": "confirm_overwrite"},
    )

    assert state.task_id == "direct-message"
    assert state.message == message
    assert state.inquiry_choice == "quick_answer"
    assert state.current_graph == graph
    assert state.has_run_history is True
    assert state.artifact_refs == ["artifact-1"]
    assert state.pending_choice == {"id": "confirm_overwrite"}


def test_from_run_graph_request_preserves_execution_context() -> None:
    graph = _sample_graph(metadata={"question": "Research Python packaging"})
    request = RunGraphRequest(
        task_id="task-run",
        run_id="run-1",
        project_path=r"D:\Projects\demo.alita",
        attachments=[
            RunAttachment(
                attachment_id="doc-1",
                name="notes.md",
                path=r"D:\Projects\notes.md",
                size_bytes=64,
                mime_type="text/markdown",
            )
        ],
        graph=graph,
        mode=RunMode(type="from_node", node_id="node-1", source_run_id="run-0"),
        disabled_tool_ids=["document.disabled"],
        approved_permissions=["network"],
        model_session_id="model-session-2",
    )

    state = AgentRunState.from_run_graph_request(request)

    assert state.task_id == "task-run"
    assert state.run_id == "run-1"
    assert state.message == UserMessage(
        task_id="task-run",
        content="Research Python packaging",
        attachments=list(request.attachments),
        model_session_id="model-session-2",
    )
    assert state.current_graph == graph
    assert state.project_path == r"D:\Projects\demo.alita"
    assert state.run_mode == request.mode
    assert state.disabled_tool_ids == ["document.disabled"]
    assert state.approved_permissions == ["network"]


def test_from_run_graph_request_uses_empty_content_when_question_metadata_is_missing() -> None:
    request = RunGraphRequest(
        task_id="task-run-empty",
        run_id="run-empty",
        project_path=r"D:\Projects\demo.alita",
        attachments=[],
        graph=_sample_graph(),
    )

    state = AgentRunState.from_run_graph_request(request)

    assert state.message.content == ""


def test_with_routing_returns_updated_copy_without_mutating_original() -> None:
    state = AgentRunState.from_user_message(
        UserMessage(task_id="task-routing", content="hello")
    )
    goal_spec = GoalSpec(
        goal="hello",
        task_type="chat",
        deliverable="chat_answer",
        success_criteria=["回答用户的问题"],
        risk_level="read_only",
        confidence=0.7,
    )

    updated = state.with_routing(
        intent="chat",
        route_decision={
            "intent": {"kind": "chat"},
            "inquiry": None,
            "reason": "conversation",
            "missing_inputs": [],
        },
        goal_spec=goal_spec,
    )

    assert state.intent is None
    assert state.route_decision is None
    assert state.goal_spec is None
    assert updated.intent == "chat"
    assert updated.route_decision == {
        "intent": {"kind": "chat"},
        "inquiry": None,
        "reason": "conversation",
        "missing_inputs": [],
    }
    assert updated.goal_spec == goal_spec


def _sample_graph(metadata: dict | None = None) -> RunGraph:
    return RunGraph(
        graphId="graph-state",
        nodes=[
            GraphNode(
                nodeId="node-1",
                nodeType="planning",
                displayName="Plan",
                status="waiting",
                summary="Plan the task.",
                createdBy="agent",
                position={"x": 0, "y": 0},
            )
        ],
        edges=[],
        metadata=metadata or {},
    )
