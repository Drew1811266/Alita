from __future__ import annotations

from agent_service.node_output import NodeOutput
from agent_service.verifier_v2 import VerifierV2


class ResultVerifier:
    def __init__(self, verifier: VerifierV2 | None = None) -> None:
        self._verifier = verifier or VerifierV2()

    def verify(self, node_id: str, output: NodeOutput) -> None:
        self._verifier.verify(node_id, output)
