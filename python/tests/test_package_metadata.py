from __future__ import annotations

import json
from pathlib import Path
import re


VERSION_PATTERN = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)


def test_python_sidecar_version_matches_desktop_versions() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    package_version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))[
        "version"
    ]
    tauri_version = json.loads(
        (repo_root / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )["version"]
    cargo_version = _toml_version(repo_root / "src-tauri" / "Cargo.toml")
    sidecar_version = _toml_version(repo_root / "python" / "pyproject.toml")

    assert sidecar_version == package_version
    assert sidecar_version == tauri_version
    assert sidecar_version == cargo_version


def _toml_version(path: Path) -> str:
    match = VERSION_PATTERN.search(path.read_text(encoding="utf-8"))
    assert match is not None, f"{path} must contain a version field"
    return match.group(1)
