# Replace Legacy Task Product Path Phase 4 Design

## Status

Phase 4 corrects the remaining migration gap from the original
`Deep Agent Reasoning Runtime Design`.

The previous discussion of a LangGraph execution subgraph belongs to Phase 5.
Phase 4 must first make the product path honest: user task graph creation must
not silently fall back to legacy workflow/template planning.

## Purpose

Alita's product principle is:

```text
Alita is an Agent.
Every user request passes through reasoning.
The node canvas shows the Agent's reasoned plan.
It is not a workflow template canvas.
```

Phase 1, Phase 2, and Phase 3 made the Deep Agent path capable of reasoning,
planning, checkpointing, confirming, compiling, and reaching `execution_ready`.

Phase 4 removes the remaining legacy product fallback so the user cannot receive
a graph that was produced by old template routing when the Deep Agent path did
not complete.

## Official LangGraph Sources

Phase 4 should preserve the LangGraph model already established in Phase 2 and
Phase 3:

- Graph API: https://docs.langchain.com/oss/python/langgraph/graph-api
- Persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- Interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- Streaming: https://docs.langchain.com/oss/python/langgraph/streaming
- Python reference: https://reference.langchain.com/python/langgraph/graph/

Implementation implication:

- Deep Agent graph states, interrupts, resumes, and terminal outcomes are the
  source of truth.
- The UI should react to actual events emitted by the runtime.
- A missing Deep Agent terminal state is a runtime defect or honest failure,
  not permission to synthesize a template graph.

## Baseline

Current Deep Agent modules in the worktree:

- `python/agent_service/deep_agent_runtime_graph.py`
- `python/agent_service/deep_agent_models.py`
- `python/agent_service/deep_agent_planner.py`
- `python/agent_service/deep_agent_graph_compile.py`
- `python/agent_service/agent_plan_compile.py`
- `python/agent_service/deep_agent_checkpointer.py`
- `python/agent_service/deep_agent_checkpoint_mirror.py`

Current product entry point:

- `python/agent_service/agent_runtime_engine.py`

Current issue:

```text
AgentRuntimeEngine.run_from_state()
  -> deep_runtime_runner(...)
  -> if no terminal Deep Agent event:
       _legacy_route_and_plan(...)
```

Streaming has the same shape:

```text
AgentRuntimeEngine.stream_from_state()
  -> deep_runtime_stream_runner(...)
  -> if no terminal Deep Agent event:
       stream_runner(...)
```

Manual stepping has a legacy graph path:

```text
AgentRuntimeEngine.step(stage="plan")
  -> _plan_legacy_action_graph(...)
```

## Product Path Matrix

Phase 4 introduces an explicit product path decision after Deep Agent runtime
events are emitted.

| Deep Agent outcome | Product behavior |
| --- | --- |
| `agent_plan_graph.execution_ready` | Stop. Deep Agent handled the graph-task path. |
| `agent_plan_graph.compile_failed` | Stop. Show compile failure. |
| `planning.confirmation_required` | Stop. Wait for user confirmation. |
| `planning.interrupted` with confirmation payload | Stop. Wait for resume. |
| `planning.interrupted` with clarification payload | Stop. Wait for resume. |
| `planning.clarification_required` | Stop. Ask the user for missing information. |
| `planning.cancelled` | Stop. User cancelled. |
| `planning.failed` | Stop. Fail honestly. |
| `node_graph.created` from Deep Agent | Stop. Show the Deep Agent plan graph. |
| `reasoning.completed` with `next_action=simple_answer` | Allow temporary legacy answer path, but block graph events. |
| `reasoning.completed` with `next_action=tool_action` or `bounded_tool` | Allow temporary direct action path if it does not emit a graph. |
| no terminal event and no simple/direct allowance | Emit product-path failure; do not call legacy graph planner. |

## Hard Rule

Legacy graph creation is not a product fallback.

If the temporary legacy response path emits any graph event, Phase 4 blocks it
and replaces it with a failure event:

```text
runtime.legacy_graph_blocked
task.failed(errorCode="legacy_graph_blocked")
```

This keeps simple answers working during migration without letting a task graph
quietly come from the old planner.

## Architecture

Add a small product-path classifier inside `agent_runtime_engine.py`.

Recommended shape:

```python
@dataclass(frozen=True)
class DeepAgentProductPathDecision:
    kind: Literal[
        "handled",
        "allow_legacy_response",
        "blocked",
    ]
    reason: str
```

The classifier reads actual Deep Agent events, not inferred UI state.

```python
def _deep_agent_product_path_decision(
    events: list[AgentEvent],
) -> DeepAgentProductPathDecision:
    ...
```

Then replace the old boolean:

```python
if _deep_agent_finished_without_legacy(deep_events):
    ...
else:
    _legacy_route_and_plan(...)
```

with:

```python
decision = _deep_agent_product_path_decision(deep_events)
if decision.kind == "handled":
    ...
elif decision.kind == "allow_legacy_response":
    ...
else:
    emit product-path failure
```

The allowed legacy response path must pass through a graph guard:

```python
def _guard_no_legacy_graph_events(
    events: list[AgentEvent],
    *,
    state: RuntimeState,
) -> list[AgentEvent]:
    ...
```

If the guard sees `node_graph.created`, `planning.graph_compiled`, or
`agent_plan_graph.*`, it returns a blocking event and `task.failed`.

## Manual Runtime Step Path

`AgentRuntimeEngine.step(stage="plan")` currently calls the legacy planner. Phase
4 should stop doing this by default.

Keep legacy step behavior only behind an explicit constructor flag for migration
tests:

```python
AgentRuntimeEngine(allow_legacy_task_product_path=True)
```

Default product behavior:

```text
stage="plan" -> runtime.legacy_graph_blocked + task.failed
```

This keeps old tests or migration helpers possible while making the product
default match the Agent principle.

## Events

Add one public event type:

```text
runtime.legacy_graph_blocked
```

Payload:

```json
{
  "runId": "run-1",
  "threadId": "thread-1",
  "taskId": "task-1",
  "reason": "legacy graph event emitted from response-only fallback",
  "blockedEventTypes": ["node_graph.created"]
}
```

The event is followed by:

```text
task.failed
```

with:

```json
{
  "errorCode": "legacy_graph_blocked",
  "error": "Legacy graph creation is blocked from the Agent Runtime product path."
}
```

## Non-Goals

Phase 4 does not implement:

- execution after `agent_plan_graph.execution_ready`,
- step-level result verification,
- automatic repair,
- multi-agent delegation,
- autonomous desktop control,
- new tool catalog expansion,
- deletion of legacy planner modules.

Those remain Phase 5 or later work.

## Acceptance Tests

Phase 4 is done when tests prove:

1. Graph-task requests never call legacy graph planner from the product runtime.
2. Deep Agent planning failure does not fall back to legacy graph planning.
3. A malformed or incomplete Deep Agent event stream does not fall back to legacy
   graph planning.
4. Simple-answer delegation can still emit `message.created`.
5. Simple-answer delegation is blocked if it emits `node_graph.created`.
6. `step(stage="plan")` does not call legacy planning by default.
7. Legacy planner behavior is available only through explicit migration opt-in.
8. Frontend event contracts accept and surface `runtime.legacy_graph_blocked`.

## Phase 5 Handoff

After Phase 4, the next correct phase is:

```text
Phase 5: Execute, Verify, Repair
```

Phase 5 should start from `AgentCompiledGraph` at
`agent_plan_graph.execution_ready`. It should not consume a raw legacy graph or
derive execution from a template.
