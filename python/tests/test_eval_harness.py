from __future__ import annotations

import json
from pathlib import Path

from agent_service.eval_harness import (
    EvalCase,
    EvalCategorySummary,
    EvalCaseResult,
    EvalRunSummary,
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
