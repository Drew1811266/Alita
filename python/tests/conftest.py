from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def allow_unauthenticated_dev_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALITA_SIDECAR_TOKEN", raising=False)
    monkeypatch.setenv("ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV", "1")
