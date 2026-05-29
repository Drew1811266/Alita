from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


FORBIDDEN_NETWORK_IMPORTS = (
    "socket",
    "requests",
    "urllib",
    "http.client",
    "ftplib",
    "smtplib",
    "subprocess",
)


class SandboxRequest(BaseModel):
    script: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    project_path: str
    allowed_roots: list[str]
    network_allowed: bool = False
    timeout_seconds: float = 10.0
    artifact_dir: str


class SandboxResult(BaseModel):
    ok: bool
    stdout: str = ""
    stderr: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None


class SandboxViolation(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_sandbox_path(path: str, allowed_roots: list[str]) -> Path:
    candidate = Path(path).resolve(strict=False)
    roots = [Path(root).resolve(strict=False) for root in allowed_roots]
    if any(candidate == root or root in candidate.parents for root in roots):
        return candidate
    raise SandboxViolation("path_not_allowed", str(candidate))


def run_sandboxed_python(request: SandboxRequest) -> SandboxResult:
    if not request.script.strip():
        return SandboxResult(ok=False, error_code="empty_script")

    try:
        _reject_forbidden_imports(request.script, request.network_allowed)
        _validate_argument_paths(request.arguments, request.allowed_roots)
    except SandboxViolation as error:
        return SandboxResult(ok=False, error_code=error.code, stderr=str(error))

    artifact_dir = Path(request.artifact_dir).resolve(strict=False)
    sandbox_dir = artifact_dir / ".sandbox" / uuid4().hex
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    script_path = sandbox_dir / "script.py"
    script_path.write_text(request.script, encoding="utf-8")

    try:
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(sandbox_dir),
            input=json.dumps(request.arguments),
            text=True,
            capture_output=True,
            timeout=request.timeout_seconds,
            env=_sandbox_env(),
        )
    except subprocess.TimeoutExpired as error:
        return SandboxResult(
            ok=False,
            stdout=error.stdout or "",
            stderr=error.stderr or "",
            error_code="timeout",
        )

    if completed.returncode != 0:
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error_code="sandbox_process_failed",
        )

    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error_code="invalid_json_output",
        )
    if not isinstance(payload, dict):
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error_code="invalid_json_output",
        )

    values = payload.get("values") or {}
    artifacts = payload.get("artifacts") or []
    if not isinstance(values, dict) or not isinstance(artifacts, list):
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error_code="invalid_json_output",
        )

    try:
        artifact_paths = _artifact_paths_inside_dir(artifacts, artifact_dir)
    except SandboxViolation as error:
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=str(error),
            error_code=error.code,
        )

    return SandboxResult(
        ok=True,
        stdout=completed.stdout,
        stderr=completed.stderr,
        values=_sanitize_values(values),
        artifacts=[str(path) for path in artifact_paths],
    )


def _reject_forbidden_imports(script: str, network_allowed: bool) -> None:
    if network_allowed:
        return
    tree = ast.parse(script)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _reject_module_name(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            _reject_module_name(node.module)


def _reject_module_name(name: str) -> None:
    for forbidden in FORBIDDEN_NETWORK_IMPORTS:
        if name == forbidden or name.startswith(f"{forbidden}."):
            raise SandboxViolation(
                "network_import_denied",
                f"import is not allowed in sandbox: {name}",
            )


def _validate_argument_paths(value: Any, allowed_roots: list[str]) -> None:
    if isinstance(value, str) and _looks_like_path(value):
        validate_sandbox_path(value, allowed_roots)
    elif isinstance(value, list):
        for item in value:
            _validate_argument_paths(item, allowed_roots)
    elif isinstance(value, dict):
        for item in value.values():
            _validate_argument_paths(item, allowed_roots)


def _looks_like_path(value: str) -> bool:
    return (
        Path(value).is_absolute()
        or value.startswith("\\\\")
        or re.match(r"^[a-zA-Z]:[\\/]", value) is not None
    )


def _artifact_paths_inside_dir(
    artifacts: list[Any],
    artifact_dir: Path,
) -> list[Path]:
    root = artifact_dir.resolve(strict=False)
    paths: list[Path] = []
    for artifact in artifacts:
        candidate = Path(str(artifact))
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        if not (resolved == root or root in resolved.parents):
            raise SandboxViolation("artifact_path_not_allowed", str(resolved))
        paths.append(resolved)
    return paths


def _sanitize_values(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _sanitize_value(value) for key, value in values.items()}


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute() or ":\\" in value:
            return path.name
        return value
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return [
            _sanitize_value(item)
            for item in value
            if isinstance(item, str | int | float | bool) or item is None
        ]
    if isinstance(value, dict):
        return _sanitize_values(value)
    return str(value)


def _sandbox_env() -> dict[str, str]:
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    for key in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env
