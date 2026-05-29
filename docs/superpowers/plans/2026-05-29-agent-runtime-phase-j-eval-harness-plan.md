# Agent Runtime Phase J Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline eval harness that turns router, planner, tool, and research expectations into deterministic regression signals.

**Architecture:** Add `eval_harness.py` with JSONL case loading, category-specific runners, and JSON/Markdown summary output under `.codex-run/evals`. Start with smoke-sized fixtures so `verify-mvp.ps1` can run the harness without network or model services. This phase measures existing behavior; it does not add model judging, remote telemetry, or frontend UI.

**Tech Stack:** Python 3.12, Pydantic v2, JSONL fixtures, existing router/planner/execution/research modules, pytest, PowerShell verify script.

---

## Files

### Create

- `python/agent_service/eval_harness.py`
- `python/evals/router_cases.jsonl`
- `python/evals/planner_cases.jsonl`
- `python/evals/tool_cases.jsonl`
- `python/evals/research_cases.jsonl`
- `python/tests/test_eval_harness.py`

### Modify

- `scripts/verify-mvp.ps1`
  - Add a small eval smoke invocation after Python tests.

---

## Design Contract

Create `python/agent_service/eval_harness.py`:

```python
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
```

Required API:

- `load_eval_cases(path: str | Path) -> list[EvalCase]`
- `run_eval_cases(cases: list[EvalCase], output_dir: str | Path | None = None) -> EvalRunSummary`
- `write_eval_summary(summary: EvalRunSummary, output_dir: str | Path) -> tuple[Path, Path]`
- CLI entrypoint: `python -m agent_service.eval_harness --cases python/evals/router_cases.jsonl --output .codex-run/evals`

Runner behavior:

- Router cases call `router_v2.deterministic_route(UserMessage(task_id=case.case_id, content=case.input)).to_payload()`.
- Planner cases call `PlannerChain` and validate expected node IDs.
- Tool cases use a fake gateway or internal fixed-tool graph that requires no external service.
- Research cases use fake search/source providers and require no network.
- Summary JSON contains every result.
- Summary Markdown contains total, passed, failed, and one row per case.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/router_v2.py`
- Read: `python/agent_service/planner_chain.py`
- Read: `python/agent_service/execution.py`

- [ ] **Step 1: Run Phase I baseline**

Run:

```powershell
python -m pytest -q python\tests\test_research_evidence.py python\tests\test_web_research.py python\tests\test_execution.py
```

Expected:

```text
... passed
```

---

## Task 1: JSONL Loader And Summary Writer

**Files:**
- Create: `python/agent_service/eval_harness.py`
- Create: `python/tests/test_eval_harness.py`

- [ ] **Step 1: Write failing loader tests**

Create `python/tests/test_eval_harness.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.eval_harness'
```

- [ ] **Step 3: Implement loader and writer**

Implement the design contract's models, `load_eval_cases()`, and `write_eval_summary()`.

- [ ] **Step 4: Run eval harness tests**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/eval_harness.py python/tests/test_eval_harness.py
git commit -m "feat: add eval harness loader"
```

---

## Task 2: Router And Planner Eval Runners

**Files:**
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/tests/test_eval_harness.py`
- Create: `python/evals/router_cases.jsonl`
- Create: `python/evals/planner_cases.jsonl`

- [ ] **Step 1: Add runner tests**

Append to `python/tests/test_eval_harness.py`:

```python
from agent_service.eval_harness import run_eval_cases


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
                    "nodeIds": ["task-analysis", "temporary-script-file-inspect", "task-output"],
                },
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].passed is True
```

- [ ] **Step 2: Run new tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py::test_run_eval_cases_handles_router_case python\tests\test_eval_harness.py::test_run_eval_cases_handles_planner_case
```

Expected:

```text
ImportError: cannot import name 'run_eval_cases'
```

- [ ] **Step 3: Implement router/planner runners**

Implement:

- `_run_router_case(case: EvalCase) -> EvalCaseResult`
- `_run_planner_case(case: EvalCase) -> EvalCaseResult`
- `run_eval_cases(cases, output_dir=None)`

Planner runner must:

- Build `UserMessage`.
- Get route payload from `router_v2.deterministic_route(message).to_payload()`.
- Build `GoalSpec` with `parse_goal_spec(message)`.
- Build `ContextBundle` with current `ToolRegistry`.
- Call `PlannerChain`.
- Compare expected `strategy`.
- Check every expected node ID is present.

- [ ] **Step 4: Create smoke eval JSONL files**

Create `python/evals/router_cases.jsonl`:

```jsonl
{"case_id":"router-code-task","category":"router","input":{"task_id":"router-code-task","content":"Create a Python script that counts rows in a CSV file."},"expected":{"intent":"task","taskType":"code_task"},"tags":["smoke"]}
```

Create `python/evals/planner_cases.jsonl`:

```jsonl
{"case_id":"planner-code-task","category":"planner","input":{"task_id":"planner-code-task","content":"Create a Python script that counts rows in a CSV file."},"expected":{"strategy":"legacy_task_planner","nodeIds":["task-analysis","temporary-script-file-inspect","task-output"]},"tags":["smoke"]}
```

- [ ] **Step 5: Run eval harness tests**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py
```

Expected:

```text
4 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/eval_harness.py python/tests/test_eval_harness.py python/evals/router_cases.jsonl python/evals/planner_cases.jsonl
git commit -m "feat: add router and planner evals"
```

---

## Task 3: Tool And Research Eval Smoke Cases

**Files:**
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/tests/test_eval_harness.py`
- Create: `python/evals/tool_cases.jsonl`
- Create: `python/evals/research_cases.jsonl`

- [ ] **Step 1: Add tool and research runner tests**

Append to `python/tests/test_eval_harness.py`:

```python
def test_run_eval_cases_handles_research_case_without_network() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="research-citations",
                category="research",
                input={"task_id": "research-citations", "content": "Research Python packaging."},
                expected={"requiresCitation": True},
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["citationPresent"] is True
```

- [ ] **Step 2: Run new test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py::test_run_eval_cases_handles_research_case_without_network
```

Expected:

```text
FAILED
```

- [ ] **Step 3: Implement deterministic research runner**

Research runner must:

- Use fake `SearchProvider` responses.
- Use fake source content.
- Run `run_graph_events()` on a research flow graph.
- Read the Markdown artifact.
- Set `citationPresent=True` when `[S1]` or `[1]` appears.

Create `python/evals/research_cases.jsonl`:

```jsonl
{"case_id":"research-citation-smoke","category":"research","input":{"task_id":"research-citation-smoke","content":"Research Python packaging."},"expected":{"requiresCitation":true},"tags":["smoke","offline"]}
```

Create `python/evals/tool_cases.jsonl`:

```jsonl
{"case_id":"tool-gateway-smoke","category":"tool","input":{"tool_id":"document.receive_attachment","arguments":{"paths":"example.docx"}},"expected":{"ok":true},"tags":["smoke","offline"]}
```

- [ ] **Step 4: Run eval tests**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/eval_harness.py python/tests/test_eval_harness.py python/evals/tool_cases.jsonl python/evals/research_cases.jsonl
git commit -m "feat: add offline research eval smoke"
```

---

## Task 4: CLI And Verify Script Smoke

**Files:**
- Modify: `python/agent_service/eval_harness.py`
- Modify: `scripts/verify-mvp.ps1`
- Modify: `python/tests/test_eval_harness.py`

- [ ] **Step 1: Add CLI test**

Append to `python/tests/test_eval_harness.py`:

```python
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
```

- [ ] **Step 2: Run test**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py::test_eval_harness_writes_summary_for_loaded_cases
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Add CLI entrypoint**

Add `if __name__ == "__main__":` using `argparse`:

```python
python -m agent_service.eval_harness --cases python/evals/router_cases.jsonl --output .codex-run/evals
```

Exit with code `1` when any case fails.

- [ ] **Step 4: Add verify-mvp smoke command**

In `scripts/verify-mvp.ps1`, after Python tests, add:

```powershell
Write-Host "`n==> Agent eval smoke"
python -m agent_service.eval_harness --cases python/evals/router_cases.jsonl --output .codex-run/evals
```

- [ ] **Step 5: Run CLI and verify script**

Run:

```powershell
python -m agent_service.eval_harness --cases python/evals/router_cases.jsonl --output .codex-run/evals
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/eval_harness.py python/tests/test_eval_harness.py scripts/verify-mvp.ps1
git commit -m "feat: add eval harness smoke verification"
```

---

## Task 5: Final Regression And Review

**Files:**
- Read: `python/agent_service/eval_harness.py`
- Read: `python/evals/router_cases.jsonl`
- Read: `scripts/verify-mvp.ps1`

- [ ] **Step 1: Run Phase J tests**

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run eval CLI smoke**

Run:

```powershell
python -m agent_service.eval_harness --cases python/evals/router_cases.jsonl --output .codex-run/evals
```

Expected:

```text
```

Exit code must be `0`, and `.codex-run/evals/summary.json` plus `.codex-run/evals/summary.md` must exist.

- [ ] **Step 3: Run full MVP verification**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

- [ ] **Step 4: Final code review**

Dispatch final review:

```text
Review Phase J Eval Harness implementation. Prioritize deterministic offline behavior, JSONL compatibility, useful failure details, no network/model dependency, verify-mvp runtime impact, summary output quality, and whether it avoids telemetry, model judging, frontend UI, or broad benchmark scope.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing Phase J.

---

## Acceptance Criteria

Phase J is complete when all statements are true:

- `python/agent_service/eval_harness.py` exists and is tested.
- Router, planner, tool, and research JSONL smoke cases exist.
- Eval harness runs without network and without live model services.
- Summary JSON and Markdown files are written under `.codex-run/evals`.
- `scripts/verify-mvp.ps1` runs a smoke eval.
- Eval failures are deterministic and include case-level details.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase K

Phase K can use eval summaries as regression input for memory/context behavior. Memory should remain local and project-scoped; eval output should not become model memory by default.
