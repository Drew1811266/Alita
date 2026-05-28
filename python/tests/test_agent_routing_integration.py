from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_service.app import app
from agent_service.execution import run_graph_events
from agent_service.graph import run_agent
from agent_service.model_client import ChatMessage
from agent_service.model_policy import ModelCallPolicy
from agent_service.schemas import RunGraph, RunGraphRequest, UserMessage
from agent_service.web_search import SearchResponse, SearchResult


class FakeModelClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []

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


def test_complex_web_inquiry_first_asks_quick_vs_research_choice() -> None:
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
    assert [event["type"] for event in events] == ["research.choice_required"]
    assert events[0]["payload"]["taskId"] == "complex-web"
    assert [choice["id"] for choice in events[0]["payload"]["choices"]] == [
        "quick_answer",
        "research_flow",
    ]


def test_research_choice_creates_graph_and_markdown_report(tmp_path: Path) -> None:
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
    graph_event = response.json()[0]
    assert graph_event["type"] == "node_graph.created"
    graph = graph_event["payload"]["graph"]

    provider = SequencedSearchProvider(
        {
            question: [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="Python packaging guide",
                            url="https://packaging.python.org/en/latest/",
                            snippet="Official guide to Python packaging tools.",
                        )
                    ]
                )
            ],
            f"{question} official sources": [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="Python docs",
                            url="https://docs.python.org/3/",
                            snippet="Python documentation for packaging references.",
                        )
                    ]
                )
            ],
        }
    )
    run_request = RunGraphRequest(
        task_id="research-task",
        run_id="research-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=graph,
    )

    run_events = list(run_graph_events(run_request, search_provider=provider))

    assert provider.queries == [question, f"{question} official sources"]
    assert graph["metadata"]["kind"] == "research"
    artifact_event = next(event for event in run_events if event.type == "artifact.created")
    report_path = Path(artifact_event.payload["path"])
    assert report_path.suffix == ".md"
    assert report_path.read_text(encoding="utf-8").startswith("# Research Report")
    completed = next(event for event in run_events if event.type == "research.completed")
    assert completed.payload["reportArtifactPath"] == str(report_path)
    assert completed.payload["acceptedSources"]
    assert run_events[-1].type == "task.completed"


def test_task_message_creates_graph_with_planning_and_executable_nodes() -> None:
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
    assert [event["type"] for event in events] == ["node_graph.created"]
    graph = events[0]["payload"]["graph"]
    planning_nodes = [node for node in graph["nodes"] if node["nodeType"] == "planning"]
    executable_nodes = [
        node
        for node in graph["nodes"]
        if node["nodeType"] in {"fixed_tool", "model", "temporary_script", "output"}
    ]
    assert [node["nodeId"] for node in planning_nodes] == [
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
        "capability-analysis",
        "tool-selection",
        "plan-review",
        "execution-order-planning",
    ]
    assert graph["metadata"]["planningMode"] == "deep"
    assert graph["metadata"]["planningTrace"]["review"]["hardBlockerCount"] == 0
    assert [node["nodeId"] for node in executable_nodes] == [
        "temporary-script-file-inspect",
        "task-output",
    ]
    route_decision = graph["metadata"]["routeDecision"]
    assert route_decision["intent"] == "task"
    assert route_decision["source"] == "deterministic"
    assert executable_nodes[0]["scriptReview"]["status"] == "not_reviewed"
    assert executable_nodes[0].get("estimate")
    assert executable_nodes[1]["nodeType"] == "output"


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


def test_full_replan_asks_for_overwrite_confirmation_when_artifacts_exist() -> None:
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
    assert [event["type"] for event in events] == [
        "graph.overwrite_confirmation_required"
    ]
    payload = events[0]["payload"]
    assert payload["previousGraphId"] == graph.graphId
    assert payload["pendingChoice"]["kind"] == "full_replan"
    assert [choice["id"] for choice in payload["choices"]] == [
        "confirm_overwrite",
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
