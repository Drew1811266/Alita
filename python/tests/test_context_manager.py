from __future__ import annotations

from pathlib import Path

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import GoalSpec
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_registry import ToolRegistry


def test_build_context_bundle_includes_goal_metadata_tools_and_attachment_context(
    tmp_path: Path,
) -> None:
    private_body = "PRIVATE ATTACHMENT BODY DO NOT INCLUDE"
    attachment_path = tmp_path / "inputs" / "source.txt"
    attachment_path.parent.mkdir()
    attachment_path.write_text(private_body, encoding="utf-8")
    project_path = str(tmp_path / "workspace.alita")
    message = UserMessage(
        task_id="task-document",
        content="summarize this document",
        attachments=[
            Attachment(
                attachment_id="att-1",
                name="source.txt",
                path=str(attachment_path),
                size_bytes=attachment_path.stat().st_size,
                mime_type="text/plain",
            )
        ],
    )
    goal_spec = GoalSpec(
        goal="summarize this document",
        task_type="document_processing",
        deliverable="markdown_report",
        constraints=["Do not upload attachments", "Write artifacts locally"],
        success_criteria=["A markdown report exists"],
        required_context=["attachment"],
        risk_level="local_write",
        permissions_required=["read_attachment", "write_project_artifact"],
        confidence=0.9,
    )
    registry = ToolRegistry.from_packages_root(
        Path(__file__).resolve().parents[2] / "tool-packages"
    )

    bundle = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path=project_path,
        tool_registry=registry,
    )

    assert bundle.project_path == project_path
    assert bundle.artifact_dir == str(tmp_path / "artifacts")
    assert bundle.goal == "summarize this document"
    assert bundle.task_type == "document_processing"
    assert bundle.constraints == ["Do not upload attachments", "Write artifacts locally"]
    assert bundle.attachments[0].model_dump() == {
        "attachment_id": "att-1",
        "name": "source.txt",
        "path": str(attachment_path),
        "size_bytes": len(private_body),
        "mime_type": "text/plain",
    }

    tool_by_id = {tool.tool_id: tool for tool in bundle.available_tools}
    assert "document.markitdown_convert" in tool_by_id
    assert tool_by_id["document.markitdown_convert"].operations == [
        "convert_local_file"
    ]
    assert tool_by_id["document.markitdown_convert"].capabilities
    assert "read_project_files" in tool_by_id[
        "document.markitdown_convert"
    ].permissions

    assert private_body not in bundle.model_dump_json()


def test_build_context_bundle_can_use_filtered_unified_tool_catalog(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry.from_packages_root(
        Path(__file__).resolve().parents[2] / "tool-packages"
    )
    gateway = UnifiedToolGateway(providers=[InternalToolProvider(registry=registry)])
    goal_spec = GoalSpec(
        goal="convert this docx to markdown",
        task_type="document_processing",
        deliverable="markdown_report",
        constraints=[],
        success_criteria=["Markdown exists"],
        required_context=["attachment"],
        risk_level="read_only",
        permissions_required=[],
        confidence=0.9,
    )

    bundle = build_context_bundle(
        message=UserMessage(task_id="task-1", content="convert this docx to markdown"),
        goal_spec=goal_spec,
        project_path=str(tmp_path / "workspace.alita"),
        tool_registry=registry,
        tool_gateway=gateway,
        disabled_tool_ids=["internal:document.typst_compile"],
    )

    tool_ids = [tool.tool_id for tool in bundle.available_tools]

    assert "internal:document.markitdown_convert" in tool_ids
    assert "internal:document.typst_compile" not in tool_ids
