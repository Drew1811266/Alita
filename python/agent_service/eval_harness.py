from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field

from agent_service.context_manager import build_context_bundle
from agent_service.execution import run_graph_events
from agent_service.goal_spec import parse_goal_spec
from agent_service.harness_errors import HarnessError
from agent_service.intent import classify_route
from agent_service.permission_gate import PermissionGate
from agent_service.planner_chain import (
    PlannerChain,
    PlannerChainRequest,
    route_context_from_payload,
)
from agent_service.router_v2 import deterministic_route
from agent_service.sandbox import SandboxRequest, run_sandboxed_python
from agent_service.schemas import GraphNode, RunGraphRequest, UserMessage
from agent_service.tool_execution import (
    ToolExecutor,
    ToolInvocation,
    default_tool_packages_root,
)
from agent_service.tool_registry import ToolRegistry
from agent_service.web_research import build_research_graph
from agent_service.web_search import SearchResponse, SearchResult


class EvalCase(BaseModel):
    case_id: str
    category: Literal["router", "planner", "tool", "research", "recovery", "security"]
    input: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str] = Field(default_factory=list)


class EvalCaseResult(BaseModel):
    case_id: str
    category: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class EvalCategorySummary(BaseModel):
    total: int
    passed: int
    failed: int


class EvalRunSummary(BaseModel):
    total: int
    passed: int
    failed: int
    categories: dict[str, EvalCategorySummary] = Field(default_factory=dict)
    results: list[EvalCaseResult] = Field(default_factory=list)


def load_eval_cases(path: str | Path) -> list[EvalCase]:
    case_path = Path(path)
    cases: list[EvalCase] = []
    for line_number, raw_line in enumerate(
        case_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"invalid JSONL in {case_path} line {line_number}: {error.msg}"
            ) from error
        cases.append(EvalCase.model_validate(payload))
    return cases


def load_eval_cases_from_dir(path: str | Path) -> list[EvalCase]:
    cases_dir = Path(path)
    cases: list[EvalCase] = []
    for case_path in sorted(cases_dir.glob("*.jsonl")):
        cases.extend(load_eval_cases(case_path))
    return cases


def run_eval_cases(
    cases: list[EvalCase],
    output_dir: str | Path | None = None,
) -> EvalRunSummary:
    results = [_run_eval_case(case) for case in cases]
    summary = EvalRunSummary(
        total=len(results),
        passed=sum(1 for result in results if result.passed),
        failed=sum(1 for result in results if not result.passed),
        categories=_category_summaries(results),
        results=results,
    )
    if output_dir is not None:
        write_eval_summary(summary, output_dir)
    return summary


def write_eval_summary(
    summary: EvalRunSummary,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_path = output_path / "summary.json"
    markdown_path = output_path / "summary.md"

    json_path.write_text(
        json.dumps(summary.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_summary_markdown(summary), encoding="utf-8")
    return json_path, markdown_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Alita eval cases.")
    cases_group = parser.add_mutually_exclusive_group(required=True)
    cases_group.add_argument("--cases", help="Path to a JSONL eval case file.")
    cases_group.add_argument(
        "--cases-dir",
        help="Directory containing JSONL eval case files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Directory for summary.json and summary.md.",
    )
    args = parser.parse_args(argv)

    cases = (
        load_eval_cases_from_dir(args.cases_dir)
        if args.cases_dir
        else load_eval_cases(args.cases)
    )
    summary = run_eval_cases(cases, output_dir=args.output)
    print(
        f"Agent eval summary: {summary.passed}/{summary.total} passed, "
        f"{summary.failed} failed."
    )
    return 1 if summary.failed else 0


def _run_eval_case(case: EvalCase) -> EvalCaseResult:
    try:
        if case.category == "router":
            return _run_router_case(case)
        if case.category == "planner":
            return _run_planner_case(case)
        if case.category == "tool":
            return _run_tool_case(case)
        if case.category == "research":
            return _run_research_case(case)
        if case.category == "security":
            return _run_security_case(case)
        return EvalCaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=False,
            details={"error": f"unsupported eval category: {case.category}"},
        )
    except Exception as error:
        return EvalCaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=False,
            details={"error": str(error)},
        )


def _run_security_case(case: EvalCase) -> EvalCaseResult:
    kind = str(case.input.get("kind") or "")
    if kind == "sandbox":
        return _run_sandbox_security_case(case)
    if kind == "permission":
        return _run_permission_security_case(case)
    return EvalCaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=False,
        details={"error": f"unsupported security eval kind: {kind}"},
    )


def _run_sandbox_security_case(case: EvalCase) -> EvalCaseResult:
    with TemporaryDirectory(prefix="alita-eval-security-") as temp_dir:
        temp_path = Path(temp_dir)
        project_dir = temp_path / "project"
        artifact_dir = temp_path / "artifacts"
        project_dir.mkdir()
        artifact_dir.mkdir()
        inside_file = project_dir / "inside.txt"
        outside_file = temp_path / "outside.txt"
        inside_file.write_text("inside", encoding="utf-8")
        outside_file.write_text("outside", encoding="utf-8")
        placeholders = {
            "project_dir": str(project_dir),
            "artifact_dir": str(artifact_dir),
            "inside_file": str(inside_file),
            "outside_file": str(outside_file),
            "outside_artifact": str(temp_path / "outside-artifact.txt"),
        }
        request = SandboxRequest(
            script=str(_render_placeholders(case.input.get("script", ""), placeholders)),
            arguments=dict(
                _render_placeholders(case.input.get("arguments", {}), placeholders)
            ),
            project_path=str(project_dir / "eval.alita"),
            allowed_roots=[str(project_dir)],
            artifact_dir=str(artifact_dir),
            timeout_seconds=float(case.input.get("timeout_seconds", 1.0)),
            network_allowed=bool(case.input.get("network_allowed", False)),
            max_script_bytes=int(case.input.get("max_script_bytes", 64 * 1024)),
            max_output_bytes=int(case.input.get("max_output_bytes", 256 * 1024)),
            max_artifacts=int(case.input.get("max_artifacts", 16)),
            max_artifact_bytes=int(
                case.input.get("max_artifact_bytes", 10 * 1024 * 1024)
            ),
        )
        result = run_sandboxed_python(request)
        details = {
            "ok": result.ok,
            "errorCode": result.error_code,
            "artifacts": [Path(path).name for path in result.artifacts],
            "values": dict(result.values),
        }
        return EvalCaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=_expected_subset_matches(details, case.expected),
            details=details,
        )


def _run_permission_security_case(case: EvalCase) -> EvalCaseResult:
    default_allowed = case.input.get("default_allowed_permissions", None)
    try:
        PermissionGate(
            approved_permissions=list(case.input.get("approved_permissions") or []),
            default_allowed_permissions=(
                None if default_allowed is None else list(default_allowed)
            ),
        ).ensure_node_allowed(
            _security_node(
                case_id=case.case_id,
                permissions=list(case.input.get("permissions") or []),
            ),
            tool_registry=ToolRegistry([]),
        )
        details = {"ok": True, "errorCode": None}
    except HarnessError as error:
        details = {"ok": False, "errorCode": error.code}
    return EvalCaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=_expected_subset_matches(details, case.expected),
        details=details,
    )


def _run_router_case(case: EvalCase) -> EvalCaseResult:
    message = _message_from_case(case)
    payload = deterministic_route(message).to_payload()
    return EvalCaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=_expected_subset_matches(payload, case.expected),
        details=payload,
    )


def _run_planner_case(case: EvalCase) -> EvalCaseResult:
    message = _message_from_case(case)
    route_payload = deterministic_route(message).to_payload()
    goal_spec = parse_goal_spec(message)
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path="eval.alita",
        tool_registry=tool_registry,
    )
    result = PlannerChain(tool_registry=tool_registry).plan(
        PlannerChainRequest(
            task_id=message.task_id,
            message=message,
            goal_spec=goal_spec,
            route=route_context_from_payload(route_payload),
            context=context,
        )
    )
    node_ids = [
        str(node.get("nodeId"))
        for node in result.graph_payload.get("nodes", [])
        if isinstance(node, dict)
    ]
    details = {
        "strategy": result.strategy,
        "planner": result.planner,
        "nodeIds": node_ids,
    }
    return EvalCaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=_planner_expectation_matches(details, case.expected),
        details=details,
    )


def _run_tool_case(case: EvalCase) -> EvalCaseResult:
    tool_id = str(case.input.get("tool_id") or "")
    operation = str(
        case.input.get("operation")
        or _default_operation_for_tool(tool_id)
        or ""
    )
    invocation = ToolInvocation(
        tool_id=tool_id,
        operation=operation,
        arguments=dict(case.input.get("arguments") or {}),
        project_path=str(case.input.get("project_path") or "eval.alita"),
    )
    result = ToolExecutor().run(invocation)
    details = {
        "ok": True,
        "toolId": tool_id,
        "operation": operation,
        "values": dict(result.values),
        "artifacts": list(result.artifacts),
        "metadata": dict(result.metadata),
    }
    return EvalCaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=_expected_subset_matches(details, case.expected),
        details=details,
    )


def _run_research_case(case: EvalCase) -> EvalCaseResult:
    message = _message_from_case(case)
    with TemporaryDirectory(prefix="alita-eval-research-") as temp_dir:
        temp_path = Path(temp_dir)
        request = RunGraphRequest(
            task_id=message.task_id,
            run_id=f"{case.case_id}-run",
            project_path=str(temp_path / "eval.alita"),
            graph=build_research_graph(message, classify_route(message)),
        )
        events = list(
            run_graph_events(
                request,
                search_provider=_OfflineEvalSearchProvider(message.content),
                source_fetcher=_OfflineEvalSourceFetcher(),
            )
        )

        artifact_event = next(
            (event for event in events if event.type == "artifact.created"),
            None,
        )
        markdown = ""
        if artifact_event is not None:
            markdown = Path(artifact_event.payload["path"]).read_text(
                encoding="utf-8"
            )
        citation_present = "[S1]" in markdown or "[1]" in markdown
        details = {
            "ok": bool(artifact_event),
            "citationPresent": citation_present,
            "eventTypes": [event.type for event in events],
        }
        expected = dict(case.expected)
        requires_citation = bool(expected.pop("requiresCitation", False))
        passed = _expected_subset_matches(details, expected)
        if requires_citation:
            passed = passed and citation_present
        return EvalCaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=passed,
            details=details,
        )


def _message_from_case(case: EvalCase) -> UserMessage:
    return UserMessage(
        task_id=str(case.input.get("task_id") or case.case_id),
        content=str(case.input.get("content") or ""),
    )


def _expected_subset_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _planner_expectation_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    if expected.get("strategy") and actual.get("strategy") != expected["strategy"]:
        return False
    expected_node_ids = [str(value) for value in expected.get("nodeIds", [])]
    actual_node_ids = set(str(value) for value in actual.get("nodeIds", []))
    return all(node_id in actual_node_ids for node_id in expected_node_ids)


def _default_operation_for_tool(tool_id: str) -> str | None:
    return {
        "document.receive_attachment": "receive_attachment",
        "document.markitdown_convert": "convert_local_file",
        "document.typst_compile": "compile_report_pdf",
    }.get(tool_id)


def _category_summaries(
    results: list[EvalCaseResult],
) -> dict[str, EvalCategorySummary]:
    categories: dict[str, EvalCategorySummary] = {}
    for result in results:
        current = categories.get(
            result.category,
            EvalCategorySummary(total=0, passed=0, failed=0),
        )
        categories[result.category] = EvalCategorySummary(
            total=current.total + 1,
            passed=current.passed + (1 if result.passed else 0),
            failed=current.failed + (0 if result.passed else 1),
        )
    return categories


def _render_placeholders(value: Any, placeholders: dict[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in placeholders.items():
            rendered = rendered.replace(f"{{{key}}}", replacement)
        return rendered
    if isinstance(value, list):
        return [_render_placeholders(item, placeholders) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _render_placeholders(item, placeholders)
            for key, item in value.items()
        }
    return value


def _security_node(case_id: str, permissions: list[str]) -> GraphNode:
    return GraphNode(
        nodeId=case_id,
        nodeType="model",
        displayName=case_id,
        status="waiting",
        summary="security eval node",
        createdBy="agent",
        position={"x": 0, "y": 0},
        permissionsRequired=permissions,
    )


class _OfflineEvalSearchProvider:
    def __init__(self, question: str) -> None:
        self.question = question
        self.queries: list[str] = []

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        if query != self.question:
            return SearchResponse(results=[])
        return SearchResponse(
            results=[
                SearchResult(
                    title="Python Packaging User Guide",
                    url="https://packaging.python.org/en/latest/",
                    snippet="Official guide to Python packaging tools and workflows.",
                )
            ],
            metadata={"provider": "offline_eval"},
        )


class _OfflineEvalSourceFetcher:
    def fetch(self, url: str) -> str:
        if url != "https://packaging.python.org/en/latest/":
            raise ValueError(f"unexpected eval source URL: {url}")
        return (
            "The Python Packaging User Guide explains pip, build backends, "
            "publishing workflows, and project metadata."
        )


def _summary_markdown(summary: EvalRunSummary) -> str:
    lines = [
        "# Agent Eval Summary",
        "",
        f"- Total: {summary.total}",
        f"- Passed: {summary.passed}",
        f"- Failed: {summary.failed}",
        "",
        "| Category | Total | Passed | Failed |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, category_summary in sorted(summary.categories.items()):
        lines.append(
            f"| {category} | {category_summary.total} | "
            f"{category_summary.passed} | {category_summary.failed} |"
        )
    lines.extend(
        [
            "",
            "| Case | Category | Status |",
            "| --- | --- | --- |",
        ]
    )
    for result in summary.results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"| {result.case_id} | {result.category} | {status} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
