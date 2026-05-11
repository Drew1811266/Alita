from typing import Any


def validate_json_schema_subset(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    if schema.get("type") == "object" and not isinstance(payload, dict):
        raise ValueError("invalid_type:root")

    for field in schema.get("required", []):
        if field not in payload:
            raise ValueError(f"missing_required:{field}")

    properties = schema.get("properties", {})
    for field, field_schema in properties.items():
        if field not in payload:
            continue

        value = payload[field]
        expected_type = field_schema.get("type")
        if expected_type and not _matches_json_type(value, expected_type):
            raise ValueError(f"invalid_type:{field}")

        enum_values = field_schema.get("enum")
        if enum_values is not None and value not in enum_values:
            raise ValueError(f"invalid_enum:{field}")


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True
