# Deep Agent Reasoning Runtime Design

## Purpose

This document defines the next main development line for Alita after `0.35.1`.

The product direction is:

```text
Alita is an Agent.
Every user request must pass through reasoning.
The node canvas is the visual execution graph of the Agent's reasoned plan.
It is not a workflow template canvas.
```

The current product has a working desktop shell, local model runtime, project files,
node graph execution, artifacts, checkpointing, memory, tool manifests, research
flows, and evaluation gates. The bottleneck is that the default task path can still
feel like a workflow generator: the graph often appears too quickly, many flows are
derived from deterministic planners or templates, and the user cannot tell whether
the local model actually performed deep planning.

The next phase must move Alita from "route to a workflow" toward "reason, plan,
verify, compile, execute, and repair".

## Core Decision

Alita has one product entry point: the Agent Runtime.

There is no user-facing workflow mode. There is no deep-task template fallback. The
system may keep legacy planner code during migration, but user task handling must
not silently fall back to template-generated graphs when Agent reasoning fails.

The new invariant is:

```text
User Message
  -> Reasoning Gate
  -> Context Build
  -> Deep Planning when an execution graph is needed
  -> Plan Review
  -> Agent Plan Graph Compile
  -> Graph Review
  -> Present Plan Graph
  -> Execute
  -> Verify Result
  -> Repair or Final
```

Simple requests still pass through the Reasoning Gate. They can use a shorter
reasoning path, but they do not bypass reasoning. Complex project and document
tasks enter Deep Planning.

## Current Runtime Reality

The current LangGraph route is concentrated in:

- `python/agent_service/graph.py`
- `python/agent_service/agent_runtime_engine.py`
- `python/agent_service/execution.py`

The current top-level graph in `graph.py` is primarily:

```text
classify_intent
  -> answer_with_model
  -> answer_with_web
  -> choose_research_mode
  -> plan_research_graph
  -> request_required_inputs
  -> plan_task_graph
  -> END
```

For task requests, the path is effectively:

```text
classify_intent -> plan_task_graph -> END
```

`AgentRuntimeEngine` wraps this route, but it still delegates core planning to the
legacy route and graph-generation path. `run_graph_events()` is a capable DAG
runner, but it is not yet the single Agent loop.

`model_policy.py` defines `DEEP_REASONING_POLICY`, and `model_client.py` can send
Qwen/llama.cpp style `chat_template_kwargs` such as `enable_thinking` and
`preserve_thinking`. However, that is not enough. The runtime must prove that deep
planning was requested, whether it was accepted by the model runtime, and whether
the resulting graph came from the plan.

## Product Principle

The node canvas shows the Agent's plan, not a predefined workflow.

Every graph node must be traceable to a plan step produced by the Agent:

```text
GraphNode
  -> sourcePlanDraftId
  -> sourcePlanStepId
  -> rationale
  -> expectedOutput
  -> verificationCriteria
  -> requiredCapabilities
```

The user should be able to inspect why a node exists, what part of the user goal it
serves, what it depends on, what it should produce, and how Alita will verify it.

The graph is therefore:

```text
Agent Plan Graph = executable visual projection of PlanDraft
```

It is not:

```text
Workflow Template = predefined flow instance
```

## No Template Fallback Rule

Deep Agent planning must not silently use templates.

Rules:

1. If deep planning does not call the model, no Agent Plan Graph is produced.
2. If the model is unavailable, the runtime returns a clear planning failure.
3. If the model output cannot be parsed into a valid `PlanDraft`, the runtime revises
   or asks for clarification, then fails honestly if still invalid.
4. If `PlanReview` rejects a plan, graph compilation does not run.
5. If `GraphReview` rejects a graph, the graph is not presented as executable.
6. Legacy template planners may exist only as migration code or test fixtures. They
   are not a product mode, not a default path, and not a fallback for Agent planning.

This is a deliberate tradeoff. Early versions may be slower and may fail more often,
but they must not pretend that a template is reasoning.

## LangGraph Runtime Shape

Add a new graph module:

```text
python/agent_service/deep_agent_runtime_graph.py
```

The first target state machine is:

```text
START
 -> reasoning_gate
 -> build_context
 -> deep_plan
 -> review_plan
 -> decide_plan_next
    -> clarify_required -> END(interrupted)
    -> revise_plan -> review_plan
    -> compile_agent_plan_graph
    -> planning_failed -> END(failed)
 -> review_graph
 -> present_plan
 -> END(waiting_for_confirmation)
```

The later execution extension is:

```text
confirmed
 -> execute_graph
 -> verify_result
 -> decide_result_next
    -> repair_plan -> execute_graph
    -> final
    -> failed
```

This graph should become the main path for task requests that need an execution
graph. Ordinary chat and direct answers can use a shorter Agent Runtime branch, but
they still pass through `reasoning_gate`.

The LangGraph node names are intentionally product meaningful. Each node writes a
structured state update and emits events. The UI reads these real state transitions;
it does not invent progress states.

## Runtime State

Introduce a state model for the new graph:

```text
DeepAgentRuntimeState
  taskId
  threadId
  runId
  userMessage
  routeDecision
  reasoningDecision
  contextBundle
  modelPolicy
  thinkingStatus
  planDraft
  planReview
  revisionCount
  compiledGraph
  graphReview
  pendingQuestion
  executionResult
  resultVerification
  repairPlan
  events
  trace
```

The durable state should be checkpointed at least after:

- `reasoning_gate`
- `deep_plan`
- `review_plan`
- `compile_agent_plan_graph`
- `present_plan`
- `execute_graph`
- `verify_result`
- `repair_plan`
- `final`

## Reasoning Gate

`reasoning_gate` is the single conceptual entry point for all requests.

It emits `ReasoningDecision`:

```text
ReasoningDecision
  taskUnderstanding
  intent
  complexity: simple | bounded_tool | graph_task
  whyThisPath
  confidence
  needsClarification
  requiredCapabilities
  nextAction: simple_answer | tool_action | clarification | deep_planning
```

For simple requests, this decision can be short. For graph tasks, it becomes the
handoff into deep planning.

The Reasoning Gate may use deterministic guards for safety and missing critical
inputs, but it must not generate a graph.

## Deep Planning

`deep_plan` must call the configured model with `DEEP_REASONING_POLICY`.

The model output must be parsed into `PlanDraft`:

```text
PlanDraft
  planDraftId
  taskUnderstanding
  successCriteria
  inputs
  assumptions
  missingInformation
  candidateStrategies
  recommendedStrategy
  steps
  requiredCapabilities
  risks
  verificationPlan
```

Each step must have:

```text
PlanStep
  stepId
  title
  objective
  rationale
  inputs
  requiredCapabilities
  expectedOutput
  verificationCriteria
  dependsOn
```

The raw model response may be stored for developer trace if privacy policy allows it,
but the UI should show structured planning summaries, not raw hidden reasoning.

## Plan Review

`review_plan` has real veto power.

It emits `PlanReview`:

```text
PlanReview
  status: approved | needs_clarification | invalid
  coverageFindings
  missingInputs
  unsupportedCapabilities
  riskFindings
  suggestedClarifyingQuestion
  revisionInstructions
```

Review checks include:

- The plan covers the user's stated goal.
- Success criteria exist and are concrete.
- Required attachments or inputs are represented.
- Each step has a purpose and expected output.
- Required capabilities map to known tools, model actions, or human input.
- The verification plan is specific enough to test final success.
- The plan is not a generic document workflow in disguise.

If the plan is invalid and `revisionCount < 1`, the graph goes to `revise_plan`.
If information is missing, the graph goes to `clarify_required`.
If invalid after the revision budget, planning fails honestly.

## Graph Compile

`compile_agent_plan_graph` converts an approved `PlanDraft` into a `RunGraph`.

The compiler may use tool manifests and node schemas to create valid executable
nodes, but it cannot choose a predefined end-to-end template.

Every compiled node must include:

```text
metadata.sourcePlanDraftId
metadata.sourcePlanStepId
metadata.rationale
metadata.expectedOutput
metadata.verificationCriteria
metadata.requiredCapabilities
```

The graph metadata must include:

```text
metadata.generatedBy = "deep_agent_runtime"
metadata.sourcePlanDraftId
metadata.planningTraceId
metadata.modelPolicy = "deep_reasoning"
```

## Graph Review

`review_graph` verifies that the graph faithfully represents the plan.

Checks include:

- Every executable node traces to a valid `PlanStep`.
- Every required `PlanStep` has at least one graph representation.
- Dependencies do not violate plan dependencies.
- Tool bindings match declared required capabilities.
- There are no extra template nodes without plan-step provenance.
- Final output nodes map to the plan's success criteria.

If graph review fails, the runtime can revise the plan or fail. It must not present
an unreviewed graph as ready.

## Thinking Status

The runtime must distinguish requested thinking from effective thinking.

Emit `ThinkingStatus`:

```text
ThinkingStatus
  requested
  modelPolicy
  requestPayloadHadThinkingParams
  enableThinkingSent
  preserveThinkingSent
  fallbackUsed: none | unsupported_request_body | empty_reasoning_response | provider_error
  effectiveMode: deep | degraded | unavailable
  rawProviderStatus
```

If llama.cpp rejects `chat_template_kwargs` and the client retries without them, the
runtime records `effectiveMode = degraded`. It must not display normal deep planning.

## Events

Add planning events:

```text
reasoning.started
reasoning.decision_created
planning.started
planning.stage_changed
planning.model_policy_resolved
planning.thinking_status
planning.draft_created
planning.review_completed
planning.revision_requested
planning.clarification_required
planning.graph_compiled
planning.graph_review_completed
planning.presented
planning.failed
```

Later execution events:

```text
execution.started
execution.completed
result.verification_completed
repair.proposed
repair.applied
agent.final
```

Events should be emitted from real graph nodes and state transitions.

## UI Behavior

The UI should not invent a fake thinking sequence. It renders actual events.

Expected visible planning states:

```text
Understanding request
Building context
Generating plan
Reviewing plan
Compiling execution graph
Reviewing execution graph
Waiting for confirmation
```

The plan panel should show:

- Task understanding
- Success criteria
- Recommended strategy
- Plan steps
- Rationale per step
- Risks and assumptions
- Missing information or clarification prompt
- Thinking status and degradation warnings in developer builds

The node canvas should show the compiled Agent Plan Graph. Node detail should expose
the plan-step provenance and verification criteria.

## Execution And Repair

Execution repair is a later phase after planning is trustworthy.

The target loop is:

```text
execute_graph
 -> collect RunResult
 -> verify_result
 -> repair_plan if recoverable
 -> continue execution or final
```

The first repair budget should be conservative:

- Default automatic repair attempts: 1
- No unbounded self-directed loops
- Every repair action writes trace and user-visible runtime notice

Repair actions can include:

- rerun failed node
- resume latest checkpoint
- add refinement node derived from failed verification
- ask user for missing input
- fail with clear diagnostic

## Implementation Phases

### Phase 1: Reasoning Gate

Route all user messages through `ReasoningDecision`.

Deliverables:

- `ReasoningDecision` model
- runtime events for reasoning
- tests proving simple and complex requests both pass through the gate
- no graph generation in the gate

### Phase 2: Deep Planning LangGraph

Build `deep_agent_runtime_graph.py`.

Deliverables:

- `DeepAgentRuntimeState`
- `PlanDraft`
- `PlanReview`
- `ThinkingStatus`
- `deep_plan`, `review_plan`, `revise_plan`, `clarify_required` graph nodes
- tests proving model calls are mandatory for graph-task planning

### Phase 3: Agent Plan Graph Compile

Compile approved plans into visible node graphs.

Deliverables:

- plan-step to graph-node compiler
- graph review
- node provenance metadata
- UI surfaces for plan-step rationale
- tests proving different `PlanDraft.steps` produce different graphs

### Phase 4: Replace Legacy Task Product Path

Move user task graph creation onto the new runtime.

Deliverables:

- no product path from user task request to legacy template graph
- legacy planner remains only behind tests or explicit migration helpers
- tests fail if legacy task planner is called from Agent Runtime graph creation

### Phase 5: Execute, Verify, Repair

Connect the new plan graph to execution and result verification.

Deliverables:

- `RunResult`
- runtime-level final verifier
- bounded repair planner
- checkpoint-aware resume path
- result quality events and trace records

## Evaluation And Tests

Add Agent Plan Graph evals.

The minimum acceptance tests are:

1. A graph-task request must call the deep planning model.
2. If the deep planning model is not called, no graph is produced.
3. Different fake `PlanDraft.steps` produce different graph structures.
4. Every graph node traces to a `sourcePlanStepId`.
5. Invalid `PlanDraft` blocks graph compilation.
6. Missing information returns clarification instead of a fake graph.
7. Model unavailable returns `deep_planning_unavailable`.
8. Thinking degradation emits `effectiveMode = degraded`.
9. Legacy task templates are not called by the Agent Runtime graph path.
10. The node canvas can display plan-step rationale and verification criteria.

Eval cases should cover:

- management summary from one document
- contract risk extraction
- multi-document comparison
- project action plan from mixed files
- unsupported request requiring clarification
- model unavailable
- invalid JSON plan
- plan revision success
- graph review rejection

## Non-Goals

This design does not introduce:

- multi-agent teams
- arbitrary desktop automation
- OS-level sandbox isolation
- unlimited autonomous loops
- user-facing workflow/template mode
- raw chain-of-thought display

## Risks

Planning quality will now depend more directly on the configured model. This is
intentional, but it means local model configuration and thinking support become
product-critical.

The new runtime can be slower than the legacy path. That is acceptable for deep
Agent behavior. The product should prefer honest latency over instant fake graphs.

Plan JSON parsing and schema repair will be a major reliability surface. The system
should use structured prompts, strict parsing, bounded revision, and clear failure
messages.

## References

- LangGraph `StateGraph`: https://reference.langchain.com/python/langgraph/graph/state/StateGraph
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
