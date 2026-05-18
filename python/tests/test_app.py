from fastapi.testclient import TestClient

from agent_service.app import app


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
