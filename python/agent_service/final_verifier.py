from __future__ import annotations

from pathlib import Path

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput
from agent_service.schemas import RunGraphRequest


class FinalVerifier:
    def verify(
        self,
        request: RunGraphRequest,
        *,
        outputs: dict[str, NodeOutput],
    ) -> None:
        for node in request.graph.nodes:
            if node.nodeType != "output":
                continue

            output = outputs.get(node.nodeId)
            if output is None:
                raise HarnessError(
                    "missing_final_output",
                    f"missing final output for node: {node.nodeId}",
                )

            artifact_value = output.values.get("artifact", "")
            if artifact_value and artifact_value not in output.artifacts:
                raise HarnessError(
                    "missing_artifact",
                    f"final artifact is not listed: {artifact_value}",
                )

            for path in output.artifacts:
                if not Path(path).is_file():
                    raise HarnessError(
                        "missing_artifact",
                        f"artifact does not exist: {path}",
                    )
