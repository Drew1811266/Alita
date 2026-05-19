from __future__ import annotations

import hashlib
import json

from agent_service.schemas import ScriptReviewState


def script_review_fingerprint(review: ScriptReviewState) -> str:
    payload = {
        "codePreview": review.codePreview,
        "permissions": review.permissions,
        "riskLevel": review.riskLevel,
        "inputContract": review.inputContract,
        "outputContract": review.outputContract,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
