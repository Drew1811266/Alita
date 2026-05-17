# Typst Tool Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Typst CLI-backed tool node that exports generated reports as `.typ` and `.pdf` artifacts.

**Architecture:** Register a new `document.typst_compile` manifest, route it through the Python sidecar `ToolExecutor`, and add a `typst-export` fixed tool node to the default document graph. The final `file-export` node passes through Typst output artifacts when present.

**Tech Stack:** Python sidecar, Typst CLI subprocess, existing tool manifest registry, React node popover tests, pytest and Vitest.

---

### Task 1: Typst CLI Tool

**Files:**
- Create: `python/tools/typst_tool.py`
- Test: `python/tests/test_typst_tool.py`

- [ ] Write a failing pytest that invokes `compile_report_pdf` with a fake Typst executable and expects `.typ` and `.pdf` artifacts.
- [ ] Run `python -m pytest python/tests/test_typst_tool.py -q` and confirm the import or behavior fails.
- [ ] Implement `compile_report_pdf` with path checks, safe Typst escaping, timeout handling, and PDF existence validation.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Tool Manifest And Executor Routing

**Files:**
- Create: `tool-packages/typst/manifest.json`
- Modify: `python/agent_service/tool_execution.py`
- Test: `python/tests/test_tool_execution.py`, `python/tests/test_tool_registry.py`

- [ ] Add failing tests that the real registry loads `document.typst_compile` and that `ToolExecutor` routes `compile_report_pdf`.
- [ ] Run focused pytest tests and confirm the new expectations fail.
- [ ] Add the manifest and executor branch.
- [ ] Re-run focused pytest tests and confirm they pass.

### Task 3: Default Document Workflow

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_graph.py`, `python/tests/test_execution.py`

- [ ] Add failing tests that the generated graph includes `typst-export` and that flow execution passes Typst artifacts through `file-export`.
- [ ] Run focused pytest tests and confirm the new expectations fail.
- [ ] Add the graph node, execution branch, and file-export pass-through behavior.
- [ ] Re-run focused pytest tests and confirm they pass.

### Task 4: Frontend Node Metadata

**Files:**
- Modify: `src/features/canvas/NodePopover.tsx`
- Test: `src/features/canvas/NodePopover.test.tsx`

- [ ] Add a failing Vitest expectation for the Typst tool capability label.
- [ ] Run the focused frontend test and confirm the new expectation fails.
- [ ] Add the Typst tool label.
- [ ] Re-run the focused frontend test and confirm it passes.

### Task 5: Full Verification

**Files:** No production changes expected.

- [ ] Run `python -m pytest -q`.
- [ ] Run `npm run frontend:test`.
- [ ] Run `npm run frontend:lint`.
- [ ] Run `npm run frontend:build`.
- [ ] Run `cargo test` from `src-tauri`.
- [ ] Check `git status --short` and summarize changed files.
