# Alita Human Agent Smoke Traceability

Date: 2026-06-07

Command:

```powershell
.\scripts\run-human-agent-smoke.ps1
```

Pytest target:

```text
python/tests/test_human_task_smoke.py
```

## Scope

These smoke tests are offline and deterministic. They do not call a real model or public network. The goal is to preserve the product-path regressions found during manual testing:

- Chinese deterministic input guards.
- Tool-backed weather and web inquiry responses.
- Executable `web.search.parallel` / `web.fetch.sources` bindings.
- Current graph feedback preflight before Deep Agent reasoning.
- Chinese user-visible paths do not contain known English fixed error strings.

## Case Mapping

| Manual case | Smoke coverage | Expected signal |
| --- | --- | --- |
| H01 Empty input | `test_human_smoke_empty_input_and_missing_document_are_chinese_guards` | `input.required`, Chinese prompt |
| H02 Missing document attachment | `test_human_smoke_empty_input_and_missing_document_are_chinese_guards` | `input.required`, missing `attachment` |
| H03 Weather query | `test_human_smoke_weather_and_simple_web_use_tools_with_chinese_output` | Chinese weather answer with source |
| H04 Multi-turn context | Covered by focused conversation-history tests outside smoke | No known English fixed error in smoke |
| H05 Simple web query | `test_human_smoke_weather_and_simple_web_use_tools_with_chinese_output` | Python source returned, Chinese answer |
| H06 README summary/export path | Covered by Deep Agent product-path tests outside smoke | No `legacy_graph_blocked` fallback |
| H07 Complex web planning | `test_human_smoke_complex_web_planning_contains_executable_web_nodes` | Search/fetch nodes compile |
| H08 Confirm complex web graph execution | `test_human_smoke_confirmed_web_graph_executes_search_and_fetch` | Search and fetch tool invocations run |
| H09 Current graph feedback | `test_human_smoke_current_graph_feedback_routes_to_replanned` | `graph.replanned` before Deep Agent |
| H10 Research report generation | `test_human_smoke_complex_web_planning_contains_executable_web_nodes` | Research graph contains executable web nodes |

## Acceptance

- Smoke command exits with code `0`.
- Chinese smoke cases do not contain these fixed English strings:
  - `I could not complete`
  - `I could not find reliable`
  - `The input is empty`
  - `Search provider failed.`
- Web node smoke must fail on unsupported binding regressions.
