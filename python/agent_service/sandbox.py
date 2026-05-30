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
    "importlib",
    "ftplib",
    "smtplib",
    "subprocess",
)

SANDBOX_SECURITY_MODEL = "constrained_subprocess_runner"
SANDBOX_SECURITY_BOUNDARY = "preflight_and_runtime_limits_not_os_isolation"


class SandboxRequest(BaseModel):
    script: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    project_path: str
    allowed_roots: list[str]
    network_allowed: bool = False
    timeout_seconds: float = 10.0
    artifact_dir: str
    max_script_bytes: int = 64 * 1024
    max_output_bytes: int = 256 * 1024
    max_artifacts: int = 16
    max_artifact_bytes: int = 10 * 1024 * 1024


class SandboxResult(BaseModel):
    ok: bool
    stdout: str = ""
    stderr: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None
    security_model: str = SANDBOX_SECURITY_MODEL
    security_boundary: str = SANDBOX_SECURITY_BOUNDARY


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
    if _byte_len(request.script) > request.max_script_bytes:
        return SandboxResult(ok=False, error_code="script_too_large")

    try:
        _reject_forbidden_script_apis(
            request.script,
            network_allowed=request.network_allowed,
            allowed_roots=request.allowed_roots,
            artifact_dir=request.artifact_dir,
        )
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
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if _byte_len(stdout) > request.max_output_bytes or _byte_len(stderr) > request.max_output_bytes:
            return SandboxResult(
                ok=False,
                stdout=stdout,
                stderr=stderr,
                error_code="output_too_large",
            )
        return SandboxResult(
            ok=False,
            stdout=stdout,
            stderr=stderr,
            error_code="timeout",
        )

    if (
        _byte_len(completed.stdout) > request.max_output_bytes
        or _byte_len(completed.stderr) > request.max_output_bytes
    ):
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error_code="output_too_large",
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
    if len(artifacts) > request.max_artifacts:
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error_code="too_many_artifacts",
        )

    try:
        artifact_paths = _artifact_paths_inside_dir(artifacts, artifact_dir)
        _validate_artifact_sizes(artifact_paths, request.max_artifact_bytes)
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


def _reject_forbidden_script_apis(
    script: str,
    *,
    network_allowed: bool,
    allowed_roots: list[str],
    artifact_dir: str,
) -> None:
    try:
        tree = ast.parse(script)
    except SyntaxError as error:
        raise SandboxViolation("sandbox_process_failed", str(error)) from error
    for node in ast.walk(tree):
        if not network_allowed and isinstance(node, ast.Import):
            for alias in node.names:
                _reject_module_name(alias.name)
        elif not network_allowed and isinstance(node, ast.ImportFrom) and node.module:
            _reject_module_name(node.module)
        elif isinstance(node, ast.Call):
            if not network_allowed:
                _reject_dynamic_import_call(node)
                _reject_network_call(node)
            _reject_direct_file_api_call(node, allowed_roots, artifact_dir)
            _reject_secret_env_call(node)
            _reject_process_launch_call(node)
        elif isinstance(node, ast.Subscript):
            _reject_secret_env_subscript(node)


def _reject_module_name(name: str) -> None:
    for forbidden in FORBIDDEN_NETWORK_IMPORTS:
        if name == forbidden or name.startswith(f"{forbidden}."):
            raise SandboxViolation(
                "network_import_denied",
                f"import is not allowed in sandbox: {name}",
            )


def _reject_dynamic_import_call(node: ast.Call) -> None:
    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
        _reject_literal_import_argument(node)
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "importlib"
    ):
        _reject_literal_import_argument(node)


def _reject_literal_import_argument(node: ast.Call) -> None:
    if not node.args:
        return
    first_arg = node.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        _reject_module_name(first_arg.value)


def _reject_direct_file_api_call(
    node: ast.Call,
    allowed_roots: list[str],
    artifact_dir: str,
) -> None:
    literal = _literal_path_for_file_call(node)
    if literal is None:
        return
    literal_path, path_use = literal
    if literal_path is None:
        return
    if not _looks_like_path(literal_path):
        return
    roots = [artifact_dir] if path_use == "write" else allowed_roots
    try:
        validate_sandbox_path(literal_path, roots)
    except SandboxViolation as error:
        raise SandboxViolation("forbidden_file_api", str(error)) from error


def _literal_path_for_file_call(node: ast.Call) -> tuple[str, str] | None:
    if isinstance(node.func, ast.Name) and node.func.id == "open":
        return _literal_string_arg(node), "read"
    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr == "open":
        return _path_constructor_literal(node.func.value), "read"
    if node.func.attr in {"read_text", "read_bytes"}:
        return _path_constructor_literal(node.func.value), "read"
    if node.func.attr in {"write_text", "write_bytes"}:
        return _path_constructor_literal(node.func.value), "write"
    return None


def _path_constructor_literal(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name) and node.func.id == "Path":
        return _literal_string_arg(node)
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "Path"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pathlib"
    ):
        return _literal_string_arg(node)
    return None


def _literal_string_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first_arg = node.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    return None


def _reject_secret_env_call(node: ast.Call) -> None:
    if not isinstance(node.func, ast.Attribute):
        return
    if (
        isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
        and node.func.attr == "getenv"
    ):
        _reject_secret_env_name(_literal_string_arg(node))
    if (
        isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "environ"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "os"
        and node.func.attr == "get"
    ):
        _reject_secret_env_name(_literal_string_arg(node))


def _reject_secret_env_subscript(node: ast.Subscript) -> None:
    if not (
        isinstance(node.value, ast.Attribute)
        and node.value.attr == "environ"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "os"
    ):
        return
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        _reject_secret_env_name(key.value)


def _reject_secret_env_name(name: str | None) -> None:
    if name is None:
        return
    upper = name.upper()
    if any(marker in upper for marker in SECRET_ENV_MARKERS):
        raise SandboxViolation(
            "secret_env_denied",
            f"secret environment access is not allowed in sandbox: {name}",
        )


def _reject_network_call(node: ast.Call) -> None:
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "socket"
        and node.func.attr == "socket"
    ):
        raise SandboxViolation(
            "network_call_denied",
            "network socket API is not allowed in sandbox: socket.socket",
        )


def _reject_process_launch_call(node: ast.Call) -> None:
    if not isinstance(node.func, ast.Attribute):
        return
    if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
        if node.func.attr in OS_PROCESS_APIS:
            raise SandboxViolation(
                "process_launch_denied",
                f"process launch API is not allowed in sandbox: os.{node.func.attr}",
            )
    if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
        raise SandboxViolation(
            "process_launch_denied",
            f"process launch API is not allowed in sandbox: subprocess.{node.func.attr}",
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


def _validate_artifact_sizes(
    artifact_paths: list[Path],
    max_artifact_bytes: int,
) -> None:
    for path in artifact_paths:
        if path.exists() and path.is_file() and path.stat().st_size > max_artifact_bytes:
            raise SandboxViolation("artifact_too_large", str(path))


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


def _byte_len(value: str | bytes) -> int:
    if isinstance(value, bytes):
        return len(value)
    return len(value.encode("utf-8", errors="replace"))


SECRET_ENV_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
OS_PROCESS_APIS = {
    "system",
    "popen",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "startfile",
}
