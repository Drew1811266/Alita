# Agent Routing And Task Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the confirmed intent routing, web research, and task planning designs into Alita's local agent runtime so the agent can classify user input, answer simple chat directly, perform privacy-safe web research when needed, generate user-visible research documents, plan executable task graphs, handle missing tools through temporary script analysis, and let users revise generated graphs through chat feedback.

**Architecture:** Add a layered decision pipeline around the existing Python LangGraph service. The pipeline starts with intent classification, then routes into direct chat, inquiry answering, web research, or task graph planning. Execution remains event-driven through the existing sidecar stream, but the graph schema gains planning nodes, estimates, script risk metadata, runtime notices, and research/report events. The frontend consumes the same event stream, renders richer node types in the canvas, shows approval gates for high-risk temporary scripts, and previews generated Markdown research reports in the existing artifact preview surface.

**Tech Stack:** Python sidecar, LangGraph, existing llama.cpp-compatible model client, Tauri/Rust command bridge, React, TypeScript, Vitest, Pytest, existing local tool registry, `urllib.request` and `html.parser` for the first built-in no-key web search provider boundary.

---

## Confirmed Product Rules

- User input is classified into `chat`, `inquiry`, `task`, or `need_input`.
- `chat` is answered directly.
- `inquiry` is further classified into local-answerable or web-needed.
- Simple web-needed questions run automatic web search and answer directly.
- Complex web-needed questions ask the user whether they want a quick answer or a full research flow.
- Privacy guard must remove local paths, full file contents, model paths, preferences, logs, and other local identifiers before any external search request.
- Full research flow produces a visible node graph and a Markdown report previewable in the right-side artifact area.
- Research report structure is brief conclusion first, research process second, full conclusion and recommendations last.
- Research flow includes accepted and rejected sources.
- Research graph has one visible parallel web search node, while internal queries run in parallel.
- Failed internal search queries retry automatically; later retries only retry failed query units.
- Task intent produces an analysis of task type, needed capabilities, selected tools, tool order, and a complete visible execution graph.
- Generated task graphs are shown first; users explicitly run them.
- Planning nodes are visible and saved to `.alita`, but are not rerun during execution.
- If a required tool is missing, the planner checks whether a temporary script can substitute it.
- If no built-in tool or safe temporary substitute exists, planning stops and tells the user what is missing.
- Low-risk temporary scripts can run automatically but still show code preview and permission summary.
- High-risk temporary scripts require centralized approval before graph execution.
- User feedback on a graph is routed as local modification, full replan, constraint update, or new task.
- Local graph modifications preserve unaffected nodes.
- Existing graphs are overwritten by default on feedback, but if a graph has already run or generated artifacts, the user is asked before overwrite.
- Approved high-risk scripts require reapproval if code, permissions, risk level, input contract, or output contract changes.
- Each executable node has estimated duration and resource usage.
- If actual duration exceeds estimate, the UI shows a runtime notice.

## Current Code Map

- `python/agent_service/graph.py` currently builds a small LangGraph with `classify_intent`, `request_required_inputs`, `plan_node_graph`, and `answer_with_model`.
- `python/agent_service/execution.py` currently topologically executes all graph nodes and is hardcoded around document-flow nodes.
- `python/agent_service/schemas.py` defines Python graph/event-facing models.
- `python/agent_service/tool_registry.py` loads built-in tool manifests and exposes enabled tools.
- `python/agent_service/tool_execution.py` executes registered built-in tools.
- `python/agent_service/model_client.py` provides llama.cpp-compatible chat and stream calls.
- `src/shared/types.ts` defines frontend graph and run-history types.
- `src/shared/events.ts` defines backend event unions.
- `src/app/backendEvents.ts` reduces sidecar events into UI state.
- `src/features/task/useTaskEvents.ts` owns sidecar submit/run streaming calls.
- `src/features/canvas/NodeCanvas.tsx` and `src/features/canvas/NodePopover.tsx` render node graphs and details.
- `src-tauri/src/domain.rs` contains Rust graph domain types used by tests and project data.
- `src-tauri/src/agent_client.rs` forwards generic agent events from Python.

---

## Task 1: Add Shared Graph, Estimate, And Script Risk Schema

**Files:**

- `python/agent_service/schemas.py`
- `src/shared/types.ts`
- `src/shared/events.ts`
- `src-tauri/src/domain.rs`
- `python/tests/test_graph.py`
- `src-tauri/tests/domain_tests.rs`
- `src/features/canvas/nodeLayout.test.ts`

**Step 1: Write failing schema tests.**

- [ ] Add a Python test that parses a graph containing:
  - `planning` node
  - `temporary_script` node
  - `estimate`
  - `resourceUsage`
  - expanded `scriptReview`
  - `runtimeNotice`
- [ ] Add a Rust domain serialization test for the new node types.
- [ ] Add or update a TypeScript test that confirms canvas sample layout accepts the new node types.

Expected first command:

```powershell
pytest python/tests/test_graph.py
```

Expected first result:

```text
FAIL: planning and temporary_script are not accepted node types yet.
```

**Step 2: Extend Python schema.**

- [ ] In `python/agent_service/schemas.py`, extend `GraphNode.nodeType` to include `planning` and `temporary_script`.
- [ ] Add `NodeEstimate`:

```python
class NodeEstimate(BaseModel):
    durationMs: int | None = None
    cpu: str | None = None
    memory: str | None = None
    network: str | None = None
```

- [ ] Add `RuntimeNotice` with `kind`, `message`, and `actualDurationMs`.
- [ ] Extend `ScriptReviewState` with:
  - `riskLevel: "low" | "medium" | "high"`
  - `requiresApproval: bool`
  - `codePreview: str | None`
  - `inputContract: dict[str, Any]`
  - `outputContract: dict[str, Any]`
  - `approvalFingerprint: str | None`
- [ ] Add optional `estimate`, `resourceUsage`, and `runtimeNotice` fields to `GraphNode`.

**Step 3: Extend TypeScript and Rust types.**

- [ ] In `src/shared/types.ts`, extend `NodeType`.
- [ ] Add matching `NodeEstimate`, `RuntimeNotice`, `ResourceUsage`, and expanded `ScriptReviewState` interfaces.
- [ ] In `src/shared/events.ts`, add event payload types needed later:
  - `research.completed`
  - `research.choice_required`
  - `node.needs_permission`
  - `node.runtime_notice`
  - `graph.replanned`
- [ ] In `src-tauri/src/domain.rs`, extend `NodeType` enum with `Planning` and `TemporaryScript`.

**Step 4: Run schema tests.**

```powershell
pytest python/tests/test_graph.py
npm test -- src/features/canvas/nodeLayout.test.ts src-tauri/tests/domain_tests.rs
```

Expected result:

```text
All selected schema and serialization tests pass.
```

---

## Task 2: Build Intent And Inquiry Router

**Files:**

- `python/agent_service/intent.py`
- `python/agent_service/graph.py`
- `python/tests/test_intent.py`
- `python/tests/test_graph.py`

**Step 1: Write failing router tests.**

- [ ] Create `python/tests/test_intent.py`.
- [ ] Cover Chinese and English examples for:
  - chat
  - local inquiry
  - web-needed simple inquiry
  - web-needed complex inquiry
  - task
  - missing input
- [ ] Include examples that mention files, project paths, and local model paths to prove routing does not itself leak data.

Expected first command:

```powershell
pytest python/tests/test_intent.py
```

Expected first result:

```text
FAIL: python/agent_service/intent.py does not exist.
```

**Step 2: Implement `intent.py`.**

- [ ] Add enums:

```python
class IntentKind(str, Enum):
    CHAT = "chat"
    INQUIRY = "inquiry"
    TASK = "task"
    NEED_INPUT = "need_input"

class InquiryMode(str, Enum):
    LOCAL = "local"
    WEB_SIMPLE = "web_simple"
    WEB_COMPLEX = "web_complex"
```

- [ ] Add dataclasses or Pydantic models:
  - `IntentDecision`
  - `InquiryDecision`
  - `RouteDecision`
- [ ] Implement deterministic heuristics first:
  - Direct greeting, thanks, simple conversation -> `chat`.
  - Question markers and factual/current-data phrases -> `inquiry`.
  - Creation/modification/execution verbs -> `task`.
  - Missing attachment or empty input -> `need_input`.
  - Current, latest, price, ranking, release, law, official docs, GitHub, library version, model info -> web-needed.
  - Research/compare/design/方案/调研/流程图/详细文档 -> complex web-needed.
- [ ] Add a model-assisted classification hook that is disabled by default but can later be wired to local model calls without changing callers.

**Step 3: Integrate router into `graph.py`.**

- [ ] Replace the existing `_classify_message()` logic with `classify_route()`.
- [ ] Preserve current document-task behavior for existing tests.
- [ ] Return a route payload that downstream nodes can use for inquiry and task handling.

**Step 4: Run router tests.**

```powershell
pytest python/tests/test_intent.py python/tests/test_graph.py
```

Expected result:

```text
All selected router tests pass.
```

---

## Task 3: Add Privacy Guard For External Search

**Files:**

- `python/agent_service/privacy.py`
- `python/tests/test_privacy.py`
- `python/agent_service/web_research.py`

**Step 1: Write failing privacy tests.**

- [ ] Create tests for:
  - Windows paths such as `D:\Software Project\Alita\src\app\App.tsx`
  - POSIX paths
  - model paths and model filenames
  - full file-like pasted content
  - email addresses and obvious tokens
  - local project names when adjacent to paths
  - Chinese queries that mix local and public terms
- [ ] Assert sanitized query keeps public intent while removing local details.

Expected first command:

```powershell
pytest python/tests/test_privacy.py
```

Expected first result:

```text
FAIL: python/agent_service/privacy.py does not exist.
```

**Step 2: Implement privacy guard.**

- [ ] Add `PrivacyGuardResult` with:
  - `sanitizedText`
  - `removedCategories`
  - `blocked`
  - `reason`
- [ ] Implement `sanitize_for_web_search(text: str) -> PrivacyGuardResult`.
- [ ] Redact with category labels rather than leaking specifics:
  - `[LOCAL_PATH]`
  - `[LOCAL_FILE_CONTENT]`
  - `[MODEL_PATH]`
  - `[SECRET]`
  - `[EMAIL]`
- [ ] Block search when sanitization removes so much content that the remaining query is not meaningful.
- [ ] Keep the function deterministic and dependency-free.

**Step 3: Run privacy tests.**

```powershell
pytest python/tests/test_privacy.py
```

Expected result:

```text
All privacy guard tests pass.
```

---

## Task 4: Create Web Search Provider Boundary

**Files:**

- `python/agent_service/web_search.py`
- `python/tests/test_web_search.py`
- `python/agent_service/privacy.py`

**Step 1: Write failing provider tests.**

- [ ] Create tests for:
  - query is sanitized before request construction
  - timeout produces a structured failure
  - HTML search result parser returns title, URL, snippet
  - official domains are ranked above forum or aggregator domains when the question type calls for official sources
  - dynamic source ranking for model, software, academic, policy, and product questions

Expected first command:

```powershell
pytest python/tests/test_web_search.py
```

Expected first result:

```text
FAIL: python/agent_service/web_search.py does not exist.
```

**Step 2: Implement provider interfaces.**

- [ ] Add `SearchResult`, `SearchFailure`, and `SearchProvider` protocol.
- [ ] Add `DuckDuckGoHtmlSearchProvider` using:
  - `urllib.request`
  - `urllib.parse.urlencode`
  - `html.parser.HTMLParser`
  - fixed timeout
  - non-identifying user agent
- [ ] Add `InjectedSearchProvider` for tests.
- [ ] Add `rank_sources(question_type, results)` with official/primary-source preference.
- [ ] Add accepted/rejected source classification:
  - accepted: official docs, vendor pages, primary repo, research paper, standards body, recognized documentation
  - rejected: SEO aggregators, content farms, low-signal reposts, stale pages, unrelated forum threads

**Step 3: Ensure no local data reaches provider.**

- [ ] Provider public API accepts raw user query but internally calls `sanitize_for_web_search`.
- [ ] Tests assert the transport layer only receives sanitized text.

**Step 4: Run provider tests.**

```powershell
pytest python/tests/test_web_search.py python/tests/test_privacy.py
```

Expected result:

```text
All search provider and privacy tests pass.
```

---

## Task 5: Implement Inquiry Answering And Research Flow

**Files:**

- `python/agent_service/web_research.py`
- `python/agent_service/graph.py`
- `python/agent_service/execution.py`
- `python/agent_service/node_output.py`
- `python/tests/test_web_research.py`
- `python/tests/test_execution.py`
- `python/tests/test_graph.py`

**Step 1: Write failing research tests.**

- [ ] Test simple web inquiry:
  - classifier returns `WEB_SIMPLE`
  - search runs automatically
  - answer includes source references
  - no graph is required
- [ ] Test complex web inquiry:
  - classifier returns `WEB_COMPLEX`
  - user receives `research.choice_required`
  - quick answer choice runs direct answer path
  - research-flow choice creates a graph
- [ ] Test full research graph:
  - nodes include planning, privacy guard, query generation, parallel web search, source analysis, report synthesis, Markdown output
  - visible graph has only one web search node for all parallel internal queries
  - report artifact has the confirmed section order
  - accepted and rejected sources are included
- [ ] Test internal query retry:
  - successful query results are reused
  - failed query units retry
  - search node fails only after retry budget is exhausted

Expected first command:

```powershell
pytest python/tests/test_web_research.py
```

Expected first result:

```text
FAIL: python/agent_service/web_research.py does not exist.
```

**Step 2: Add research models and graph builder.**

- [ ] Create:
  - `ResearchMode`
  - `ResearchQuery`
  - `ResearchPlan`
  - `ResearchSourceSet`
  - `ResearchReport`
- [ ] Implement `build_research_graph(message, route_decision)` that returns `AgentGraph` with:
  - `research-intent-analysis` as `planning`
  - `research-privacy-guard` as `planning`
  - `research-query-plan` as `planning`
  - `research-parallel-search` as `fixed_tool`
  - `research-source-review` as `model`
  - `research-report-synthesis` as `model`
  - `research-markdown-output` as `output`
- [ ] Add estimates:
  - planning nodes: short CPU-only estimate
  - search node: network estimate
  - synthesis node: model/CPU estimate

**Step 3: Add direct inquiry answering path.**

- [ ] For local inquiry, call existing local model answer path.
- [ ] For simple web inquiry, call `SearchProvider`, rank results, synthesize a concise answer, and emit source metadata.
- [ ] Keep source snippets short and avoid embedding large copied text into final answers.

**Step 4: Execute research graph nodes.**

- [ ] Extend execution dispatch so research node IDs are handled explicitly.
- [ ] Store intermediate values in `NodeOutput.values`.
- [ ] Create Markdown report artifact in the task artifact area.
- [ ] Emit `artifact.created` and `research.completed`.
- [ ] Emit `node.runtime_notice` if actual duration exceeds estimate.

**Step 5: Run research tests.**

```powershell
pytest python/tests/test_web_research.py python/tests/test_execution.py python/tests/test_graph.py
```

Expected result:

```text
All selected research tests pass.
```

---

## Task 6: Implement Task Planner And Tool Gap Resolver

**Files:**

- `python/agent_service/task_planner.py`
- `python/agent_service/graph.py`
- `python/agent_service/tool_registry.py`
- `python/tests/test_task_planner.py`
- `python/tests/test_graph.py`

**Step 1: Write failing planner tests.**

- [ ] Test task classification creates a graph instead of immediate answer.
- [ ] Test planner emits visible planning nodes:
  - task analysis
  - capability analysis
  - tool selection
  - execution-order planning
- [ ] Test built-in tool selection prefers enabled integrated tools.
- [ ] Test disabled tool is not selected.
- [ ] Test missing capability checks temporary script feasibility.
- [ ] Test no tool and no safe substitute returns a user-facing missing-tool message.
- [ ] Test low-risk temporary script creates a `temporary_script` node with preview and no required approval.
- [ ] Test high-risk temporary script creates a `temporary_script` node with `requiresApproval=true`.

Expected first command:

```powershell
pytest python/tests/test_task_planner.py
```

Expected first result:

```text
FAIL: python/agent_service/task_planner.py does not exist.
```

**Step 2: Implement planner data structures.**

- [ ] Add:
  - `TaskKind`
  - `CapabilityRequirement`
  - `SelectedTool`
  - `ToolGap`
  - `TemporaryScriptPlan`
  - `TaskPlan`
- [ ] Implement `analyze_task(message, attachments)` with deterministic rules and model-assisted extension hook.
- [ ] Implement `select_tools(requirements, ToolRegistry.enabled_tools(...))`.
- [ ] Implement `resolve_tool_gaps(requirements, selected_tools)`:
  - safe file inspection or transformation can become low-risk temporary script
  - network, destructive file writes, credential handling, shell execution, broad filesystem access, or process control becomes high-risk or unsupported
  - unsupported gaps stop planning and produce a missing-tool response

**Step 3: Generate graph with visible planning nodes.**

- [ ] Implement `build_task_graph(task_plan)`:
  - planning nodes use `nodeType="planning"`
  - executable built-in tool nodes use `nodeType="fixed_tool"`
  - model reasoning nodes use `nodeType="model"`
  - temporary scripts use `nodeType="temporary_script"`
  - output nodes use `nodeType="output"`
- [ ] Add estimates and resource usage to every executable node.
- [ ] Mark planning nodes as `completed` once generated.
- [ ] Add summaries that explain what each planning node decided.

**Step 4: Integrate with `graph.py`.**

- [ ] Route `IntentKind.TASK` into `build_task_graph`.
- [ ] Preserve the existing document generation graph as one concrete task-plan output.
- [ ] Ensure graph creation events are still `node_graph.created` so existing UI remains compatible.

**Step 5: Run planner tests.**

```powershell
pytest python/tests/test_task_planner.py python/tests/test_graph.py
```

Expected result:

```text
All planner and graph routing tests pass.
```

---

## Task 7: Update Execution Engine For Planning Nodes, Permissions, And Runtime Notices

**Files:**

- `python/agent_service/execution.py`
- `python/agent_service/run_journal.py`
- `python/agent_service/schemas.py`
- `python/tests/test_execution.py`

**Step 1: Write failing execution tests.**

- [ ] Planning nodes are saved and visible but not rerun.
- [ ] Full graph run skips completed planning nodes and starts at executable nodes.
- [ ] High-risk temporary script blocks graph execution before any executable node runs.
- [ ] Low-risk temporary script can run when script execution support is available.
- [ ] Changed approved script fingerprint returns to `not_reviewed` and blocks if high risk.
- [ ] Node exceeding estimate emits `node.runtime_notice`.
- [ ] `failed_only` mode does not rerun successful internal research query results.

Expected first command:

```powershell
pytest python/tests/test_execution.py
```

Expected first result:

```text
FAIL: planning nodes are treated as executable or permission events are missing.
```

**Step 2: Filter executable nodes.**

- [ ] Add `is_executable_node(node)`:
  - `planning` returns false
  - `fixed_tool`, `model`, `temporary_script`, `output` return true when status and permissions allow
- [ ] Update `_topological_nodes()` or its caller to keep dependency validation but exclude non-executable planning nodes from actual execution.
- [ ] Ensure dependencies on planning nodes are considered satisfied if those nodes are `completed`.

**Step 3: Add permission gate.**

- [ ] Before execution starts, scan selected nodes for `scriptReview.requiresApproval`.
- [ ] If a high-risk script is unapproved, emit:
  - `node.needs_permission`
  - `task.failed` or `task.waiting_for_permission` based on existing reducer compatibility
- [ ] Do not execute any downstream node after a permission block.

**Step 4: Track estimates and notices.**

- [ ] Capture node start and finish time.
- [ ] If `actualDurationMs > estimate.durationMs`, emit `node.runtime_notice`.
- [ ] Store notice in run journal.

**Step 5: Preserve run journal compatibility.**

- [ ] Extend node records with optional `values` and `runtimeNotice`.
- [ ] Keep existing fields and filenames stable.

**Step 6: Run execution tests.**

```powershell
pytest python/tests/test_execution.py
```

Expected result:

```text
All execution tests pass.
```

---

## Task 8: Add Graph Feedback Router

**Files:**

- `python/agent_service/plan_feedback.py`
- `python/agent_service/graph.py`
- `python/agent_service/schemas.py`
- `src/features/task/useTaskEvents.ts`
- `src/app/App.tsx`
- `python/tests/test_plan_feedback.py`
- `src/features/task/useTaskEvents.test.ts`

**Step 1: Write failing feedback tests.**

- [ ] Test feedback is classified as:
  - local node modification
  - full replan
  - added constraint
  - new task
- [ ] Test local modification preserves unaffected nodes.
- [ ] Test full replan replaces graph.
- [ ] Test graph with run history asks before overwrite.
- [ ] Test changed high-risk script requires reapproval.

Expected first command:

```powershell
pytest python/tests/test_plan_feedback.py
```

Expected first result:

```text
FAIL: python/agent_service/plan_feedback.py does not exist.
```

**Step 2: Extend message request context.**

- [ ] Add optional request fields:
  - `currentGraph`
  - `hasRunHistory`
  - `artifactRefs`
  - `pendingChoice`
- [ ] In the frontend submit path, include the active graph snapshot and run-history flag when the user sends a message after a graph exists.
- [ ] Keep fields optional so existing message tests and older project files remain compatible.

**Step 3: Implement feedback router.**

- [ ] Create `classify_graph_feedback(message, current_graph, has_run_history)`.
- [ ] Add deterministic rules:
  - mentions one node or one step -> local modification
  - says direction is wrong or restart -> full replan
  - adds constraints such as source type, budget, style, or order -> constraint update
  - unrelated request -> new task
- [ ] Add model-assisted extension hook for ambiguous feedback.

**Step 4: Implement graph update behavior.**

- [ ] For local modification, update affected nodes and downstream summaries only.
- [ ] For full replan, regenerate graph from current constraints.
- [ ] For constraint update, persist constraints in planning node summary and regenerate affected selections.
- [ ] If run history or artifacts exist, emit a confirmation-choice event before overwriting.
- [ ] On confirmed overwrite, emit `graph.replanned`.

**Step 5: Run feedback tests.**

```powershell
pytest python/tests/test_plan_feedback.py
npm test -- src/features/task/useTaskEvents.test.ts
```

Expected result:

```text
All feedback routing tests pass.
```

---

## Task 9: Update Frontend Event Reduction And Canvas UI

**Files:**

- `src/app/backendEvents.ts`
- `src/app/backendEvents.test.ts`
- `src/shared/events.ts`
- `src/shared/types.ts`
- `src/features/canvas/NodeCanvas.tsx`
- `src/features/canvas/NodePopover.tsx`
- `src/features/canvas/nodeLayout.ts`
- `src/features/canvas/NodeCanvas.test.tsx`
- `src/features/canvas/NodePopover.test.tsx`
- `src/features/task/useTaskEvents.ts`

**Step 1: Write failing UI state tests.**

- [ ] Reducer handles `research.choice_required`.
- [ ] Reducer handles `research.completed` and opens or registers Markdown artifact.
- [ ] Reducer handles `node.needs_permission`.
- [ ] Reducer handles `node.runtime_notice`.
- [ ] Canvas renders planning and temporary script node labels.
- [ ] Popover shows estimates, resource usage, script preview, approval status, and runtime notice.

Expected first command:

```powershell
npm test -- src/app/backendEvents.test.ts src/features/canvas/NodeCanvas.test.tsx src/features/canvas/NodePopover.test.tsx
```

Expected first result:

```text
FAIL: new events and node types are not handled yet.
```

**Step 2: Extend reducer behavior.**

- [ ] `research.choice_required` adds a message with actions:
  - quick answer
  - generate research flow
- [ ] `research.completed` appends concise result message and registers the Markdown artifact.
- [ ] `node.needs_permission` marks node status `needs_permission` and adds an actionable message.
- [ ] `node.runtime_notice` attaches notice to the node and run history.
- [ ] `graph.replanned` replaces current graph and adds a concise message explaining what changed.

**Step 3: Extend canvas rendering.**

- [ ] Add labels:
  - `planning` -> `规划`
  - `temporary_script` -> `临时代码`
- [ ] Give planning nodes a quiet visual treatment and keep them visible.
- [ ] Give high-risk temporary script nodes a permission-state visual treatment.
- [ ] Show estimate/resource chips in compact form without causing node size jumps.

**Step 4: Extend popover.**

- [ ] For planning nodes, show the decision summary and mark as non-executable.
- [ ] For temporary scripts, show:
  - risk level
  - approval status
  - permission summary
  - code preview
  - input/output contract
- [ ] For any node, show estimate and runtime notice if present.

**Step 5: Add frontend action path for research choices and approvals.**

- [ ] Add an event action dispatcher in `useTaskEvents.ts` for:
  - research quick answer
  - research flow generation
  - approve high-risk temporary script
  - reject high-risk temporary script
- [ ] Keep sidecar request payloads typed and optional-compatible.

**Step 6: Run frontend tests.**

```powershell
npm test -- src/app/backendEvents.test.ts src/features/canvas/NodeCanvas.test.tsx src/features/canvas/NodePopover.test.tsx
```

Expected result:

```text
All selected frontend tests pass.
```

---

## Task 10: Wire Sidecar Commands For Choices And Script Approval

**Files:**

- `python/agent_service/server.py`
- `python/agent_service/graph.py`
- `python/agent_service/execution.py`
- `src-tauri/src/agent_client.rs`
- `src/features/task/useTaskEvents.ts`
- `python/tests/test_server.py`
- `src-tauri/tests/domain_tests.rs`

**Step 1: Write failing command tests.**

- [ ] Test sidecar accepts research choice request.
- [ ] Test sidecar accepts script approval request.
- [ ] Test rejecting script keeps graph blocked.
- [ ] Test approved script fingerprint is persisted into graph state.

Expected first command:

```powershell
pytest python/tests/test_server.py
```

Expected first result:

```text
FAIL: choice and approval endpoints are not available yet.
```

**Step 2: Add sidecar API handlers.**

- [ ] Add endpoints or stream actions for:
  - `research/choose`
  - `scripts/approve`
  - `scripts/reject`
- [ ] Use existing event stream patterns.
- [ ] Return updated graph snapshots after approval state changes.

**Step 3: Add Tauri and frontend callers.**

- [ ] Add typed functions in `useTaskEvents.ts`.
- [ ] If Rust bridge needs command names, add them in `src-tauri/src/agent_client.rs`.
- [ ] Keep event payloads generic enough for existing Python event forwarding.

**Step 4: Run command tests.**

```powershell
pytest python/tests/test_server.py
npm test -- src/features/task/useTaskEvents.test.ts
```

Expected result:

```text
Choice and approval command tests pass.
```

---

## Task 11: Add Full Integration Coverage

**Files:**

- `python/tests/test_agent_routing_integration.py`
- `src/app/backendEvents.test.ts`
- `src/features/task/useTaskEvents.test.ts`
- `src/features/canvas/NodeCanvas.test.tsx`

**Step 1: Add integration tests.**

- [ ] Chat message returns direct assistant response with no graph.
- [ ] Simple web inquiry returns answer with source metadata and no graph.
- [ ] Complex web inquiry first asks quick-vs-research choice.
- [ ] Research choice creates graph and Markdown report.
- [ ] Task message creates graph with planning nodes and executable nodes.
- [ ] High-risk temporary script blocks execution until approved.
- [ ] Graph feedback updates a single node and preserves unaffected nodes.
- [ ] Full replan asks for overwrite confirmation if prior run artifacts exist.

Expected first command:

```powershell
pytest python/tests/test_agent_routing_integration.py
```

Expected first result:

```text
FAIL until previous tasks are implemented.
```

**Step 2: Run integration tests after implementation tasks.**

```powershell
pytest python/tests/test_agent_routing_integration.py python/tests/test_graph.py python/tests/test_execution.py
npm test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/features/canvas/NodeCanvas.test.tsx src/features/canvas/NodePopover.test.tsx
```

Expected result:

```text
All selected Python and frontend integration tests pass.
```

---

## Task 12: Manual Verification In Development App

**Files:**

- No code files expected unless manual verification reveals a defect.

**Step 1: Start local development stack.**

```powershell
npm run dev
```

Expected result:

```text
Vite dev server starts, Tauri app opens, Python sidecar reports healthy.
```

**Step 2: Verify routing manually.**

- [ ] Send a greeting. Expected: direct response, no graph.
- [ ] Ask a stable local question. Expected: local answer, no search event.
- [ ] Ask a simple current question. Expected: automatic search answer with sources.
- [ ] Ask a complex research question. Expected: quick answer vs research flow choice.
- [ ] Choose research flow. Expected: visible graph and Markdown report preview.
- [ ] Send a task request. Expected: visible task graph with planning nodes.
- [ ] Run the task graph. Expected: planning nodes are not rerun.
- [ ] Trigger a high-risk temporary script case. Expected: graph waits for approval before execution.
- [ ] Give feedback on one graph node. Expected: affected node updates and other nodes remain stable.

**Step 3: Verify privacy behavior manually.**

- [ ] Ask a current web question containing a local path.
- [ ] Confirm logs or mocked provider show only sanitized query text.
- [ ] Confirm local paths and file contents are not sent to the search provider.

---

## Commit Plan

Commit each coherent slice separately after tests pass:

```powershell
git status --short
git add python/agent_service/schemas.py src/shared/types.ts src/shared/events.ts src-tauri/src/domain.rs python/tests/test_graph.py src-tauri/tests/domain_tests.rs
git commit -m "feat: extend agent graph schema for planning"

git add python/agent_service/intent.py python/agent_service/graph.py python/tests/test_intent.py python/tests/test_graph.py
git commit -m "feat: add agent intent routing"

git add python/agent_service/privacy.py python/tests/test_privacy.py
git commit -m "feat: add privacy guard for web search"

git add python/agent_service/web_search.py python/tests/test_web_search.py
git commit -m "feat: add privacy-safe web search provider"

git add python/agent_service/web_research.py python/agent_service/execution.py python/agent_service/node_output.py python/tests/test_web_research.py python/tests/test_execution.py
git commit -m "feat: add web research graph flow"

git add python/agent_service/task_planner.py python/agent_service/graph.py python/tests/test_task_planner.py
git commit -m "feat: add task graph planner"

git add python/agent_service/execution.py python/agent_service/run_journal.py python/tests/test_execution.py
git commit -m "feat: gate graph execution by planning and script risk"

git add python/agent_service/plan_feedback.py python/agent_service/schemas.py src/features/task/useTaskEvents.ts src/app/App.tsx python/tests/test_plan_feedback.py
git commit -m "feat: add graph feedback routing"

git add src/app/backendEvents.ts src/shared/events.ts src/shared/types.ts src/features/canvas/NodeCanvas.tsx src/features/canvas/NodePopover.tsx src/features/canvas/nodeLayout.ts src/app/backendEvents.test.ts src/features/canvas/NodeCanvas.test.tsx src/features/canvas/NodePopover.test.tsx
git commit -m "feat: render planning and research graph events"

git add python/agent_service/server.py src-tauri/src/agent_client.rs src/features/task/useTaskEvents.ts python/tests/test_server.py
git commit -m "feat: add research choice and script approval commands"
```

Before the final integration commit, run:

```powershell
pytest python/tests/test_agent_routing_integration.py python/tests/test_graph.py python/tests/test_execution.py python/tests/test_intent.py python/tests/test_privacy.py python/tests/test_web_search.py python/tests/test_web_research.py python/tests/test_task_planner.py python/tests/test_plan_feedback.py
npm test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/features/canvas/NodeCanvas.test.tsx src/features/canvas/NodePopover.test.tsx src/features/canvas/nodeLayout.test.ts
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected final verification result:

```text
All selected Python, frontend, and Rust tests pass.
```

---

## Risk Controls

- Keep web search behind `SearchProvider` so the provider can be replaced without touching planner logic.
- Keep privacy guard mandatory inside provider request construction.
- Keep planning nodes non-executable at the execution layer, not only in the UI.
- Keep script approval enforced in the backend before execution starts.
- Keep graph feedback request fields optional for compatibility with existing saved projects and frontend tests.
- Avoid adding broad new dependencies for the first version; use standard-library networking and parser boundaries with test-injected transports.
- Do not persist raw web page contents in project files; persist source metadata, short snippets, accepted/rejected decisions, and generated reports.
- Do not send full file contents, full project paths, logs, preference files, model paths, or local environment details to external search.
