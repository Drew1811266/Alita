# Workflow-First Agent Kernel Mainline Design

## Purpose

This document defines the next main development line for Alita's Agent architecture after version `0.28.0`.

The chosen direction is:

```text
Workflow-first Agent Kernel
  + General Plan-and-Execute
  + Controlled ReAct tool loop
  + Reflexion verification and replanning layer
  -> Multi-Agent later, after the single-agent kernel is stable
```

This is not a replacement for the current product. It is a consolidation and extension plan based on the code that already exists in this repository.

## Current Runtime Reality

Alita is already beyond a chat prototype. The current runtime has a real desktop workbench, a Python Agent sidecar, LangGraph routing, graph execution, model selection, unified tool protocol work, web research flow, run journals, permission gates, and artifact previews.

The current strongest architecture pattern is Workflow/Orchestration:

- `python/agent_service/graph.py` routes incoming messages into chat, local inquiry, simple web inquiry, complex research choice, research flow, missing input, and task planning.
- `python/agent_service/execution.py` executes node graphs with topological ordering, run journal records, cancellation, permission checks, result verification, final verification, and repair suggestions.
- `python/agent_service/task_graph.py`, `planner_v2.py`, `graph_compiler.py`, and `task_planner.py` provide the current task graph and planning foundation.
- `python/agent_service/tool_gateway.py`, `tool_protocol.py`, `tool_resolver.py`, and `tool_providers/*` provide the unified tool catalog direction.
- `python/agent_service/model_tool_adapter.py` can convert unified tool definitions to model-provider tool schemas, but it is not yet wired into a complete ReAct loop.
- `python/agent_service/replan.py`, `plan_feedback.py`, `result_verifier.py`, `final_verifier.py`, and `verifier_v2.py` provide pieces of Reflexion-like recovery, but not a full self-reflection and improvement system.

The current gaps are not missing files. The gaps are architectural integration:

- Planning exists, but it is still split between `PlannerV2` templates and heuristic task planning.
- Execution exists, but arbitrary planned tool nodes are not yet uniformly executed through the Unified Tool Gateway.
- Tool calling adapters exist, but model-requested tool calls are not yet part of a bounded observe-act loop.
- Replanning exists as suggestions and feedback handling, but not as a structured reflect -> patch -> verify cycle.
- Research flow exists, but synthesis and quality checks are still mostly deterministic and not a generalized agent loop.
- Multi-agent collaboration does not exist yet and should remain out of scope until the single-agent loop is reliable.

## Architecture Decision

Adopt a Workflow-first Agent Kernel.

The graph remains the product's control plane. User-visible task progress, permission gates, artifacts, run history, and retries continue to be represented as node graph state. ReAct is added inside controlled boundaries, not as a replacement for graph execution.

The target pipeline is:

```text
User Message
  -> Intent Router
  -> GoalSpec
  -> Context Bundle
  -> Planner
  -> Plan Validator
  -> NodeGraph / ExecutionGraph Compiler
  -> Execution Kernel
  -> Controlled ReAct Loop where needed
  -> Node Verifier
  -> Final Verifier
  -> Reflexion Analyzer
  -> Replan / Patch Proposal
  -> Run Journal + Artifact Store
```

The main rule is:

```text
No tool, model tool call, web access, script, or external provider call may bypass the Agent Kernel safety path.
```

That path is:

```text
Planner or ReAct Controller
  -> Unified Tool Gateway
  -> Permission Gate
  -> Provider Adapter
  -> Result Normalizer
  -> Verifier
  -> Run Journal
```

## Alternative Approaches Considered

### Approach A: ReAct-first Agent

Make the model decide actions in a continuous reason-act-observe loop and use the graph only as a trace.

This is not recommended now. It would undermine the strongest part of Alita: visible workflow state, artifact tracking, permissions, and deterministic graph execution. It would also make local-model reliability harder because small local models may produce unstable tool calls.

### Approach B: Workflow-first Kernel With Bounded ReAct

Keep workflow orchestration as the control plane. Use Plan-and-Execute to create graphs. Add a controlled ReAct loop only inside specific nodes or chat modes, with budgets, allowlists, permissions, and verifier checks.

This is the recommended path. It matches the current code and reduces risk. It also makes Multi-Agent easier later because each future agent role can become a planner, verifier, critic, or executor policy around the same kernel.

### Approach C: Multi-Agent-first System

Introduce planner, executor, researcher, critic, and tool agents immediately.

This should be deferred. The current single-agent kernel still needs a unified planning contract, bounded tool loop, and consistent reflection/replan semantics. Multi-Agent would multiply those unresolved contracts.

## Design Principles

### Preserve The Working Product Loop

Document processing, research flows, weather lookup, search, artifact preview, and project persistence are current product value. Refactors must preserve these user-visible flows.

### Keep Graphs As The Control Plane

The graph is not only a UI. It is the orchestration state: dependencies, status, permissions, run records, artifacts, retry mode, and user feedback.

### Separate Planning, Execution, And Reflection

The planner proposes a graph. The executor runs it. The verifier judges outputs. The reflection layer explains failures and proposes repairs. These should not collapse into one large model prompt.

### Make Tool Calls Boring

Tool calls should be normalized, validated, permission-checked, executed through one gateway, and recorded. Provider-specific details should stay behind adapters.

### Add Autonomy In Small Loops

ReAct should start as a bounded loop inside one node:

- max tool calls
- max wall-clock time
- allowed tool IDs
- allowed permissions
- observable intermediate results
- safe failure when uncertain

### Treat Reflexion As Engineering Feedback

Reflection should produce structured records:

- what failed
- evidence
- likely cause
- proposed patch
- whether user approval is required
- whether automatic retry is allowed

It should not be a free-form apology message.

## Target Core Contracts

### AgentRunState

Create a durable state object used by routing, planning, execution, reflection, and event emission.

Fields:

- `task_id`
- `run_id`
- `message`
- `goal_spec`
- `context_bundle`
- `current_graph`
- `execution_mode`
- `model_session_id`
- `disabled_tool_ids`
- `approved_permissions`
- `budget`
- `events`
- `journal_ref`

This should not replace existing request schemas immediately. It should be introduced as an internal object inside the sidecar.

### Planner Interface

Unify current `PlannerV2` and heuristic `task_planner` behind one interface:

```python
class Planner(Protocol):
    def can_plan(self, goal: GoalSpec, context: ContextBundle) -> bool:
        ...

    def plan(self, request: PlanningRequest) -> PlanningResult:
        ...
```

Initial planner chain:

1. `DocumentTemplatePlanner`
2. `ResearchTemplatePlanner`
3. `ContentTaskPlanner`
4. `ToolCapabilityPlanner`
5. future `ModelAssistedPlanner`, disabled by default

### ExecutionGraph

Keep `RunGraph` as the frontend shape, but introduce an internal execution graph model that carries normalized bindings:

- node ID
- node kind
- dependencies
- tool binding
- model binding
- ReAct policy
- verifier spec
- permission requirements
- retry policy
- artifact policy

The existing UI `NodeGraph` can remain stable while execution becomes more explicit.

### ReActPolicy

Add a per-node policy, not a global always-on mode.

Fields:

- `enabled`
- `max_steps`
- `max_tool_calls`
- `max_runtime_ms`
- `allowed_tool_ids`
- `allowed_permissions`
- `stop_on_first_success`
- `observation_limit_chars`
- `requires_user_visible_trace`

Default: disabled.

### ToolUseRequest And Observation

Model-requested or planner-requested tool actions should normalize into:

- `tool_id`
- `arguments`
- `reason`
- `expected_output`
- `permission_context`
- `origin`: `planner`, `react_loop`, `manual_graph_run`, or `external_mcp`

The observation should normalize:

- `ok`
- `content`
- `structured_content`
- `artifacts`
- `safe_error`
- `source`
- `duration_ms`

### ReflectionRecord

Every failed or low-quality node can produce a reflection record:

- `node_id`
- `failure_code`
- `evidence`
- `root_cause`
- `repair_strategy`
- `patch_operations`
- `auto_retry_allowed`
- `requires_user_approval`
- `confidence`

This record should be written to the run journal and optionally shown in the UI as an advisory event.

## Implementation Roadmap

### Phase 0: Baseline Audit And Contract Map

Goal: document the current contracts before refactoring.

Work:

- Map all current Agent events emitted by `graph.py`, `execution.py`, `plan_feedback.py`, and `web_research.py`.
- Map all graph node types used by backend and frontend.
- Map current tool execution paths:
  - internal manifest tools
  - weather provider
  - web search provider chain
  - MCP provider
  - optional Alita MCP server
  - model tool adapter
- Map current run journal shape.
- Add a short architecture inventory document under `docs/superpowers/audits/`.

Acceptance:

- No runtime behavior changes.
- Inventory identifies which tool paths already use `UnifiedToolGateway` and which still bypass it.
- Inventory identifies all places where model calls happen.

### Phase 1: Kernel Contract Consolidation

Goal: introduce a consistent internal kernel state without changing user-visible behavior.

Create:

- `python/agent_service/kernel_state.py`
- `python/agent_service/planning.py`
- `python/agent_service/execution_graph.py`
- `python/agent_service/agent_events.py`

Modify:

- `python/agent_service/graph.py`
- `python/agent_service/execution.py`
- `python/agent_service/planner_v2.py`
- `python/agent_service/task_planner.py`

Behavior:

- `run_agent()` and `stream_agent_events()` build `AgentRunState`.
- Existing routes still emit the same public events.
- Document task graphs keep the same node IDs.
- Research graph creation keeps the same graph shape.
- Planning metadata includes planner name and confidence.

Acceptance:

- Full Python test suite passes.
- Frontend event tests pass without UI changes.
- Existing document graph and research graph snapshots remain compatible.

### Phase 2: General Plan-And-Execute Planner Chain

Goal: make planning extensible beyond fixed document templates.

Create:

- `python/agent_service/planners/document.py`
- `python/agent_service/planners/research.py`
- `python/agent_service/planners/content.py`
- `python/agent_service/planners/tool_capability.py`
- `python/agent_service/planners/__init__.py`

Modify:

- `python/agent_service/planner_v2.py`
- `python/agent_service/task_planner.py`
- `python/agent_service/context_manager.py`
- `python/agent_service/plan_validator.py`
- `python/agent_service/graph_compiler.py`

Behavior:

- Planner selection becomes explicit and testable.
- Known task types are planned deterministically.
- Unknown task types produce a safe clarification or model-only output node, not unsupported tool nodes that fail later.
- Tool selection uses unified tool summaries when available.
- Disabled tools and high-risk tools are filtered during planning when the request contains that context.

Acceptance:

- Tests cover planner selection for chat, document, research, local-file, content, and unsupported/high-risk requests.
- Planned fixed-tool nodes have executable bindings or are blocked before execution.
- Existing `PlannedTaskExecutor` no longer raises `unsupported_runtime` for selected internal tools that the gateway can execute.

### Phase 3: Unified Tool Gateway As The Only Execution Path

Goal: route all non-model tool execution through one gateway.

Create:

- `python/agent_service/tool_runtime.py`
- `python/agent_service/tool_audit.py`

Modify:

- `python/agent_service/execution.py`
- `python/agent_service/tool_execution.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/tool_providers/internal.py`
- `python/agent_service/tool_providers/mcp.py`
- `python/agent_service/tool_providers/weather.py`
- `python/agent_service/tool_providers/web_search.py`

Behavior:

- Internal document tools execute through `UnifiedToolGateway`.
- Web and weather provider calls are represented as unified tool invocations.
- MCP tools remain behind provider adapters.
- Run journals include safe tool invocation summaries.
- Raw provider errors are sanitized before reaching model prompts or UI events.

Acceptance:

- No tool execution code path directly calls provider internals from graph nodes.
- Tests prove unsupported, disabled, invalid-input, permission-denied, and provider-failed tools return stable unified errors.
- Secrets and full local paths are not written to tool audit records.

### Phase 4: Controlled ReAct Loop

Goal: add action-observation loops without losing workflow control.

Create:

- `python/agent_service/react_loop.py`
- `python/agent_service/react_policy.py`
- `python/agent_service/tool_call_parser.py`

Modify:

- `python/agent_service/model_client.py`
- `python/agent_service/model_tool_adapter.py`
- `python/agent_service/execution.py`
- `python/agent_service/model_runtime.py`

Behavior:

- ReAct runs only when a node has `ReActPolicy.enabled`.
- Native model tool calls are supported for API providers that declare capability.
- Text-only fallback can parse explicit safe tool-call JSON for local models, but only behind strict validation.
- Every requested tool call goes through `UnifiedToolGateway`.
- Tool observations are appended to the model context with size limits.
- Loop stops on success, budget exhaustion, permission denial, verifier failure, or user input requirement.

Acceptance:

- Unit tests cover successful one-tool loop, multi-step loop, invalid tool call, unavailable tool, permission denial, budget exhaustion, and verifier failure.
- Integration test proves a simple web question can be answered through ReAct without bypassing search privacy rules.
- Providers without native tool calling continue to use existing graph planning.

### Phase 5: Reflexion Verification And Replan Layer

Goal: turn current verifier and replanner pieces into a full reflect -> patch -> verify flow.

Create:

- `python/agent_service/reflection.py`
- `python/agent_service/graph_patch.py`
- `python/agent_service/retry_policy.py`

Modify:

- `python/agent_service/replan.py`
- `python/agent_service/result_verifier.py`
- `python/agent_service/final_verifier.py`
- `python/agent_service/verifier_v2.py`
- `python/agent_service/run_journal.py`
- `src/app/backendEvents.ts`
- `src/shared/events.ts`

Behavior:

- Known failures map to structured `ReflectionRecord` values.
- Patch proposals are explicit:
  - retry node
  - rerun from node
  - replace tool
  - ask for missing input
  - request permission
  - reduce scope
  - full replan
- Low-risk retries can be automatic within budget.
- High-risk patches require user approval.
- The UI can show why a run failed and what the system suggests next.

Acceptance:

- Tests cover reflection records for empty output, missing artifact, invalid input contract, tool disabled, permission required, search failure, and final verifier failure.
- Automatic retry is limited and journaled.
- User-visible patch suggestions remain advisory unless the patch is approved or classified as safe.

### Phase 6: Workflow Orchestration Maturity

Goal: make graph execution robust enough for longer tasks.

Create or extend:

- graph scheduler
- checkpoint manager
- run budget manager
- idempotency keys for tool calls
- cancellation propagation
- partial-output hydration

Behavior:

- Independent safe nodes can run concurrently later, but sequential execution remains the default.
- Failed-only and from-node reruns reuse valid source outputs.
- Cancelling a run stops pending tool/model operations when possible.
- Runtime notices distinguish slow node, retried node, partial result, and degraded provider.

Acceptance:

- Existing run modes still work.
- Checkpoint resume tests cover completed source outputs, missing artifacts, failed partial outputs, cancelled runs, and permission pauses.
- Long-running research flow can be cancelled cleanly.

### Phase 7: Evals And Release Gates

Goal: stop architecture growth from regressing the Agent behavior.

Create:

- `python/agent_service/evals/`
- `python/tests/test_agent_eval_cases.py`
- `docs/superpowers/audits/<date>-agent-kernel-mainline-audit.md`

Eval categories:

- intent routing
- goal spec parsing
- planner selection
- graph shape
- tool selection
- tool safety
- ReAct loop safety
- verifier quality
- replan quality
- artifact correctness

Acceptance:

- A small deterministic eval suite runs in CI/local verification without external API keys.
- Web/provider-dependent evals use fakes or are marked integration-only.
- Each new Agent capability adds at least one eval case.

### Phase 8: Multi-Agent Preparation, Not Multi-Agent Runtime

Goal: prepare roles without spawning multiple autonomous agents.

Create role interfaces:

- `PlannerPolicy`
- `ExecutorPolicy`
- `VerifierPolicy`
- `ReflectionPolicy`
- `ResearchPolicy`

Behavior:

- These policies run inside the single kernel.
- Each policy has explicit inputs and outputs.
- No independent agent memory, hidden conversations, or unbounded recursive delegation.

Acceptance:

- The single-agent kernel can swap policies in tests.
- The codebase has clean seams for future Multi-Agent work.
- No user-visible Multi-Agent feature is shipped in this phase.

## API And Event Changes

### Keep Stable Initially

These events should remain compatible:

- `message.created`
- `message.started`
- `message.delta`
- `message.completed`
- `input.required`
- `research.choice_required`
- `node_graph.created`
- `graph.replanned`
- `graph.overwrite_confirmation_required`
- `run.started`
- `node.running`
- `node.completed`
- `node.failed`
- `node.needs_permission`
- `node.run_recorded`
- `node.runtime_notice`
- `artifact.created`
- `graph.patch_suggested`
- `task.failed`
- `task.completed`
- `research.completed`

### Add Later

Add these only when the corresponding phases need them:

- `react.step_started`
- `react.tool_call_requested`
- `react.observation_received`
- `react.completed`
- `reflection.created`
- `graph.patch_applied`
- `run.retry_started`
- `run.budget_exceeded`

All new events must be added to:

- `python/agent_service/schemas.py` if typed later
- `src/shared/events.ts`
- `src/app/backendEvents.ts`
- focused frontend reducer tests

## Testing Strategy

### Backend Unit Tests

Add focused tests for:

- planner chain selection
- execution graph compilation
- unified tool runtime
- ReAct budget and permission behavior
- reflection record generation
- graph patch validation
- retry policy

### Backend Integration Tests

Keep and expand:

- message -> graph creation
- graph run -> artifact output
- research flow -> markdown artifact
- weather inquiry -> weather provider
- web simple inquiry -> search provider chain
- MCP fake provider -> unified gateway call
- model tool call -> gateway -> observation -> final answer

### Frontend Tests

Add tests only when events or request payloads change:

- backend event reducer
- graph run request payload
- permission/retry/reflection notices
- artifact preview compatibility

### Rust/Tauri Tests

Add tests when request/session fields change:

- model session handoff
- sidecar auth
- project persistence compatibility
- preferences for provider/tool settings

### Evals

Add deterministic evals before enabling model-assisted planning or ReAct by default.

Minimum eval cases:

- document report task
- markdown conversion-only task
- simple current web question
- weather question with missing city
- research-flow choice
- local content generation task
- unsupported destructive task
- failed tool with repair suggestion

## Security Requirements

- All external network input must pass through a privacy guard.
- Tool calls must never receive secrets through model prompt text.
- API keys and MCP tokens remain in the credential store.
- Run journals store safe summaries, not raw credentials.
- High-risk permissions require explicit approval.
- Temporary scripts remain preview/approval-only until sandboxing is implemented.
- External MCP exposure remains disabled by default.
- Model-generated tool calls are treated as untrusted input.

## Non-Goals For This Mainline

Do not implement these until the single-agent kernel is stable:

- autonomous Multi-Agent collaboration
- recursive agent delegation
- long-term cross-project memory
- automatic destructive file operations
- arbitrary script execution
- unbounded browser automation
- provider-specific advanced model features beyond the common adapter
- schema generation across Python/TypeScript/Rust unless event drift becomes a blocking issue

## Suggested Immediate Next Work

The next concrete implementation plan should cover Phase 0 and Phase 1 only.

Recommended first plan title:

```text
Agent Kernel Mainline Phase 0-1 Implementation Plan
```

Expected scope:

1. Add current architecture inventory audit.
2. Introduce `AgentRunState`.
3. Introduce planner chain interfaces without changing public behavior.
4. Add execution graph internal contract.
5. Preserve existing event shapes and graph node IDs.
6. Add focused regression tests.

Do not start with ReAct or Reflexion automation. Those depend on stable planning, execution, and tool gateway contracts.

## Acceptance Criteria For The Mainline

The mainline is successful when:

- Existing Alita workflows keep working.
- New task types can be planned through a common planner chain.
- Tool execution has one safety path.
- ReAct tool use is bounded, observable, and permission-aware.
- Reflection produces structured repair records.
- Replanning can safely retry or patch common failures.
- Frontend users can understand what the Agent is doing from graph events and run history.
- Multi-Agent can be added later without rewriting the single-agent kernel.

## Design Self-Review

- No Multi-Agent runtime is included in the near-term scope.
- The plan starts from the current 0.28 code, not from older outdated design assumptions.
- The current working document and research flows are preserved.
- ReAct is bounded and placed inside the workflow kernel.
- Reflexion is structured as verification and repair, not free-form self-talk.
- Tool execution stays behind Unified Tool Gateway and permission checks.
- Each phase has clear files, behavior changes, and acceptance criteria.
