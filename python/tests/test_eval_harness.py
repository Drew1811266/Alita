from __future__ import annotations

import json
from pathlib import Path

from agent_service.eval_harness import (
    EvalCase,
    EvalCaseResult,
    EvalRunSummary,
    load_eval_cases,
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
