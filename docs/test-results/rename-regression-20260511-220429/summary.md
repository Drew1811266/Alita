# Alita Rename Regression Summary

## Result
- Overall: Pass for automated, build, runtime, service, model, project-file, and document-flow coverage.
- Date: 2026-05-11
- Evidence folder: `D:\Software Project\Alita\docs\test-results\rename-regression-20260511-220429`

## Commands
- `powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1`: pass.
- `powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 -IncludeGenerated`: pass.
- `npm run frontend:test`: 13 files, 49 tests passed.
- `npm run frontend:lint`: pass.
- `python -m pytest`: 69 tests passed.
- `cargo test`: pass.
- `npm run frontend:build`: pass; `dist/index.html` title is `Alita`.
- `npm run desktop:build`: pass; generated `Alita_0.1.0_x64-setup.exe`.

## Runtime
- `alita.exe`: launched from `D:\Software Project\Alita\src-tauri\target\release\alita.exe`.
- Window title: `Alita`.
- `alita-agent-sidecar.exe`: launched and `http://127.0.0.1:8765/health` returned HTTP 200.
- `llama-server.exe`: launched with model `D:\Software Project\Alita\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`.
- `http://127.0.0.1:8766/health`: returned HTTP 200.
- Normal window close via `CloseMainWindow()` left no Alita-owned child processes.

## Configuration
- Alita preferences path: `%APPDATA%\com.alita.ai-workbench\preferences.json`.
- `defaultModelId`: present.
- Model source: `recovered`.
- Model path: `D:\Software Project\Alita\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`.
- Model storage dir: `%LOCALAPPDATA%\com.alita.ai-workbench\models`.

## Workflows
- Project file coverage: Rust `project_tests` passed, including `.alita` save/load, run history persistence, warnings for missing attachments, and rejection of non-`.alita` extension.
- Frontend project coverage: `projectApi` and `App` targeted tests passed.
- Agent model coverage: direct Python Agent call used llama.cpp and did not return the disabled-model message.
- Sidecar auth coverage: non-Alita sidecar token header rejection test passed.
- Document graph coverage: attachment request generated a node graph with document input, MarkItDown parse, model nodes, and export node.
- Document execution coverage: graph run completed, created converted Markdown and final report artifacts.
- Tool disabled coverage: disabling `document.markitdown_convert` produced `tool_disabled`.

## Notes
- Direct protected sidecar `/agent/message` positive call was not made because the packaged Tauri app keeps the sidecar auth token in process memory. Equivalent positive coverage was performed through the Python Agent graph plus live llama.cpp runtime.
- Manual desktop clicking was not automated in this environment. UI behavior is covered by frontend component tests, project API tests, runtime process checks, and API-level workflow execution.
- Force-killing `alita.exe` leaves child processes because Tauri exit cleanup cannot run under a forced kill. Normal window close was tested separately and cleaned up child processes correctly.

## Failures Or Deviations
- No rename-related failures found.
- One initial document-flow probe failed because PowerShell pipe encoding converted Chinese input to question marks. The test was rerun with Python Unicode escapes and passed.
