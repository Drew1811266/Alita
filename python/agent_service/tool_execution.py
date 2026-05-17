from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from collections.abc import Iterable

from agent_service.harness_errors import HarnessError
from agent_service.schema_validation import validate_json_schema_subset
from agent_service.tool_registry import ToolRegistry
from tools.markitdown_tool import convert_local_file as convert_markitdown_local_file
from tools.typst_tool import compile_report_pdf as compile_typst_report_pdf


def _default_tool_packages_root() -> Path:
    return default_tool_packages_root()


def default_tool_packages_root() -> Path:
    return resolve_tool_packages_root(_tool_packages_root_candidates())


def resolve_tool_packages_root(candidates: Iterable[Path]) -> Path:
    candidate_list = list(candidates)
    for candidate in candidate_list:
        if _contains_tool_manifests(candidate):
            return candidate

    if candidate_list:
        return candidate_list[-1]

    return Path(__file__).resolve().parents[2] / "tool-packages"


def _tool_packages_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured_root = os.getenv("ALITA_TOOL_PACKAGES_ROOT", "").strip()
    if configured_root:
        candidates.append(Path(configured_root))

    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        candidates.append(Path(pyinstaller_root) / "tool-packages")

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "tool-packages")

    candidates.append(Path(__file__).resolve().parents[2] / "tool-packages")
    candidates.append(Path.cwd() / "tool-packages")
    return candidates


def _contains_tool_manifests(path: Path) -> bool:
    return any(path.glob("*/manifest.json"))


@dataclass(frozen=True)
class ToolInvocation:
    tool_id: str
    operation: str
    arguments: dict[str, object]
    project_path: str
    allowed_roots: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResult:
    values: dict[str, str] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


class ToolExecutor:
    def __init__(self, *, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry.from_packages_root(
            _default_tool_packages_root()
        )

    def run(self, invocation: ToolInvocation) -> ToolResult:
        try:
            manifest = self.registry.get(invocation.tool_id)
        except KeyError as exc:
            raise HarnessError(
                "unsupported_tool", f"unsupported tool: {invocation.tool_id}"
            ) from exc

        if not self.registry.has_operation(invocation.tool_id, invocation.operation):
            raise HarnessError(
                "unsupported_operation",
                f"unsupported operation for {invocation.tool_id}: {invocation.operation}",
            )

        arguments = {"operation": invocation.operation, **invocation.arguments}
        try:
            validate_json_schema_subset(manifest.input_schema, arguments)
        except ValueError as exc:
            raise HarnessError("invalid_tool_input", str(exc)) from exc

        if invocation.tool_id == "document.markitdown_convert":
            return self._run_markitdown(invocation)
        if invocation.tool_id == "document.typst_compile":
            return self._run_typst(invocation)

        raise HarnessError("unsupported_tool", f"unsupported tool: {invocation.tool_id}")

    def _run_markitdown(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.operation != "convert_local_file":
            raise HarnessError(
                "unsupported_operation",
                f"unsupported operation for {invocation.tool_id}: {invocation.operation}",
            )

        result = convert_markitdown_local_file(
            input_path=str(invocation.arguments["input_path"]),
            output_path=str(invocation.arguments["output_path"]),
            project_path=invocation.project_path,
            allowed_roots=invocation.allowed_roots,
        )

        return ToolResult(
            values={"text": result.text},
            artifacts=result.artifacts,
            metadata=result.metadata,
        )

    def _run_typst(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.operation != "compile_report_pdf":
            raise HarnessError(
                "unsupported_operation",
                f"unsupported operation for {invocation.tool_id}: {invocation.operation}",
            )

        result = compile_typst_report_pdf(
            title=str(invocation.arguments["title"]),
            outline=str(invocation.arguments["outline"]),
            report=str(invocation.arguments["report"]),
            source_output_path=str(invocation.arguments["source_output_path"]),
            pdf_output_path=str(invocation.arguments["pdf_output_path"]),
            project_path=invocation.project_path,
            allowed_roots=invocation.allowed_roots,
        )

        return ToolResult(
            values={"source": result.source_path, "artifact": result.pdf_path},
            artifacts=result.artifacts,
            metadata=result.metadata,
        )
