# Alita v0.35 Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking; this copy records the completed v0.35 implementation state.

**Goal:** Implement the v0.35 testing and bug-audit plan by closing README drift, adding Rust CI coverage, expanding deterministic Agent evals, adding fake-model and artifact regression coverage, and documenting release evidence gates.

**Architecture:** Treat this as a test infrastructure project, not a feature rewrite. Start with documentation and CI gates, then expand deterministic backend evals, then add narrow integration tests around model, document/artifact, checkpoint, and research evidence flows. Keep all external-network, real-model, and desktop-window checks separated into release smoke scripts/checklists so PR tests remain deterministic.

**Tech Stack:** GitHub Actions on Windows, PowerShell scripts, Python 3.12 + pytest + FastAPI/http server helpers, TypeScript/Vitest, Rust cargo tests, Tauri 2, existing Alita deterministic eval harness.

---

## File Structure

Create:

- `docs/test-traceability/alita-v035-feature-test-map.md` - canonical mapping from README capability claims to tests, eval cases, and manual release smoke checks.
- `scripts/collect-test-baseline.ps1` - local command that prints current test file counts and current eval case counts for README updates.
- `python/tests/test_model_client_http_integration.py` - local fake OpenAI-compatible HTTP server tests for non-streaming and streaming model calls.
- `python/tests/test_document_artifact_fixtures.py` - real document fixture regression tests for Markdown, DOCX, corrupt DOCX, and exported artifacts.
- `docs/release-smoke/alita-v035-release-smoke.md` - release checklist for desktop, live search/weather, ASR, artifact preview, and evidence capture.

Modify:

- `README.md` - update current test file counts and current verification results.
- `.github/workflows/ci.yml` - add Rust/Tauri job.
- `docs/alita-v0.35-test-plan.md` - add link to the implementation plan and traceability map.
- `docs/mvp-verification.md` - clarify that `verify-mvp.ps1` is the local full gate and CI is split into jobs.
- `python/agent_service/eval_harness.py` - allow scripted model-loop cases to configure tool permissions and allowed permissions.
- `python/evals/model_loop_cases.jsonl` - expand model-loop eval from 1 case to 12 deterministic cases.
- `python/evals/router_cases.jsonl` - add Chinese mixed-intent router cases.
- `python/evals/planner_cases.jsonl` - add multi-tool and schema rejection planner cases.
- `python/tests/test_eval_harness.py` - test the expanded scripted model-loop behaviors.
- `python/tests/test_execution.py` - add checkpoint resume and research evidence artifact regression tests.
- `src/features/artifacts/ArtifactPreviewPanel.test.tsx` - add audio preview and unsupported-file regression coverage if missing after inspection.

Do not modify runtime behavior outside the narrow hooks needed for deterministic tests. If a test reveals a real bug, fix the bug in the same phase that introduced the failing test.

---

## Phase 1: README Drift, Baseline Script, and Traceability Map

**Outcome:** README and test-plan documentation reflect the actual v0.35 state, and future count drift is easy to detect locally.

**Files:**

- Modify: `README.md`
- Modify: `docs/alita-v0.35-test-plan.md`
- Modify: `docs/mvp-verification.md`
- Create: `docs/test-traceability/alita-v035-feature-test-map.md`
- Create: `scripts/collect-test-baseline.ps1`

### Task 1.1: Add baseline count script

- [x] **Step 1: Create `scripts/collect-test-baseline.ps1`**

Create the file with this content:

```powershell
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $pythonTestFiles = @(Get-ChildItem python\tests -Filter "test_*.py").Count
    $rustTestFiles = @(Get-ChildItem src-tauri\tests -Filter "*.rs").Count
    $frontendTestFiles = @(Get-ChildItem src -Recurse -Include "*.test.ts", "*.test.tsx").Count

    $evalCounts = [ordered]@{}
    Get-ChildItem python\evals -Filter "*.jsonl" | Sort-Object Name | ForEach-Object {
        Get-Content $_.FullName | Where-Object { $_.Trim() } | ForEach-Object {
            $case = $_ | ConvertFrom-Json
            $category = [string]$case.category
            if (-not $evalCounts.Contains($category)) {
                $evalCounts[$category] = 0
            }
            $evalCounts[$category]++
        }
    }

    [pscustomobject]@{
        pythonTestFiles = $pythonTestFiles
        rustTauriTestFiles = $rustTestFiles
        frontendTestFiles = $frontendTestFiles
        evalTotal = ($evalCounts.Values | Measure-Object -Sum).Sum
        evalCounts = $evalCounts
    } | ConvertTo-Json -Depth 5
}
finally {
    Pop-Location
}
```

- [x] **Step 2: Run the script**

Run:

```powershell
.\scripts\collect-test-baseline.ps1
```

Expected output after this implementation plan is complete:

```json
{
  "pythonTestFiles": 71,
  "rustTauriTestFiles": 17,
  "frontendTestFiles": 32,
  "evalTotal": 87,
  "evalCounts": {
    "model_loop": 12,
    "planner": 16,
    "research": 10,
    "router": 15,
    "security": 24,
    "tool": 10
  }
}
```

### Task 1.2: Update README counts and verification results

- [x] **Step 1: Modify README test file counts**

Replace the block under `当前仓库大约包含：` with:

```markdown
- Python 测试文件：71 个
- Rust/Tauri 测试文件：17 个
- 前端测试文件：32 个
```

- [x] **Step 2: Modify README verification result block**

Replace the block under `本轮 Agent Runtime goal 验证结果：` with:

```text
git diff --check
passed

npm run agent:eval
87/87 passed

Push-Location python; python -m pytest -q; Pop-Location
823 passed

npm run frontend:typecheck
passed

npm run frontend:test
32 test files passed, 211 tests passed

npm run frontend:build
passed

cargo test --manifest-path src-tauri/Cargo.toml
162 tests passed

.\scripts\verify-mvp.ps1
passed
```

- [x] **Step 3: Verify README no longer has stale numbers**

Run:

```powershell
rg -n "39 个|12 个|23 个|67/67|780 passed" README.md
```

Expected: no matches.

### Task 1.3: Add feature-test traceability map

- [x] **Step 1: Create `docs/test-traceability/alita-v035-feature-test-map.md`**

Create the file with this content:

```markdown
# Alita v0.35 Feature-Test Traceability Map

Generated: 2026-05-31
Scope: README feature claims, automated test references, eval coverage, and release smoke coverage.

| Feature Claim | Automated Tests | Eval Cases | Release Smoke |
| --- | --- | --- | --- |
| `.alita` project create/open/save and run history persistence | `src-tauri/tests/project_tests.rs`, `src/features/project/*.test.tsx` | none | `docs/release-smoke/alita-v035-release-smoke.md#project-file-smoke` |
| Tauri desktop workbench launch | `src-tauri/tests/sidecar_tests.rs`, `src-tauri/tests/tauri_config_tests.rs` | none | `docs/release-smoke/alita-v035-release-smoke.md#desktop-launch-smoke` |
| Local llama.cpp model client | `python/tests/test_model_client.py`, `python/tests/test_model_client_http_integration.py`, `src-tauri/tests/llama_runtime_tests.rs` | none | `docs/release-smoke/alita-v035-release-smoke.md#local-model-smoke` |
| Agent intent routing | `python/tests/test_intent.py`, `python/tests/test_router_v2.py`, `python/tests/test_graph.py` | `python/evals/router_cases.jsonl` | none |
| Weather and web search | `python/tests/test_weather_provider.py`, `python/tests/test_web_provider_chain.py`, `python/tests/test_web_search.py` | `python/evals/tool_cases.jsonl`, `python/evals/research_cases.jsonl` | `docs/release-smoke/alita-v035-release-smoke.md#live-network-smoke` |
| Research flow and claim/evidence output | `python/tests/test_web_research.py`, `python/tests/test_research_evidence.py`, `python/tests/test_execution.py` | `python/evals/research_cases.jsonl` | `docs/release-smoke/alita-v035-release-smoke.md#research-artifact-smoke` |
| Document task graph and artifact output | `python/tests/test_task_planner.py`, `python/tests/test_graph_compiler.py`, `python/tests/test_execution.py`, `python/tests/test_document_artifact_fixtures.py` | `python/evals/planner_cases.jsonl` | `docs/release-smoke/alita-v035-release-smoke.md#document-artifact-smoke` |
| Tool gateway, manifest tools, and permission boundary | `python/tests/test_tool_gateway.py`, `python/tests/test_tool_execution.py`, `src-tauri/tests/tool_manifest_tests.rs`, `python/tests/test_authority.py` | `python/evals/security_cases.jsonl`, `python/evals/tool_cases.jsonl` | none |
| Checkpoint, resume, trace, and memory | `python/tests/test_run_journal.py`, `python/tests/test_runtime_store.py`, `python/tests/test_trace_store.py`, `python/tests/test_memory_store.py`, `python/tests/test_execution.py` | none | `docs/release-smoke/alita-v035-release-smoke.md#runtime-resume-smoke` |
| API provider secrets and redaction | `src-tauri/tests/api_provider_commands_tests.rs`, `src-tauri/tests/agent_model_config_tests.rs`, `python/tests/test_model_client.py` | `python/evals/security_cases.jsonl` | `docs/release-smoke/alita-v035-release-smoke.md#api-key-redaction-smoke` |
| Voice input and ASR | `src/features/voice/*.test.ts`, `src-tauri/tests/asr_tests.rs`, `python/tests/test_asr.py` | none | `docs/release-smoke/alita-v035-release-smoke.md#asr-smoke` |
| Artifact preview and open/reveal | `src/features/artifacts/*.test.tsx`, `src-tauri/tests/artifact_open_tests.rs` | none | `docs/release-smoke/alita-v035-release-smoke.md#artifact-preview-smoke` |
| MCP stdio tool provider | `python/tests/test_mcp_client_factory.py`, `python/tests/test_mcp_tool_provider.py`, `src-tauri/tests/tool_provider_commands_tests.rs` | none | `docs/release-smoke/alita-v035-release-smoke.md#mcp-stdio-smoke` |
```

- [x] **Step 2: Link traceability map from `docs/alita-v0.35-test-plan.md`**

Add this sentence after the "目标" paragraph:

```markdown
实施追踪表见 `docs/test-traceability/alita-v035-feature-test-map.md`；分阶段实施任务见 `docs/superpowers/plans/2026-05-31-alita-v035-test-implementation-plan.md`。
```

### Task 1.4: Clarify MVP verification documentation

- [x] **Step 1: Update `docs/mvp-verification.md` automatic verification section**

After the existing list of commands in `## 自动验证`, add:

```markdown
GitHub Actions 当前把快速门禁拆成 frontend 和 python 两个 job；Rust/Tauri 测试由 `verify-mvp.ps1` 在本地全量门禁中执行。Rust/Tauri CI job 会在测试实施计划 Phase 2 中补齐。
```

- [x] **Step 2: Run documentation checks**

Run:

```powershell
rg -n "alita-v035-feature-test-map|alita-v035-test-implementation-plan" docs
git diff --check
```

Expected: both doc paths appear; `git diff --check` exits 0.

### Phase 1 Gate

Run:

```powershell
.\scripts\collect-test-baseline.ps1
rg -n "39 个|12 个|23 个|67/67|780 passed" README.md
git diff --check
```

Pass criteria:

- Baseline script prints valid JSON.
- README has no stale test counts.
- No whitespace errors.

---

## Phase 2: Rust/Tauri CI Gate

**Outcome:** PR and main branch pushes run Rust formatting and Rust/Tauri tests on Windows CI.

**Files:**

- Modify: `.github/workflows/ci.yml`

### Task 2.1: Add Rust CI job

- [x] **Step 1: Modify `.github/workflows/ci.yml`**

Append this job after the `python` job:

```yaml
  rust:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: x86_64-pc-windows-msvc
      - name: Rust format
        working-directory: src-tauri
        run: cargo fmt --check
      - name: Rust tests
        run: cargo test --manifest-path src-tauri/Cargo.toml
```

- [x] **Step 2: Run local Rust gate**

Run:

```powershell
Push-Location src-tauri
cargo fmt --check
Pop-Location
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected: format exits 0; Rust/Tauri tests pass with current count `162`.

- [x] **Step 3: Verify workflow syntax is still parseable YAML text**

Run:

```powershell
rg -n "rust:|Rust format|cargo test --manifest-path src-tauri/Cargo.toml" .github\workflows\ci.yml
git diff --check
```

Expected: all three patterns appear; no whitespace errors.

### Phase 2 Gate

Run:

```powershell
Push-Location src-tauri; cargo fmt --check; Pop-Location
cargo test --manifest-path src-tauri/Cargo.toml
git diff --check
```

Pass criteria:

- Rust format passes.
- Rust/Tauri tests pass.
- Workflow contains the new `rust` job.

---

## Phase 3: Expand Scripted Model-Loop Eval

**Outcome:** deterministic Agent eval proves ReAct tool loops, malformed actions, tool budgets, step budgets, permission denial, and redacted observations without real model calls.

**Files:**

- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/tests/test_eval_harness.py`
- Modify: `python/evals/model_loop_cases.jsonl`

### Task 3.1: Add configurable tool permissions to scripted eval harness

- [x] **Step 1: Write failing test in `python/tests/test_eval_harness.py`**

Add this test after `test_run_eval_cases_handles_scripted_model_loop_case_by_default`:

```python
def test_model_loop_eval_respects_scripted_tool_permissions() -> None:
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="model-loop-permission-denied",
                category="model_loop",
                input={
                    "kind": "react_scripted",
                    "content": "Read a file.",
                    "tool_id": "internal:file.inspect",
                    "tool_permissions": ["read_project_files"],
                    "allowed_permissions": [],
                    "model_replies": [
                        '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{"path":"README.md"}}'
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
```

- [x] **Step 2: Run the new test and confirm it fails**

Run:

```powershell
Push-Location python
python -m pytest tests/test_eval_harness.py::test_model_loop_eval_respects_scripted_tool_permissions -q
Pop-Location
```

Expected before implementation: fail because `_scripted_tool()` always returns `permissions=[]`.

- [x] **Step 3: Modify `_run_scripted_model_loop()` and `_scripted_tool()`**

In `python/agent_service/eval_harness.py`, replace:

```python
    tool = _scripted_tool(tool_id)
```

with:

```python
    tool = _scripted_tool(
        tool_id,
        permissions=[
            str(permission)
            for permission in case.input.get("tool_permissions") or []
        ],
    )
```

Replace the `ReActPolicy(...)` block with:

```python
        policy=ReActPolicy(
            enabled=True,
            max_steps=int(case.input.get("max_steps") or 4),
            max_tool_calls=int(case.input.get("max_tool_calls") or 3),
            allowed_tool_ids=[
                str(tool_id)
                for tool_id in case.input.get("allowed_tool_ids") or [tool_id]
            ],
            allowed_permissions=[
                str(permission)
                for permission in case.input.get("allowed_permissions") or []
            ],
            stop_on_first_success=False,
        ),
```

Change `_scripted_tool()` signature and permissions:

```python
def _scripted_tool(
    tool_id: str,
    *,
    permissions: list[str] | None = None,
) -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id=tool_id,
        source="internal",
        provider_id="internal",
        provider_tool_name=tool_id.removeprefix("internal:"),
        display_name="Scripted Tool",
        description="Deterministic scripted eval tool.",
        capabilities=["scripted"],
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
        output_schema={"type": "object"},
        permissions=list(permissions or []),
        safety_policy=ToolSafetyPolicy(
            filesystem="none",
            network="none",
            user_approval="never",
            secrets="none",
            sandbox="not_required",
            max_runtime_ms=1000,
        ),
        timeout_ms=1000,
    )
```

- [x] **Step 4: Run targeted tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_eval_harness.py::test_run_eval_cases_handles_scripted_model_loop_case_by_default tests/test_eval_harness.py::test_model_loop_eval_respects_scripted_tool_permissions -q
Pop-Location
```

Expected: both tests pass.

### Task 3.2: Add deterministic model-loop eval cases

- [x] **Step 1: Replace `python/evals/model_loop_cases.jsonl`**

Replace the file with these 12 JSONL lines:

```jsonl
{"case_id":"model-loop-scripted-react-tool-final","category":"model_loop","input":{"kind":"react_scripted","content":"Inspect README.","model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"README\"}}","{\"kind\":\"final\",\"text\":\"README inspected.\"}"]},"expected":{"skipped":false,"runner":"scripted","ok":true,"toolCallCount":1,"observationCount":1,"errorCode":null},"tags":["model-loop","offline","scripted"]}
{"case_id":"model-loop-scripted-two-tool-calls","category":"model_loop","input":{"kind":"react_scripted","content":"Inspect README twice.","model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"README first\"}}","{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"README second\"}}","{\"kind\":\"final\",\"text\":\"Two inspections completed.\"}"],"max_steps":4,"max_tool_calls":3},"expected":{"skipped":false,"runner":"scripted","ok":true,"toolCallCount":2,"observationCount":2,"errorCode":null},"tags":["model-loop","offline","scripted"]}
{"case_id":"model-loop-scripted-final-immediately","category":"model_loop","input":{"kind":"react_scripted","content":"Answer without tools.","model_replies":["{\"kind\":\"final\",\"text\":\"No tool required.\"}"]},"expected":{"skipped":false,"runner":"scripted","ok":true,"finalAnswer":"No tool required.","toolCallCount":0,"observationCount":0,"errorCode":null},"tags":["model-loop","offline","scripted"]}
{"case_id":"model-loop-scripted-unknown-tool","category":"model_loop","input":{"kind":"react_scripted","content":"Use an unknown tool.","tool_id":"internal:test.echo","model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:unknown\",\"arguments\":{\"message\":\"README\"}}"]},"expected":{"skipped":false,"runner":"scripted","ok":false,"toolCallCount":0,"observationCount":0,"errorCode":"tool_not_allowed"},"tags":["model-loop","offline","scripted","security"]}
{"case_id":"model-loop-scripted-malformed-action","category":"model_loop","input":{"kind":"react_scripted","content":"Return malformed action.","model_replies":["not json"]},"expected":{"skipped":false,"runner":"scripted","ok":false,"toolCallCount":0,"observationCount":0,"errorCode":"malformed_action"},"tags":["model-loop","offline","scripted","parser"]}
{"case_id":"model-loop-scripted-ambiguous-json-action","category":"model_loop","input":{"kind":"react_scripted","content":"Return two actions.","model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{}}\n{\"kind\":\"final\",\"text\":\"done\"}"]},"expected":{"skipped":false,"runner":"scripted","ok":false,"toolCallCount":0,"observationCount":0,"errorCode":"malformed_action"},"tags":["model-loop","offline","scripted","parser"]}
{"case_id":"model-loop-scripted-tool-budget-exceeded","category":"model_loop","input":{"kind":"react_scripted","content":"Use too many tools.","model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"one\"}}","{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"two\"}}"],"max_steps":3,"max_tool_calls":1},"expected":{"skipped":false,"runner":"scripted","ok":false,"toolCallCount":1,"observationCount":1,"errorCode":"tool_budget_exceeded"},"tags":["model-loop","offline","scripted","budget"]}
{"case_id":"model-loop-scripted-step-budget-exceeded","category":"model_loop","input":{"kind":"react_scripted","content":"Never final.","model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"one\"}}"],"max_steps":1,"max_tool_calls":3},"expected":{"skipped":false,"runner":"scripted","ok":false,"toolCallCount":1,"observationCount":1,"errorCode":"step_budget_exceeded"},"tags":["model-loop","offline","scripted","budget"]}
{"case_id":"model-loop-scripted-tool-error-observed","category":"model_loop","input":{"kind":"react_scripted","content":"Tool fails then model finalizes.","tool_response":{"ok":false,"values":{"text":"tool failed"}},"model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"fail\"}}","{\"kind\":\"final\",\"text\":\"Observed tool failure.\"}"],"max_steps":3,"max_tool_calls":2},"expected":{"skipped":false,"runner":"scripted","ok":true,"finalAnswer":"Observed tool failure.","toolCallCount":1,"observationCount":1,"errorCode":null},"tags":["model-loop","offline","scripted","tool-error"]}
{"case_id":"model-loop-scripted-permission-denied","category":"model_loop","input":{"kind":"react_scripted","content":"Read README with permission denied.","tool_id":"internal:file.inspect","tool_permissions":["read_project_files"],"allowed_permissions":[],"model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:file.inspect\",\"arguments\":{\"path\":\"README.md\"}}"]},"expected":{"skipped":false,"runner":"scripted","ok":false,"toolCallCount":0,"observationCount":0,"errorCode":"permission_not_allowed"},"tags":["model-loop","offline","scripted","permission"]}
{"case_id":"model-loop-scripted-permission-allowed","category":"model_loop","input":{"kind":"react_scripted","content":"Read README with permission allowed.","tool_id":"internal:file.inspect","tool_permissions":["read_project_files"],"allowed_permissions":["read_project_files"],"model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:file.inspect\",\"arguments\":{\"path\":\"README.md\"}}","{\"kind\":\"final\",\"text\":\"Permission path passed.\"}"],"max_steps":3,"max_tool_calls":2},"expected":{"skipped":false,"runner":"scripted","ok":true,"finalAnswer":"Permission path passed.","toolCallCount":1,"observationCount":1,"errorCode":null},"tags":["model-loop","offline","scripted","permission"]}
{"case_id":"model-loop-scripted-redacted-observation","category":"model_loop","input":{"kind":"react_scripted","content":"Observe redacted tool output.","tool_response":{"ok":true,"values":{"text":"safe summary","secret":"sk-test-secret"}},"model_replies":["{\"kind\":\"tool\",\"tool_id\":\"internal:test.echo\",\"arguments\":{\"message\":\"secret\"}}","{\"kind\":\"final\",\"text\":\"Secret was not exposed.\"}"]},"expected":{"skipped":false,"runner":"scripted","ok":true,"finalAnswer":"Secret was not exposed.","toolCallCount":1,"observationCount":1,"errorCode":null},"tags":["model-loop","offline","scripted","redaction"]}
```

- [x] **Step 2: Run model-loop eval only**

Run:

```powershell
Push-Location python
python -m agent_service.eval_harness --cases evals/model_loop_cases.jsonl --output ..\.codex-run\evals\model-loop
Pop-Location
```

Expected: `Agent eval summary: 12/12 passed, 0 failed.`

### Task 3.3: Add eval harness aggregate tests

- [x] **Step 1: Add aggregate test**

Add this test to `python/tests/test_eval_harness.py`:

```python
def test_repository_model_loop_eval_cases_pass() -> None:
    cases = load_eval_cases(Path("evals/model_loop_cases.jsonl"))

    summary = run_eval_cases(cases)

    assert summary.total == 12
    assert summary.failed == 0
    assert summary.categories["model_loop"].passed == 12
```

- [x] **Step 2: Run eval harness tests and full eval**

Run:

```powershell
Push-Location python
python -m pytest tests/test_eval_harness.py -q
Pop-Location
npm run agent:eval
```

Expected after this phase: model-loop eval grows from the initial single smoke case to 12 deterministic cases. The final full eval suite reaches `87/87` after the router and planner additions in Phase 4.

### Phase 3 Gate

Run:

```powershell
Push-Location python
python -m pytest tests/test_eval_harness.py tests/test_react_controller.py -q
Pop-Location
npm run agent:eval
```

Pass criteria:

- Eval harness and ReAct tests pass.
- `npm run agent:eval` reports the current full deterministic suite passing; after this completed implementation that is `87/87 passed`.

---

## Phase 4: Router and Planner Eval Expansion

**Outcome:** README-level Agent logic claims are backed by more Chinese router and planner regression cases.

**Files:**

- Modify: `python/evals/router_cases.jsonl`
- Modify: `python/evals/planner_cases.jsonl`
- Modify: `python/tests/test_eval_harness.py`

### Task 4.1: Add Chinese router cases

- [x] **Step 1: Append these router cases to `python/evals/router_cases.jsonl`**

```jsonl
{"case_id":"router-cn-weather-missing-city","category":"router","input":{"task_id":"router-cn-weather-missing-city","content":"明天会下雨吗？"},"expected":{"intent":"missing_input","missing":["weather_location"]},"tags":["router","cn","weather","missing-input"]}
{"case_id":"router-cn-document-task-missing-attachment","category":"router","input":{"task_id":"router-cn-document-task-missing-attachment","content":"帮我把这个文档整理成中文报告并导出 PDF。"},"expected":{"intent":"missing_input","missing":["attachment"]},"tags":["router","cn","document","missing-input"]}
{"case_id":"router-cn-complex-research-choice","category":"router","input":{"task_id":"router-cn-complex-research-choice","content":"请比较 2026 年主流本地 Agent 框架的架构差异，并给出选型建议。"},"expected":{"intent":"web_complex_choice"},"tags":["router","cn","research"]}
{"case_id":"router-cn-simple-web-version","category":"router","input":{"task_id":"router-cn-simple-web-version","content":"现在最新的 Tauri 2 版本是多少？"},"expected":{"intent":"web_simple_inquiry"},"tags":["router","cn","web"]}
{"case_id":"router-cn-local-chat","category":"router","input":{"task_id":"router-cn-local-chat","content":"解释一下什么是 checkpoint，不需要联网。"},"expected":{"intent":"local_inquiry"},"tags":["router","cn","local"]}
```

- [x] **Step 2: Run router eval**

Run:

```powershell
Push-Location python
python -m agent_service.eval_harness --cases evals/router_cases.jsonl --output ..\.codex-run\evals\router
Pop-Location
```

Expected: router eval total increases from 10 to 15 and all pass. If any expected intent differs, inspect `python/agent_service/intent.py` and either fix the classifier or update the case only if the README claim supports the actual route.

### Task 4.2: Add planner cases

- [x] **Step 1: Append these planner cases to `python/evals/planner_cases.jsonl`**

```jsonl
{"case_id":"planner-cn-document-pdf-export","category":"planner","input":{"task_id":"planner-cn-document-pdf-export","content":"把附件整理成一份中文报告，并导出 PDF。","attachments":[{"attachment_id":"att-cn-doc","name":"input.md","path":"inputs/input.md","size_bytes":100,"mime_type":"text/markdown"}]},"expected":{"strategy":"document_template","nodeIds":["document-input","document-parse","content-organize","report-generate","typst-export","file-export"]},"tags":["document","chinese","artifact"]}
{"case_id":"planner-cn-research-flow","category":"planner","input":{"task_id":"planner-cn-research-flow","content":"请联网搜索并比较 2026 年本地 Agent Runtime 架构的最新方案，输出带来源的研究报告。","inquiry_choice":"research_flow"},"expected":{"strategy":"research_flow","nodeIds":["research-intent-analysis","research-privacy-guard","research-query-plan","research-parallel-search","research-source-review","research-source-reading","research-report-synthesis","research-report-quality-check","research-markdown-output"]},"tags":["planner","cn","research"]}
{"case_id":"planner-tool-schema-document-chain","category":"planner","input":{"task_id":"planner-tool-schema-document-chain","content":"读取附件文档，整理摘要，并导出 markdown artifact。","attachments":[{"attachment_id":"att-chain","name":"input.md","path":"inputs/input.md","size_bytes":100,"mime_type":"text/markdown"}]},"expected":{"strategy":"document_template","nodeIds":["document-input","document-parse","content-organize","report-generate","typst-export","file-export"],"minNodeCount":6},"tags":["document","tool-dag","schema"]}
```

- [x] **Step 2: Run planner eval**

Run:

```powershell
Push-Location python
python -m agent_service.eval_harness --cases evals/planner_cases.jsonl --output ..\.codex-run\evals\planner
Pop-Location
```

Expected: planner eval increases from 13 to 16 and passes. If `minNodeCount` is not currently supported by the planner eval details, add support in `_run_planner_case()` by comparing `len(details["nodeIds"]) >= expected["minNodeCount"]`.

### Task 4.3: Add aggregate eval count test

- [x] **Step 1: Add this test to `python/tests/test_eval_harness.py`**

```python
def test_repository_eval_case_counts_match_v035_gate() -> None:
    cases = load_eval_cases_from_dir(Path("evals"))
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
```

- [x] **Step 2: Run full eval**

Run:

```powershell
Push-Location python
python -m pytest tests/test_eval_harness.py -q
Pop-Location
npm run agent:eval
```

Expected after this phase: `87/87 passed`.

### Phase 4 Gate

Run:

```powershell
npm run agent:eval
Push-Location python; python -m pytest tests/test_eval_harness.py -q; Pop-Location
```

Pass criteria:

- Full deterministic eval reports `87/87 passed`.
- Eval harness tests enforce the new case counts.

---

## Phase 5: Fake OpenAI-Compatible Model Server Tests

**Outcome:** The model client is tested against a real local HTTP server shape, not only injected transport functions.

**Files:**

- Create: `python/tests/test_model_client_http_integration.py`

### Task 5.1: Add local fake server integration tests

- [x] **Step 1: Create `python/tests/test_model_client_http_integration.py`**

Create the file with this content:

```python
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from agent_service.model_client import ChatMessage, LlamaCppModelClient, ModelClientConfig


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append(payload)

        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n')
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n')
            self.wfile.write(b"data: [DONE]\n\n")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {"choices": [{"message": {"content": "fake server reply"}}]},
                ensure_ascii=False,
            ).encode("utf-8")
        )

    def log_message(self, format: str, *args) -> None:
        return None


def _serve_fake_openai():
    _FakeOpenAIHandler.requests.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_llama_client_works_against_fake_openai_http_server() -> None:
    server, base_url = _serve_fake_openai()
    try:
        client = LlamaCppModelClient(
            ModelClientConfig(
                enabled=True,
                base_url=base_url,
                model="fake-model",
                timeout_seconds=3,
            )
        )

        result = client.chat([ChatMessage(role="user", content="hello")])

        assert result == "fake server reply"
        assert _FakeOpenAIHandler.requests[0]["model"] == "fake-model"
        assert _FakeOpenAIHandler.requests[0]["messages"] == [
            {"role": "user", "content": "hello"}
        ]
    finally:
        server.shutdown()
        server.server_close()


def test_llama_client_streams_against_fake_openai_http_server() -> None:
    server, base_url = _serve_fake_openai()
    try:
        client = LlamaCppModelClient(
            ModelClientConfig(
                enabled=True,
                base_url=base_url,
                model="fake-model",
                timeout_seconds=3,
            )
        )

        chunks = list(client.stream_chat([ChatMessage(role="user", content="hello")]))

        assert chunks == ["hel", "lo"]
        assert _FakeOpenAIHandler.requests[0]["stream"] is True
    finally:
        server.shutdown()
        server.server_close()
```

- [x] **Step 2: Run the new tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_client_http_integration.py -q
Pop-Location
```

Expected: 2 tests pass.

- [x] **Step 3: Run model client suite**

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_client.py tests/test_model_client_http_integration.py -q
Pop-Location
```

Expected: all model client tests pass.

### Phase 5 Gate

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_client.py tests/test_model_client_http_integration.py tests/test_app.py -q
Pop-Location
```

Pass criteria:

- Fake server chat and stream paths pass.
- Existing app/model client behavior is unchanged.

---

## Phase 6: Document Artifact Fixture Coverage

**Outcome:** Document and artifact claims are backed by real fixture tests, including corrupt input failure.

**Files:**

- Create: `python/tests/test_document_artifact_fixtures.py`
- Modify: `python/tests/test_execution.py`

### Task 6.1: Add real document fixture tests

- [x] **Step 1: Create `python/tests/test_document_artifact_fixtures.py`**

Create the file with this content:

```python
from __future__ import annotations

from pathlib import Path

from docx import Document
import pytest

from agent_service.execution import run_graph_events
from tests.test_execution import (
    FakeModelClient,
    FakeToolExecutor,
    build_document_flow_request,
    build_document_flow_request_with_typst,
    TypstFlowToolExecutor,
)
from python.tools.document_tool import run as document_tool_run
from python.tools.markitdown_tool import run as markitdown_tool_run


def test_markdown_document_fixture_exports_markdown_artifact(tmp_path: Path) -> None:
    source = tmp_path / "sample-note.md"
    source.write_text("# 测试标题\n\n这是一个可回归的 Markdown 样本文档。", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=FakeToolExecutor(),
        )
    )

    artifact_event = next(
        event
        for event in events
        if event.type == "artifact.created"
        and event.payload["sourceNodeId"] == "file-export"
    )
    artifact_path = Path(artifact_event.payload["path"])
    assert artifact_path.is_file()
    assert artifact_path.suffix == ".md"
    content = artifact_path.read_text(encoding="utf-8")
    assert "outline result" in content
    assert "report result" in content
    assert events[-1].type == "task.completed"


def test_typst_document_fixture_exports_pdf_artifact(tmp_path: Path) -> None:
    source = tmp_path / "sample-note.md"
    source.write_text("# Export\n\nPDF body.", encoding="utf-8")
    request = build_document_flow_request_with_typst(tmp_path, source)

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=TypstFlowToolExecutor(),
        )
    )

    artifact_paths = [
        Path(event.payload["path"])
        for event in events
        if event.type == "artifact.created"
    ]
    assert any(path.suffix == ".pdf" for path in artifact_paths)
    assert any(path.suffix == ".typ" for path in artifact_paths)
    assert events[-1].type == "task.completed"


def test_document_read_write_docx_fixture_extracts_text(tmp_path: Path) -> None:
    source = tmp_path / "sample-report.docx"
    doc = Document()
    doc.add_heading("Alita 回归样本", level=1)
    doc.add_paragraph("这是用于文档工具回归测试的正文。")
    doc.save(source)

    result = document_tool_run(
        {
            "operation": "read",
            "path": str(source),
        }
    )

    assert result["ok"] is True
    assert "Alita 回归样本" in result["values"]["text"]
    assert "文档工具回归测试" in result["values"]["text"]


def test_corrupt_docx_fixture_returns_parse_error(tmp_path: Path) -> None:
    source = tmp_path / "sample-corrupt.docx"
    source.write_bytes(b"not a valid docx")

    with pytest.raises(Exception):
        markitdown_tool_run(
            {
                "input_path": str(source),
                "output_path": str(tmp_path / "out.md"),
            }
        )
```

- [x] **Step 2: Run fixture tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_document_artifact_fixtures.py -q
Pop-Location
```

Expected: all fixture tests pass. If imports from `python.tools.*` fail, change imports to match existing tool test imports in `python/tests/test_document_tool.py` and `python/tests/test_markitdown_tool.py`.

### Task 6.2: Strengthen research artifact evidence test

- [x] **Step 1: Add test to `python/tests/test_execution.py`**

Add this test near existing research tests:

```python
def test_research_report_artifact_has_claim_evidence_citations(tmp_path: Path) -> None:
    question = "Research Alita checkpoint resume evidence."
    request = build_research_flow_request(tmp_path, question)

    events = list(run_graph_events(request))

    artifact_event = next(event for event in events if event.type == "artifact.created")
    report = Path(artifact_event.payload["path"]).read_text(encoding="utf-8")
    assert "[S1]" in report
    assert "## Sources" in report or "## 来源" in report
    completed = next(event for event in events if event.type == "research.completed")
    assert completed.payload["reportArtifactPath"] == artifact_event.payload["path"]
```

- [x] **Step 2: Run research and fixture tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_document_artifact_fixtures.py tests/test_execution.py::test_research_report_artifact_has_claim_evidence_citations -q
Pop-Location
```

Expected: all pass.

### Phase 6 Gate

Run:

```powershell
Push-Location python
python -m pytest tests/test_document_artifact_fixtures.py tests/test_execution.py tests/test_research_evidence.py -q
Pop-Location
```

Pass criteria:

- Real document fixture tests pass.
- Existing execution and research evidence tests still pass.

---

## Phase 7: Checkpoint Resume and Runtime Evidence Tests

**Outcome:** checkpoint/resume claims are covered by an execution-level regression, and runtime evidence is easy to inspect.

**Files:**

- Modify: `python/tests/test_execution.py`
- Modify: `docs/test-traceability/alita-v035-feature-test-map.md`

### Task 7.1: Add checkpoint resume regression

- [x] **Step 1: Add test to `python/tests/test_execution.py`**

Add this test near existing resume/checkpoint tests:

```python
def test_resume_from_specific_checkpoint_does_not_repeat_completed_outputs(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Resume\n\nBody", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-resume-specific")

    first_events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=FakeToolExecutor(),
        )
    )
    checkpoint_events = [
        event for event in first_events if event.type == "runtime.checkpoint_recorded"
    ]
    assert checkpoint_events
    checkpoint_id = checkpoint_events[-1].payload["checkpoint"]["checkpointId"]

    resumed_request = request.model_copy(
        update={
            "resume_from_checkpoint_id": checkpoint_id,
        },
        deep=True,
    )
    resumed_events = list(
        run_graph_events(
            resumed_request,
            model_client=FakeModelClient(),
            tool_executor=FakeToolExecutor(),
        )
    )

    resumed_started = next(
        event for event in resumed_events if event.type == "runtime.resume_started"
    )
    assert resumed_started.payload["checkpointId"] == checkpoint_id
    assert resumed_events[-1].type == "task.completed"
```

- [x] **Step 2: Run targeted test**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py::test_resume_from_specific_checkpoint_does_not_repeat_completed_outputs -q
Pop-Location
```

Expected: pass. If the field name differs, inspect `RunGraphRequest` in `python/agent_service/schemas.py` and use the existing resume field name from current resume tests.

### Task 7.2: Update traceability map with new test references

- [x] **Step 1: Modify `docs/test-traceability/alita-v035-feature-test-map.md`**

In the checkpoint row, add the explicit test name:

```markdown
`python/tests/test_execution.py::test_resume_from_specific_checkpoint_does_not_repeat_completed_outputs`
```

- [x] **Step 2: Run runtime tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_run_journal.py tests/test_runtime_store.py tests/test_execution.py::test_resume_from_specific_checkpoint_does_not_repeat_completed_outputs -q
Pop-Location
```

Expected: all pass.

### Phase 7 Gate

Run:

```powershell
Push-Location python
python -m pytest tests/test_run_journal.py tests/test_runtime_store.py tests/test_trace_store.py tests/test_execution.py -q
Pop-Location
```

Pass criteria:

- Runtime persistence tests pass.
- Full execution test module passes.

---

## Phase 8: Artifact Preview Regression and Build Gate

**Outcome:** artifact preview coverage includes audio/unsupported states and production build remains part of release verification.

**Files:**

- Modify: `src/features/artifacts/ArtifactPreviewPanel.test.tsx`
- Modify: `docs/mvp-verification.md`

### Task 8.1: Add artifact preview tests

- [x] **Step 1: Inspect current audio handling**

Run:

```powershell
rg -n "audio|unsupported|previewKind" src\features\artifacts
```

Expected: identify whether audio maps to `video`, `unsupported`, or a dedicated preview kind.

- [x] **Step 2: Add exact tests according to current types**

If `previewKind` supports `audio`, add:

```tsx
  it("renders an audio preview surface when the selected artifact is audio", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={{
          ...artifact,
          fileName: "voice.wav",
          path: "D:\\Project\\artifacts\\voice.wav",
        }}
        error={null}
        fileUrl="asset://localhost/voice.wav"
        loading={false}
        preview={null}
        previewKind="audio"
        selectedNode={{
          ...outputNode,
          artifactRefs: ["D:\\Project\\artifacts\\voice.wav"],
        }}
      />,
    );

    expect(markup).toContain("voice.wav");
  });
```

If audio is represented by `video`, add:

```tsx
  it("routes audio files through the media preview surface", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={{
          ...artifact,
          fileName: "voice.wav",
          path: "D:\\Project\\artifacts\\voice.wav",
        }}
        error={null}
        fileUrl="asset://localhost/voice.wav"
        loading={false}
        preview={null}
        previewKind="video"
        selectedNode={{
          ...outputNode,
          artifactRefs: ["D:\\Project\\artifacts\\voice.wav"],
        }}
      />,
    );

    expect(markup).toContain("artifactPreviewVideo");
    expect(markup).toContain("voice.wav");
  });
```

Also add unsupported state test:

```tsx
  it("renders unsupported artifact state with open and reveal actions", () => {
    const markup = renderToStaticMarkup(
      <ArtifactPreviewPanel
        artifact={{
          ...artifact,
          fileName: "archive.zip",
          path: "D:\\Project\\artifacts\\archive.zip",
        }}
        error={null}
        fileUrl={null}
        loading={false}
        preview={null}
        previewKind="unsupported"
        selectedNode={{
          ...outputNode,
          artifactRefs: ["D:\\Project\\artifacts\\archive.zip"],
        }}
        onOpenArtifact={() => undefined}
        onRevealArtifact={() => undefined}
      />,
    );

    expect(markup).toContain("archive.zip");
    expect(markup).toContain("打开");
    expect(markup).toContain("定位");
  });
```

- [x] **Step 3: Run artifact tests and build**

Run:

```powershell
npm run frontend:test -- src/features/artifacts/ArtifactPreviewPanel.test.tsx
npm run frontend:build
```

Expected: artifact tests pass and production build succeeds.

### Task 8.2: Update MVP verification docs

- [x] **Step 1: Add frontend production build to automatic verification section**

In `docs/mvp-verification.md`, add this bullet under the script command list:

```markdown
- 前端生产构建：`npm run frontend:build`，用于验证懒加载 artifact 预览 chunk 和 PDF worker 路径。
```

- [x] **Step 2: Run documentation check**

Run:

```powershell
rg -n "frontend:build|PDF worker" docs\mvp-verification.md
git diff --check
```

Expected: both terms appear; whitespace check passes.

### Phase 8 Gate

Run:

```powershell
npm run frontend:test -- src/features/artifacts/ArtifactPreviewPanel.test.tsx
npm run frontend:build
git diff --check
```

Pass criteria:

- Artifact preview targeted tests pass.
- Production build passes.

---

## Phase 9: Release Smoke Checklist and Evidence Discipline

**Outcome:** live dependencies and desktop UI are verified through a clear release checklist without making PR CI depend on network or real local models.

**Files:**

- Create: `docs/release-smoke/alita-v035-release-smoke.md`
- Modify: `docs/mvp-verification.md`
- Modify: `docs/test-traceability/alita-v035-feature-test-map.md`

### Task 9.1: Create release smoke checklist

- [x] **Step 1: Create `docs/release-smoke/alita-v035-release-smoke.md`**

Create the file with this content:

```markdown
# Alita v0.35 Release Smoke Checklist

Date:
Commit:
Tester:
Windows version:

Evidence folder: `docs/test-results/v035-release-smoke-YYYYMMDD-HHMMSS`

## Desktop Launch Smoke

1. Run `npm run check:desktop-prereqs`.
2. Run `npm run desktop:dev`.
3. Expected: a Windows desktop window titled `Alita` opens.
4. Save screenshot as `desktop-launch.png`.

## Project File Smoke

1. Create `D:\Temp\alita-smoke\v035.alita`.
2. Send `你好，记录一条 smoke 消息。`.
3. Save the project.
4. Close and reopen the application.
5. Open `D:\Temp\alita-smoke\v035.alita`.
6. Expected: chat message, project path, saved state, and graph area restore.
7. Save the `.alita` file copy as `project-after-reopen.alita`.

## Local Model Smoke

1. Set `ALITA_LLAMA_MODEL_PATH` to a local GGUF model.
2. Run `npm run desktop:dev`.
3. Send `用一句话回复：本地模型 smoke 通过。`.
4. Expected: model response is streamed or returned without sidecar error.
5. Save sidecar log excerpt as `local-model-sidecar.log`.

## Document Artifact Smoke

1. Attach a small `.md` or `.docx` file.
2. Send `帮我整理成中文报告并导出 PDF。`.
3. Run the generated graph.
4. Expected: Markdown and PDF/Typst artifacts are created or a clear Typst dependency error appears.
5. Save artifact preview screenshot as `document-artifact-preview.png`.

## Research Artifact Smoke

1. Ask `请调研 Alita v0.35 当前 Agent Runtime 测试覆盖情况，并生成研究报告。`.
2. Choose `Research flow`.
3. Run graph.
4. Expected: Markdown report artifact contains citations such as `[S1]`.
5. Save report as `research-report.md`.

## Live Network Smoke

1. Without `ALITA_BRAVE_SEARCH_API_KEY`, ask a simple current web question.
2. Expected: DuckDuckGo fallback is used or a safe network failure is shown.
3. With `ALITA_BRAVE_SEARCH_API_KEY`, ask the same question.
4. Expected: Brave provider is used.
5. Ask `今天上海天气怎么样？`.
6. Expected: weather path is used instead of generic search.

## API Key Redaction Smoke

1. Configure an API provider with a test key.
2. Save preferences.
3. Inspect `.alita`, preferences JSON, run history, and visible UI.
4. Expected: the raw key is not present.
5. Save grep output summary as `api-key-redaction.txt`.

## ASR Smoke

1. Configure Qwen3-ASR model directory.
2. Record a 3-second Chinese sentence.
3. Expected: transcribed text appears in the chat draft.
4. Save screenshot as `asr-transcription.png`.

## Artifact Preview Smoke

1. Open Markdown/text artifact preview.
2. Open PDF artifact preview.
3. Open image artifact preview.
4. Open audio/video artifact preview if sample exists.
5. Expected: each preview is non-empty or gives a precise unsupported-format message.

## Runtime Resume Smoke

1. Run a document or research graph until checkpoints are recorded.
2. Trigger a recoverable failure by disabling one tool.
3. Re-enable the tool.
4. Resume from latest checkpoint.
5. Expected: completed nodes are not repeated, and final artifact is present.

## MCP Stdio Smoke

1. Configure the test echo MCP stdio server.
2. Refresh tools.
3. Run a task using the echo tool.
4. Expected: tool discovery and call complete with authority records.
```

- [x] **Step 2: Link release checklist from `docs/mvp-verification.md`**

Add this line near the desktop window validation section:

```markdown
候选版本发布前还必须执行 `docs/release-smoke/alita-v035-release-smoke.md` 中的 live smoke checklist，并保存证据目录。
```

### Task 9.2: Verify smoke docs

- [x] **Step 1: Run doc link search**

Run:

```powershell
rg -n "alita-v035-release-smoke|release smoke|Evidence folder" docs
git diff --check
```

Expected: release smoke doc and MVP link both appear; whitespace check passes.

### Phase 9 Gate

Run:

```powershell
rg -n "Desktop Launch Smoke|Project File Smoke|Runtime Resume Smoke|MCP Stdio Smoke" docs\release-smoke\alita-v035-release-smoke.md
git diff --check
```

Pass criteria:

- All smoke sections exist.
- No whitespace errors.

---

## Phase 10: Full Verification and README Final Sync

**Outcome:** all implemented testing changes pass together, README reflects the new eval total, and the worktree contains only intentional changes.

**Files:**

- Modify: `README.md`
- Modify: `docs/alita-v0.35-test-plan.md`
- Modify: `docs/test-traceability/alita-v035-feature-test-map.md`

### Task 10.1: Update README with new eval total

- [x] **Step 1: Run baseline script**

Run:

```powershell
.\scripts\collect-test-baseline.ps1
```

Expected after Phases 3 and 4:

```json
{
  "pythonTestFiles": 71,
  "rustTauriTestFiles": 17,
  "frontendTestFiles": 32,
  "evalTotal": 87,
  "evalCounts": {
    "model_loop": 12,
    "planner": 16,
    "research": 10,
    "router": 15,
    "security": 24,
    "tool": 10
  }
}
```

The Python test file count is expected to increase from 69 to 71 because this plan creates `test_model_client_http_integration.py` and `test_document_artifact_fixtures.py`.

- [x] **Step 2: Update README verification block**

Update only the lines whose counts changed:

```text
npm run agent:eval
87/87 passed
```

If the Python total changed after running the full suite, update the README Python passed count to the exact value from the final pytest output.

### Task 10.2: Run full gate

- [x] **Step 1: Run full verification**

Run:

```powershell
git diff --check
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
Push-Location python
python -m pytest -q
Pop-Location
npm run agent:eval
Push-Location src-tauri
cargo fmt --check
Pop-Location
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected:

- `git diff --check` exits 0.
- Frontend typecheck exits 0.
- Frontend tests pass.
- Frontend build exits 0.
- Python tests pass.
- Agent eval reports `87/87 passed`.
- Rust format exits 0.
- Rust/Tauri tests pass.

- [x] **Step 2: Inspect final diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected changed files are limited to:

```text
.github/workflows/ci.yml
README.md
docs/alita-v0.35-test-plan.md
docs/mvp-verification.md
docs/release-smoke/alita-v035-release-smoke.md
docs/superpowers/plans/2026-05-31-alita-v035-test-implementation-plan.md
docs/test-traceability/alita-v035-feature-test-map.md
python/agent_service/eval_harness.py
python/evals/model_loop_cases.jsonl
python/evals/planner_cases.jsonl
python/evals/router_cases.jsonl
python/tests/test_document_artifact_fixtures.py
python/tests/test_eval_harness.py
python/tests/test_execution.py
python/tests/test_model_client_http_integration.py
scripts/collect-test-baseline.ps1
src/features/artifacts/ArtifactPreviewPanel.test.tsx
src-tauri/Cargo.lock
```

If a file outside this list changed, inspect the diff and keep it only when it is required by a failing test or count update.

### Final Gate

Run:

```powershell
git diff --check
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
Push-Location python; python -m pytest -q; Pop-Location
npm run agent:eval
Push-Location src-tauri; cargo fmt --check; Pop-Location
cargo test --manifest-path src-tauri/Cargo.toml
.\scripts\verify-mvp.ps1
```

Pass criteria:

- All commands exit 0.
- README count block matches `scripts/collect-test-baseline.ps1`.
- README verification block matches the latest command outputs.
- Traceability map links every README major capability to an automated test, eval case, or release smoke section.
- `git status --short` contains only intentional test infrastructure, eval, documentation, and lockfile changes.

---

## Execution Notes

Recommended execution shape:

1. Ship Phase 1 and Phase 2 as the first PR because they close documentation and CI risk.
2. Ship Phase 3 and Phase 4 as the second PR because they change eval totals and README verification counts.
3. Ship Phase 5 through Phase 8 as the third PR because they add integration tests.
4. Ship Phase 9 and Phase 10 as the release-hardening PR.

Each phase has its own gate and can be reviewed independently. Do not update README final counts until the phase that changes those counts has passed locally.

