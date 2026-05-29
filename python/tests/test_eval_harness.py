from __future__ import annotations

import json
from pathlib import Path

from agent_service.eval_harness import (
    EvalCase,
    EvalCaseResult,
    EvalRunSummary,
    load_eval_cases,
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
    assert "| router-hello | router | PASS |" in markdown


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
