# Alita v0.35 Feature-Test Traceability Map

Generated: 2026-05-31
Scope: README feature claims, current automated test references, eval coverage, and manual release smoke coverage.

| Feature Claim | Current Automated Tests | Planned Automated Tests | Eval Cases | Release Smoke |
| --- | --- | --- | --- | --- |
| `.alita` project create/open/save and run history persistence | `src-tauri/tests/project_tests.rs`, `src/features/project/*.test.tsx` | none | none | [`Project File Smoke`](../release-smoke/alita-v035-release-smoke.md#project-file-smoke) |
| Tauri desktop workbench launch | `src-tauri/tests/sidecar_tests.rs`, `src-tauri/tests/tauri_config_tests.rs` | none | none | [`Desktop Launch Smoke`](../release-smoke/alita-v035-release-smoke.md#desktop-launch-smoke) |
| Local llama.cpp model client | `python/tests/test_model_client.py`, `python/tests/test_model_client_http_integration.py`, `src-tauri/tests/llama_runtime_tests.rs` | none | none | [`Local Model Smoke`](../release-smoke/alita-v035-release-smoke.md#local-model-smoke) |
| Agent intent routing | `python/tests/test_intent.py`, `python/tests/test_router_v2.py`, `python/tests/test_graph.py` | none | `python/evals/router_cases.jsonl` | none |
| Weather and web search | `python/tests/test_weather_provider.py`, `python/tests/test_web_provider_chain.py`, `python/tests/test_web_search.py` | none | `python/evals/tool_cases.jsonl`, `python/evals/research_cases.jsonl` | [`Live Network Smoke`](../release-smoke/alita-v035-release-smoke.md#live-network-smoke) |
| Research flow and claim/evidence output | `python/tests/test_web_research.py`, `python/tests/test_research_evidence.py`, `python/tests/test_execution.py` | none | `python/evals/research_cases.jsonl` | [`Research Artifact Smoke`](../release-smoke/alita-v035-release-smoke.md#research-artifact-smoke) |
| Document task graph and artifact output | `python/tests/test_task_planner.py`, `python/tests/test_graph_compiler.py`, `python/tests/test_execution.py`, `python/tests/test_document_artifact_fixtures.py` | none | `python/evals/planner_cases.jsonl` | [`Document Artifact Smoke`](../release-smoke/alita-v035-release-smoke.md#document-artifact-smoke) |
| Tool gateway, manifest tools, and permission boundary | `python/tests/test_tool_gateway.py`, `python/tests/test_tool_execution.py`, `src-tauri/tests/tool_manifest_tests.rs`, `python/tests/test_authority.py` | none | `python/evals/security_cases.jsonl`, `python/evals/tool_cases.jsonl` | none |
| Checkpoint, resume, trace, and memory | `python/tests/test_run_journal.py`, `python/tests/test_runtime_store.py`, `python/tests/test_trace_store.py`, `python/tests/test_memory_store.py`, `python/tests/test_execution.py::test_resume_checkpoint_reuses_completed_outputs_without_rerunning_upstream` | none | none | [`Runtime Resume Smoke`](../release-smoke/alita-v035-release-smoke.md#runtime-resume-smoke) |
| API provider secrets and redaction | `src-tauri/tests/api_provider_commands_tests.rs`, `src-tauri/tests/agent_model_config_tests.rs`, `python/tests/test_model_client.py` | none | `python/evals/security_cases.jsonl` | [`API Key Redaction Smoke`](../release-smoke/alita-v035-release-smoke.md#api-key-redaction-smoke) |
| Voice input and ASR | `src/features/voice/*.test.ts`, `src-tauri/tests/asr_tests.rs`, `python/tests/test_asr.py` | none | none | [`ASR Smoke`](../release-smoke/alita-v035-release-smoke.md#asr-smoke) |
| Artifact preview and open/reveal | `src/features/artifacts/*.test.tsx`, `src-tauri/tests/artifact_open_tests.rs` | none | none | [`Artifact Preview Smoke`](../release-smoke/alita-v035-release-smoke.md#artifact-preview-smoke) |
| MCP stdio tool provider | `python/tests/test_mcp_client_factory.py`, `python/tests/test_mcp_tool_provider.py`, `src-tauri/tests/tool_provider_commands_tests.rs` | none | none | [`MCP Stdio Smoke`](../release-smoke/alita-v035-release-smoke.md#mcp-stdio-smoke) |
