from __future__ import annotations

import pytest

from agent_service.execution_graph import (
    ExecutionGraphError,
    compile_execution_graph,
    validate_execution_graph_bindings,
)
from agent_service.schemas import GraphEdge, GraphNode, RunGraph, RunGraphRequest


def _node(
    node_id: str,
    node_type: str,
    *,
    dependencies: list[str] | None = None,
    tool_ref: str | None = None,
    model_ref: str | None = None,
    permissions: list[str] | None = None,
) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType=node_type,
        displayName=node_id,
        status="waiting",
        summary=f"{node_id} summary",
        createdBy="test",
        inputPorts=[],
        outputPorts=[],
        dependencies=list(dependencies or []),
        toolRef=tool_ref,
        modelRef=model_ref,
        permissionsRequired=list(permissions or []),
        position={"x": 0, "y": 0},
    )


def _request(nodes: list[GraphNode]) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="task-execution-graph",
        run_id="run-execution-graph",
        project_path="D:\\Project\\demo.alita",
        attachments=[],
        graph=RunGraph(
            graphId="graph-execution",
            nodes=nodes,
            edges=[
                GraphEdge(
                    id=f"{source.nodeId}-{target.nodeId}",
                    source=source.nodeId,
                    target=target.nodeId,
                )
                for source in nodes
                for target in nodes
                if source.nodeId in target.dependencies
            ],
            metadata={
                "kind": "task",
                "plannerChain": {"strategy": "legacy_task_planner"},
            },
        ),
    )


def test_compile_execution_graph_maps_tool_and_model_bindings() -> None:
    request = _request(
        [
            _node(
                "inspect",
                "fixed_tool",
                tool_ref="internal:document.markitdown_convert",
                permissions=["read_attachment"],
            ),
            _node(
                "reason",
                "model",
                dependencies=["inspect"],
                model_ref="local-task-reasoner",
            ),
            _node("output", "output", dependencies=["reason"]),
        ]
    )

    graph = compile_execution_graph(request)

    assert graph.graph_id == "graph-execution"
    assert graph.task_id == "task-execution-graph"
    assert graph.metadata["plannerChain"]["strategy"] == "legacy_task_planner"
    inspect = graph.node_by_id("inspect")
    reason = graph.node_by_id("reason")
    output = graph.node_by_id("output")
    assert inspect.tool_binding is not None
    assert inspect.tool_binding.tool_id == "document.markitdown_convert"
    assert inspect.permissions_required == ["read_attachment"]
    assert reason.model_binding is not None
    assert reason.model_binding.model_ref == "local-task-reasoner"
    assert reason.dependencies == ["inspect"]
    assert output.tool_binding is None
    assert output.model_binding is None


def test_compile_execution_graph_derives_manifest_tool_binding_contract() -> None:
    graph = compile_execution_graph(
        _request(
            [
                _node(
                    "document-parse",
                    "fixed_tool",
                    tool_ref="internal:document.markitdown_convert",
                    permissions=["read_attachment"],
                )
            ]
        )
    )

    binding = graph.node_by_id("document-parse").tool_binding

    assert binding is not None
    assert binding.provider_id == "internal"
    assert binding.operation == "convert_local_file"
    assert binding.arguments_template.values == {
        "operation": "convert_local_file",
        "input_path": "{attachment.path}",
        "output_path": "{artifact_dir}/converted/{index:02d}-{attachment_stem}.md",
    }
    assert [
        mapping.model_dump()
        for mapping in binding.input_mappings
    ] == [
        {
            "source": "attachments",
            "source_key": "path",
            "target_argument": "input_path",
            "required": True,
        }
    ]
    assert binding.output_schema is not None
    assert binding.output_schema["required"] == ["text", "artifacts"]
    assert [artifact.model_dump() for artifact in binding.expected_artifacts] == [
        {
            "name": "markdown",
            "path_template": "artifacts/converted/{index:02d}-{attachment_stem}.md",
            "mime_type": "text/markdown",
            "source_argument": "output_path",
        }
    ]
    assert binding.permission_scope.permissions == [
        "read_attachment",
        "read_project_files",
        "write_project_outputs",
        "run_python_plugin",
    ]
    assert binding.permission_scope.timeout_ms == 120_000


def test_compile_execution_graph_prefers_explicit_runtime_tool_binding() -> None:
    node = _node(
        "custom-parse",
        "fixed_tool",
        tool_ref="internal:document.markitdown_convert",
        permissions=["read_attachment"],
    )
    node = GraphNode.model_validate(
        {
            **node.model_dump(),
            "toolBinding": {
                "providerId": "internal",
                "operation": "convert_local_file",
                "argumentsTemplate": {
                    "values": {
                        "operation": "convert_local_file",
                        "input_path": "{document-input.path}",
                        "output_path": "{artifact_dir}/custom.md",
                    },
                    "required": ["operation", "input_path", "output_path"],
                },
                "inputMappings": [
                    {
                        "source": "document-input",
                        "sourceKey": "path",
                        "targetArgument": "input_path",
                    }
                ],
                "expectedArtifacts": [
                    {
                        "name": "custom_markdown",
                        "pathTemplate": "artifacts/custom.md",
                        "mimeType": "text/markdown",
                        "sourceArgument": "output_path",
                    }
                ],
            },
        }
    )

    graph = compile_execution_graph(_request([node]))
    binding = graph.node_by_id("custom-parse").tool_binding

    assert binding is not None
    assert binding.operation == "convert_local_file"
    assert binding.arguments_template.values["output_path"] == (
        "{artifact_dir}/custom.md"
    )
    assert binding.input_mappings[0].source == "document-input"
    assert binding.expected_artifacts[0].name == "custom_markdown"


def test_compile_execution_graph_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ExecutionGraphError, match="duplicate execution node id: same"):
        compile_execution_graph(_request([_node("same", "output"), _node("same", "output")]))


def test_compile_execution_graph_rejects_missing_dependency() -> None:
    with pytest.raises(
        ExecutionGraphError,
        match="node child depends on missing node: missing",
    ):
        compile_execution_graph(_request([_node("child", "output", dependencies=["missing"])]))


def test_validate_execution_graph_rejects_unsupported_fixed_tool_binding() -> None:
    graph = compile_execution_graph(
        _request([_node("unknown-tool", "fixed_tool", tool_ref="internal:unknown.tool")])
    )

    with pytest.raises(
        ExecutionGraphError,
        match="fixed_tool node unknown-tool references unsupported tool binding: unknown.tool",
    ):
        validate_execution_graph_bindings(graph)


def test_validate_execution_graph_rejects_fixed_tool_without_binding() -> None:
    graph = compile_execution_graph(_request([_node("broken-tool", "fixed_tool")]))

    with pytest.raises(
        ExecutionGraphError,
        match="fixed_tool node broken-tool has no tool binding",
    ):
        validate_execution_graph_bindings(graph)


def test_validate_execution_graph_rejects_model_without_binding() -> None:
    graph = compile_execution_graph(_request([_node("broken-model", "model")]))

    with pytest.raises(
        ExecutionGraphError,
        match="model node broken-model has no model binding",
    ):
        validate_execution_graph_bindings(graph)


def test_execution_graph_node_by_id_reports_missing_node() -> None:
    graph = compile_execution_graph(_request([_node("output", "output")]))

    with pytest.raises(ExecutionGraphError, match="execution node not found: missing"):
        graph.node_by_id("missing")
