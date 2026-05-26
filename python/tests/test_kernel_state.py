from __future__ import annotations

from agent_service.kernel_state import AgentRunBudget, build_agent_run_state
from agent_service.schemas import Attachment, RunGraph, UserMessage


def test_build_agent_run_state_captures_message_goal_and_route() -> None:
    message = UserMessage(
        task_id="task-doc",
        content="整理这个文档并导出 PDF",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="input.docx",
                path="workspace/input.docx",
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
        model_session_id="model-session-1",
    )

    state = build_agent_run_state(
        message,
        model_session_id=message.model_session_id,
        disabled_tool_ids=["internal:document.typst_compile"],
        approved_permissions=["write_project_artifact"],
    )

    assert state.task_id == "task-doc"
    assert state.message == message
    assert state.goal_spec.task_type == "document_processing"
    assert state.goal_spec.deliverable == "pdf_report"
    assert state.route_decision["intent"]["kind"] == "task"
    assert state.model_session_id == "model-session-1"
    assert state.disabled_tool_ids == ["internal:document.typst_compile"]
    assert state.approved_permissions == ["write_project_artifact"]
    assert state.budget.max_planning_steps == 16
    assert state.events == []


def test_build_agent_run_state_preserves_current_graph_and_run_context() -> None:
    graph = RunGraph(
        graphId="graph-1",
        nodes=[
            {
                "nodeId": "task-analysis",
                "nodeType": "planning",
                "displayName": "Task Analysis",
                "status": "completed",
                "summary": "Existing graph.",
                "createdBy": "agent",
                "position": {"x": 0, "y": 0},
            }
        ],
        edges=[],
    )

    state = build_agent_run_state(
        UserMessage(task_id="task-1", content="hello"),
        run_id="run-1",
        current_graph=graph,
        has_run_history=True,
        artifact_refs=["artifact-1"],
        pending_choice={"id": "confirm_overwrite"},
    )

    assert state.run_id == "run-1"
    assert state.current_graph == graph
    assert state.has_run_history is True
    assert state.artifact_refs == ["artifact-1"]
    assert state.pending_choice == {"id": "confirm_overwrite"}
    assert state.execution_mode == "message"


def test_agent_run_budget_defaults_are_safe() -> None:
    budget = AgentRunBudget()

    assert budget.max_planning_steps == 16
    assert budget.max_react_steps == 0
    assert budget.max_tool_calls == 0
    assert budget.max_runtime_ms == 120_000
