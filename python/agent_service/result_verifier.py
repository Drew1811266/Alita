from __future__ import annotations

from pathlib import Path

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput


class ResultVerifier:
    _REQUIRED_VALUES = {
        "document-input": "paths",
        "document-parse": "text",
        "content-organize": "outline",
        "report-generate": "report",
        "file-export": "artifact",
        "research-markdown-output": "artifact",
    }

    def verify(self, node_id: str, output: NodeOutput) -> None:
        required_value = self._REQUIRED_VALUES.get(node_id)
        if required_value is not None:
            value = output.values.get(required_value, "")
            if not value.strip():
                raise HarnessError(
                    "empty_node_output",
                    f"node {node_id} returned empty value: {required_value}",
                )

        if node_id in {"file-export", "research-markdown-output"}:
            artifact_value = output.values["artifact"]
            if not output.artifacts:
                raise HarnessError(
                    "missing_artifact",
                    f"{node_id} artifact is missing from artifact list",
                )
            if Path(artifact_value) not in {Path(artifact) for artifact in output.artifacts}:
                raise HarnessError(
                    "missing_artifact",
                    f"{node_id} artifact is not listed: {artifact_value}",
                )

        for artifact in output.artifacts:
            if not Path(artifact).is_file():
                raise HarnessError(
                    "missing_artifact",
                    f"artifact does not exist: {artifact}",
                )
