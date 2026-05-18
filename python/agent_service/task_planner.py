from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Literal

from agent_service.schemas import Attachment
from agent_service.tool_registry import ToolManifestSpec


class TaskKind(str, Enum):
    DOCUMENT = "document"
    CONTENT = "content"
    LOCAL_FILE = "local_file"
    SCRIPT = "script"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilityRequirement:
    capability: str
    description: str
    can_use_model: bool = False
    temporary_script_candidate: bool = False
    risk_factors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SelectedTool:
    capability: str
    tool_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class TemporaryScriptPlan:
    capability: str
    description: str
    risk_level: Literal["low", "medium", "high"]
    requires_approval: bool
    code_preview: str
    permissions: list[str]
    input_contract: dict[str, str]
    output_contract: dict[str, str]
    summary: str


@dataclass(frozen=True)
class ToolGap:
    requirement: CapabilityRequirement
    temporary_script: TemporaryScriptPlan | None = None
    user_message: str | None = None


@dataclass
class TaskPlan:
    kind: TaskKind
    summary: str
    requirements: list[CapabilityRequirement]
    task_id: str = "task"
    selected_tools: list[SelectedTool] = field(default_factory=list)
    tool_gaps: list[ToolGap] = field(default_factory=list)


ModelAnalysisHook = Callable[
    [str, list[Attachment]], Iterable[CapabilityRequirement] | None
]


def analyze_task(
    message: str,
    attachments: list[Attachment],
    *,
    model_analysis_hook: ModelAnalysisHook | None = None,
) -> TaskPlan:
    normalized = message.lower()
    requirements: list[CapabilityRequirement] = []

    if attachments and _contains_any(normalized, ["document", "file", "convert", "markdown", "pdf", "report"]):
        kind = TaskKind.DOCUMENT
        requirements.append(
            CapabilityRequirement(
                capability="document_input",
                description="Receive the user-provided attachment.",
            )
        )
        if _contains_any(normalized, ["convert", "markdown", "md"]):
            requirements.append(
                CapabilityRequirement(
                    capability="document.convert.markdown",
                    description="Convert the attached document to Markdown.",
                )
            )
        if _contains_any(normalized, ["pdf", "export", "report"]):
            requirements.extend(
                [
                    CapabilityRequirement(
                        capability="model.reasoning",
                        description="Organize content into a report.",
                        can_use_model=True,
                    ),
                    CapabilityRequirement(
                        capability="document.render.typst_pdf",
                        description="Render the report as a PDF artifact.",
                    ),
                ]
            )
    elif _contains_any(normalized, ["csv", "inspect", "count rows", "transform local", "local file"]):
        kind = TaskKind.LOCAL_FILE
        requirements.append(
            CapabilityRequirement(
                capability="file.inspect",
                description="Inspect or transform a bounded local file.",
                temporary_script_candidate=True,
            )
        )
    elif _contains_any(normalized, ["delete", "remove matching files", "overwrite"]):
        kind = TaskKind.SCRIPT
        requirements.append(
            CapabilityRequirement(
                capability="file.delete",
                description="Modify or delete selected local files.",
                temporary_script_candidate=True,
                risk_factors=["destructive_write"],
            )
        )
    elif _contains_any(normalized, ["network", "fetch", "download", "credential", "password", "shell", "process"]):
        kind = TaskKind.UNSUPPORTED
        requirements.append(
            CapabilityRequirement(
                capability=_unsupported_capability(normalized),
                description="Perform an operation that needs an unsupported unsafe capability.",
            )
        )
    else:
        kind = TaskKind.CONTENT
        requirements.append(
            CapabilityRequirement(
                capability="model.reasoning",
                description="Reason about and draft the requested content.",
                can_use_model=True,
            )
        )

    if model_analysis_hook is not None:
        requirements.extend(model_analysis_hook(message, attachments) or [])

    return TaskPlan(
        kind=kind,
        summary=_task_summary(kind, message),
        requirements=requirements,
    )


def select_tools(
    requirements: list[CapabilityRequirement],
    enabled_tools: list[ToolManifestSpec],
) -> list[SelectedTool]:
    selected: list[SelectedTool] = []
    selected_capabilities = set()

    for requirement in requirements:
        if requirement.can_use_model:
            continue

        candidates = [
            tool
            for tool in enabled_tools
            if requirement.capability in tool.capabilities
        ]
        if not candidates:
            continue

        tool = sorted(
            candidates,
            key=lambda item: (
                item.source_type == "virtual_system_tool",
                item.runtime is None,
                item.tool_id,
            ),
        )[0]
        if requirement.capability in selected_capabilities:
            continue
        selected.append(
            SelectedTool(
                capability=requirement.capability,
                tool_id=tool.tool_id,
                name=tool.name,
                reason=f"Enabled integrated tool provides {requirement.capability}.",
            )
        )
        selected_capabilities.add(requirement.capability)

    return selected


def resolve_tool_gaps(
    requirements: list[CapabilityRequirement],
    selected_tools: list[SelectedTool],
) -> list[ToolGap]:
    selected_capabilities = {tool.capability for tool in selected_tools}
    gaps: list[ToolGap] = []

    for requirement in requirements:
        if requirement.capability in selected_capabilities or requirement.can_use_model:
            continue

        if requirement.temporary_script_candidate:
            gaps.append(
                ToolGap(
                    requirement=requirement,
                    temporary_script=_temporary_script_for(requirement),
                )
            )
            continue

        gaps.append(
            ToolGap(
                requirement=requirement,
                user_message=(
                    "I do not have an enabled tool or safe temporary-script substitute "
                    f"for: {requirement.description}"
                ),
            )
        )

    return gaps


def build_task_graph(task_plan: TaskPlan) -> dict:
    nodes = _planning_nodes(task_plan)
    edges = _sequential_edges([node["nodeId"] for node in nodes])
    executable_dependencies = ["execution-order-planning"]
    final_dependencies: list[str] = []

    for requirement in task_plan.requirements:
        if not requirement.can_use_model:
            continue
        node_id = _node_id("model", requirement.capability)
        nodes.append(
            _node(
                node_id=node_id,
                node_type="model",
                display_name="Model reasoning",
                status="waiting",
                dependencies=executable_dependencies,
                summary=requirement.description,
                position={"x": 120 + 220 * len(final_dependencies), "y": 420},
                model_ref="local-task-reasoner",
                estimate=_estimate(1200, "medium", "medium", "none"),
                resource_usage=_resource_usage("medium", "medium", "none"),
            )
        )
        edges.append(_edge("execution-order-planning", node_id))
        final_dependencies.append(node_id)

    for selected_tool in task_plan.selected_tools:
        node_id = _node_id("tool", selected_tool.tool_id)
        nodes.append(
            _node(
                node_id=node_id,
                node_type="fixed_tool",
                display_name=selected_tool.name,
                status="waiting",
                dependencies=executable_dependencies,
                summary=selected_tool.reason,
                position={"x": 120 + 220 * len(final_dependencies), "y": 420},
                tool_ref=selected_tool.tool_id,
                estimate=_estimate(2000, "medium", "low", "none"),
                resource_usage=_resource_usage("medium", "low", "none"),
            )
        )
        edges.append(_edge("execution-order-planning", node_id))
        final_dependencies.append(node_id)

    for gap in task_plan.tool_gaps:
        if gap.temporary_script is None:
            continue
        script_plan = gap.temporary_script
        node_id = _node_id("temporary-script", script_plan.capability)
        status = "needs_permission" if script_plan.requires_approval else "waiting"
        nodes.append(
            _node(
                node_id=node_id,
                node_type="temporary_script",
                display_name="Temporary script",
                status=status,
                dependencies=executable_dependencies,
                summary=script_plan.summary,
                position={"x": 120 + 220 * len(final_dependencies), "y": 420},
                script_review={
                    "status": "not_reviewed",
                    "summary": script_plan.summary,
                    "permissions": script_plan.permissions,
                    "riskLevel": script_plan.risk_level,
                    "requiresApproval": script_plan.requires_approval,
                    "codePreview": script_plan.code_preview,
                    "inputContract": script_plan.input_contract,
                    "outputContract": script_plan.output_contract,
                    "approvalFingerprint": None,
                },
                estimate=_estimate(1500, "low", "low", "none"),
                resource_usage=_resource_usage("low", "low", "none"),
            )
        )
        edges.append(_edge("execution-order-planning", node_id))
        final_dependencies.append(node_id)

    unsupported_gaps = [gap for gap in task_plan.tool_gaps if gap.user_message]
    if unsupported_gaps:
        node_id = "missing-tool-response"
        nodes.append(
            _node(
                node_id=node_id,
                node_type="output",
                display_name="Missing tool response",
                status="completed",
                dependencies=["execution-order-planning"],
                summary=" ".join(gap.user_message or "" for gap in unsupported_gaps),
                position={"x": 260, "y": 610},
            )
        )
        edges.append(_edge("execution-order-planning", node_id))
    else:
        node_id = "task-output"
        dependencies = final_dependencies or ["execution-order-planning"]
        nodes.append(
            _node(
                node_id=node_id,
                node_type="output",
                display_name="Task output",
                status="waiting",
                dependencies=dependencies,
                summary="Collect results from the planned task steps and present them to the user.",
                position={"x": 260, "y": 610},
            )
        )
        edges.extend(_edge(dependency, node_id) for dependency in dependencies)

    return {
        "graphId": f"{task_plan.task_id}-graph",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "taskKind": task_plan.kind.value,
            "summary": task_plan.summary,
        },
    }


def _planning_nodes(task_plan: TaskPlan) -> list[dict]:
    planning = [
        (
            "task-analysis",
            "Task analysis",
            task_plan.summary,
        ),
        (
            "capability-analysis",
            "Capability analysis",
            "Required capabilities: "
            + ", ".join(requirement.capability for requirement in task_plan.requirements),
        ),
        (
            "tool-selection",
            "Tool selection",
            _tool_selection_summary(task_plan),
        ),
        (
            "execution-order-planning",
            "Execution-order planning",
            "Run completed planning first, then executable tool/model/script nodes, then output.",
        ),
    ]
    return [
        _node(
            node_id=node_id,
            node_type="planning",
            display_name=display_name,
            status="completed",
            dependencies=[planning[index - 1][0]] if index > 0 else [],
            summary=summary,
            position={"x": 260, "y": 20 + 110 * index},
            estimate=_estimate(100, "low", "low", "none"),
            resource_usage=_resource_usage("low", "low", "none"),
        )
        for index, (node_id, display_name, summary) in enumerate(planning)
    ]


def _temporary_script_for(requirement: CapabilityRequirement) -> TemporaryScriptPlan:
    risk_level: Literal["low", "medium", "high"] = (
        "high" if _is_high_risk(requirement) else "low"
    )
    requires_approval = risk_level == "high"
    return TemporaryScriptPlan(
        capability=requirement.capability,
        description=requirement.description,
        risk_level=risk_level,
        requires_approval=requires_approval,
        code_preview=_script_preview(requirement, risk_level),
        permissions=_script_permissions(requirement, risk_level),
        input_contract={"targetPath": "project-relative file or folder path"},
        output_contract={"summary": "text", "artifacts": "list[string]"},
        summary=(
            "Temporary script can fill this capability gap after approval."
            if requires_approval
            else "Low-risk temporary script can fill this bounded local-file gap."
        ),
    )


def _script_preview(requirement: CapabilityRequirement, risk_level: str) -> str:
    if risk_level == "high":
        return (
            "from pathlib import Path\n\n"
            "def plan_delete(root: str, pattern: str) -> list[str]:\n"
            "    base = Path(root).resolve()\n"
            "    return [str(path) for path in base.glob(pattern) if path.is_file()]\n"
            "# Preview only: deletion requires explicit approval before execution.\n"
        )
    if "csv" in requirement.description.lower() or requirement.capability == "file.inspect":
        return (
            "import csv\n\n"
            "def inspect_csv(path: str) -> dict[str, int]:\n"
            "    with open(path, newline='', encoding='utf-8') as handle:\n"
            "        return {'rows': sum(1 for _ in csv.reader(handle))}\n"
        )
    return (
        "from pathlib import Path\n\n"
        "def inspect_text(path: str) -> dict[str, int]:\n"
        "    text = Path(path).read_text(encoding='utf-8')\n"
        "    return {'characters': len(text), 'lines': len(text.splitlines())}\n"
    )


def _script_permissions(
    requirement: CapabilityRequirement,
    risk_level: str,
) -> list[str]:
    if risk_level == "high":
        return ["read_project_files", "write_project_outputs"]
    return ["read_project_files"]


def _is_high_risk(requirement: CapabilityRequirement) -> bool:
    high_risk_factors = {
        "network",
        "destructive_write",
        "credential",
        "shell_execution",
        "broad_filesystem",
        "process_control",
    }
    return bool(high_risk_factors.intersection(requirement.risk_factors))


def _tool_selection_summary(task_plan: TaskPlan) -> str:
    selected = ", ".join(tool.tool_id for tool in task_plan.selected_tools)
    gaps = ", ".join(gap.requirement.capability for gap in task_plan.tool_gaps)
    if selected and gaps:
        return f"Selected enabled tools: {selected}. Remaining gaps: {gaps}."
    if selected:
        return f"Selected enabled tools: {selected}."
    if gaps:
        return f"No enabled integrated tool matched these capabilities: {gaps}."
    return "No integrated tool required; model or output nodes can satisfy the request."


def _task_summary(kind: TaskKind, message: str) -> str:
    compact_message = re.sub(r"\s+", " ", message.strip())
    if len(compact_message) > 120:
        compact_message = compact_message[:117] + "..."
    return f"Plan a {kind.value.replace('_', ' ')} task for: {compact_message}"


def _unsupported_capability(normalized: str) -> str:
    if _contains_any(normalized, ["network", "fetch", "download"]):
        return "network.fetch"
    if _contains_any(normalized, ["credential", "password"]):
        return "credential.handle"
    if _contains_any(normalized, ["shell"]):
        return "shell.execute"
    if _contains_any(normalized, ["process"]):
        return "process.control"
    return "unsupported.operation"


def _node(
    *,
    node_id: str,
    node_type: str,
    display_name: str,
    status: str,
    dependencies: list[str],
    summary: str,
    position: dict[str, float],
    tool_ref: str | None = None,
    model_ref: str | None = None,
    script_review: dict | None = None,
    estimate: dict | None = None,
    resource_usage: dict | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": display_name,
        "status": status,
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies,
        "summary": summary,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": position,
    }
    if tool_ref is not None:
        node["toolRef"] = tool_ref
    if model_ref is not None:
        node["modelRef"] = model_ref
    if script_review is not None:
        node["scriptReview"] = script_review
    if estimate is not None:
        node["estimate"] = estimate
    if resource_usage is not None:
        node["resourceUsage"] = resource_usage
    return node


def _node_id(prefix: str, value: str) -> str:
    safe_value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return f"{prefix}-{safe_value}"


def _sequential_edges(node_ids: list[str]) -> list[dict]:
    return [
        _edge(source, target)
        for source, target in zip(node_ids, node_ids[1:], strict=False)
    ]


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"{source}-{target}",
        "source": source,
        "target": target,
    }


def _estimate(
    duration_ms: int,
    cpu: str,
    memory: str,
    network: str,
) -> dict[str, int | str]:
    return {
        "durationMs": duration_ms,
        "cpu": cpu,
        "memory": memory,
        "network": network,
    }


def _resource_usage(cpu: str, memory: str, network: str) -> dict[str, str]:
    return {
        "cpu": cpu,
        "memory": memory,
        "network": network,
    }


def _contains_any(content: str, keywords: list[str]) -> bool:
    return any(keyword in content for keyword in keywords)
