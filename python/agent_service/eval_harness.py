from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    case_id: str
    category: Literal["router", "planner", "tool", "research", "recovery"]
    input: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str] = Field(default_factory=list)


class EvalCaseResult(BaseModel):
    case_id: str
    category: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class EvalRunSummary(BaseModel):
    total: int
    passed: int
    failed: int
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


def _summary_markdown(summary: EvalRunSummary) -> str:
    lines = [
        "# Agent Eval Summary",
        "",
        f"- Total: {summary.total}",
        f"- Passed: {summary.passed}",
        f"- Failed: {summary.failed}",
        "",
        "| Case | Category | Status |",
        "| --- | --- | --- |",
    ]
    for result in summary.results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"| {result.case_id} | {result.category} | {status} |")
    return "\n".join(lines) + "\n"
