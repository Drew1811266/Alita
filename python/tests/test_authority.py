from __future__ import annotations

from pathlib import Path

from agent_service.authority import (
    AuthorityContext,
    authorize_tool_invocation,
    extract_invocation_paths,
)
from agent_service.tool_protocol import (
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
)


def test_default_authority_denies_sensitive_runtime_permissions(tmp_path: Path) -> None:
    tool = _tool_definition(permissions=["run_local_cli"])
    invocation = _invocation(
        tmp_path,
        arguments={"operation": "run", "source_output_path": str(tmp_path / "out.txt")},
        requested_permissions=["run_local_cli"],
    )

    decision = authorize_tool_invocation(invocation, tool, AuthorityContext())

    assert decision.allowed is False
    assert decision.code == "permission_denied"
    assert "run_local_cli" in decision.message


def test_extract_invocation_paths_reads_common_argument_names(tmp_path: Path) -> None:
    input_path = tmp_path / "input.md"
    output_path = tmp_path / "artifacts" / "output.md"
    source_path = tmp_path / "artifacts" / "report.typ"
    pdf_path = tmp_path / "artifacts" / "report.pdf"

    paths = extract_invocation_paths(
        {
            "input_path": str(input_path),
            "output_path": str(output_path),
            "source_output_path": str(source_path),
            "pdf_output_path": str(pdf_path),
            "paths": f"{input_path}\n{tmp_path / 'second.md'}",
        }
    )

    assert [path.kind for path in paths] == [
        "read",
        "write",
        "write",
        "write",
        "read",
        "read",
    ]
    assert Path(paths[0].path) == input_path
    assert Path(paths[1].path) == output_path


def test_authority_denies_path_outside_approved_roots(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    tool = _tool_definition(permissions=["read_project_files"])
    invocation = _invocation(
        tmp_path,
        arguments={"operation": "read", "input_path": str(outside)},
        requested_permissions=["read_project_files"],
    )
    context = AuthorityContext(
        approved_permissions=["read_project_files"],
        read_roots=[str(tmp_path)],
        write_roots=[str(tmp_path / "artifacts")],
    )

    decision = authorize_tool_invocation(invocation, tool, context)

    assert decision.allowed is False
    assert decision.code == "path_denied"
    assert str(outside) in decision.message


def test_authority_allows_approved_read_and_artifact_write_roots(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    tool = _tool_definition(
        permissions=["read_project_files", "write_project_outputs", "run_python_plugin"]
    )
    invocation = _invocation(
        tmp_path,
        arguments={
            "operation": "convert",
            "input_path": str(tmp_path / "input.md"),
            "output_path": str(artifact_dir / "output.md"),
        },
        requested_permissions=[
            "read_project_files",
            "write_project_outputs",
            "run_python_plugin",
        ],
    )
    context = AuthorityContext(
        approved_permissions=[
            "read_project_files",
            "write_project_outputs",
            "run_python_plugin",
        ],
        read_roots=[str(tmp_path)],
        write_roots=[str(artifact_dir)],
    )

    decision = authorize_tool_invocation(invocation, tool, context)

    assert decision.allowed is True
    assert decision.code == "allowed"


def _invocation(
    tmp_path: Path,
    *,
    arguments: dict,
    requested_permissions: list[str],
) -> UnifiedToolInvocation:
    return UnifiedToolInvocation(
        invocation_id="inv-authority",
        run_id="run-authority",
        task_id="task-authority",
        tool_id="internal:test.authority",
        arguments=arguments,
        project_path=str(tmp_path / "project.alita"),
        allowed_roots=[str(tmp_path)],
        requested_permissions=requested_permissions,
    )


def _tool_definition(*, permissions: list[str]) -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id="internal:test.authority",
        source="internal",
        provider_id="internal",
        provider_tool_name="test.authority",
        display_name="Authority Test",
        description="Authority test tool.",
        capabilities=[],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=permissions,
        safety_policy=ToolSafetyPolicy(
            filesystem="project_write",
            network="none",
            user_approval="high_risk_only",
            secrets="none",
            sandbox="not_required",
            max_runtime_ms=5000,
        ),
        timeout_ms=5000,
    )
