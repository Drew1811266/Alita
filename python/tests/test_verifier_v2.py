from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput
from agent_service.verifier_v2 import VerifierV2


def test_verifier_v2_rejects_empty_required_value() -> None:
    with pytest.raises(HarnessError) as exc_info:
        VerifierV2().verify(
            "content-organize",
            NodeOutput(values={"outline": "   "}),
        )

    assert exc_info.value.code == "empty_node_output"
    assert str(exc_info.value) == "node content-organize returned empty value: outline"


def test_verifier_v2_rejects_missing_artifact() -> None:
    with pytest.raises(HarnessError) as exc_info:
        VerifierV2().verify(
            "document-parse",
            NodeOutput(
                artifacts=["missing.md"],
                values={"text": "parsed text"},
            ),
        )

    assert exc_info.value.code == "missing_artifact"
    assert str(exc_info.value) == "artifact does not exist: missing.md"


def test_verifier_v2_accepts_existing_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "report.md"
    artifact.write_text("report", encoding="utf-8")

    VerifierV2().verify(
        "file-export",
        NodeOutput(artifacts=[str(artifact)], values={"artifact": str(artifact)}),
    )
