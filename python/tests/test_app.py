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


def test_register_model_session_requires_sidecar_token(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from agent_service.app import app

    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "expected-token")
    client = TestClient(app)

    response = client.post(
        "/agent/model/session",
        json={
            "modelConfig": {
                "mode": "api",
                "providerId": "provider-1",
                "providerType": "openai",
                "displayName": "OpenAI",
                "baseUrl": "https://api.openai.com/v1",
                "model": "gpt-4.1",
                "apiKey": "sk-test",
            }
        },
    )

    assert response.status_code == 401


def test_register_model_session_returns_session_id_with_valid_sidecar_token(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "expected-token")
    client = TestClient(app)

    response = client.post(
        "/agent/model/session",
        json={
            "modelConfig": {
                "mode": "api",
                "providerId": "provider-1",
                "providerType": "openai",
                "displayName": "OpenAI",
                "baseUrl": "https://api.openai.com/v1",
                "model": "gpt-4.1",
                "apiKey": "sk-test",
            }
        },
        headers={"X-Alita-Sidecar-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()["modelSessionId"].startswith("model-session-")
