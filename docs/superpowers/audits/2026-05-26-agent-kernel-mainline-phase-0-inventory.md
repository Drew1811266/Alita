# Agent Kernel Mainline Phase 0 Inventory

## Purpose

This audit records the current Agent runtime contracts before Phase 1 kernel contract consolidation.

## Public Agent Message Events

Current message and planning events:

- `message.created`
- `message.started`
- `message.delta`
- `message.completed`
- `input.required`
- `research.choice_required`
- `planning.progress`
- `node_graph.created`
- `graph.replanned`
- `graph.overwrite_confirmation_required`

Current run events:

- `run.started`
- `run.cancelled`
- `node.created`
- `node.updated`
- `node.running`
- `node.completed`
- `node.failed`
- `node.skipped`
- `node.needs_permission`
- `permission.required`
- `node.run_recorded`
- `node.runtime_notice`
- `artifact.created`
- `graph.patch_suggested`
- `research.completed`
- `task.failed`
- `task.completed`

## Graph Node Types

Backend `GraphNode.nodeType` currently accepts:

- `fixed_tool`
- `model`
- `output`
- `temporary_placeholder`
- `planning`
- `temporary_script`

Frontend `AgentNode.nodeType` must remain compatible with these values.

## Message Routing Paths

`python/agent_service/graph.py` routes:

- `chat` -> `answer_with_model`
- `local_inquiry` -> `answer_with_model`
- `web_simple_inquiry` -> `answer_with_web`
- `web_complex_choice` -> `choose_research_mode`
- `web_complex_research_flow` -> `plan_research_graph`
- `missing_input` -> `request_required_inputs`
- `task` -> `plan_task_graph`

## Planning Paths

Current planning is split:

- Document processing uses `GoalSpec`, `ContextBundle`, `PlannerV2`, `TaskGraph`, and `GraphCompiler`.
- General task planning uses `task_planner.analyze_task`, `select_tools`, `resolve_tool_gaps`, and `build_task_graph`.
- Research graph planning uses `web_research.build_research_graph`.
- Graph feedback uses `plan_feedback.apply_graph_feedback`.

## Execution Paths

`python/agent_service/execution.py` currently selects executors as follows:

- Research graphs use `ResearchFlowExecutor`.
- Planned task graphs use `PlannedTaskExecutor`.
- Other document graphs use `DocumentFlowExecutor`.
- Tests can inject a custom `NodeExecutor`.

## Tool Execution Paths

Current tool paths:

- Document conversion and Typst export go through `ToolExecutor` adapters.
- Research search and source reading are executed inside `ResearchFlowExecutor`.
- Weather answers are routed through `tool_router` and `tool_providers.weather`.
- Simple web search uses `tool_providers.web_search` provider chain.
- Internal and MCP tools are represented by `UnifiedToolGateway`, `InternalToolProvider`, and `MCPToolProvider`.
- Model-provider tool schema conversion exists in `model_tool_adapter.py`, but a full ReAct loop is not yet wired.

## Model Call Paths

Current model call paths:

- Chat and local inquiry use `answer_with_model`.
- Streaming chat uses `stream_agent_events`.
- Document model nodes use `ModelRuntime`.
- Planned generic model nodes use `PlannedTaskExecutor`.
- API and local model selection are resolved through model sessions and `create_model_client`.

## Run Journal Paths

Run journals are written by `run_graph_events` through `RunJournal`.

Node records include:

- `nodeRunId`
- `runId`
- `nodeId`
- `status`
- `startedAt`
- `completedAt`
- `artifactRefs`
- `values`
- `error`
- `errorCode`
- `runtimeNotice`

## Phase 1 Compatibility Requirement

Phase 1 must not change public event names, public graph node IDs, current document graph shape, current research graph shape, or frontend reducer expectations.
