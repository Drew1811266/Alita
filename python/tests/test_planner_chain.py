from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.planner_chain import (
    PlannerChain,
    PlannerChainError,
    PlannerChainRequest,
    _validate_graph_payload,
    route_context_from_payload,
)
from agent_service.schemas import Attachment, RunGraph, UserMessage
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"
DOCUMENT_NODE_IDS = [
    "document-input",
    "document-parse",
    "content-organize",
    "report-generate",
    "typst-export",
    "file-export",
]


def _tool_registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)


def _document_message() -> UserMessage:
    return UserMessage(
        task_id="task-document-chain",
        content="summarize this document as a PDF report",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="source.docx",
                path=str(PROJECT_ROOT / "fixtures" / "source.docx"),
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )


def _route_payload(**overrides):
    payload = {
        "intent": "task",
        "confidence": 0.88,
        "taskType": "code_task",
        "missingInputs": [],
        "requiredPermissions": ["read_project_files"],
        "toolCandidates": ["internal:file.inspect"],
        "reason": "User asks for a coding task.",
        "source": "deterministic",
        "shouldClarify": False,
        "clarificationPrompt": None,
    }
    payload.update(overrides)
    return payload


def _request_for(message: UserMessage, route_payload: dict) -> PlannerChainRequest:
    goal_spec = parse_goal_spec(message)
    registry = _tool_registry()
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT),
        registry,
    )
    return PlannerChainRequest(
        task_id=message.task_id,
        message=message,
        goal_spec=goal_spec,
        route=route_context_from_payload(route_payload),
        context=context,
    )


def test_route_context_parses_phase_d_payload_keys() -> None:
    route = route_context_from_payload(_route_payload())

    assert route.intent == "task"
    assert route.task_type == "code_task"
    assert route.required_permissions == ["read_project_files"]
    assert route.tool_candidates == ["internal:file.inspect"]


def test_route_context_safe_payload_scrubs_path_values() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    route = route_context_from_payload(
        _route_payload(
            missingInputs=[local_path],
            toolCandidates=[local_path],
            reason=f"Need {local_path}",
        )
    )

    payload_dump = repr(route.safe_payload())

    assert local_path not in payload_dump
    assert "Software Project" not in payload_dump
    assert "agent_service" not in payload_dump


def test_route_context_rejects_invalid_payload() -> None:
    with pytest.raises(PlannerChainError, match="invalid structured route payload"):
        route_context_from_payload({"intent": "task"})


def test_route_context_validation_error_does_not_leak_path_values() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"

    with pytest.raises(PlannerChainError) as exc_info:
        route_context_from_payload(_route_payload(taskType=local_path))

    message = str(exc_info.value)

    assert "invalid structured route payload" in message
    assert local_path not in message
    assert "Software Project" not in message
    assert "agent_service" not in message
    assert exc_info.value.__cause__ is None


def test_planner_chain_uses_planner_v2_for_document_processing() -> None:
    message = _document_message()
    request = _request_for(
        message,
        _route_payload(taskType="document_processing"),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "template.document.v1"
    assert result.strategy == "document_template"
    RunGraph.model_validate(result.graph_payload)
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == DOCUMENT_NODE_IDS
    metadata = result.graph_payload["metadata"]["plannerChain"]
    assert metadata["version"] == "planner_chain.v1"
    assert metadata["planner"] == "template.document.v1"
    assert metadata["strategy"] == "document_template"
    assert metadata["routeIntent"] == "task"
    assert metadata["taskType"] == "document_processing"
    assert metadata["routeSource"] == "deterministic"
    assert metadata["routeConfidence"] == 0.88
    assert metadata["toolCandidates"] == ["internal:file.inspect"]
    assert metadata["requiredPermissions"] == ["read_project_files"]


def test_planner_chain_does_not_treat_amd_as_markdown_token() -> None:
    message = UserMessage(
        task_id="task-amd-document-chain",
        content="Convert this AMD filing into an organized document summary.",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="amd-filing.docx",
                path=str(PROJECT_ROOT / "fixtures" / "amd-filing.docx"),
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )
    request = _request_for(
        message,
        _route_payload(taskType="document_processing"),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "template.document.v1"
    assert result.strategy == "document_template"
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == DOCUMENT_NODE_IDS


def test_planner_chain_uses_legacy_task_planner_for_code_task() -> None:
    message = UserMessage(
        task_id="task-code-chain",
        content="Create a Python script that counts rows in a CSV file.",
    )
    request = _request_for(
        message,
        _route_payload(taskType="code_task", toolCandidates=[]),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "legacy.task_planner.v1"
    assert result.strategy == "legacy_task_planner"
    RunGraph.model_validate(result.graph_payload)
    assert result.graph_payload["graphId"] == "task-code-chain-graph"
    assert result.graph_payload["metadata"]["plannerChain"]["strategy"] == (
        "legacy_task_planner"
    )
    assert [
        node["nodeId"]
        for node in result.graph_payload["nodes"]
        if node["nodeType"] == "planning"
    ] == [
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
        "capability-analysis",
        "tool-selection",
        "plan-review",
        "execution-order-planning",
    ]


def test_planner_chain_metadata_does_not_include_raw_route_paths() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    message = UserMessage(
        task_id="task-path-chain",
        content=f"Create a Python script that counts rows in {local_path}.",
    )
    request = _request_for(
        message,
        _route_payload(
            taskType="code_task",
            toolCandidates=[local_path],
            requiredPermissions=[local_path],
        ),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)
    metadata_dump = repr(result.graph_payload["metadata"])

    assert local_path not in metadata_dump
    assert "Software Project" not in metadata_dump
    assert "agent_service" not in metadata_dump
    assert "graph.py" not in metadata_dump


def test_planner_chain_preserves_markdown_conversion_legacy_strategy() -> None:
    message = UserMessage(
        task_id="doc-markdown-chain",
        content="Please convert this document to Markdown.",
        attachments=[
            Attachment(
                attachment_id="a-markdown",
                name="markdown-source.docx",
                path=str(PROJECT_ROOT / "fixtures" / "markdown-source.docx"),
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )
    request = _request_for(
        message,
        _route_payload(taskType="document_processing", toolCandidates=[]),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "legacy.task_planner.v1"
    assert result.strategy == "legacy_task_planner"
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "document-input",
        "document-parse",
        "file-export",
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
        "capability-analysis",
        "tool-selection",
        "plan-review",
        "execution-order-planning",
    ]
    assert "typst-export" not in {
        node["nodeId"] for node in result.graph_payload["nodes"]
    }


def test_planner_chain_rejects_missing_inputs_before_planning() -> None:
    message = UserMessage(task_id="missing-doc", content="summarize this document")
    request = _request_for(
        message,
        _route_payload(taskType="document_processing", missingInputs=["document_file"]),
    )

    with pytest.raises(PlannerChainError, match="missing inputs: document_file"):
        PlannerChain(tool_registry=_tool_registry()).plan(request)


def test_planner_chain_rejects_missing_inputs_without_leaking_paths() -> None:
    local_path = r"D:\Software Project\Alita\secret.docx"
    message = UserMessage(task_id="missing-doc-path", content="summarize this document")
    request = _request_for(
        message,
        _route_payload(taskType="document_processing", missingInputs=[local_path]),
    )

    with pytest.raises(PlannerChainError) as exc_info:
        PlannerChain(tool_registry=_tool_registry()).plan(request)

    message = str(exc_info.value)

    assert "missing inputs:" in message
    assert local_path not in message
    assert "Software Project" not in message
    assert "secret.docx" not in message
    assert exc_info.value.__cause__ is None


def test_planner_chain_rejects_non_task_routes() -> None:
    message = UserMessage(task_id="not-task", content="hello")
    request = _request_for(
        message,
        _route_payload(intent="chat", taskType="chat"),
    )

    with pytest.raises(PlannerChainError, match="cannot plan non-task route"):
        PlannerChain(tool_registry=_tool_registry()).plan(request)


def test_validate_graph_payload_does_not_leak_path_values() -> None:
    local_path = r"D:\Software Project\Alita\secret.docx"
    bad_graph_payload = {
        "graphId": "bad-graph",
        "nodes": [
            {
                "nodeId": "bad-node",
                "nodeType": local_path,
                "displayName": "Bad node",
                "status": "ready",
                "summary": "Bad graph",
                "createdBy": "test",
                "position": {"x": 0, "y": 0},
            }
        ],
        "edges": [],
        "metadata": {},
    }

    with pytest.raises(PlannerChainError) as exc_info:
        _validate_graph_payload(bad_graph_payload)

    message = str(exc_info.value)

    assert message == "invalid node graph payload"
    assert local_path not in message
    assert "Software Project" not in message
    assert "secret.docx" not in message
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    "content",
    [
        "Convert this document to Markdown.",
        "Convert this document to .md",
        "Convert this document as md",
    ],
)
def test_planner_chain_markdown_only_conversion_uses_legacy_strategy(content: str) -> None:
    message = UserMessage(
        task_id="task-markdown-document-chain",
        content=content,
        attachments=[
            Attachment(
                attachment_id="a1",
                name="source.docx",
                path=str(PROJECT_ROOT / "fixtures" / "source.docx"),
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )
    request = _request_for(
        message,
        _route_payload(taskType="document_processing"),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "legacy.task_planner.v1"
    assert result.strategy == "legacy_task_planner"
    assert "typst-export" not in {
        node["nodeId"] for node in result.graph_payload["nodes"]
    }
