import pytest

from agent_service.schema_validation import validate_json_schema_subset


def test_accepts_required_string_and_enum_values() -> None:
    schema = {
        "type": "object",
        "required": ["operation", "input_path"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["convert_local_file"],
            },
            "input_path": {"type": "string"},
        },
    }
    payload = {
        "operation": "convert_local_file",
        "input_path": "book files/sample.pdf",
    }

    validate_json_schema_subset(schema, payload)


def test_rejects_missing_required_field() -> None:
    schema = {
        "type": "object",
        "required": ["operation", "input_path"],
        "properties": {
            "operation": {"type": "string"},
            "input_path": {"type": "string"},
        },
    }

    with pytest.raises(ValueError, match="missing_required:input_path"):
        validate_json_schema_subset(schema, {"operation": "convert_local_file"})


def test_rejects_wrong_type_and_invalid_enum() -> None:
    schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["convert_local_file"],
            },
            "input_path": {"type": "string"},
        },
    }

    with pytest.raises(ValueError, match="invalid_enum:operation"):
        validate_json_schema_subset(
            schema,
            {"operation": "delete_file", "input_path": "book files/sample.pdf"},
        )

    with pytest.raises(ValueError, match="invalid_type:input_path"):
        validate_json_schema_subset(
            schema,
            {"operation": "convert_local_file", "input_path": 123},
        )


def test_accepts_schema_without_root_type_and_still_validates_required_fields() -> None:
    schema = {
        "required": ["operation", "input_path"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["convert_local_file"],
            },
            "input_path": {"type": "string"},
        },
    }

    validate_json_schema_subset(
        schema,
        {"operation": "convert_local_file", "input_path": "book files/sample.pdf"},
    )

    with pytest.raises(ValueError, match="missing_required:input_path"):
        validate_json_schema_subset(schema, {"operation": "convert_local_file"})
