from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.final_verifier import FinalVerifier
from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput
from agent_service.schemas import RunGraphRequest


def test_existing_output_artifact_passes(tmp_path: Path) -> None:
    artifact = tmp_path / "report.md"
    artifact.write_text("report", encoding="utf-8")
    request = build_request(tmp_path, output_node_id="file-export")

    FinalVerifier().verify(
        request,
        outputs={
            "file-export": NodeOutput(
                artifacts=[str(artifact)],
                values={"artifact": str(artifact)},
            )
        },
    )


def test_missing_output_node_raises_missing_final_output(tmp_path: Path) -> None:
    request = build_request(tmp_path, output_node_id="file-export")

    with pytest.raises(HarnessError) as exc_info:
        FinalVerifier().verify(request, outputs={})

    assert exc_info.value.code == "missing_final_output"
    assert "file-export" in exc_info.value.message


def test_missing_output_artifact_raises_missing_artifact(tmp_path: Path) -> None:
    missing_artifact = tmp_path / "missing.md"
    request = build_request(tmp_path, output_node_id="file-export")

    with pytest.raises(HarnessError) as exc_info:
        FinalVerifier().verify(
            request,
            outputs={
                "file-export": NodeOutput(
                    artifacts=[str(missing_artifact)],
                    values={"artifact": str(missing_artifact)},
                )
            },
        )

    assert exc_info.value.code == "missing_artifact"


def build_request(tmp_path: Path, *, output_node_id: str) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="task-final-verifier",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph={
            "graphId": "graph-final-verifier",
            "nodes": [
                {
                    "nodeId": output_node_id,
                    "nodeType": "output",
                    "displayName": output_node_id,
                    "status": "waiting",
                    "inputPorts": [],
                    "outputPorts": [],
                    "dependencies": [],
                    "summary": "test output node",
                    "createdBy": "agent",
                    "artifactRefs": [],
                    "retryCount": 0,
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )
