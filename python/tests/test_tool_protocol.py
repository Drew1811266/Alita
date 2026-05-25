from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolError,
    UnifiedToolResult,
)


def test_unified_tool_definition_rejects_blank_id() -> None:
    try:
        UnifiedToolDefinition(
            id="",
            source="internal",
            provider_id="internal",
            provider_tool_name="document.markitdown_convert",
            display_name="MarkItDown",
            description="Convert supported local documents to Markdown.",
            capabilities=["document_conversion"],
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            permissions=["read_project_files"],
            safety_policy=ToolSafetyPolicy(
                filesystem="project_read",
                network="none",
                user_approval="never",
                secrets="none",
                sandbox="not_required",
                max_runtime_ms=60000,
            ),
            timeout_ms=60000,
            examples=[],
            enabled=True,
        )
    except ValueError as error:
        assert "tool id is required" in str(error)
    else:
        raise AssertionError("blank tool id should fail")


def test_unified_tool_result_sanitizes_error_shape() -> None:
    result = UnifiedToolResult(
        ok=False,
        content=[],
        structured_content=None,
        artifacts=[],
        metadata={},
        error=UnifiedToolError(
            code="provider_failed",
            message="provider failed",
            recoverable=True,
            safe_details={"status": 502},
        ),
    )

    assert result.error is not None
    assert result.error.code == "provider_failed"
    assert result.error.safe_details == {"status": 502}


def test_text_result_content_preserves_text() -> None:
    content = ToolResultContent(type="text", text="converted text")

    assert content.type == "text"
    assert content.text == "converted text"
