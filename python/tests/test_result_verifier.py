from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.execution import NodeOutput
from agent_service.harness_errors import HarnessError
from agent_service.result_verifier import ResultVerifier


class RecordingVerifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, NodeOutput]] = []

    def verify(self, node_id: str, output: NodeOutput) -> None:
        self.calls.append((node_id, output))


def test_delegates_to_injected_verifier() -> None:
    verifier = RecordingVerifier()
    output = NodeOutput(values={"outline": "outline"})

    ResultVerifier(verifier=verifier).verify("content-organize", output)

    assert verifier.calls == [("content-organize", output)]


def test_accepts_existing_artifact_and_required_value(tmp_path: Path) -> None:
    artifact = tmp_path / "report.md"
    artifact.write_text("report", encoding="utf-8")

    ResultVerifier().verify(
        "file-export",
        NodeOutput(artifacts=[str(artifact)], values={"artifact": str(artifact)}),
    )


def test_rejects_missing_artifact() -> None:
    with pytest.raises(HarnessError) as exc_info:
        ResultVerifier().verify(
            "document-parse",
            NodeOutput(
                artifacts=["missing.md"],
                values={"text": "parsed text"},
            ),
        )

    assert exc_info.value.code == "missing_artifact"
    assert str(exc_info.value) == "artifact does not exist: missing.md"


def test_rejects_file_export_without_artifact_list() -> None:
    with pytest.raises(HarnessError) as exc_info:
        ResultVerifier().verify(
            "file-export",
            NodeOutput(values={"artifact": "missing.md"}, artifacts=[]),
        )

    assert exc_info.value.code == "missing_artifact"
    assert "file-export artifact" in str(exc_info.value)


def test_rejects_file_export_when_artifact_value_is_not_listed(
    tmp_path: Path,
) -> None:
    listed_artifact = tmp_path / "listed.md"
    listed_artifact.write_text("report", encoding="utf-8")
    missing_artifact = tmp_path / "missing.md"

    with pytest.raises(HarnessError) as exc_info:
        ResultVerifier().verify(
            "file-export",
            NodeOutput(
                values={"artifact": str(missing_artifact)},
                artifacts=[str(listed_artifact)],
            ),
        )

    assert exc_info.value.code == "missing_artifact"
    assert "file-export artifact" in str(exc_info.value)


def test_rejects_empty_content_organize_outline() -> None:
    with pytest.raises(HarnessError) as exc_info:
        ResultVerifier().verify(
            "content-organize",
            NodeOutput(values={"outline": "   "}),
        )

    assert exc_info.value.code == "empty_node_output"
    assert str(exc_info.value) == "node content-organize returned empty value: outline"
