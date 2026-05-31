import pytest
from fastapi.testclient import TestClient

from agent_service.agent_run_state import AgentRunState
from agent_service.app import app
from agent_service.schemas import AgentEvent, ScriptReviewState
from agent_service.script_review import script_review_fingerprint


def test_agent_message_endpoint_passes_agent_run_state_to_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AgentRunState] = []

    class FakeRuntimeEngine:
        def run_from_state(self, run_state: AgentRunState, **kwargs):
            del kwargs
            captured.append(run_state)
            return type(
                "RuntimeResult",
                (),
                {
                    "events": [
                        AgentEvent(
                            type="message.created",
                            payload={"message": {"content": "ok"}},
                        )
                    ]
                },
            )()

    monkeypatch.setattr(
        "agent_service.app._runtime_engine",
        lambda: FakeRuntimeEngine(),
        raising=False,
    )
    client = TestClient(app)
    graph = _temporary_script_graph()

    response = client.post(
        "/agent/message",
        json={
            "task_id": "task-state-endpoint",
            "content": "Restart, the direction is wrong.",
            "attachments": [],
            "current_graph": graph,
            "has_run_history": True,
            "artifact_refs": ["artifact-1"],
            "pending_choice": {"id": "confirm_overwrite", "kind": "full_replan"},
            "inquiry_choice": "quick_answer",
        },
    )

    assert response.status_code == 200
    assert len(captured) == 1
    run_state = captured[0]
    assert run_state.task_id == "task-state-endpoint"
    assert run_state.message.content == "Restart, the direction is wrong."
    assert run_state.inquiry_choice == "quick_answer"
    assert run_state.current_graph is not None
    assert run_state.has_run_history is True
    assert run_state.artifact_refs == ["artifact-1"]
    assert run_state.pending_choice == {
        "id": "confirm_overwrite",
        "kind": "full_replan",
    }


def test_research_choose_endpoint_passes_agent_run_state_to_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AgentRunState] = []

    class FakeRuntimeEngine:
        def run_from_state(self, run_state: AgentRunState, **kwargs):
            del kwargs
            captured.append(run_state)
            return type(
                "RuntimeResult",
                (),
                {
                    "events": [
                        AgentEvent(
                            type="research.choice_required",
                            payload={"taskId": run_state.task_id},
                        )
                    ]
                },
            )()

    monkeypatch.setattr(
        "agent_service.app._runtime_engine",
        lambda: FakeRuntimeEngine(),
        raising=False,
    )
    client = TestClient(app)

    response = client.post(
        "/agent/research/choose",
        json={
            "task_id": "research-state-endpoint",
            "content": "Research and compare current Python packaging tools",
            "attachments": [],
            "inquiry_choice": "research_flow",
        },
    )

    assert response.status_code == 200
    assert captured[0].task_id == "research-state-endpoint"
    assert captured[0].inquiry_choice == "research_flow"


def test_agent_message_stream_endpoint_passes_agent_run_state_to_streamer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AgentRunState] = []

    class FakeRuntimeEngine:
        def stream_from_state(self, run_state: AgentRunState, **kwargs):
            del kwargs
            captured.append(run_state)
            yield AgentEvent(
                type="message.completed",
                payload={"messageId": f"assistant-{run_state.task_id}"},
            )

    monkeypatch.setattr(
        "agent_service.app._runtime_engine",
        lambda: FakeRuntimeEngine(),
        raising=False,
    )
    client = TestClient(app)

    response = client.post(
        "/agent/message/stream",
        json={
            "task_id": "stream-state-endpoint",
            "content": "hello",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    assert "stream-state-endpoint" in response.text
    assert captured[0].task_id == "stream-state-endpoint"


def test_graph_run_stream_endpoint_passes_agent_run_state_to_executor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: list[AgentRunState] = []

    def fake_run_graph_events(
        request,
        *,
        run_state: AgentRunState,
        model_client,
        registry,
    ):
        del request, model_client, registry
        captured.append(run_state)
        yield AgentEvent(
            type="run.started",
            payload={"taskId": run_state.task_id, "runId": run_state.run_id},
        )

    monkeypatch.setattr("agent_service.app.run_graph_events", fake_run_graph_events)
    client = TestClient(app)

    response = client.post(
        "/agent/graph/run/stream",
        json={
            "task_id": "graph-state-endpoint",
            "run_id": "graph-state-run",
            "project_path": str(tmp_path / "demo.alita"),
            "attachments": [],
            "graph": {
                "graphId": "graph-state",
                "nodes": [],
                "edges": [],
                "metadata": {"question": "Summarize the graph"},
            },
        },
    )

    assert response.status_code == 200
    assert "graph-state-run" in response.text
    assert len(captured) == 1
    assert captured[0].task_id == "graph-state-endpoint"
    assert captured[0].run_id == "graph-state-run"
    assert captured[0].message.content == "Summarize the graph"


def test_agent_message_stream_returns_sse_events() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/message/stream",
        json={
            "task_id": "task-stream",
            "content": "",
            "attachments": [
                {
                    "attachment_id": "a1",
                    "name": "input.docx",
                    "path": "workspace/inputs/input.docx",
                    "size_bytes": 100,
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data:" in response.text
    assert "node_graph.created" in response.text


def test_agent_message_stream_returns_planning_progress_before_task_graph() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/message/stream",
        json={
            "task_id": "task-stream-plan",
            "content": "Create a Python script that counts rows in a CSV file.",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    assert "planning.progress" in response.text
    assert response.text.index("planning.progress") < response.text.index(
        "node_graph.created"
    )
    assert "context-gathering" in response.text
    assert "plan-review" in response.text


def test_agent_message_complex_inquiry_default_returns_research_choice_payload() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/message",
        json={
            "task_id": "task-choice",
            "content": "Research and compare current Python packaging tools",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["type"] for event in events] == ["research.choice_required"]
    assert events[0]["payload"] == {
        "taskId": "task-choice",
        "prompt": "This question can be answered quickly or turned into a research flow. Choose how to proceed.",
        "choices": [
            {
                "id": "quick_answer",
                "label": "Quick answer",
                "description": "Search the web now and return a concise sourced answer.",
            },
            {
                "id": "research_flow",
                "label": "Research flow",
                "description": "Create a research graph for planning, source review, and report synthesis.",
            },
        ],
    }


def test_agent_message_complex_inquiry_research_flow_choice_returns_graph() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/message",
        json={
            "task_id": "task-research-flow",
            "content": "Research and compare current Python packaging tools",
            "attachments": [],
            "inquiry_choice": "research_flow",
        },
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["type"] for event in events] == ["node_graph.created"]
    assert events[0]["payload"]["graph"]["graphId"] == "task-research-flow-research-graph"


def test_research_choose_accepts_choice_request() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/research/choose",
        json={
            "task_id": "task-research-command",
            "content": "Research and compare current Python packaging tools",
            "attachments": [],
            "inquiry_choice": "research_flow",
        },
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["type"] for event in events] == ["node_graph.created"]
    assert events[0]["payload"]["graph"]["graphId"] == "task-research-command-research-graph"


def test_agent_message_stream_research_flow_choice_returns_graph_sse() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/message/stream",
        json={
            "task_id": "task-stream-research-flow",
            "content": "Research and compare current Python packaging tools",
            "attachments": [],
            "inquiry_choice": "research_flow",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "node_graph.created" in response.text
    assert "research-parallel-search" in response.text
    assert "research.choice_required" not in response.text


def test_agent_endpoints_require_sidecar_token_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "secret-token")
    client = TestClient(app)
    payload = {
        "task_id": "task-auth",
        "content": "hello",
        "attachments": [],
    }

    response = client.post("/agent/message", json=payload)

    assert response.status_code == 401

    authenticated_response = client.post(
        "/agent/message",
        json=payload,
        headers={"X-Alita-Sidecar-Token": "secret-token"},
    )
    assert authenticated_response.status_code == 200


def test_agent_endpoints_reject_non_alita_sidecar_token_header(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "secret-token")
    client = TestClient(app)
    non_alita_header = "X-" + "Boo" + "ook" + "-Sidecar-Token"
    payload = {
        "task_id": "task-auth-non-alita",
        "content": "hello",
        "attachments": [],
    }

    response = client.post(
        "/agent/message",
        json=payload,
        headers={non_alita_header: "secret-token"},
    )

    assert response.status_code == 401


def test_agent_message_without_token_or_bypass_returns_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALITA_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV", raising=False)
    client = TestClient(app)

    response = client.post(
        "/agent/message",
        json={
            "task_id": "task-auth-missing-token",
            "content": "hello",
            "attachments": [],
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "sidecar token is not configured"}


def test_agent_message_without_token_allows_explicit_dev_bypass() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/message",
        json={
            "task_id": "task-auth-dev-bypass",
            "content": "hello",
            "attachments": [],
        },
    )

    assert response.status_code == 200


def test_agent_message_preflight_allows_known_local_origin() -> None:
    client = TestClient(app)
    origin = "http://127.0.0.1:1420"

    response = client.options(
        "/agent/message",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Alita-Sidecar-Token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_agent_message_preflight_rejects_unknown_origin() -> None:
    client = TestClient(app)

    response = client.options(
        "/agent/message",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Alita-Sidecar-Token",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_graph_run_stream_returns_node_events(tmp_path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文内容", encoding="utf-8")
    client = TestClient(app)

    response = client.post(
        "/agent/graph/run/stream",
        json={
            "task_id": "task-run",
            "project_path": str(tmp_path / "demo.alita"),
            "attachments": [
                {
                    "attachment_id": "a1",
                    "name": "input.md",
                    "path": str(source),
                    "size_bytes": source.stat().st_size,
                    "mime_type": "text/markdown",
                }
            ],
            "graph": {
                "graphId": "graph-run",
                "nodes": [
                    {
                        "nodeId": "document-input",
                        "nodeType": "fixed_tool",
                        "displayName": "文档输入",
                        "status": "waiting",
                        "inputPorts": [],
                        "outputPorts": [],
                        "dependencies": [],
                        "toolRef": "document.receive_attachment",
                        "summary": "接收附件。",
                        "createdBy": "agent",
                        "artifactRefs": [],
                        "retryCount": 0,
                        "position": {"x": 0, "y": 0},
                    }
                ],
                "edges": [],
            },
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "node.running" in response.text
    assert "task.completed" in response.text


def test_cancel_graph_run_returns_cancelled_flag() -> None:
    client = TestClient(app)

    response = client.post("/agent/graph/run/cancel", json={"run_id": "missing"})

    assert response.status_code == 200
    assert response.json() == {"cancelled": False}


def test_scripts_reject_keeps_graph_blocked() -> None:
    client = TestClient(app)
    graph = _temporary_script_graph()

    response = client.post(
        "/agent/scripts/reject",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": graph,
            "reason": "Needs narrower file access.",
        },
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["type"] for event in events] == ["graph.replanned"]
    updated_node = events[0]["payload"]["graph"]["nodes"][0]
    assert updated_node["nodeId"] == "temporary-script"
    assert updated_node["status"] == "needs_permission"
    assert updated_node["scriptReview"]["status"] == "rejected"
    assert updated_node["scriptReview"]["approvalFingerprint"] is None


def test_scripts_approve_persists_fingerprint_and_unblocks_graph() -> None:
    client = TestClient(app)
    graph = _temporary_script_graph()
    expected_fingerprint = _script_review_fingerprint(
        graph["nodes"][0]["scriptReview"],
    )

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": graph,
            "approval_fingerprint": expected_fingerprint,
        },
    )

    assert response.status_code == 200
    events = response.json()
    assert [event["type"] for event in events] == ["graph.replanned"]
    updated_node = events[0]["payload"]["graph"]["nodes"][0]
    assert updated_node["status"] == "ready"
    assert updated_node["scriptReview"]["status"] == "approved"
    assert updated_node["scriptReview"]["approvalFingerprint"] == expected_fingerprint


def test_scripts_approve_requires_fingerprint() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": _temporary_script_graph(),
        },
    )

    assert response.status_code == 422


def test_scripts_approve_rejects_mismatched_fingerprint() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": _temporary_script_graph(),
            "approval_fingerprint": "stale-fingerprint",
        },
    )

    assert response.status_code == 409


def test_scripts_approve_rejects_stale_fingerprint_when_summary_changes() -> None:
    client = TestClient(app)
    graph = _temporary_script_graph()
    stale_fingerprint = _script_review_fingerprint(graph["nodes"][0]["scriptReview"])
    graph["nodes"][0]["scriptReview"]["summary"] = "Changed visible review summary."

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": graph,
            "approval_fingerprint": stale_fingerprint,
        },
    )

    assert response.status_code == 409


def test_scripts_approve_rejects_stale_fingerprint_when_requires_approval_changes() -> None:
    client = TestClient(app)
    graph = _temporary_script_graph()
    stale_fingerprint = _script_review_fingerprint(graph["nodes"][0]["scriptReview"])
    graph["nodes"][0]["scriptReview"]["requiresApproval"] = False

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": graph,
            "approval_fingerprint": stale_fingerprint,
        },
    )

    assert response.status_code == 409


def test_scripts_approve_rejects_unknown_node() -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "missing",
            "current_graph": _temporary_script_graph(),
            "approval_fingerprint": "stale-fingerprint",
        },
    )

    assert response.status_code == 404


def test_scripts_approve_rejects_non_temporary_node() -> None:
    client = TestClient(app)
    graph = _temporary_script_graph()
    graph["nodes"][0] = {
        **graph["nodes"][0],
        "nodeType": "fixed_tool",
        "toolRef": "document.receive_attachment",
        "scriptReview": None,
    }

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": graph,
            "approval_fingerprint": "stale-fingerprint",
        },
    )

    assert response.status_code == 400


def test_scripts_approve_rejects_temporary_script_without_review() -> None:
    client = TestClient(app)
    graph = _temporary_script_graph()
    graph["nodes"][0]["scriptReview"] = None

    response = client.post(
        "/agent/scripts/approve",
        json={
            "task_id": "task-script",
            "node_id": "temporary-script",
            "current_graph": graph,
            "approval_fingerprint": "stale-fingerprint",
        },
    )

    assert response.status_code == 400


def _temporary_script_graph() -> dict:
    return {
        "graphId": "graph-script-review",
        "nodes": [
            {
                "nodeId": "temporary-script",
                "nodeType": "temporary_script",
                "displayName": "Temporary script",
                "status": "needs_permission",
                "inputPorts": [],
                "outputPorts": [],
                "dependencies": [],
                "summary": "Inspect project files.",
                "createdBy": "agent",
                "artifactRefs": [],
                "retryCount": 0,
                "scriptReview": {
                    "status": "not_reviewed",
                    "summary": "Needs review before execution.",
                    "permissions": ["read_project_files"],
                    "riskLevel": "high",
                    "requiresApproval": True,
                    "codePreview": "print('preview')",
                    "inputContract": {"path": "string"},
                    "outputContract": {"result": "string"},
                    "approvalFingerprint": None,
                },
                "position": {"x": 0, "y": 0},
            }
        ],
        "edges": [],
        "metadata": {"preserve": True},
    }


def _script_review_fingerprint(script_review: dict) -> str:
    return script_review_fingerprint(ScriptReviewState(**script_review))
