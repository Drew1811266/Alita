from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal


ToolStatus = Literal["ok", "failed", "blocked", "not_configured"]


@dataclass(frozen=True)
class ToolFailure:
    kind: str
    message: str
    retryable: bool = False
    provider: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "retryable": self.retryable,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: ToolStatus
    data: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    failure: ToolFailure | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", deepcopy(self.data))
        object.__setattr__(self, "sources", deepcopy(self.sources))
        object.__setattr__(self, "metadata", deepcopy(self.metadata))

    def to_payload(self) -> dict[str, Any]:
        return {
            "toolName": self.tool_name,
            "status": self.status,
            "data": deepcopy(self.data),
            "sources": deepcopy(self.sources),
            "failure": self.failure.to_payload() if self.failure else None,
            "metadata": deepcopy(self.metadata),
        }
