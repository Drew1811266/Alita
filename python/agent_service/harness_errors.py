from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message

    def to_payload(self) -> dict[str, str]:
        return {"errorCode": self.code, "error": self.message}


def harness_error_payload(error: Exception) -> dict[str, str]:
    if isinstance(error, HarnessError):
        return error.to_payload()
    return {"errorCode": "execution_failed", "error": str(error)}
