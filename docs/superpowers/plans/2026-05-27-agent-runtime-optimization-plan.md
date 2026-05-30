# Agent Runtime Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Alita from a workflow-first local Agent workbench MVP+ into a stronger single-agent runtime with structured routing, dynamic planning, unified tool execution, bounded ReAct loops, sandboxed execution, memory, and task-level evaluation.

**Architecture:** Preserve Alita's visible workflow graph as the product control plane. Add autonomy inside bounded kernel components: structured router, planner chain, execution graph, Unified Tool Gateway, verifier/reflection loop, and optional per-node ReAct policy. Defer multi-agent orchestration until the single-agent kernel has reliable tool execution, recovery, and eval coverage.

**Tech Stack:** React 19, Tauri 2, Rust, Python FastAPI sidecar, LangGraph, Pydantic, llama.cpp/OpenAI-compatible chat APIs, MCP, MarkItDown, Typst, pytest, Vitest, Rust tests.

---

## 1. Executive Verdict

The external review is mostly accurate and useful. It correctly identifies that Alita is already more than a chat UI wrapper, but is not yet a mature autonomous Agent system.

The main correction is wording: Alita does have valuable runtime infrastructure that the review underweights, especially node graph execution, `RunJournal`, failed-only/from-node reruns, result verification, permission gates, artifact events, model policies, and a unified tool protocol foundation. However, the review's central critique holds: the current intelligence loop is still mostly rules, templates, and deterministic executors rather than a general plan-act-observe-reflect loop.

Recommended product direction:

1. Keep the visible workflow graph as the control plane.
2. Build a stronger single-agent kernel before multi-agent features.
3. Wire every tool path through `UnifiedToolGateway`.
4. Add bounded ReAct only where it is useful and auditable, not as a global free-running loop.
5. Add task-level evals before broadening the supported task surface.

## 2. Code Evidence Map

Current Agent entry and routing:

- `python/agent_service/app.py`: FastAPI sidecar endpoints for message, streaming, graph run, cancellation, model session, script approval, ASR.
- `python/agent_service/graph.py`: LangGraph `StateGraph` router with `classify_intent -> conditional edge -> terminal handler`.
- `python/agent_service/intent.py`: keyword and regex route classifier.
- `python/agent_service/goal_spec.py`: heuristic `GoalSpec` parser.
- `python/agent_service/tool_router.py`: direct weather routing only.

Current planning and graph generation:

- `python/agent_service/planner_v2.py`: template planner for `document_processing`.
- `python/agent_service/task_graph.py`: typed document `TaskGraph`.
- `python/agent_service/task_planner.py`: heuristic planner for document/content/local-file/script/unsupported task kinds.
- `python/agent_service/graph_compiler.py`: compiles typed `TaskGraph` into frontend `RunGraph`.
- `python/agent_service/web_research.py`: builds fixed research graph and simple web answer.

Current execution and recovery:

- `python/agent_service/execution.py`: topological graph execution, executor selection, node events, cancellation, permissions, result verification, final verification, artifacts, failure suggestions.
- `python/agent_service/run_journal.py`: per-run JSON records.
- `python/agent_service/run_registry.py`: cancellation registry.
- `python/agent_service/permission_gate.py`: permission allow/deny.
- `python/agent_service/result_verifier.py`, `final_verifier.py`, `verifier_v2.py`: node and final output checks.
- `python/agent_service/replan.py`, `plan_feedback.py`: failure suggestions and user feedback handling.

Current tool architecture:

- `python/agent_service/tool_protocol.py`: unified tool definition, invocation, result, safety policy.
- `python/agent_service/tool_gateway.py`: validates and dispatches `UnifiedToolInvocation`.
- `python/agent_service/tool_providers/internal.py`: maps internal manifests to unified definitions.
- `python/agent_service/tool_providers/mcp.py`: maps MCP tools to unified definitions.
- `python/agent_service/model_tool_adapter.py`: converts unified tools to OpenAI-compatible tool schemas and executes model tool calls through the gateway.
- `python/agent_service/tool_execution.py`: older internal tool executor used by document flow.

Current desktop and frontend bridge:

- `src-tauri/src/lib.rs`: starts llama runtime and sidecar.
- `src-tauri/src/sidecar.rs`: packaged sidecar lifecycle and auth token env.
- `src-tauri/src/llama_runtime.rs`: llama.cpp runtime lifecycle.
- `src/features/task/useTaskEvents.ts`: HTTP/SSE bridge to sidecar.
- `src/app/backendEvents.ts`: frontend event reducer.
- `src/app/App.tsx`: current workbench state owner.

## 3. External Review Verdict Matrix

| External claim | Verdict | Code-based assessment | Priority |
| --- | --- | --- | --- |
| Alita is not a chat UI wrapper, but is not yet a mature autonomous Agent. | Accurate | Desktop workbench, node graph, sidecar, tools, artifact, and run history exist. General autonomous loop does not. | P0 framing |
| Main Agent Loop is a fixed route-to-END state machine. | Accurate | `graph.py` builds a `StateGraph` with terminal handlers after classification. `execution.py` loops over graph nodes, but it is not a reasoning loop. | P0 |
| Alita used LangGraph but is not fully LangGraph-like. | Mostly accurate | `StateGraph` is used for routing. There is no checkpointer/thread durable runtime. Alita does have custom `RunJournal` and rerun modes, so it is not stateless. | P1 |
| Intent router is brittle keyword logic. | Accurate | `intent.py`, `goal_spec.py`, and `tool_router.py` are mostly keyword/regex. Mojibake entries exist in document keyword lists. | P0 |
| PlannerV2 is template planning, not dynamic planning. | Accurate | `PlannerV2` only supports `document_processing`; `task_planner.py` is heuristic rather than model/tool-catalog driven dynamic DAG planning. | P0 |
| Tool protocol is good, execution surface is narrow. | Accurate | Unified protocol and MCP provider exist. Main document flow still calls `ToolExecutor`; generic fixed tools in `PlannedTaskExecutor` can hit `unsupported_runtime`. | P0 |
| MCP is not yet a first-class Agent action surface. | Accurate | MCP tools can be represented and called through provider tests, but primary graph execution does not dynamically select MCP tools. | P1 |
| Web Research is more search/report workflow than deep research Agent. | Accurate with nuance | Research flow reads source content and writes artifacts, but source review and quality checks are deterministic; simple answer stitches snippets. Search loop is sequential. | P1 |
| Model policy exists but is static. | Accurate | Policies map from intent/node identity. No adaptive budget, fallback chain, structured-output governance, or success-rate feedback. | P1 |
| Security awareness exists, but defaults are not strict enough. | Accurate | CORS is `*`; token auth is disabled if env var absent; Tauri CSP is `null`. Tauri-managed sidecar does set token, which is good. | P0 |
| `App.tsx` is becoming a state monolith. | Accurate | It owns project, messages, voice, graph, run, artifacts, preferences, and preview state. `backendEvents.ts` already proves extraction is possible. | P2 |
| Version discipline has a crack. | Accurate | package/Tauri/Cargo are `0.28.0`; Python sidecar is `0.27.0`. | P0 |
| Alita should copy OpenHands/AutoGPT/AutoGen/CrewAI features. | Directionally useful, not literal | These projects reveal missing capabilities, but Alita should stay workflow-first/local-first and avoid adopting multi-agent or marketplace complexity too early. | P3 |

## 4. What Should Not Be Done Yet

Do not make the model a global free-running agent that can call tools indefinitely. The current product value is visible graph state, approval gates, run history, artifacts, and deterministic recovery. Replacing that with an opaque ReAct loop would make local-model reliability and safety worse.

Do not introduce multi-agent orchestration before the single-agent kernel is reliable. Planner, executor, verifier, critic, researcher, and tool agents only make sense after the contracts for planning, tool invocation, observation, verification, memory, and retry are stable.

Do not make Docker or heavyweight virtualization a required dependency for the Windows MVP. Start with a restricted local Python runner with strict roots, no network by default, timeout, stdout/stderr capture, and artifact allowlists. Add stronger sandbox backends after the local contract is clear.

Do not replace keyword routing entirely in one pass. Keep deterministic fast paths for weather, empty input, obvious document attachment handling, and graph feedback. Add structured LLM routing as a calibrated fallback and review layer.

## 5. Target Agent Kernel

Target pipeline:

```text
User Message
  -> AgentRunState
  -> Deterministic Fast Router
  -> Structured Router when needed
  -> GoalSpec
  -> Context Bundle
  -> Planner Chain
  -> Plan Validator
  -> ExecutionGraph Compiler
  -> Execution Kernel
  -> Unified Tool Gateway for every tool call
  -> Optional bounded ReAct inside selected nodes
  -> Node Verifier
  -> Final Verifier
  -> Reflection Record
  -> Replan/Patch Proposal
  -> Run Journal + Artifact Store + Evals
```

Core rule:

```text
No tool, model tool call, web access, script, external provider, or MCP call may bypass:
Unified Tool Gateway -> Permission Gate -> Provider Adapter -> Result Normalizer -> Verifier -> Run Journal.
```

## 6. File Responsibility Map

New files to introduce:

- `python/agent_service/agent_run_state.py`: internal durable run state shared across routing, planning, execution, reflection, and events.
- `python/agent_service/router_v2.py`: structured router output schema, deterministic fast path wrapper, model-assisted fallback, confidence handling.
- `python/agent_service/planner_protocol.py`: `Planner`, `PlanningRequest`, `PlanningResult`, and planner chain contracts.
- `python/agent_service/planners/document_template.py`: current document planner moved behind the planner protocol.
- `python/agent_service/planners/research_template.py`: current research graph planner behind the planner protocol.
- `python/agent_service/planners/tool_capability.py`: first dynamic tool-catalog planner using `UnifiedToolDefinition`.
- `python/agent_service/execution_graph.py`: internal execution graph with normalized tool/model/react/verifier bindings.
- `python/agent_service/react_controller.py`: bounded per-node ReAct loop using model tool calls and `UnifiedToolGateway`.
- `python/agent_service/sandbox.py`: restricted local script runner contract and default Python subprocess implementation.
- `python/agent_service/eval_harness.py`: task-level eval runner and metrics aggregation.
- `python/tests/test_router_v2.py`: structured router and confidence tests.
- `python/tests/test_planner_chain.py`: planner chain selection and validation tests.
- `python/tests/test_execution_gateway_integration.py`: proof that tool nodes execute through `UnifiedToolGateway`.
- `python/tests/test_react_controller.py`: bounded tool loop tests.
- `python/tests/test_sandbox.py`: script sandbox allowlist, timeout, network-deny, and artifact tests.
- `python/tests/test_eval_harness.py`: task benchmark metrics tests.

Existing files to modify:

- `python/agent_service/app.py`: construct `AgentRunState`; keep endpoint schemas stable.
- `python/agent_service/graph.py`: reduce responsibility to message orchestration; route through router/planner chain.
- `python/agent_service/execution.py`: switch internal tools to gateway path; use `ExecutionGraph`; remove unsupported generic internal fixed-tool behavior.
- `python/agent_service/context_manager.py`: always support unified catalog context.
- `python/agent_service/tool_gateway.py`: enforce permission/safety policy before provider call.
- `python/agent_service/tool_providers/internal.py`: normalize all current internal tool results; preserve legacy adapters behind provider.
- `python/agent_service/model_client.py`: add optional structured-output and tool-call response surface for API providers that support it.
- `python/agent_service/model_tool_adapter.py`: support ReAct observation message formatting.
- `python/agent_service/web_research.py` and `python/agent_service/execution.py`: upgrade research evidence and parallelism.
- `python/agent_service/privacy.py`: keep web query sanitization, add eval cases for path/secret redaction.
- `src/app/App.tsx`: later split graph run, artifact preview, preferences, and voice state into hooks/stores.
- `src/app/backendEvents.ts`: remain the canonical event reducer; expand event coverage for reflection/eval if needed.
- `src-tauri/tauri.conf.json`: set a real CSP.
- `python/pyproject.toml`: align sidecar version with app version.

## 7. Implementation Phases

### Phase 0: Correctness, Security, and Release Hygiene

Goal: remove known correctness and default-security problems before expanding autonomy.

Files:

- Modify: `python/pyproject.toml`
- Modify: `python/agent_service/intent.py`
- Modify: `python/agent_service/app.py`
- Modify: `src-tauri/tauri.conf.json`
- Test: `python/tests/test_intent.py`
- Test: `python/tests/test_app.py`
- Test: `src-tauri/tests/*`

Tasks:

- [ ] Align `python/pyproject.toml` version to `0.28.0`.
- [ ] Remove mojibake keyword entries from `python/agent_service/intent.py` and add regression cases for normal Chinese document terms.
- [ ] Change sidecar auth to fail closed by default outside explicit dev mode.
- [ ] Add `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV=1` as the only unauthenticated sidecar escape hatch.
- [ ] Restrict CORS to localhost origins used by Tauri/Vite.
- [ ] Replace `csp: null` with a CSP that permits app assets and local sidecar calls without broad remote script execution.
- [ ] Run `python -m pytest -q python/tests/test_intent.py python/tests/test_app.py`.
- [ ] Run `npm run frontend:test -- --run src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts`.
- [ ] Run `cargo test --manifest-path src-tauri/Cargo.toml`.

Acceptance:

- Sidecar refuses protected endpoints if no token is configured and dev bypass is not explicit.
- Tauri-managed sidecar still works because `src-tauri/src/sidecar.rs` sets `ALITA_SIDECAR_TOKEN`.
- Chinese document routing still recognizes normal document actions.
- Python, frontend, and Rust tests pass.

### Phase 1: AgentRunState and Kernel Boundary

Goal: introduce one internal run-state object without changing public endpoint schemas.

Files:

- Create: `python/agent_service/agent_run_state.py`
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/graph.py`
- Test: `python/tests/test_agent_run_state.py`
- Test: `python/tests/test_agent_routing_integration.py`

AgentRunState fields:

```python
class AgentRunState(BaseModel):
    task_id: str
    run_id: str | None = None
    message: UserMessage
    goal_spec: GoalSpec | None = None
    current_graph: RunGraph | None = None
    has_run_history: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    model_session_id: str | None = None
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)
```

Tasks:

- [ ] Add `AgentRunState.from_message_request()` for `AgentMessageRequest`.
- [ ] Add `AgentRunState.from_run_graph_request()` for `RunGraphRequest`.
- [ ] Keep `UserMessage` and endpoint models stable.
- [ ] Change `run_agent()` and `stream_agent_events()` internals to build and pass `AgentRunState`.
- [ ] Assert returned event sequences are unchanged for existing chat, web, research choice, task graph, and graph feedback tests.

Acceptance:

- Public API remains backward compatible.
- Internal routing no longer passes many loose optional parameters across layers.
- Existing routing integration tests pass unchanged.

### Phase 2: Unified Tool Gateway as the Execution Path

Goal: make the gateway the only tool invocation path for internal fixed tools and future MCP tools.

Files:

- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/tool_providers/internal.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/context_manager.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_execution_gateway_integration.py`
- Test: `python/tests/test_execution.py`

Tasks:

- [ ] Add gateway-level permission/safety checks using `ToolSafetyPolicy`.
- [ ] Build a default gateway factory with `InternalToolProvider`.
- [ ] Change `DocumentFlowExecutor` to call `UnifiedToolGateway` instead of direct `ToolExecutor`.
- [ ] Change `PlannedTaskExecutor` so selected internal `fixed_tool` nodes call `UnifiedToolGateway`.
- [ ] Preserve special research pseudo-tools only until Phase 7 converts them into real providers.
- [ ] Convert gateway errors into `HarnessError` codes used by existing graph execution.
- [ ] Add tests proving `document.markitdown_convert` and `document.typst_compile` execute through gateway.
- [ ] Add tests proving an enabled internal tool no longer raises `unsupported_runtime`.

Acceptance:

- All internal manifest tools reachable from graph nodes go through `UnifiedToolGateway`.
- `ToolExecutor` becomes an internal implementation detail of `InternalToolProvider`.
- `PlannedTaskExecutor` no longer rejects selected internal tools that the gateway can execute.

### Phase 3: Structured Router V2

Goal: keep deterministic fast paths while adding a structured, observable router for ambiguous tasks.

Files:

- Create: `python/agent_service/router_v2.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/intent.py`
- Test: `python/tests/test_router_v2.py`
- Test: `python/tests/test_agent_routing_integration.py`

Structured decision shape:

```python
class RouterV2Decision(BaseModel):
    intent: Literal["chat", "local_inquiry", "web_simple_inquiry", "web_complex_choice", "web_complex_research_flow", "task", "missing_input"]
    confidence: float
    task_type: str
    missing_inputs: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    reason: str
```

Tasks:

- [ ] Implement deterministic fast path for empty input, weather, document attachment, explicit graph feedback, and explicit research choice.
- [ ] Implement model-assisted structured router for ambiguous messages using JSON schema output.
- [ ] Add confidence thresholds: high confidence proceeds; medium confidence asks a clarifying question; low confidence falls back to chat or missing input.
- [ ] Log router decision metadata in graph metadata or event payload without leaking secrets.
- [ ] Add tests for mixed-language prompts, implicit context continuation, task-vs-question ambiguity, and graph feedback.

Acceptance:

- Existing deterministic routes remain stable.
- Ambiguous prompts produce either a structured route or a clear clarification request.
- Router decisions are visible enough for debugging and eval.

### Phase 4: Planner Chain and Dynamic DAG Planning

Goal: replace planner fragmentation with a planner chain that can produce validated graphs from templates or the tool catalog.

Files:

- Create: `python/agent_service/planner_protocol.py`
- Create: `python/agent_service/planners/document_template.py`
- Create: `python/agent_service/planners/research_template.py`
- Create: `python/agent_service/planners/tool_capability.py`
- Modify: `python/agent_service/planner_v2.py`
- Modify: `python/agent_service/task_planner.py`
- Modify: `python/agent_service/plan_validator.py`
- Test: `python/tests/test_planner_chain.py`
- Test: `python/tests/test_plan_validator.py`

Planner interface:

```python
class Planner(Protocol):
    name: str

    def can_plan(self, request: PlanningRequest) -> bool:
        ...

    def plan(self, request: PlanningRequest) -> PlanningResult:
        ...
```

Tasks:

- [ ] Move current document template behavior behind `DocumentTemplatePlanner`.
- [ ] Move research graph creation behind `ResearchTemplatePlanner`.
- [ ] Add `ToolCapabilityPlanner` that selects tools from `UnifiedToolDefinition.capabilities`.
- [ ] Preserve `task_planner.py` heuristic outputs as a fallback planner, not the primary long-term planner contract.
- [ ] Validate every plan for acyclic dependencies, required bindings, permission declarations, verifier coverage, and output node presence.
- [ ] Add plan rejection reasons that can be shown to the user or fed to the reflection layer.

Acceptance:

- Document and research flows continue to generate the same user-visible graph shape.
- Non-document content/local-file tasks are planned through a common planner result contract.
- Tool-catalog-generated plans are validated before reaching the frontend.

### Phase 5: ExecutionGraph and Bounded ReAct Controller

Goal: introduce controlled per-node autonomy without replacing the visible workflow graph.

Files:

- Create: `python/agent_service/execution_graph.py`
- Create: `python/agent_service/react_controller.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/model_client.py`
- Modify: `python/agent_service/model_tool_adapter.py`
- Test: `python/tests/test_execution_graph.py`
- Test: `python/tests/test_react_controller.py`
- Test: `python/tests/test_model_tool_adapter.py`

ReAct policy shape:

```python
class ReActPolicy(BaseModel):
    enabled: bool = False
    max_steps: int = 4
    max_tool_calls: int = 3
    max_runtime_ms: int = 30000
    allowed_tool_ids: list[str] = Field(default_factory=list)
    allowed_permissions: list[str] = Field(default_factory=list)
    stop_on_first_success: bool = True
```

Tasks:

- [ ] Compile frontend `RunGraph` into internal `ExecutionGraph`.
- [ ] Bind normalized tool, model, verifier, retry, artifact, permission, and optional ReAct policies per node.
- [ ] Extend API model client response parsing for native tool calls where provider supports them.
- [ ] For local models without native tool calls, support a strict JSON action format inside `react_controller.py`.
- [ ] Execute every model-requested tool call through `UnifiedToolGateway`.
- [ ] Append observation summaries to node outputs and journal records.
- [ ] Stop on budget, verifier success, explicit final answer, or unrecoverable tool error.
- [ ] Add tests for max tool calls, disallowed tools, malformed action JSON, recoverable tool errors, and successful observation-to-answer loop.

Acceptance:

- ReAct can be enabled for a node without changing the whole graph runtime.
- Tool calls remain auditable and permission-gated.
- A failed ReAct loop produces a structured error and replan suggestion.

### Phase 6: Temporary Script Sandbox

Goal: move temporary scripts from preview-only to controlled execution for bounded local-file tasks.

Files:

- Create: `python/agent_service/sandbox.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/task_planner.py`
- Modify: `python/agent_service/permission_gate.py`
- Test: `python/tests/test_sandbox.py`
- Test: `python/tests/test_execution.py`

Sandbox contract:

```python
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
    stdout: str
    stderr: str
    values: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None
```

Tasks:

- [ ] Implement local subprocess Python runner with temp working dir under project artifacts.
- [ ] Pass only explicit arguments and approved roots to the script.
- [ ] Deny network by default through policy and static preflight checks for common network imports.
- [ ] Enforce timeout and stdout/stderr size limits.
- [ ] Require approval for high-risk scripts before execution.
- [ ] Capture output as `NodeOutput` and write run journal records.
- [ ] Add tests for root escape attempts, timeout, high-risk approval, low-risk CSV inspection, and artifact allowlist.

Acceptance:

- Low-risk temporary script nodes can run after validation.
- High-risk temporary script nodes still require approval.
- Scripts cannot read/write outside approved roots in supported test cases.

### Phase 7: Evidence-Driven Research Upgrade

Goal: turn research from snippet/report workflow into an evidence-grounded research node set.

Files:

- Modify: `python/agent_service/web_research.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/web_search.py`
- Create: `python/agent_service/research_evidence.py`
- Test: `python/tests/test_web_research.py`
- Test: `python/tests/test_research_evidence.py`

Tasks:

- [ ] Make search queries execute concurrently with bounded worker count.
- [ ] Store search metadata including provider attempts, query, timestamp, and sanitized query.
- [ ] Extract source text with URL, title, observed date when available, content hash, excerpt spans, and fetch status.
- [ ] Deduplicate sources by normalized URL and content hash.
- [ ] Add source reliability scoring by source type, domain, date, and query relevance.
- [ ] Replace simple snippet synthesis with model-assisted report synthesis over accepted source excerpts.
- [ ] Add citation span checks so claims reference source IDs.
- [ ] Add a model-assisted critique node with deterministic fallback checks.
- [ ] Add tests for dedupe, citation presence, no-source failure, source-read partial failure, and concurrent search behavior.

Acceptance:

- Research report can distinguish accepted, rejected, unreadable, and duplicate sources.
- Report includes citations tied to accepted source IDs.
- Quality check catches empty reports, missing citations, and no accepted source cases.

### Phase 8: Memory and Context Management

Goal: add project-scoped memory that improves routing and planning without leaking private local data.

Files:

- Modify: `python/agent_service/context_manager.py`
- Create: `python/agent_service/memory_store.py`
- Create: `python/agent_service/context_policy.py`
- Modify: `src-tauri/src/project.rs`
- Modify: `src/shared/types.ts`
- Test: `python/tests/test_context_manager.py`
- Test: `python/tests/test_memory_store.py`
- Test: `src-tauri/tests/project_tests.rs`

Tasks:

- [ ] Define project memory records for user preferences, prior graph summaries, prior artifact summaries, and tool outcomes.
- [ ] Store memory in the project directory, not global preferences, unless explicitly marked global.
- [ ] Add context budget policy for chat, planning, node execution, and research.
- [ ] Summarize old run histories into compact memory records.
- [ ] Exclude secrets, raw local paths, and large file content from model context by default.
- [ ] Add tests for memory persistence, redaction, budget trimming, and context selection by task type.

Acceptance:

- Follow-up tasks can use prior graph/artifact summaries.
- Memory is inspectable and scoped.
- Sensitive data is not injected into prompts by default.

### Phase 9: Agent Eval Harness

Goal: measure Agent improvements before broadening autonomy.

Files:

- Create: `python/agent_service/eval_harness.py`
- Create: `python/evals/router_cases.jsonl`
- Create: `python/evals/planner_cases.jsonl`
- Create: `python/evals/tool_cases.jsonl`
- Create: `python/evals/research_cases.jsonl`
- Test: `python/tests/test_eval_harness.py`
- Modify: `scripts/verify-mvp.ps1`

Metrics:

- Router accuracy by intent and missing input.
- Planner validity rate.
- Tool selection precision.
- Tool execution success rate.
- Research citation coverage.
- Failure recovery success rate.
- End-to-end runtime.
- Model call count and token budget where available.

Tasks:

- [ ] Add eval case schema and JSONL loader.
- [ ] Add deterministic fake model/tool/search providers for CI.
- [ ] Add a command to run all evals locally.
- [ ] Add threshold assertions for non-flaky deterministic cases.
- [ ] Add summary output as JSON and Markdown.
- [ ] Wire eval smoke run into `scripts/verify-mvp.ps1`.

Acceptance:

- Agent architecture changes have task-level regression signals.
- CI/local verification can fail on routing/planning/tool regressions, not only unit test failures.

### Phase 10: Frontend State Decomposition

Goal: keep frontend maintainable as Agent runtime events become richer.

Files:

- Create: `src/features/task/useGraphRunController.ts`
- Create: `src/features/artifacts/useArtifactPreviewController.ts`
- Create: `src/features/preferences/usePreferencesController.ts`
- Create: `src/features/voice/useVoiceInputController.ts`
- Modify: `src/app/App.tsx`
- Keep: `src/app/backendEvents.ts` as event reducer.
- Test: existing frontend tests plus new hook tests.

Tasks:

- [ ] Extract graph run state and actions from `App.tsx`.
- [ ] Extract artifact preview state and actions.
- [ ] Extract preferences state and actions.
- [ ] Extract voice input lifecycle.
- [ ] Keep project save/open composition in `App.tsx` until a dedicated project controller is justified.
- [ ] Add tests proving event reducer behavior remains unchanged.

Acceptance:

- `App.tsx` becomes a composition shell rather than the owner of every domain state.
- Existing UI behavior remains stable.
- Runtime events can be expanded without growing one component indefinitely.

## 8. Recommended Priority Order

P0 work for the next development line:

1. Phase 0: hygiene and security defaults.
2. Phase 1: `AgentRunState`.
3. Phase 2: `UnifiedToolGateway` in the main execution path.
4. Phase 3: structured router.
5. Phase 4: planner chain.

P1 work after P0 stabilizes:

1. Phase 5: bounded ReAct controller.
2. Phase 6: temporary script sandbox.
3. Phase 7: evidence-driven research.
4. Phase 9: eval harness, started early with small case sets and expanded continuously.

P2 work:

1. Phase 8: memory and context management.
2. Phase 10: frontend state decomposition.

P3 work to defer:

1. Multi-agent roles and group chat.
2. Marketplace/distribution of third-party agents.
3. Long-running cloud deployment.
4. Enterprise connector ecosystem.

## 9. Testing Strategy

Python:

```powershell
python -m pytest -q python/tests/test_agent_routing_integration.py python/tests/test_execution.py python/tests/test_tool_gateway.py python/tests/test_model_tool_adapter.py python/tests/test_planner_v2.py
```

Frontend:

```powershell
npm run frontend:test
npm run frontend:typecheck
```

Rust/Tauri:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml
```

MVP verification:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

Each phase must add or update tests before implementation. No phase should rely only on manual desktop testing.

## 10. Success Criteria

Alita should be considered significantly improved when these are true:

- Router decisions are structured, logged, testable, and not limited to keyword tables.
- Planner chain can produce validated graphs from both templates and tool catalog capabilities.
- Every internal and external tool call enters through `UnifiedToolGateway`.
- ReAct loops are bounded, per-node, observable, permission-gated, and journaled.
- Temporary scripts can execute only inside a controlled sandbox.
- Research reports cite accepted sources and are checked for evidence coverage.
- Project memory improves follow-up tasks without leaking secrets or raw local paths.
- Eval harness catches regressions in routing, planning, tool use, research, and recovery.
- Frontend state remains maintainable as runtime events grow.

## 11. Final Architecture Stance

The external critique should be accepted as a strong warning, not as a request to turn Alita into a clone of OpenHands, AutoGPT, AutoGen, CrewAI, or LangGraph Cloud.

Alita's best path is narrower and more defensible:

```text
Local-first workflow Agent workbench
  + visible graph control plane
  + unified safe tool gateway
  + bounded per-node autonomy
  + eval-driven runtime growth
  + optional multi-agent roles later
```

The immediate product risk is not the UI or Tauri shell. The risk is that Agent capabilities appear in the UI faster than they become real in the runtime. The optimization path should therefore prioritize runtime contracts, tool execution, verification, and evals before adding more visible Agent labels.

