# Agent Runtime Phase K Memory And Context Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe project-scoped memory records and context budget selection without leaking secrets or raw local paths into model prompts.

**Architecture:** Add `memory_store.py` as a sidecar-owned JSONL memory store and `context_policy.py` as a deterministic selector for chat, planning, execution, and research contexts. Extend `context_manager.py` to accept compact memory summaries without changing public endpoint schemas. Keep storage inspectable and project-scoped; do not add embeddings or vector search in this phase.

**Tech Stack:** Python 3.12, Pydantic v2, JSONL files, existing `ContextBundle`, existing privacy redaction helpers, pytest.

---

## Files

### Create

- `python/agent_service/memory_store.py`
- `python/agent_service/context_policy.py`
- `python/tests/test_memory_store.py`

### Modify

- `python/agent_service/context_manager.py`
- `python/tests/test_context_manager.py`
- `src-tauri/src/project.rs`
- `src/shared/types.ts`
- `src-tauri/tests/project_tests.rs`

---

## Design Contract

Create `python/agent_service/memory_store.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    memory_id: str
    scope: Literal["project", "global"] = "project"
    kind: Literal["preference", "graph_summary", "artifact_summary", "tool_outcome"]
    summary: str
    source_ref: str
    created_at: str
    tags: list[str] = Field(default_factory=list)
```

Required API:

- `memory_dir_for_project(project_path: str) -> Path`
- `MemoryStore(project_path: str)`
- `MemoryStore.append(record: MemoryRecord) -> None`
- `MemoryStore.list(scope: str = "project", tags: list[str] | None = None) -> list[MemoryRecord]`
- `sanitize_memory_summary(text: str, max_chars: int = 1200) -> str`

Storage rule:

- For `D:\Work\demo.alita`, memory lives in sibling directory `D:\Work\demo.alita-memory\memory.jsonl`.
- Do not mutate `.alita` project schema unless later frontend inspection requires it.

Create `python/agent_service/context_policy.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContextBudget(BaseModel):
    mode: Literal["chat", "planning", "execution", "research"]
    max_memory_records: int
    max_chars: int
    allowed_kinds: list[str] = Field(default_factory=list)
```

Required API:

- `budget_for_mode(mode: str) -> ContextBudget`
- `select_memory_for_context(records: list[MemoryRecord], budget: ContextBudget) -> list[MemoryRecord]`

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/context_manager.py`
- Read: `python/tests/test_context_manager.py`
- Read: `src-tauri/src/project.rs`

- [ ] **Step 1: Run current context/project baseline**

Run:

```powershell
python -m pytest -q python\tests\test_context_manager.py
cargo test --manifest-path src-tauri/Cargo.toml project
```

Expected:

```text
... passed
```

---

## Task 1: Memory Store Persistence And Redaction

**Files:**
- Create: `python/agent_service/memory_store.py`
- Create: `python/tests/test_memory_store.py`

- [ ] **Step 1: Write failing memory store tests**

Create `python/tests/test_memory_store.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_service.memory_store import (
    MemoryRecord,
    MemoryStore,
    memory_dir_for_project,
    sanitize_memory_summary,
)


def test_memory_dir_is_project_sibling(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"

    assert memory_dir_for_project(str(project_path)) == tmp_path / "demo.alita-memory"


def test_memory_store_appends_and_lists_records(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "demo.alita"))
    record = MemoryRecord(
        memory_id="m1",
        kind="graph_summary",
        summary="Generated a report.",
        source_ref="run-1",
        created_at="2026-05-29T00:00:00Z",
        tags=["report"],
    )

    store.append(record)

    assert store.list() == [record]
    assert store.list(tags=["report"]) == [record]
    assert store.list(tags=["missing"]) == []


def test_sanitize_memory_summary_removes_secrets_paths_and_large_content() -> None:
    text = "api_key=sk-secret D:\\Project\\secret.docx " + ("x" * 2000)

    sanitized = sanitize_memory_summary(text, max_chars=120)

    assert "sk-secret" not in sanitized
    assert "D:\\Project" not in sanitized
    assert "secret.docx" not in sanitized
    assert len(sanitized) <= 120
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_memory_store.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.memory_store'
```

- [ ] **Step 3: Implement memory store**

Implement `memory_store.py` with JSONL append/list. Use existing privacy redaction helpers when available; otherwise implement local redaction for API keys and absolute paths. Ensure writes create the memory directory.

- [ ] **Step 4: Run memory tests**

Run:

```powershell
python -m pytest -q python\tests\test_memory_store.py
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/memory_store.py python/tests/test_memory_store.py
git commit -m "feat: add project memory store"
```

---

## Task 2: Context Policy Selection

**Files:**
- Create: `python/agent_service/context_policy.py`
- Modify: `python/tests/test_memory_store.py`

- [ ] **Step 1: Add context selection tests**

Append to `python/tests/test_memory_store.py`:

```python
from agent_service.context_policy import budget_for_mode, select_memory_for_context


def test_context_policy_selects_recent_allowed_memory_records() -> None:
    records = [
        MemoryRecord(memory_id="old", kind="tool_outcome", summary="old", source_ref="r1", created_at="2026-05-28T00:00:00Z"),
        MemoryRecord(memory_id="new", kind="graph_summary", summary="new", source_ref="r2", created_at="2026-05-29T00:00:00Z"),
        MemoryRecord(memory_id="pref", kind="preference", summary="pref", source_ref="user", created_at="2026-05-27T00:00:00Z"),
    ]
    budget = budget_for_mode("planning")

    selected = select_memory_for_context(records, budget)

    assert [record.memory_id for record in selected] == ["new", "pref"]
    assert budget.max_chars > 0
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_memory_store.py::test_context_policy_selects_recent_allowed_memory_records
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.context_policy'
```

- [ ] **Step 3: Implement context policy**

Create `python/agent_service/context_policy.py`:

- `budget_for_mode("chat")`: 3 records, 1600 chars, preference + graph_summary.
- `budget_for_mode("planning")`: 5 records, 2400 chars, preference + graph_summary + tool_outcome.
- `budget_for_mode("execution")`: 3 records, 1200 chars, tool_outcome + graph_summary.
- `budget_for_mode("research")`: 4 records, 2000 chars, graph_summary + artifact_summary.
- Sort selected records by `created_at` descending, then preserve max count.
- Always include preferences before older non-preference records when within allowed kinds.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest -q python\tests\test_memory_store.py
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/context_policy.py python/tests/test_memory_store.py
git commit -m "feat: add context memory policy"
```

---

## Task 3: ContextBundle Memory Summaries

**Files:**
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/tests/test_context_manager.py`

- [ ] **Step 1: Add ContextBundle memory test**

Append to `python/tests/test_context_manager.py`:

```python
from agent_service.memory_store import MemoryRecord


def test_context_bundle_includes_selected_memory_summaries(tmp_path) -> None:
    message = UserMessage(task_id="task-memory", content="Continue the report.")
    goal_spec = parse_goal_spec(message)
    registry = ToolRegistry([])
    memory_records = [
        MemoryRecord(
            memory_id="m1",
            kind="graph_summary",
            summary="Previous run summarized the PDF.",
            source_ref="run-1",
            created_at="2026-05-29T00:00:00Z",
        )
    ]

    bundle = build_context_bundle(
        message,
        goal_spec,
        str(tmp_path / "project.alita"),
        registry,
        memory_records=memory_records,
    )

    assert bundle.memory_summaries == ["Previous run summarized the PDF."]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_context_manager.py::test_context_bundle_includes_selected_memory_summaries
```

Expected:

```text
TypeError: build_context_bundle() got an unexpected keyword argument 'memory_records'
```

- [ ] **Step 3: Extend ContextBundle**

Modify `ContextBundle`:

```python
    memory_summaries: list[str] = Field(default_factory=list)
```

Modify the current `build_context_bundle()` signature to:

```python
def build_context_bundle(
    message: UserMessage,
    goal_spec: GoalSpec,
    project_path: str,
    tool_registry: ToolRegistry,
    tool_gateway: UnifiedToolGateway | None = None,
    disabled_tool_ids: list[str] | None = None,
    memory_records: list[MemoryRecord] | None = None,
    context_mode: str = "planning",
) -> ContextBundle:
```

Use `budget_for_mode(context_mode)` and `select_memory_for_context()` to fill `memory_summaries`.

- [ ] **Step 4: Run context tests**

Run:

```powershell
python -m pytest -q python\tests\test_context_manager.py python\tests\test_planner_chain.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/context_manager.py python/tests/test_context_manager.py
git commit -m "feat: add memory summaries to context bundle"
```

---

## Task 4: Project Schema Compatibility Check

**Files:**
- Modify: `src-tauri/tests/project_tests.rs`
- Read: `src-tauri/src/project.rs`
- Read: `src/shared/types.ts`

- [ ] **Step 1: Add no-project-schema-change regression**

Append to `src-tauri/tests/project_tests.rs`:

```rust
#[test]
fn project_schema_does_not_store_memory_records() {
    let project = alita_lib::project::new_project(
        "Memory test",
        "D:\\Projects\\memory-test.alita",
    );
    let json = serde_json::to_value(&project).expect("project serializes");

    assert!(json.get("memory").is_none());
    assert!(json.get("memories").is_none());
    assert_eq!(json.get("schemaVersion").and_then(|value| value.as_u64()), Some(1));
}
```

This uses the existing `new_project()` constructor from `src-tauri/src/project.rs`.

- [ ] **Step 2: Run project tests**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml project
```

Expected:

```text
test result: ok
```

- [ ] **Step 3: Commit**

Run:

```powershell
git add src-tauri/tests/project_tests.rs
git commit -m "test: keep memory out of project schema"
```

---

## Task 5: Final Regression And Review

**Files:**
- Read: `python/agent_service/memory_store.py`
- Read: `python/agent_service/context_policy.py`
- Read: `python/agent_service/context_manager.py`

- [ ] **Step 1: Run Phase K focused tests**

Run:

```powershell
python -m pytest -q python\tests\test_memory_store.py python\tests\test_context_manager.py
cargo test --manifest-path src-tauri/Cargo.toml project
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run planner/runtime regression**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_execution.py python\tests\test_agent_routing_integration.py
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
Review Phase K Memory and Context implementation. Prioritize memory scoping, JSONL durability, secret/path redaction, ContextBundle compatibility, project schema stability, context budget determinism, and whether implementation avoids vector search, remote telemetry, frontend UI, or broad summarization scope.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing Phase K.

---

## Acceptance Criteria

Phase K is complete when all statements are true:

- `memory_store.py` persists project-scoped JSONL records.
- Memory summaries are redacted and bounded.
- `context_policy.py` selects deterministic records per context mode.
- `ContextBundle` can include memory summaries without breaking existing callers.
- Project `.alita` schema does not store memory records.
- No embeddings, vector DB, remote telemetry, or frontend UI is introduced.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase L

Phase L can refactor frontend state without changing backend memory APIs. It should keep backend event reduction canonical and avoid adding UI for memory inspection until runtime memory behavior is stable.
