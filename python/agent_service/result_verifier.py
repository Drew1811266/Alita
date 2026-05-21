from __future__ import annotations

from pathlib import Path

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput
from agent_service.verifier_v2 import (
    NodeVerificationSpec,
    VerifierV2,
    default_document_verification_specs,
)


class ResultVerifier:
    def __init__(self, verifier: VerifierV2 | None = None) -> None:
        self._verifier = verifier or VerifierV2(_default_verification_specs())

    def verify(self, node_id: str, output: NodeOutput) -> None:
        self._verifier.verify(node_id, output)

        if node_id in {"file-export", "research-markdown-output"}:
            for artifact in output.artifacts:
                self._verify_text_artifact_has_body(node_id, Path(artifact))

    def _verify_text_artifact_has_body(self, node_id: str, artifact_path: Path) -> None:
        if artifact_path.suffix.lower() not in {".md", ".txt"}:
            return

        content = artifact_path.read_text(encoding="utf-8", errors="ignore")
        body_lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        body = "\n".join(body_lines).strip()
        if not body:
            raise HarnessError(
                "empty_artifact_content",
                f"{node_id} artifact has no body content: {artifact_path}",
            )


def _default_verification_specs() -> dict[str, NodeVerificationSpec]:
    specs = default_document_verification_specs()
    specs["research-markdown-output"] = NodeVerificationSpec(
        required_values=["artifact"],
        require_artifact_value_listed=True,
    )
    return specs
