from __future__ import annotations

from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput


class NodeVerificationSpec(BaseModel):
    required_values: list[str] = Field(default_factory=list)
    require_artifact_value_listed: bool = False


def default_document_verification_specs() -> dict[str, NodeVerificationSpec]:
    return {
        "document-input": NodeVerificationSpec(required_values=["paths"]),
        "document-parse": NodeVerificationSpec(required_values=["text"]),
        "content-organize": NodeVerificationSpec(required_values=["outline"]),
        "report-generate": NodeVerificationSpec(required_values=["report"]),
        "file-export": NodeVerificationSpec(
            required_values=["artifact"],
            require_artifact_value_listed=True,
        ),
    }


class VerifierV2:
    def __init__(
        self,
        specs: Mapping[str, NodeVerificationSpec] | None = None,
    ) -> None:
        self._specs = dict(specs or default_document_verification_specs())

    def verify(self, node_id: str, output: NodeOutput) -> None:
        spec = self._specs.get(node_id, NodeVerificationSpec())

        for required_value in spec.required_values:
            value = output.values.get(required_value, "")
            if not value.strip():
                raise HarnessError(
                    "empty_node_output",
                    f"node {node_id} returned empty value: {required_value}",
                )

        if spec.require_artifact_value_listed:
            artifact_value = output.values["artifact"]
            if not output.artifacts:
                raise HarnessError(
                    "missing_artifact",
                    "file-export artifact is missing from artifact list",
                )
            if Path(artifact_value) not in {Path(artifact) for artifact in output.artifacts}:
                raise HarnessError(
                    "missing_artifact",
                    f"file-export artifact is not listed: {artifact_value}",
                )

        for artifact in output.artifacts:
            if not Path(artifact).is_file():
                raise HarnessError(
                    "missing_artifact",
                    f"artifact does not exist: {artifact}",
                )
