from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeOutput:
    artifacts: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
