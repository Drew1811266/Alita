# Agent Runtime Phase H Temporary Script Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute low-risk temporary script nodes through a constrained local sandbox while keeping high-risk scripts blocked behind approval.

**Architecture:** Add `sandbox.py` as a narrow subprocess runner with preflight checks, stdin JSON input, stdout JSON output, timeout enforcement, import denylist, path allowlist, and artifact validation. Integrate it only into `PlannedTaskExecutor` temporary_script nodes after existing permission checks pass. This phase does not add Docker, Firecracker, wasm, background jobs, or ReAct access to script execution.

**Tech Stack:** Python 3.12, subprocess, tempfile, pathlib, Pydantic v2, existing `ScriptReviewState`, existing `PermissionGate`, pytest.

---

## Current Baseline

Before Phase H:

- `temporary_script` nodes are represented in public graph nodes.
- High-risk temporary scripts already require permission before execution.
- Low-risk temporary scripts return `scriptStatus: "preview_only"` and do not execute.
- `run_graph_events()` writes node records and task events for planned task graphs.
- Phase F and G must already pass.

The current gap is bounded execution for low-risk scripts that do not require approval.

## Non-Goals

- Do not run high-risk scripts without explicit approval.
- Do not add network access.
- Do not allow writes outside the artifact directory.
- Do not allow reads outside allowed roots.
- Do not expose arbitrary subprocess environment variables.
- Do not add Docker/Firecracker/wasm in this phase.
- Do not expose sandbox execution as a ReAct tool.

## Files

### Create

- `python/agent_service/sandbox.py`
  - Defines `SandboxRequest` and `SandboxResult`.
  - Performs script preflight checks.
  - Runs Python subprocess with timeout.
  - Passes JSON through stdin.
  - Requires JSON stdout with `values` and `artifacts`.
  - Validates returned artifacts stay inside `artifact_dir`.
- `python/tests/test_sandbox.py`
  - Unit tests for allowed reads, path escapes, timeout, network import denial, JSON output, and artifact validation.

### Modify

- `python/agent_service/execution.py`
  - Use sandbox for allowed low-risk `temporary_script` nodes.
  - Keep existing permission-required behavior for high-risk scripts.
- `python/agent_service/task_planner.py`
  - Ensure low-risk generated temporary script nodes have enough script metadata to run in sandbox only when script content is present.
- `python/agent_service/permission_gate.py`
  - Add regression coverage if permission merging needs sandbox-specific permissions.
- `python/tests/test_execution.py`
  - Add integration coverage for sandbox success, denied path escape, timeout, and high-risk approval block.

---

## Design Contract

Create `python/agent_service/sandbox.py` with:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SandboxRequest(BaseModel):
    script: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    project_path: str
    allowed_roots: list[str]
    network_allowed: bool = False
    timeout_seconds: float = 10.0
    artifact_dir: str


class SandboxResult(BaseModel):
    ok: bool
    stdout: str = ""
    stderr: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None
```

Sandbox API:

- `run_sandboxed_python(request: SandboxRequest) -> SandboxResult`
  - Rejects empty script as `error_code="empty_script"`.
  - Rejects forbidden imports when `network_allowed=False`: `socket`, `requests`, `urllib`, `http.client`, `ftplib`, `smtplib`, `subprocess`.
  - Writes script to a temp directory under `artifact_dir/.sandbox`.
  - Executes current Python interpreter with `cwd` set to the sandbox temp directory.
  - Sends `request.arguments` as JSON on stdin.
  - Requires stdout to be JSON object with optional `values` and `artifacts`.
  - Returns `timeout` on timeout.
  - Validates artifact paths are inside `artifact_dir`.
  - Returns no raw absolute artifact paths in `values`; artifact list may contain normalized absolute artifact paths only after validation.

Helper API:

- `validate_sandbox_path(path: str, allowed_roots: list[str]) -> Path`
  - Resolves symlinks.
  - Rejects paths outside all allowed roots as `SandboxViolation("path_not_allowed", str(candidate_path))`.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/execution.py`
- Read: `python/agent_service/task_planner.py`
- Read: `python/tests/test_execution.py`

- [ ] **Step 1: Run Phase G baseline**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py python\tests\test_execution.py python\tests\test_task_planner.py
```

Expected:

```text
... passed
```

---

## Task 1: Sandbox Unit Contract

**Files:**
- Create: `python/agent_service/sandbox.py`
- Create: `python/tests/test_sandbox.py`

- [ ] **Step 1: Write failing sandbox tests**

Create `python/tests/test_sandbox.py` with:

```python
from __future__ import annotations

from pathlib import Path

from agent_service.sandbox import SandboxRequest, run_sandboxed_python


def test_sandbox_reads_allowed_project_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "data.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json, sys\n"
                "payload=json.load(sys.stdin)\n"
                "text=open(payload['path'], encoding='utf-8').read()\n"
                "print(json.dumps({'values': {'rows': len(text.splitlines())}}))\n"
            ),
            arguments={"path": str(source)},
            project_path=str(project / "project.alita"),
            allowed_roots=[str(project)],
            artifact_dir=str(artifact_dir),
        )
    )

    assert result.ok is True
    assert result.values == {"rows": 2}


def test_sandbox_rejects_network_import_when_network_denied(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="import socket\nprint('{}')\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "network_import_denied"


def test_sandbox_rejects_artifact_outside_artifact_dir(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    outside = tmp_path / "outside.txt"

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json, sys\n"
                f"print(json.dumps({{'artifacts': [r'{outside}']}}))\n"
            ),
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(artifact_dir),
        )
    )

    assert result.ok is False
    assert result.error_code == "artifact_path_not_allowed"
```

- [ ] **Step 2: Run sandbox tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_sandbox.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.sandbox'
```

- [ ] **Step 3: Implement minimal sandbox module**

Implement `python/agent_service/sandbox.py` with:

- `SandboxRequest`
- `SandboxResult`
- `SandboxViolation(ValueError)` with `code`
- `_reject_forbidden_imports(script, network_allowed)`
- `_artifact_paths_inside_dir(artifacts, artifact_dir)`
- `run_sandboxed_python(request)`

Use `sys.executable` and `subprocess.run([sys.executable, str(wrapper_path)], input=json.dumps(request.arguments), text=True, capture_output=True, timeout=request.timeout_seconds)`.

Return error codes:

- `empty_script`
- `network_import_denied`
- `timeout`
- `invalid_json_output`
- `artifact_path_not_allowed`
- `sandbox_process_failed`

- [ ] **Step 4: Run sandbox tests**

Run:

```powershell
python -m pytest -q python\tests\test_sandbox.py
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/sandbox.py python/tests/test_sandbox.py
git commit -m "feat: add temporary script sandbox"
```

---

## Task 2: Timeout And Path Escape Coverage

**Files:**
- Modify: `python/agent_service/sandbox.py`
- Modify: `python/tests/test_sandbox.py`

- [ ] **Step 1: Add timeout and path validation tests**

Append to `python/tests/test_sandbox.py`:

```python
def test_sandbox_times_out_long_running_script(tmp_path: Path) -> None:
    result = run_sandboxed_python(
        SandboxRequest(
            script="import time\ntime.sleep(2)\nprint('{}')\n",
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
            artifact_dir=str(tmp_path / "artifacts"),
            timeout_seconds=0.1,
        )
    )

    assert result.ok is False
    assert result.error_code == "timeout"


def test_sandbox_rejects_project_path_escape_argument(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = run_sandboxed_python(
        SandboxRequest(
            script=(
                "import json, sys\n"
                "payload=json.load(sys.stdin)\n"
                "open(payload['path']).read()\n"
                "print(json.dumps({'values': {'ok': True}}))\n"
            ),
            arguments={"path": str(outside)},
            project_path=str(project / "project.alita"),
            allowed_roots=[str(project)],
            artifact_dir=str(tmp_path / "artifacts"),
        )
    )

    assert result.ok is False
    assert result.error_code == "path_not_allowed"
```

- [ ] **Step 2: Run new tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_sandbox.py::test_sandbox_times_out_long_running_script python\tests\test_sandbox.py::test_sandbox_rejects_project_path_escape_argument
```

Expected:

```text
FAILED
```

- [ ] **Step 3: Add recursive argument path preflight**

Before running subprocess, scan `request.arguments` recursively:

```python
def _validate_argument_paths(value: Any, allowed_roots: list[str]) -> None:
    if isinstance(value, str) and _looks_like_path(value):
        validate_sandbox_path(value, allowed_roots)
    elif isinstance(value, list):
        for item in value:
            _validate_argument_paths(item, allowed_roots)
    elif isinstance(value, dict):
        for item in value.values():
            _validate_argument_paths(item, allowed_roots)
```

Treat Windows drive paths and POSIX absolute paths as path-like.

- [ ] **Step 4: Run sandbox tests**

Run:

```powershell
python -m pytest -q python\tests\test_sandbox.py
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/sandbox.py python/tests/test_sandbox.py
git commit -m "test: cover sandbox timeout and path escapes"
```

---

## Task 3: Execution Integration

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add low-risk temporary script execution test**

Append to `python/tests/test_execution.py`:

```python
def test_low_risk_temporary_script_executes_in_sandbox(tmp_path: Path) -> None:
    graph = RunGraph(
        graphId="sandbox-graph",
        nodes=[
            _node(
                "script-node",
                "temporary_script",
                scriptReview=ScriptReviewState(
                    status="not_reviewed",
                    summary="Low-risk script can run in the local sandbox.",
                    riskLevel="low",
                    requiresApproval=False,
                    codePreview="import json, sys\npayload=json.load(sys.stdin)\nprint(json.dumps({'values': {'answer': 42}}))\n",
                    permissions=[],
                ),
            ),
            _node("task-output", "output", dependencies=["script-node"]),
        ],
        edges=[{"id": "script-node-task-output", "source": "script-node", "target": "task-output"}],
        metadata={"plannerChain": {"strategy": "legacy_task_planner"}},
    )
    request = RunGraphRequest(
        task_id="sandbox-task",
        run_id="sandbox-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=graph,
    )

    events = list(run_graph_events(request))

    records = [
        event.payload["record"]
        for event in events
        if event.type == "node.run_recorded"
    ]
    script_record = next(record for record in records if record["nodeId"] == "script-node")
    assert script_record["status"] == "completed"
    assert script_record["values"]["scriptStatus"] == "executed"
    assert script_record["values"]["answer"] == 42
```

Adjust helper names to match existing `test_execution.py`. If `_node()` does not accept `scriptReview`, add a local helper for this test.

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_low_risk_temporary_script_executes_in_sandbox
```

Expected:

```text
AssertionError
```

The current behavior returns `scriptStatus: preview_only`.

- [ ] **Step 3: Wire sandbox into PlannedTaskExecutor**

In `execution.py` temporary_script branch:

- Keep `_script_requires_permission(node)` check first.
- Read script from `node.scriptReview.codePreview`; this is the existing schema field used to expose reviewed temporary script content.
- If missing script content, keep current preview behavior with `scriptStatus: "preview_only"`.
- Build `SandboxRequest`:

```python
SandboxRequest(
    script=generated_script,
    arguments={"inputs": {node_id: output.values for node_id, output in inputs.items()}},
    project_path=self.run_state.project_path or self.request.project_path,
    allowed_roots=[str(Path(self.request.project_path).parent)],
    artifact_dir=str(self.document_executor.artifact_dir),
    timeout_seconds=10.0,
)
```

- If sandbox returns `ok=False`, raise `HarnessError(result.error_code or "sandbox_failed", result.stderr or "temporary script sandbox failed")`.
- On success return `NodeOutput(values={"scriptStatus": "executed", **result.values}, artifacts=result.artifacts)`.

- [ ] **Step 4: Run execution integration tests**

Run:

```powershell
python -m pytest -q python\tests\test_sandbox.py python\tests\test_execution.py::test_low_risk_temporary_script_executes_in_sandbox python\tests\test_execution.py::test_high_risk_temporary_script_blocks_before_any_node_runs
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution.py
git commit -m "feat: execute low risk temporary scripts in sandbox"
```

---

## Task 4: Final Regression And Review

**Files:**
- Read: `python/agent_service/sandbox.py`
- Read: `python/agent_service/execution.py`
- Read: `python/tests/test_sandbox.py`
- Read: `python/tests/test_execution.py`

- [ ] **Step 1: Run Phase H focused tests**

Run:

```powershell
python -m pytest -q python\tests\test_sandbox.py python\tests\test_execution.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run permission and gateway regressions**

Run:

```powershell
python -m pytest -q python\tests\test_permission_gate.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

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
Review Phase H Temporary Script Sandbox implementation. Prioritize path allowlist correctness, network/import denial, timeout handling, artifact validation, high-risk approval preservation, run event compatibility, and whether the sandbox avoids broader container/Docker/ReAct/memory scope.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing Phase H.

---

## Acceptance Criteria

Phase H is complete when all statements are true:

- `python/agent_service/sandbox.py` exists and is covered by `python/tests/test_sandbox.py`.
- Low-risk temporary scripts can execute only through sandbox.
- High-risk scripts remain blocked until approval.
- Script arguments cannot reference paths outside allowed roots.
- Network imports are denied by default.
- Timeouts fail deterministically.
- Artifact paths are validated inside the artifact directory.
- Public event and run journal shapes remain compatible.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase I

Phase I can improve research evidence. It should not depend on sandbox execution. Research fetching remains behind existing search/source fetcher abstractions and should continue to pass privacy guard tests before network access.
