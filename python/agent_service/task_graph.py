from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec, RiskLevel


TaskNodeKind = Literal["input", "fixed_tool", "model", "output"]


class TaskGraphValidationError(ValueError):
    pass


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff_seconds: float = 0


class ToolBinding(BaseModel):
    tool_id: str
    operation: str


class ModelBinding(BaseModel):
    model_ref: str
    purpose: str


class TaskNodeUi(BaseModel):
    display_name: str
    position: dict[str, float] = Field(default_factory=dict)


class TaskNode(BaseModel):
    node_id: str
    objective: str
    kind: TaskNodeKind
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    permissions_required: list[str] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    tool_binding: ToolBinding | None = None
    model_binding: ModelBinding | None = None
    ui: TaskNodeUi | None = None


class TaskEdge(BaseModel):
    edge_id: str
    source: str
    target: str


class TaskGraph(BaseModel):
    graph_id: str
    task_id: str
    objective: str
    nodes: list[TaskNode] = Field(default_factory=list)
    edges: list[TaskEdge] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "read_only"
    permissions_required: list[str] = Field(default_factory=list)

    def node_by_id(self, node_id: str) -> TaskNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise TaskGraphValidationError(f"node not found: {node_id}")


def build_document_task_graph(task_id: str, goal_spec: GoalSpec) -> TaskGraph:
    task_graph = TaskGraph(
        graph_id=f"{task_id}-graph",
        task_id=task_id,
        objective=goal_spec.goal,
        success_criteria=list(goal_spec.success_criteria),
        risk_level=goal_spec.risk_level,
        permissions_required=list(goal_spec.permissions_required),
        nodes=[
            TaskNode(
                node_id="document-input",
                objective="Receive the user-provided document attachment.",
                kind="input",
                inputs=[],
                outputs=["document"],
                dependencies=[],
                success_criteria=["Document attachment is available to the task."],
                risk_level="read_only",
                permissions_required=["read_attachment"],
                ui=TaskNodeUi(
                    display_name="Document input",
                    position={"x": 260, "y": 20},
                ),
            ),
            TaskNode(
                node_id="document-parse",
                objective="Convert the source document into markdown for model use.",
                kind="fixed_tool",
                inputs=["document"],
                outputs=["markdown"],
                dependencies=["document-input"],
                success_criteria=["Markdown text is produced from the document."],
                risk_level="read_only",
                permissions_required=["read_attachment"],
                tool_binding=ToolBinding(
                    tool_id="document.markitdown_convert",
                    operation="convert_local_file",
                ),
                ui=TaskNodeUi(
                    display_name="Document to Markdown",
                    position={"x": 260, "y": 190},
                ),
            ),
            TaskNode(
                node_id="content-organize",
                objective="Organize extracted document content into a usable outline.",
                kind="model",
                inputs=["markdown"],
                outputs=["outline"],
                dependencies=["document-parse"],
                success_criteria=["A structured outline captures the key points."],
                risk_level="read_only",
                model_binding=ModelBinding(
                    model_ref="local.content_organizer",
                    purpose="organize_document_content",
                ),
                ui=TaskNodeUi(
                    display_name="Organize content",
                    position={"x": 90, "y": 370},
                ),
            ),
            TaskNode(
                node_id="report-generate",
                objective="Write the report body from the extracted document content.",
                kind="model",
                inputs=["markdown", "outline"],
                outputs=["report_markdown"],
                dependencies=["document-parse", "content-organize"],
                success_criteria=["A report draft satisfies the requested goal."],
                risk_level="read_only",
                model_binding=ModelBinding(
                    model_ref="local.report_writer",
                    purpose="write_document_report",
                ),
                ui=TaskNodeUi(
                    display_name="Generate report",
                    position={"x": 430, "y": 370},
                ),
            ),
            TaskNode(
                node_id="typst-export",
                objective="Compile the organized report into Typst and PDF artifacts.",
                kind="fixed_tool",
                inputs=["outline", "report_markdown"],
                outputs=["typst_source", "pdf"],
                dependencies=["content-organize", "report-generate"],
                success_criteria=["Typst source and PDF artifacts are generated."],
                risk_level="local_write",
                permissions_required=["write_project_artifact"],
                tool_binding=ToolBinding(
                    tool_id="document.typst_compile",
                    operation="compile_report_pdf",
                ),
                ui=TaskNodeUi(
                    display_name="Typst PDF export",
                    position={"x": 260, "y": 560},
                ),
            ),
            TaskNode(
                node_id="file-export",
                objective="Expose the final files as task artifacts.",
                kind="output",
                inputs=["typst_source", "pdf"],
                outputs=["artifact"],
                dependencies=["typst-export"],
                success_criteria=list(goal_spec.success_criteria),
                risk_level=goal_spec.risk_level,
                permissions_required=list(goal_spec.permissions_required),
                ui=TaskNodeUi(
                    display_name="Export files",
                    position={"x": 260, "y": 750},
                ),
            ),
        ],
        edges=[
            TaskEdge(
                edge_id="document-input-document-parse",
                source="document-input",
                target="document-parse",
            ),
            TaskEdge(
                edge_id="document-parse-content-organize",
                source="document-parse",
                target="content-organize",
            ),
            TaskEdge(
                edge_id="document-parse-report-generate",
                source="document-parse",
                target="report-generate",
            ),
            TaskEdge(
                edge_id="content-organize-report-generate",
                source="content-organize",
                target="report-generate",
            ),
            TaskEdge(
                edge_id="content-organize-typst-export",
                source="content-organize",
                target="typst-export",
            ),
            TaskEdge(
                edge_id="report-generate-typst-export",
                source="report-generate",
                target="typst-export",
            ),
            TaskEdge(
                edge_id="typst-export-file-export",
                source="typst-export",
                target="file-export",
            ),
        ],
    )
    validate_task_graph(task_graph)
    return task_graph


def validate_task_graph(task_graph: TaskGraph) -> None:
    node_ids = [node.node_id for node in task_graph.nodes]
    known_node_ids = set(node_ids)

    if len(known_node_ids) != len(node_ids):
        raise TaskGraphValidationError("duplicate task node id")

    for node in task_graph.nodes:
        for dependency in node.dependencies:
            if dependency not in known_node_ids:
                raise TaskGraphValidationError(
                    f"missing dependency '{dependency}' for node '{node.node_id}'"
                )

    for edge in task_graph.edges:
        if edge.source not in known_node_ids:
            raise TaskGraphValidationError(
                f"missing edge source '{edge.source}' for edge '{edge.edge_id}'"
            )
        if edge.target not in known_node_ids:
            raise TaskGraphValidationError(
                f"missing edge target '{edge.target}' for edge '{edge.edge_id}'"
            )

    visiting: set[str] = set()
    visited: set[str] = set()
    nodes_by_id = {node.node_id: node for node in task_graph.nodes}

    def visit(node_id: str, path: list[str]) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            cycle_start = path.index(node_id) if node_id in path else 0
            cycle_path = path[cycle_start:] + [node_id]
            raise TaskGraphValidationError(
                f"cycle detected: {' -> '.join(cycle_path)}"
            )

        visiting.add(node_id)
        path.append(node_id)
        for dependency in nodes_by_id[node_id].dependencies:
            visit(dependency, path)
        path.pop()
        visiting.remove(node_id)
        visited.add(node_id)

    for node in task_graph.nodes:
        visit(node.node_id, [])
