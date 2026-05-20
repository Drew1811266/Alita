from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from agent_service.goal_spec import GoalSpec
from agent_service.harness_errors import HarnessError, harness_error_payload
from agent_service.model_client import (
    ChatMessage as ModelChatMessage,
    LlamaCppModelClient,
)
from agent_service.model_runtime import ModelRuntime
from agent_service.node_output import NodeOutput
from agent_service.result_verifier import ResultVerifier
from agent_service.run_journal import RunJournal
from agent_service.run_registry import DEFAULT_RUN_REGISTRY, RunRegistry
from agent_service.schemas import AgentEvent, GraphNode, RunGraphRequest
from agent_service.task_graph import build_document_task_graph
from agent_service.tool_execution import (
    ToolExecutor,
    ToolInvocation,
    default_tool_packages_root,
)
from agent_service.tool_registry import ToolRegistry
from tools.document_tool import write_markdown


class NodeExecutor(Protocol):
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        ...


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ModelChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        ...


class EmptyNodeExecutor:
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        return NodeOutput(values={"text": node_id})


class DocumentFlowExecutor:
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        model_client: ModelClient | None = None,
        model_runtime: ModelRuntime | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.request = request
        self.model_client = model_client or LlamaCppModelClient()
        self.model_runtime = model_runtime or ModelRuntime(model_client=self.model_client)
        self.tool_executor = tool_executor or ToolExecutor()
        self.project_dir = Path(request.project_path).parent
        self.artifact_dir = self.project_dir / "artifacts"
        self.task_graph = build_document_task_graph(
            request.task_id,
            GoalSpec(
                goal="Process attached documents into a report artifact.",
                task_type="document_processing",
                deliverable="markdown_report",
                success_criteria=["Generate a local project artifact."],
                required_context=["attachment"],
                risk_level="local_write",
                permissions_required=["read_attachment", "write_project_artifact"],
                confidence=0.85,
            ),
        )

    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if node_id == "document-input":
            if not self.request.attachments:
                raise ValueError("缺少可执行的文档附件")
            return NodeOutput(
                values={
                    "paths": "\n".join(
                        attachment.path for attachment in self.request.attachments
                    )
                }
            )

        if node_id == "document-parse":
            texts: list[str] = []
            artifacts: list[str] = []
            for index, attachment in enumerate(self.request.attachments):
                input_path = Path(attachment.path)
                output_path = self._converted_output_path(index, input_path)
                result = self.tool_executor.run(
                    ToolInvocation(
                        tool_id="document.markitdown_convert",
                        operation="convert_local_file",
                        arguments={
                            "input_path": attachment.path,
                            "output_path": str(output_path),
                        },
                        project_path=self.request.project_path,
                        allowed_roots=self._allowed_roots(),
                    )
                )
                text = result.values.get("text", "")
                if text:
                    texts.append(text)
                artifacts.extend(result.artifacts)
            return NodeOutput(artifacts=artifacts, values={"text": "\n\n".join(texts)})

        if node_id == "content-organize":
            node = self.task_graph.node_by_id(node_id)
            if node.model_binding is None:
                raise ValueError(f"{node_id} is missing model binding")
            return self.model_runtime.run(node.model_binding, inputs=inputs)

        if node_id == "report-generate":
            node = self.task_graph.node_by_id(node_id)
            if node.model_binding is None:
                raise ValueError(f"{node_id} is missing model binding")
            return self.model_runtime.run(node.model_binding, inputs=inputs)

        if node_id == "typst-export":
            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            output_stem = f"report-{uuid4().hex[:8]}"
            result = self.tool_executor.run(
                ToolInvocation(
                    tool_id="document.typst_compile",
                    operation="compile_report_pdf",
                    arguments={
                        "title": Path(self.request.project_path).stem or "Alita Report",
                        "outline": outline,
                        "report": report,
                        "source_output_path": str(
                            self.artifact_dir / "typst" / f"{output_stem}.typ"
                        ),
                        "pdf_output_path": str(
                            self.artifact_dir / "typst" / f"{output_stem}.pdf"
                        ),
                    },
                    project_path=self.request.project_path,
                    allowed_roots=self._allowed_roots(),
                )
            )
            return NodeOutput(artifacts=result.artifacts, values=result.values)

        if node_id == "file-export":
            compiled_artifact = _first_input_value(inputs, "artifact")
            if compiled_artifact:
                return NodeOutput(
                    artifacts=_unique_artifacts_from_inputs(inputs),
                    values={"artifact": compiled_artifact},
                )

            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            output_path = self.artifact_dir / f"report-{uuid4().hex[:8]}.md"
            exported = write_markdown(
                (
                    "# 文档处理结果\n\n"
                    f"## 整理结果\n\n{outline}\n\n"
                    f"## 报告正文\n\n{report}\n"
                ),
                str(output_path),
            )
            return NodeOutput(artifacts=[exported], values={"artifact": exported})

        raise ValueError(f"未支持的节点: {node_id}")

    def _allowed_roots(self) -> list[str]:
        roots = {str(self.project_dir)}
        roots.update(str(Path(attachment.path).parent) for attachment in self.request.attachments)
        return sorted(roots)

    def _converted_output_path(self, index: int, input_path: Path) -> Path:
        unsafe_chars = '<>:"/\\|?*'
        stem = input_path.stem or "attachment"
        safe_stem = "".join(
            "-"
            if character.isspace()
            else character
            for character in stem
            if character not in unsafe_chars
        )
        if not safe_stem:
            safe_stem = "attachment"
        return self.artifact_dir / "converted" / f"{index + 1:02d}-{safe_stem}.md"


def run_graph_events(
    request: RunGraphRequest,
    *,
    executor: NodeExecutor | None = None,
    model_client: ModelClient | None = None,
    tool_executor: ToolExecutor | None = None,
    registry: RunRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    result_verifier: ResultVerifier | None = None,
) -> Iterator[AgentEvent]:
    try:
        ordered_nodes = _topological_nodes(request)
        _validate_graph_tools(request, tool_registry or _default_tool_registry())
    except (ValueError, HarnessError) as error:
        payload = harness_error_payload(error)
        yield AgentEvent(
            type="task.failed",
            payload={
                "taskId": request.task_id,
                "runId": request.run_id,
                **payload,
            },
        )
        return

    selected_nodes = _selected_nodes_for_mode(request, ordered_nodes)
    node_executor = executor or DocumentFlowExecutor(
        request,
        model_client=model_client,
        tool_executor=tool_executor,
    )
    verifier = result_verifier or ResultVerifier()
    run_registry = registry or DEFAULT_RUN_REGISTRY
    cancel_token = run_registry.start(request.run_id)
    journal = RunJournal(project_path=request.project_path, run_id=request.run_id)
    outputs: dict[str, NodeOutput] = {}
    outputs.update(_source_outputs_for_mode(request))

    started_at = _now_iso()
    disabled_tool_ids = set(request.disabled_tool_ids)
    journal.write_run(
        {
            "runId": request.run_id,
            "taskId": request.task_id,
            "status": "running",
            "startedAt": started_at,
            "mode": request.mode.model_dump(),
        }
    )
    yield AgentEvent(
        type="run.started",
        payload={
            "runId": request.run_id,
            "taskId": request.task_id,
            "startedAt": started_at,
        },
    )

    try:
        for node in selected_nodes:
            if node.toolRef and node.toolRef in disabled_tool_ids:
                completed_at = _now_iso()
                error = HarnessError("tool_disabled", f"tool disabled: {node.toolRef}")
                payload = harness_error_payload(error)
                record = {
                    "nodeRunId": f"{request.run_id}-{node.nodeId}",
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "failed",
                    "startedAt": completed_at,
                    "completedAt": completed_at,
                    "artifactRefs": [],
                    "error": str(error),
                    "values": {},
                }
                journal.write_node(node.nodeId, record)
                journal.write_run(
                    {
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "status": "failed",
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "mode": request.mode.model_dump(),
                    }
                )
                yield AgentEvent(
                    type="node.failed",
                    payload={
                        "nodeId": node.nodeId,
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                yield AgentEvent(
                    type="node.run_recorded",
                    payload={"record": _event_record(record)},
                )
                yield AgentEvent(
                    type="task.failed",
                    payload={
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                return

            if cancel_token.cancelled:
                completed_at = _now_iso()
                journal.write_run(
                    {
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "status": "cancelled",
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "mode": request.mode.model_dump(),
                    }
                )
                yield AgentEvent(
                    type="run.cancelled",
                    payload={
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "completedAt": completed_at,
                    },
                )
                return

            node_started_at = _now_iso()
            node_run_id = f"{request.run_id}-{node.nodeId}"
            journal.write_node(
                node.nodeId,
                {
                    "nodeRunId": node_run_id,
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "running",
                    "startedAt": node_started_at,
                    "artifactRefs": [],
                    "values": {},
                },
            )
            yield AgentEvent(type="node.running", payload={"nodeId": node.nodeId})
            try:
                missing_dependencies = [
                    dependency
                    for dependency in node.dependencies
                    if dependency not in outputs
                ]
                if missing_dependencies:
                    raise HarnessError(
                        "missing_dependency_output",
                        (
                            f"node {node.nodeId} is missing dependency output: "
                            f"{', '.join(missing_dependencies)}"
                        ),
                    )
                dependency_outputs = {
                    dependency: outputs[dependency]
                    for dependency in node.dependencies
                    if dependency in outputs
                }
                output = node_executor.run(node.nodeId, dependency_outputs)
                verifier.verify(node.nodeId, output)
            except Exception as error:
                completed_at = _now_iso()
                payload = harness_error_payload(error)
                record = {
                    "nodeRunId": node_run_id,
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "failed",
                    "startedAt": node_started_at,
                    "completedAt": completed_at,
                    "artifactRefs": [],
                    "error": str(error),
                    "values": {},
                }
                journal.write_node(node.nodeId, record)
                journal.write_run(
                    {
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "status": "failed",
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "mode": request.mode.model_dump(),
                    }
                )
                yield AgentEvent(
                    type="node.failed",
                    payload={
                        "nodeId": node.nodeId,
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                yield AgentEvent(
                    type="node.run_recorded",
                    payload={"record": _event_record(record)},
                )
                yield AgentEvent(
                    type="task.failed",
                    payload={
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                return

            completed_at = _now_iso()
            outputs[node.nodeId] = output
            record = {
                "nodeRunId": node_run_id,
                "runId": request.run_id,
                "nodeId": node.nodeId,
                "status": "completed",
                "startedAt": node_started_at,
                "completedAt": completed_at,
                "artifactRefs": output.artifacts,
                "values": output.values,
            }
            journal.write_node(node.nodeId, record)
            yield AgentEvent(
                type="node.completed",
                payload={"nodeId": node.nodeId, "artifactRefs": output.artifacts},
            )
            yield AgentEvent(
                type="node.run_recorded",
                payload={"record": _event_record(record)},
            )
            for artifact_path in output.artifacts:
                yield AgentEvent(
                    type="artifact.created",
                    payload={
                        "artifactId": Path(artifact_path).stem,
                        "path": artifact_path,
                        "sourceNodeId": node.nodeId,
                        "createdAt": completed_at,
                    },
                )

        completed_at = _now_iso()
        journal.write_run(
            {
                "runId": request.run_id,
                "taskId": request.task_id,
                "status": "completed",
                "startedAt": started_at,
                "completedAt": completed_at,
                "mode": request.mode.model_dump(),
            }
        )
        yield AgentEvent(
            type="task.completed",
            payload={"taskId": request.task_id, "runId": request.run_id},
        )
    finally:
        run_registry.finish(request.run_id)


def _topological_nodes(request: RunGraphRequest) -> list[GraphNode]:
    node_ids = {node.nodeId for node in request.graph.nodes}
    for node in request.graph.nodes:
        for dependency in node.dependencies:
            if dependency not in node_ids:
                raise ValueError(f"节点 {node.nodeId} 依赖不存在: {dependency}")

    ordered: list[GraphNode] = []
    completed: set[str] = set()

    while len(ordered) < len(request.graph.nodes):
        ready = [
            node
            for node in request.graph.nodes
            if node.nodeId not in completed
            and all(dependency in completed for dependency in node.dependencies)
        ]
        if not ready:
            raise ValueError("节点流程存在循环依赖或不可满足依赖")

        for node in ready:
            ordered.append(node)
            completed.add(node.nodeId)

    return ordered


def _default_tool_registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(default_tool_packages_root())


def _validate_graph_tools(request: RunGraphRequest, registry: ToolRegistry) -> None:
    for node in request.graph.nodes:
        if node.nodeType != "fixed_tool" or not node.toolRef:
            continue
        try:
            registry.get(node.toolRef)
        except KeyError as error:
            raise HarnessError("unsupported_tool", str(error)) from error


def _selected_nodes_for_mode(
    request: RunGraphRequest,
    ordered_nodes: list[GraphNode],
) -> list[GraphNode]:
    if request.mode.type == "full":
        return ordered_nodes

    downstream = _downstream_node_ids(request)

    if request.mode.type == "from_node" and request.mode.node_id:
        selected = {request.mode.node_id, *downstream.get(request.mode.node_id, set())}
        return [node for node in ordered_nodes if node.nodeId in selected]

    if request.mode.type == "failed_only" and request.mode.source_run_id:
        failed = _failed_node_ids_from_journal(request)
        selected = set(failed)
        for node_id in failed:
            selected.update(downstream.get(node_id, set()))
        return [node for node in ordered_nodes if node.nodeId in selected]

    return ordered_nodes


def _downstream_node_ids(request: RunGraphRequest) -> dict[str, set[str]]:
    direct: dict[str, set[str]] = {node.nodeId: set() for node in request.graph.nodes}
    for edge in request.graph.edges:
        direct.setdefault(edge.source, set()).add(edge.target)
    for node in request.graph.nodes:
        for dependency in node.dependencies:
            direct.setdefault(dependency, set()).add(node.nodeId)

    downstream: dict[str, set[str]] = {node.nodeId: set() for node in request.graph.nodes}
    for node_id in downstream:
        pending = list(direct.get(node_id, set()))
        while pending:
            child = pending.pop()
            if child in downstream[node_id]:
                continue
            downstream[node_id].add(child)
            pending.extend(direct.get(child, set()))
    return downstream


def _failed_node_ids_from_journal(request: RunGraphRequest) -> list[str]:
    if not request.mode.source_run_id:
        return []
    journal = RunJournal(
        project_path=request.project_path,
        run_id=request.mode.source_run_id,
    )
    return [
        record["nodeId"]
        for record in journal.read_nodes()
        if record.get("status") == "failed" and "nodeId" in record
    ]


def _source_outputs_for_mode(request: RunGraphRequest) -> dict[str, NodeOutput]:
    if request.mode.type == "full" or not request.mode.source_run_id:
        return {}

    journal = RunJournal(
        project_path=request.project_path,
        run_id=request.mode.source_run_id,
    )
    outputs: dict[str, NodeOutput] = {}
    for record in journal.read_nodes():
        if record.get("status") != "completed":
            continue
        node_id = record.get("nodeId")
        if not isinstance(node_id, str):
            continue
        values = record.get("values")
        if not isinstance(values, dict):
            values = {}
        artifacts = record.get("artifactRefs")
        if not isinstance(artifacts, list):
            artifacts = []
        outputs[node_id] = NodeOutput(
            artifacts=[str(artifact) for artifact in artifacts],
            values={str(key): str(value) for key, value in values.items()},
        )
    return outputs


def _first_input_value(inputs: dict[str, NodeOutput], key: str) -> str:
    for output in inputs.values():
        if key in output.values:
            return output.values[key]
    return ""


def _unique_artifacts_from_inputs(inputs: dict[str, NodeOutput]) -> list[str]:
    artifacts: list[str] = []
    seen: set[str] = set()
    for output in inputs.values():
        for artifact in output.artifacts:
            if artifact in seen:
                continue
            artifacts.append(artifact)
            seen.add(artifact)
    return artifacts


def _event_record(record: dict) -> dict:
    return {
        "nodeRunId": record["nodeRunId"],
        "runId": record["runId"],
        "nodeId": record["nodeId"],
        "status": record["status"],
        "startedAt": record["startedAt"],
        "completedAt": record.get("completedAt"),
        "artifactRefs": record.get("artifactRefs", []),
        "error": record.get("error"),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
