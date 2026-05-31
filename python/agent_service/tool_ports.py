from __future__ import annotations

from typing import Any, Literal


ToolPortType = Literal[
    "text",
    "file_path",
    "file_paths",
    "json",
    "artifact_path",
    "url",
    "table",
    "pdf",
]

TEXT_NAMES = {
    "content",
    "input",
    "message",
    "outline",
    "query",
    "report",
    "source_text",
    "text",
    "title",
}
FILE_PATH_NAMES = {"input_path", "path"}
FILE_PATH_LIST_NAMES = {"input_paths", "paths"}
ARTIFACT_PATH_NAMES = {
    "artifact",
    "artifact_path",
    "output_path",
    "source",
    "source_output_path",
}
PDF_NAMES = {"pdf", "pdf_output_path"}
URL_NAMES = {"url", "urls"}
TABLE_NAMES = {"table", "rows"}


def input_port_types(input_schema: dict[str, Any]) -> dict[str, ToolPortType]:
    return _schema_port_types(input_schema)


def output_port_types(output_schema: dict[str, Any]) -> dict[str, ToolPortType]:
    return _schema_port_types(output_schema)


def port_type_for_schema(name: str, schema: dict[str, Any]) -> ToolPortType:
    normalized = name.lower()
    if normalized in PDF_NAMES or normalized.endswith("_pdf"):
        return "pdf"
    if normalized in URL_NAMES or normalized.endswith("_url"):
        return "url"
    if normalized in FILE_PATH_LIST_NAMES:
        return "file_paths"
    if normalized in FILE_PATH_NAMES:
        return "file_path"
    if normalized in ARTIFACT_PATH_NAMES or "artifact" in normalized:
        return "artifact_path"
    if normalized in TABLE_NAMES:
        return "table"
    if normalized in TEXT_NAMES or normalized.endswith("_text"):
        return "text"

    schema_type = schema.get("type")
    if schema_type == "array":
        item_type = (schema.get("items") or {}).get("type")
        if item_type == "string":
            return "file_paths" if "path" in normalized else "json"
        return "json"
    if schema_type == "object":
        return "json"
    if schema_type == "string":
        return "text"
    return "json"


def compatible_port_types(
    output_type: ToolPortType,
    input_type: ToolPortType,
) -> bool:
    if input_type == output_type:
        return True
    if input_type == "json":
        return True
    if output_type == "json":
        return False
    if input_type == "text" and output_type in {"text", "url"}:
        return True
    if input_type == "file_path" and output_type in {"file_path", "artifact_path", "pdf"}:
        return True
    if input_type == "artifact_path" and output_type in {"artifact_path", "pdf"}:
        return True
    if input_type == "file_paths" and output_type in {"file_paths"}:
        return True
    return False


def _schema_port_types(schema: dict[str, Any]) -> dict[str, ToolPortType]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return {
        str(name): port_type_for_schema(str(name), dict(property_schema or {}))
        for name, property_schema in properties.items()
    }
