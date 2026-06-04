from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agent_service.app import app
from agent_service.execution import run_graph_events
from agent_service.graph import run_agent
from agent_service.model_client import (
    ChatDiagnosticsResponse,
    ChatMessage,
    ModelCallDiagnostics,
)
from agent_service.model_policy import ModelCallPolicy
from agent_service.schemas import RunGraph, RunGraphRequest, UserMessage
from agent_service.web_search import SearchResponse, SearchResult


class FakeModelClient:
    def __init__(
        self,
        reply: str,
        *,
        deep_payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []
        self.deep_payloads = list(deep_payloads or [])
        self.deep_calls: list[list[ChatMessage]] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        del temperature, max_tokens, policy
        self.calls.append(messages)
        return self.reply

    def chat_with_diagnostics(
        self,
        messages: list[ChatMessage],
        *,
        policy: ModelCallPolicy | None = None,
        **kwargs,
    ) -> ChatDiagnosticsResponse:
        del policy, kwargs
        self.deep_calls.append(messages)
        if len(self.deep_calls) > len(self.deep_payloads):
            raise AssertionError("unexpected deep planning model call")
        payload = self.deep_payloads[len(self.deep_calls) - 1]
        return ChatDiagnosticsResponse(
            content=json.dumps(payload),
            diagnostics=ModelCallDiagnostics(
                request_payload_had_thinking_params=True,
                enable_thinking_sent=True,
                preserve_thinking_sent=True,
                enable_thinking_value=True,
                preserve_thinking_value=True,
                fallback_used="none",
                effective_mode="deep",
            ),
        )


class SequencedSearchProvider:
    def __init__(self, responses_by_query: dict[str, list[SearchResponse]]) -> None:
        self.responses_by_query = {
            query: list(responses) for query, responses in responses_by_query.items()
        }
        self.queries: list[str] = []

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        responses = self.responses_by_query.get(query)
        if not responses:
            raise AssertionError(f"unexpected search query: {query}")
        return responses.pop(0)


def _reasoning_payload(next_action: str = "deep_planning") -> dict[str, Any]:
    return {
        "task_id": "task-deep",
        "task_understanding": "User needs a planned task graph.",
        "intent": "task",
        "complexity": "graph_task" if next_action == "deep_planning" else "simple",
        "why_this_path": "The request needs a reasoned plan before execution.",
        "confidence": 0.9,
        "needs_clarification": False,
        "required_capabilities": ["model.reasoning"],
        "next_action": next_action,
    }


def _plan_payload(step_ids: list[str]) -> dict[str, Any]:
    return {
        "plan_draft_id": "plan-dynamic",
        "task_understanding": "Create a custom plan from the user request.",
        "success_criteria": ["The plan directly addresses the user request."],
        "inputs": [],
        "assumptions": [],
        "missing_information": [],
        "candidate_strategies": [
            {
                "strategyId": "custom-plan",
                "summary": "Reason from the request instead of applying a template.",
                "tradeoffs": ["Requires confirmation before execution."],
            }
        ],
        "recommended_strategy": "custom-plan",
        "steps": [
            {
                "step_id": step_id,
                "title": f"Step {step_id}",
                "objective": f"Do {step_id}.",
                "rationale": f"{step_id} is needed for the requested outcome.",
                "inputs": [],
                "required_capabilities": ["model.reasoning"],
                "expected_output": f"Output for {step_id}.",
                "verification_criteria": [f"Verify {step_id}."],
                "depends_on": step_ids[:index],
            }
            for index, step_id in enumerate(step_ids)
        ],
        "required_capabilities": ["model.reasoning"],
        "risks": [],
        "verification_plan": ["Review the plan before execution."],
    }


def _patch_deep_planning_model(
    monkeypatch,
    *,
    step_ids: list[str] | None = None,
) -> FakeModelClient:
    client = FakeModelClient(
        "unused",
        deep_payloads=[
            _reasoning_payload(),
            _plan_payload(step_ids or ["understand", "execute"]),
        ],
    )
    monkeypatch.setattr(
        "agent_service.app.create_model_client",
        lambda *args, **kwargs: client,
    )
    return client


def _phase2_graph_confirmation_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_types = [event["type"] for event in events]
    assert event_types[-3:] == [
        "node_graph.created",
        "planning.confirmation_required",
        "planning.interrupted",
    ]
    return next(event for event in events if event["type"] == "node_graph.created")


def test_chat_message_returns_direct_assistant_response_with_no_graph() -> None:
    client = FakeModelClient("Direct assistant answer.")

    events = run_agent(
        UserMessage(task_id="chat-task", content="Hello, what can you do?"),
        model_client=client,
    )

    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["message"]["content"] == "Direct assistant answer."
    assert "graph" not in events[0].payload
    assert client.calls


def test_simple_web_inquiry_returns_source_metadata_with_no_graph() -> None:
    provider = SequencedSearchProvider(
        {
            "What is the latest Python release?": [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="Python docs",
                            url="https://docs.python.org/3/",
                            snippet="Official Python documentation.",
                        ),
                        SearchResult(
                            title="Top10 Python releases",
                            url="https://top10.example/python",
                            snippet="Copied release list.",
                        ),
                    ]
                )
            ]
        }
    )

    events = run_agent(
        UserMessage(task_id="simple-web", content="What is the latest Python release?"),
        search_provider=provider,
    )

    assert provider.queries == ["What is the latest Python release?"]
    assert [event.type for event in events] == ["message.created"]
    payload = events[0].payload
    assert "graph" not in payload
    assert payload["sources"][0]["ref"] == "[1]"
    assert payload["sources"][0]["title"] == "Python docs"
    assert payload["sources"][0]["url"] == "https://docs.python.org/3/"
    assert payload["sources"][0]["accepted"] is True
    assert payload["sourceMetadata"]["answerStatus"] == "answered"
    assert payload["sourceMetadata"]["accepted"] == payload["sources"]
    assert payload["sourceMetadata"]["rejected"] == payload["rejectedSources"]


def test_complex_web_inquiry_enters_deep_planning_confirmation(monkeypatch) -> None:
    client = _patch_deep_planning_model(
        monkeypatch,
        step_ids=["compare_options", "recommend_path"],
    )

    response = TestClient(app).post(
        "/agent/message",
        json={
            "task_id": "complex-web",
            "content": "Research and compare current Python packaging tools",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    events = response.json()
    graph_event = _phase2_graph_confirmation_event(events)
    assert len(client.deep_calls) == 2
    assert "research.choice_required" not in [event["type"] for event in events]
    graph = graph_event["payload"]["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    assert [
        node["metadata"]["sourcePlanStepId"]
        for node in graph["nodes"]
        if "sourcePlanStepId" in node.get("metadata", {})
    ] == ["compare_options", "recommend_path"]


def test_research_choice_enters_deep_planning_confirmation(monkeypatch) -> None:
    client = _patch_deep_planning_model(
        monkeypatch,
        step_ids=["research_sources", "synthesize_report"],
    )
    question = "Research and compare current Python packaging tools"
    response = TestClient(app).post(
        "/agent/research/choose",
        json={
            "task_id": "research-task",
            "content": question,
            "attachments": [],
            "inquiry_choice": "research_flow",
        },
    )
    assert response.status_code == 200
    events = response.json()
    graph_event = _phase2_graph_confirmation_event(events)
    assert len(client.deep_calls) == 2
    graph = graph_event["payload"]["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    assert [
        node["metadata"]["sourcePlanStepId"]
        for node in graph["nodes"]
        if "sourcePlanStepId" in node.get("metadata", {})
    ] == ["research_sources", "synthesize_report"]


def test_task_message_creates_deep_plan_graph_awaiting_confirmation(monkeypatch) -> None:
    client = _patch_deep_planning_model(
        monkeypatch,
        step_ids=["inspect_csv", "write_counter"],
    )

    response = TestClient(app).post(
        "/agent/message",
        json={
            "task_id": "task-planner",
            "content": "Create a Python script that counts rows in a CSV file.",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    events = response.json()
    graph_event = _phase2_graph_confirmation_event(events)
    assert len(client.deep_calls) == 2
    graph = graph_event["payload"]["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    assert "plannerChain" not in graph["metadata"]
    assert [
        node["metadata"]["sourcePlanStepId"]
        for node in graph["nodes"]
        if "sourcePlanStepId" in node.get("metadata", {})
    ] == ["inspect_csv", "write_counter"]
    confirmation = next(
        event for event in events if event["type"] == "planning.confirmation_required"
    )
    assert confirmation["payload"]["pendingChoice"]["kind"] == "planning.confirmation"
    assert [choice["id"] for choice in confirmation["payload"]["choices"]] == [
        "approve",
        "revise",
        "cancel",
    ]


def test_route_metadata_does_not_change_graph_created_event_shape(monkeypatch) -> None:
    _patch_deep_planning_model(monkeypatch, step_ids=["shape_check"])

    response = TestClient(app).post(
        "/agent/message",
        json={
            "task_id": "task-route-shape",
            "content": "Create a Python script that counts rows in a CSV file.",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    events = response.json()
    graph_event = _phase2_graph_confirmation_event(events)
    assert set(graph_event.keys()) == {"type", "payload"}
    assert set(graph_event["payload"].keys()) == {"graph"}
    graph = graph_event["payload"]["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"


def test_high_risk_temporary_script_blocks_execution_until_approved(
    tmp_path: Path,
) -> None:
    graph = _temporary_script_graph()
    request = RunGraphRequest(
        task_id="script-task",
        run_id="script-run-blocked",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=graph,
    )

    blocked_events = list(run_graph_events(request))

    assert "node.running" not in [event.type for event in blocked_events]
    permission_event = next(
        event for event in blocked_events if event.type == "node.needs_permission"
    )
    fingerprint = permission_event.payload["scriptReview"]["approvalFingerprint"]
    assert permission_event.payload["nodeId"] == "temporary-script"
    assert blocked_events[-1].type == "task.failed"

    approval_response = TestClient(app).post(
        "/agent/scripts/approve",
        json={
            "task_id": "script-task",
            "node_id": "temporary-script",
            "approval_fingerprint": fingerprint,
            "current_graph": graph,
        },
    )

    assert approval_response.status_code == 200
    approved_graph = approval_response.json()[0]["payload"]["graph"]
    approved_events = list(
        run_graph_events(
            RunGraphRequest(
                task_id="script-task",
                run_id="script-run-approved",
                project_path=str(tmp_path / "project.alita"),
                attachments=[],
                graph=approved_graph,
            )
        )
    )

    assert [event.payload["nodeId"] for event in approved_events if event.type == "node.running"] == [
        "temporary-script",
        "task-output",
    ]
    assert approved_events[-1].type == "task.completed"


def test_graph_feedback_updates_target_and_downstream_nodes_preserving_unaffected_nodes() -> None:
    graph = _feedback_graph()

    events = run_agent(
        UserMessage(
            task_id="feedback-task",
            content="Change the Extract Data node to read JSON files.",
        ),
        current_graph=graph,
    )

    assert [event.type for event in events] == ["graph.replanned"]
    updated = RunGraph.model_validate(events[0].payload["graph"])
    nodes = {node.nodeId: node for node in updated.nodes}
    assert updated.metadata["feedbackUpdatedNodeIds"] == [
        "extract-data",
        "summarize-data",
    ]
    assert "read JSON files" in nodes["extract-data"].summary
    assert "Upstream feedback changed extract-data." in nodes["summarize-data"].summary
    assert nodes["task-analysis"].summary == "Understand the task."
    assert nodes["independent-output"].summary == "Leave this output unchanged."
    assert nodes["independent-output"].status == "completed"
    assert nodes["independent-output"].lastRun == {
        "runId": "run-independent",
        "completedAt": "2026-05-19T00:00:00Z",
    }


def test_full_replan_creates_deep_plan_confirmation_before_execution(monkeypatch) -> None:
    _patch_deep_planning_model(monkeypatch, step_ids=["replan_from_feedback"])
    graph = _feedback_graph()

    response = TestClient(app).post(
        "/agent/message",
        json={
            "task_id": "feedback-task",
            "content": "Restart, the direction is wrong.",
            "attachments": [],
            "current_graph": graph.model_dump(),
            "artifact_refs": ["artifact-1"],
        },
    )

    assert response.status_code == 200
    events = response.json()
    event_types = [event["type"] for event in events]
    assert "graph.overwrite_confirmation_required" not in event_types
    graph_event = _phase2_graph_confirmation_event(events)
    planned_graph = graph_event["payload"]["graph"]
    assert planned_graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    confirmation = next(
        event for event in events if event["type"] == "planning.confirmation_required"
    )
    assert confirmation["payload"]["pendingChoice"]["kind"] == "planning.confirmation"
    assert [choice["id"] for choice in confirmation["payload"]["choices"]] == [
        "approve",
        "revise",
        "cancel",
    ]


def _temporary_script_graph() -> dict:
    return {
        "graphId": "temporary-script-graph",
        "nodes": [
            {
                "nodeId": "task-analysis",
                "nodeType": "planning",
                "displayName": "Task Analysis",
                "status": "completed",
                "inputPorts": [],
                "outputPorts": [],
                "dependencies": [],
                "summary": "Plan the script.",
                "createdBy": "agent",
                "artifactRefs": [],
                "retryCount": 0,
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "temporary-script",
                "nodeType": "temporary_script",
                "displayName": "Temporary script",
                "status": "waiting",
                "inputPorts": [],
                "outputPorts": [],
                "dependencies": ["task-analysis"],
                "summary": "Inspect project CSV files.",
                "createdBy": "agent",
                "artifactRefs": [],
                "retryCount": 0,
                "scriptReview": _script_review(),
                "position": {"x": 180, "y": 0},
            },
            {
                "nodeId": "task-output",
                "nodeType": "output",
                "displayName": "Task output",
                "status": "waiting",
                "inputPorts": [],
                "outputPorts": [],
                "dependencies": ["temporary-script"],
                "summary": "Summarize script output.",
                "createdBy": "agent",
                "artifactRefs": [],
                "retryCount": 0,
                "position": {"x": 360, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "task-analysis-temporary-script",
                "source": "task-analysis",
                "target": "temporary-script",
            },
            {
                "id": "temporary-script-task-output",
                "source": "temporary-script",
                "target": "task-output",
            },
        ],
    }


def _script_review() -> dict:
    return {
        "status": "not_reviewed",
        "summary": "Generated script needs approval before it reads project files.",
        "permissions": ["read_project_files"],
        "riskLevel": "high",
        "requiresApproval": True,
        "codePreview": "print('inspect csv')",
        "inputContract": {"path": "project-relative CSV path"},
        "outputContract": {"summary": "text"},
        "approvalFingerprint": None,
    }


def _feedback_graph() -> RunGraph:
    return RunGraph(
        graphId="feedback-graph",
        nodes=[
            _feedback_node(
                "task-analysis",
                "Task Analysis",
                "Understand the task.",
                node_type="planning",
            ),
            _feedback_node("extract-data", "Extract Data", "Extract rows from CSV."),
            _feedback_node(
                "summarize-data",
                "Summarize Data",
                "Summarize extracted rows.",
                dependencies=["extract-data"],
            ),
            _feedback_node(
                "independent-output",
                "Independent Output",
                "Leave this output unchanged.",
                node_type="output",
                status="completed",
                last_run={
                    "runId": "run-independent",
                    "completedAt": "2026-05-19T00:00:00Z",
                },
            ),
        ],
        edges=[
            {
                "id": "extract-data-summarize-data",
                "source": "extract-data",
                "target": "summarize-data",
            }
        ],
    )


def _feedback_node(
    node_id: str,
    display_name: str,
    summary: str,
    *,
    node_type: str = "model",
    dependencies: list[str] | None = None,
    status: str = "waiting",
    last_run: dict | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": display_name,
        "status": status,
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies or [],
        "summary": summary,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": 0, "y": 0},
    }
    if last_run is not None:
        node["lastRun"] = last_run
    return node
