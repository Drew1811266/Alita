from __future__ import annotations

from agent_service.harness_errors import HarnessError
from agent_service.replan import FailureReplanner
from agent_service.schemas import RunGraphRequest


def test_replanner_suggests_retry_for_empty_node_output(tmp_path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = _request(tmp_path)
    node = request.graph.nodes[2]

    suggestion = FailureReplanner().propose(
        request=request,
        failed_node=node,
        error=HarnessError("empty_node_output", "node content-organize returned empty value"),
    )

    assert suggestion is not None
    assert suggestion.reason == "node content-organize returned empty value"
    assert suggestion.operations[0].op == "retry_node"
    assert suggestion.operations[0].node_id == "content-organize"


def test_replanner_suggests_rerun_missing_artifact_node(tmp_path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = _request(tmp_path)
    node = request.graph.nodes[-1]

    suggestion = FailureReplanner().propose(
        request=request,
        failed_node=node,
        error=HarnessError("missing_artifact", "artifact does not exist"),
    )

    assert suggestion is not None
    assert suggestion.operations[0].op == "rerun_node"
    assert suggestion.operations[0].node_id == "file-export"


def test_replanner_returns_none_for_permission_required(tmp_path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = _request(tmp_path)

    suggestion = FailureReplanner().propose(
        request=request,
        failed_node=request.graph.nodes[0],
        error=HarnessError("permission_required", "approval required"),
    )

    assert suggestion is None


def _request(tmp_path) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="task-replan",
        project_path=str(tmp_path / "project.alita"),
        graph={
            "graphId": "graph-replan",
            "nodes": [
                _node("document-input", "fixed_tool", []),
                _node("document-parse", "fixed_tool", ["document-input"]),
                _node("content-organize", "model", ["document-parse"]),
                _node("file-export", "output", ["content-organize"]),
            ],
            "edges": [],
        },
    )


def _node(node_id: str, node_type: str, dependencies: list[str]) -> dict:
    return {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": node_id,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies,
        "summary": "test node",
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": 0, "y": 0},
    }
