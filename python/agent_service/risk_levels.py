from __future__ import annotations

from typing import Literal

RiskLevel = Literal[
    "read_only",
    "local_write",
    "local_modify",
    "destructive",
    "network",
    "external_comm",
    "system",
]
