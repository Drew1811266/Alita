import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ToolOperationSpec:
    name: str
    description: str


@dataclass(frozen=True)
class ToolManifestSpec:
    tool_id: str
    name: str
    description: str
    version: str
    source_type: str
    license: str
    runtime: str | None
    entrypoint: str | None
    capabilities: list[str]
    operations: list[ToolOperationSpec]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[str]
    error_codes: list[str]
    timeout_policy: dict[str, Any]
    artifact_policy: dict[str, Any]
    security_policy: dict[str, Any]
    examples: list[dict[str, Any]]
    node_templates: list[dict[str, Any]]


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolManifestSpec]) -> None:
        self._tools_by_id = {tool.tool_id: tool for tool in tools}

    @classmethod
    def from_packages_root(cls, packages_root: Path | str) -> "ToolRegistry":
        root = Path(packages_root)
        tools = [
            _load_manifest(manifest_path)
            for manifest_path in sorted(root.glob("*/manifest.json"))
        ]
        tools.append(_virtual_document_input_tool())
        return cls(tools)

    def get(self, tool_id: str) -> ToolManifestSpec:
        try:
            return self._tools_by_id[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc

    def has_operation(self, tool_id: str, operation: str) -> bool:
        tool = self.get(tool_id)
        return any(spec.name == operation for spec in tool.operations)

    def enabled_tools(
        self, disabled_tool_ids: Iterable[str] | None = None
    ) -> list[ToolManifestSpec]:
        disabled = set(disabled_tool_ids or [])
        return [
            tool
            for tool_id, tool in self._tools_by_id.items()
            if tool_id not in disabled
        ]


def _load_manifest(manifest_path: Path) -> ToolManifestSpec:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return _manifest_from_dict(manifest)


def _manifest_from_dict(manifest: dict[str, Any]) -> ToolManifestSpec:
    return ToolManifestSpec(
        tool_id=manifest["tool_id"],
        name=manifest["name"],
        description=manifest["description"],
        version=manifest["version"],
        source_type=manifest["source_type"],
        license=manifest["license"],
        runtime=manifest.get("runtime"),
        entrypoint=manifest.get("entrypoint"),
        capabilities=list(manifest.get("capabilities", [])),
        operations=[
            ToolOperationSpec(
                name=operation["name"],
                description=operation.get("description", ""),
            )
            for operation in manifest.get("operations", [])
        ],
        input_schema=dict(manifest.get("input_schema", {})),
        output_schema=dict(manifest.get("output_schema", {})),
        permissions=[str(value) for value in manifest.get("permissions", [])],
        error_codes=list(manifest.get("error_codes", [])),
        timeout_policy=dict(manifest.get("timeout_policy", {})),
        artifact_policy=dict(manifest.get("artifact_policy", {})),
        security_policy=dict(manifest.get("security_policy", {})),
        examples=list(manifest.get("examples", [])),
        node_templates=list(manifest.get("node_templates", [])),
    )


def _virtual_document_input_tool() -> ToolManifestSpec:
    return ToolManifestSpec(
        tool_id="document.receive_attachment",
        name="Receive Attachment",
        description="Accept a user-provided document attachment for the workflow.",
        version="1.0.0",
        source_type="virtual_system_tool",
        license="internal",
        runtime="python_sidecar",
        entrypoint=None,
        capabilities=["document_input"],
        operations=[
            ToolOperationSpec(
                name="receive_attachment",
                description="Receive a document attachment from the user.",
            )
        ],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=["read_project_files"],
        error_codes=[],
        timeout_policy={},
        artifact_policy={},
        security_policy={"network": False, "plugins": False},
        examples=[],
        node_templates=[],
    )
