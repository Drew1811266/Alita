from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodeOutput:
    artifacts: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)
