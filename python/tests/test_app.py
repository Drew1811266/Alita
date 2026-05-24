from fastapi.testclient import TestClient

from agent_service.app import app


def register_api_model_session() -> str:
    from agent_service.model_sessions import DEFAULT_MODEL_SESSION_REGISTRY
    from agent_service.schemas import AgentModelConfig

    return DEFAULT_MODEL_SESSION_REGISTRY.register(
        AgentModelConfig(
            mode="api",
            provider_id="provider-1",
            provider_type="openai",
            display_name="OpenAI",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="sk-test",
        )
    )


class FakeSessionModelClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, messages, *, temperature=0.2, max_tokens=1024):
        return self.reply

    def stream_chat(self, messages, *, temperature=0.2, max_tokens=1024):
        yield self.reply


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


def test_agent_message_stream_uses_model_session_client(monkeypatch) -> None:
    from agent_service.model_sessions import DEFAULT_MODEL_SESSION_REGISTRY
    import agent_service.app as app_module

    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "secret-token")
    monkeypatch.setattr(
        app_module,
        "create_model_client",
        lambda config=None: FakeSessionModelClient("session stream reply"),
    )
    session_id = register_api_model_session()
    client = TestClient(app)

    response = client.post(
        "/agent/message/stream",
        json={
            "task_id": "task-stream-session",
            "content": "hello",
            "attachments": [],
            "model_session_id": session_id,
        },
        headers={"X-Alita-Sidecar-Token": "secret-token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "message.delta" in response.text
    assert "session stream reply" in response.text
    assert DEFAULT_MODEL_SESSION_REGISTRY.consume(session_id) is None


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


def test_agent_message_returns_409_for_whitespace_model_session_id(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "secret-token")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/agent/message",
        json={
            "task_id": "task-whitespace-session",
            "content": "hello",
            "attachments": [],
            "model_session_id": "   ",
        },
        headers={"X-Alita-Sidecar-Token": "secret-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Agent model session expired or was not found"


def test_agent_message_stream_returns_409_for_missing_model_session(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "secret-token")
    client = TestClient(app)

    response = client.post(
        "/agent/message/stream",
        json={
            "task_id": "task-missing-session",
            "content": "hello",
            "attachments": [],
            "model_session_id": "model-session-missing",
        },
        headers={"X-Alita-Sidecar-Token": "secret-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Agent model session expired or was not found"


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


def test_graph_run_stream_uses_model_session_client(tmp_path, monkeypatch) -> None:
    from agent_service.model_sessions import DEFAULT_MODEL_SESSION_REGISTRY
    from agent_service.run_journal import RunJournal
    import agent_service.app as app_module

    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "secret-token")
    monkeypatch.setattr(
        app_module,
        "create_model_client",
        lambda config=None: FakeSessionModelClient("graph session model output"),
    )
    session_id = register_api_model_session()
    source_run_id = "run-graph-session-source"
    RunJournal(
        project_path=str(tmp_path / "demo.alita"),
        run_id=source_run_id,
    ).write_node(
        "document-parse",
        {
            "nodeId": "document-parse",
            "status": "completed",
            "values": {"text": "source text"},
        },
    )
    client = TestClient(app)

    response = client.post(
        "/agent/graph/run/stream",
        json={
            "task_id": "task-graph-session",
            "project_path": str(tmp_path / "demo.alita"),
            "model_session_id": session_id,
            "mode": {
                "type": "from_node",
                "node_id": "content-organize",
                "source_run_id": source_run_id,
            },
            "graph": {
                "graphId": "graph-session",
                "nodes": [
                    {
                        "nodeId": "document-parse",
                        "nodeType": "fixed_tool",
                        "displayName": "文档解析",
                        "status": "waiting",
                        "inputPorts": [],
                        "outputPorts": [],
                        "dependencies": [],
                        "toolRef": "document.markitdown_convert",
                        "summary": "解析内容。",
                        "createdBy": "agent",
                        "artifactRefs": [],
                        "retryCount": 0,
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "nodeId": "content-organize",
                        "nodeType": "model",
                        "displayName": "内容整理",
                        "status": "waiting",
                        "inputPorts": [],
                        "outputPorts": [],
                        "dependencies": ["document-parse"],
                        "modelRef": "local-content-organizer",
                        "summary": "整理内容。",
                        "createdBy": "agent",
                        "artifactRefs": [],
                        "retryCount": 0,
                        "position": {"x": 0, "y": 0},
                    }
                ],
                "edges": [],
            },
        },
        headers={"X-Alita-Sidecar-Token": "secret-token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "node.run_recorded" in response.text
    assert "graph session model output" in response.text
    assert DEFAULT_MODEL_SESSION_REGISTRY.consume(session_id) is None


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


def test_register_model_session_validation_error_redacts_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "expected-token")
    client = TestClient(app)

    response = client.post(
        "/agent/model/session",
        json={
            "modelConfig": {
                "mode": "api",
                "model": "gpt-4.1",
                "apiKey": "sk-leak",
            }
        },
        headers={"X-Alita-Sidecar-Token": "expected-token"},
    )

    assert response.status_code == 422
    assert "sk-leak" not in response.text


def test_register_model_session_returns_session_id_with_valid_sidecar_token(
    monkeypatch,
) -> None:
    from agent_service.model_sessions import DEFAULT_MODEL_SESSION_REGISTRY

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
    session_id = response.json()["modelSessionId"]
    assert session_id.startswith("model-session-")

    stored_config = DEFAULT_MODEL_SESSION_REGISTRY.consume(session_id)
    assert stored_config is not None
    assert stored_config.mode == "api"
    assert stored_config.provider_id == "provider-1"
    assert stored_config.provider_type == "openai"
    assert stored_config.display_name == "OpenAI"
    assert stored_config.base_url == "https://api.openai.com/v1"
    assert stored_config.model == "gpt-4.1"
    assert stored_config.api_key == "sk-test"
    assert DEFAULT_MODEL_SESSION_REGISTRY.consume(session_id) is None
