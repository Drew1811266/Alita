from __future__ import annotations

import json
from pathlib import Path

from agent_service.eval_harness import (
    EvalCase,
    EvalCategorySummary,
    EvalCaseResult,
    EvalRunSummary,
    _node_ids_from_graph_payload,
    _planner_expectation_matches,
    load_eval_cases,
    load_eval_cases_from_dir,
    run_eval_cases,
    write_eval_summary,
)


def test_load_eval_cases_reads_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps(
            {
                "case_id": "router-hello",
                "category": "router",
                "input": {"task_id": "r1", "content": "Hello"},
                "expected": {"intent": "chat"},
                "tags": ["smoke"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_eval_cases(path)

    assert cases == [
        EvalCase(
            case_id="router-hello",
            category="router",
            input={"task_id": "r1", "content": "Hello"},
            expected={"intent": "chat"},
            tags=["smoke"],
        )
    ]


def test_write_eval_summary_writes_json_and_markdown(tmp_path: Path) -> None:
    summary = EvalRunSummary(
        total=1,
        passed=1,
        failed=0,
        categories={"router": EvalCategorySummary(total=1, passed=1, failed=0)},
        results=[
            EvalCaseResult(
                case_id="router-hello",
                category="router",
                passed=True,
                details={"intent": "chat"},
            )
        ],
    )

    json_path, markdown_path = write_eval_summary(summary, tmp_path)

    assert json_path.read_text(encoding="utf-8").startswith("{")
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "| router | 1 | 1 | 0 |" in markdown
    assert "| router-hello | router | PASS |" in markdown


def test_load_eval_cases_from_dir_reads_jsonl_files_in_name_order(tmp_path: Path) -> None:
    (tmp_path / "b.jsonl").write_text(
        '{"case_id":"router-b","category":"router","input":{"task_id":"router-b","content":"Hello"},"expected":{"intent":"chat"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "a.jsonl").write_text(
        '{"case_id":"router-a","category":"router","input":{"task_id":"router-a","content":"Hello"},"expected":{"intent":"chat"}}\n',
        encoding="utf-8",
    )

    cases = load_eval_cases_from_dir(tmp_path)

    assert [case.case_id for case in cases] == ["router-a", "router-b"]


def test_run_eval_cases_handles_router_case() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="router-task",
                category="router",
                input={
                    "task_id": "router-task",
                    "content": "Create a Python script that counts rows in a CSV file.",
                },
                expected={"intent": "task", "taskType": "code_task"},
            )
        ]
    )

    assert summary.total == 1
    assert summary.failed == 0
    assert summary.categories["router"] == EvalCategorySummary(
        total=1,
        passed=1,
        failed=0,
    )
    assert summary.results[0].details["intent"] == "task"


def test_run_eval_cases_handles_planner_case() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="planner-code",
                category="planner",
                input={
                    "task_id": "planner-code",
                    "content": "Create a Python script that counts rows in a CSV file.",
                },
                expected={
                    "strategy": "legacy_task_planner",
                    "nodeIds": [
                        "task-analysis",
                        "temporary-script-file-inspect",
                        "task-output",
                    ],
                },
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].passed is True
    assert "actionPolicyNodeCount" in summary.results[0].details


def test_planner_eval_enforces_min_node_count() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="planner-min-node-count",
                category="planner",
                input={
                    "task_id": "planner-min-node-count",
                    "content": "Create a Python script that counts rows in a CSV file.",
                },
                expected={"strategy": "legacy_task_planner", "minNodeCount": 999},
            )
        ]
    )

    assert summary.failed == 1
    assert summary.results[0].passed is False


def test_planner_eval_uses_production_reachable_research_flow_choice() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="planner-research-flow",
                category="planner",
                input={
                    "task_id": "planner-research-flow",
                    "content": (
                        "请联网搜索并比较 2026 年本地 Agent Runtime 架构的"
                        "最新方案，输出带来源的研究报告。"
                    ),
                    "inquiry_choice": "research_flow",
                },
                expected={
                    "strategy": "research_flow",
                    "nodeIds": [
                        "research-intent-analysis",
                        "research-markdown-output",
                    ],
                },
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["strategy"] == "research_flow"
    assert summary.results[0].details["routeIntent"] == "web_complex_research_flow"


def test_planner_eval_rejects_research_choice_when_route_is_not_research() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="planner-research-choice-document-task",
                category="planner",
                input={
                    "task_id": "planner-research-choice-document-task",
                    "content": "读取附件文档，整理摘要，并导出 markdown artifact。",
                    "attachments": [
                        {
                            "attachment_id": "att-doc",
                            "name": "input.md",
                            "path": "inputs/input.md",
                            "size_bytes": 100,
                            "mime_type": "text/markdown",
                        }
                    ],
                    "inquiry_choice": "research_flow",
                },
                expected={
                    "strategy": "research_flow",
                    "nodeIds": ["research-markdown-output"],
                },
            )
        ]
    )

    assert summary.failed == 1
    assert summary.results[0].details["routeIntent"] == "task"
    assert "expected research route" in summary.results[0].details["error"]


def test_node_ids_ignore_missing_or_empty_node_ids_for_min_count() -> None:
    node_ids = _node_ids_from_graph_payload(
        {
            "nodes": [
                {"nodeId": "document-input"},
                {"nodeId": None},
                {"nodeId": ""},
                {"displayName": "missing id"},
                {"nodeId": "file-export"},
            ]
        }
    )

    assert node_ids == ["document-input", "file-export"]
    assert not _planner_expectation_matches(
        {"strategy": "document_template", "nodeIds": node_ids},
        {
            "strategy": "document_template",
            "nodeIds": ["document-input", "file-export"],
            "minNodeCount": 3,
        },
    )


def test_run_eval_cases_handles_tool_case() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="tool-receive-attachment",
                category="tool",
                input={
                    "tool_id": "document.receive_attachment",
                    "arguments": {"paths": "example.docx"},
                },
                expected={"ok": True},
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["ok"] is True


def test_run_eval_cases_handles_research_case_without_network() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="research-citations",
                category="research",
                input={
                    "task_id": "research-citations",
                    "content": "Research Python packaging.",
                },
                expected={"requiresCitation": True},
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["citationPresent"] is True


def test_run_eval_cases_handles_security_permission_case() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="security-network-denied",
                category="security",
                input={
                    "kind": "permission",
                    "permissions": ["network"],
                    "default_allowed_permissions": [],
                },
                expected={"ok": False, "errorCode": "permission_required"},
            )
        ]
    )

    assert summary.failed == 0
    assert summary.categories["security"].passed == 1


def test_run_eval_cases_handles_security_sandbox_case() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="security-sandbox-network-import",
                category="security",
                input={"kind": "sandbox", "script": "import socket\nprint('{}')\n"},
                expected={"ok": False, "errorCode": "network_import_denied"},
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["errorCode"] == "network_import_denied"


def test_run_eval_cases_handles_scripted_model_loop_case_by_default() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="model-loop-scripted",
                category="model_loop",
                input={
                    "kind": "react_scripted",
                    "content": "Inspect README.",
                    "model_replies": [
                        '{"kind":"tool","tool_id":"internal:test.echo","arguments":{"message":"README"}}',
                        '{"kind":"final","text":"README inspected."}',
                    ],
                },
                expected={
                    "skipped": False,
                    "runner": "scripted",
                    "ok": True,
                    "toolCallCount": 1,
                    "observationCount": 1,
                    "errorCode": None,
                },
            )
        ]
    )

    assert summary.failed == 0
    assert summary.categories["model_loop"].passed == 1
    assert summary.results[0].details["finalAnswer"] == "README inspected."


def test_model_loop_eval_respects_scripted_tool_permissions() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="model-loop-permission-denied",
                category="model_loop",
                input={
                    "kind": "react_scripted",
                    "tool_permissions": ["read_project_files"],
                    "allowed_permissions": [],
                    "model_replies": [
                        '{"kind":"tool","tool_id":"internal:test.echo","arguments":{"message":"README"}}',
                    ],
                },
                expected={
                    "skipped": False,
                    "runner": "scripted",
                    "ok": False,
                    "toolCallCount": 0,
                    "observationCount": 0,
                    "errorCode": "permission_not_allowed",
                },
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["errorCode"] == "permission_not_allowed"


def test_model_loop_eval_runs_mock_runner_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_MODEL_LOOP_EVAL", "mock")

    summary = run_eval_cases(
        [
            EvalCase(
                case_id="model-loop-mock",
                category="model_loop",
                input={"kind": "planner_binding", "content": "Use echo tool"},
                expected={"skipped": False, "runner": "mock", "ok": True},
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["runner"] == "mock"


def test_eval_harness_writes_summary_for_loaded_cases(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        '{"case_id":"router-hello","category":"router","input":{"task_id":"router-hello","content":"Hello"},"expected":{"intent":"chat"}}\n',
        encoding="utf-8",
    )

    summary = run_eval_cases(load_eval_cases(cases_path), output_dir=tmp_path / "out")

    assert summary.total == 1
    assert (tmp_path / "out" / "summary.json").is_file()
    assert (tmp_path / "out" / "summary.md").is_file()


def test_repository_model_loop_eval_cases_pass() -> None:
    cases_path = Path(__file__).resolve().parents[1] / "evals" / "model_loop_cases.jsonl"

    summary = run_eval_cases(load_eval_cases(cases_path))

    assert summary.total == 12
    assert summary.passed == 12


def test_repository_eval_case_counts_match_v035_gate() -> None:
    cases = load_eval_cases_from_dir(Path(__file__).resolve().parents[1] / "evals")
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1

    assert counts == {
        "model_loop": 12,
        "planner": 16,
        "research": 10,
        "router": 15,
        "security": 24,
        "tool": 10,
    }
    assert sum(counts.values()) == 87
