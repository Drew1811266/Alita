# Agent Runtime Phase B AgentRunState Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a single internal `AgentRunState` contract for message routing, planning, streaming, and graph execution boundaries without changing Alita's public endpoint schemas or event payloads.

**Architecture:** Keep `UserMessage`, `AgentMessageRequest`, `ResearchChoiceRequest`, `RunGraphRequest`, `RunGraph`, and frontend event contracts stable. Add `AgentRunState` as the Python sidecar's internal run context, then adapt `graph.py`, `app.py`, and the execution stream boundary to build and pass that state while preserving existing helper signatures as compatibility wrappers. Phase B does not add dynamic planning, tool gateway migration, or ReAct loops; it only creates the state spine those later phases will use.

**Tech Stack:** Python 3.10+, Pydantic v2, FastAPI, LangGraph `StateGraph`, Pytest, existing Alita sidecar schemas and event tests.

---

## Scope

In scope:

- Create `python/agent_service/agent_run_state.py`.
- Add `python/tests/test_agent_run_state.py`.
- Keep `run_agent()` and `stream_agent_events()` public signatures working for existing tests and callers.
- Add internal `run_agent_from_state()` and `stream_agent_events_from_state()` orchestration helpers.
- Carry `AgentRunState` through the LangGraph `AgentState` dictionary and update it with routing metadata.
- Convert FastAPI message and research endpoints to build `AgentRunState` before calling graph orchestration.
- Convert graph-run streaming boundary to build and pass `AgentRunState` into `run_graph_events()`.
- Add `run_graph_events(..., run_state: AgentRunState | None = None)` as a backwards-compatible optional parameter.
- Validate that matching execution request/run-state pairs are accepted and mismatched pairs are rejected early.
- Preserve all public event types, event payload fields, endpoint JSON fields, and frontend behavior.

Out of scope:

- Structured LLM router.
- Planner chain.
- Unified Tool Gateway execution migration.
- ExecutionGraph compiler.
- Durable LangGraph checkpointing.
- Memory, eval harness, sandboxing, research upgrades, or frontend state refactors.
- Any public TypeScript/Rust schema changes.

## File Structure

### Create

- `python/agent_service/agent_run_state.py`
  - Internal Pydantic model for one Agent run context.
  - Factory methods for `AgentMessageRequest`, `ResearchChoiceRequest`, `RunGraphRequest`, and direct `UserMessage` callers.
  - Immutable-style `with_routing()` helper using `model_copy(update=...)`.
- `python/tests/test_agent_run_state.py`
  - Unit tests for request conversion, default values, copy isolation, routing metadata updates, and graph-run request conversion.

### Modify

- `python/agent_service/graph.py`
  - Add `AgentRunState` to `AgentState`.
  - Add state construction helpers.
  - Add `run_agent_from_state()` and `stream_agent_events_from_state()`.
  - Keep `run_agent()` and `stream_agent_events()` as compatibility wrappers.
  - Update `classify_intent()` to write routing metadata back onto `AgentRunState`.
- `python/agent_service/app.py`
  - Build `AgentRunState` in message/research endpoints and stream serializers.
  - Pass run-state into graph-run streaming.
- `python/agent_service/execution.py`
  - Add optional `run_state` parameter to `run_graph_events()`.
  - Validate that `run_state.task_id` and `run_state.run_id` match the `RunGraphRequest` before side effects.
- `python/tests/test_graph.py`
  - Add behavior-preserving tests for `AgentRunState` propagation through LangGraph and the new internal orchestration helpers.
- `python/tests/test_app.py`
  - Add endpoint-level tests that app handlers pass `AgentRunState` to orchestration helpers.
- `python/tests/test_execution.py`
  - Add graph execution boundary tests for matching and mismatched run-state.

### Read-Only Regression Targets

- `python/tests/test_agent_routing_integration.py`
- `python/tests/test_app.py`
- `python/tests/test_graph.py`
- `python/tests/test_execution.py`
- `python/tests/test_tool_gateway.py`
- `python/tests/test_model_tool_adapter.py`
- `python/tests/test_planner_v2.py`
- `src/features/task/useTaskEvents.test.ts`
- `src/app/backendEvents.test.ts`

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/app.py`
- Read: `python/agent_service/graph.py`
- Read: `python/agent_service/execution.py`
- Read: `python/agent_service/schemas.py`
- Read: `python/agent_service/goal_spec.py`
- Read: `python/tests/test_graph.py`
- Read: `python/tests/test_agent_routing_integration.py`

- [ ] **Step 1: Confirm the branch and worktree**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
?? docs/superpowers/plans/2026-05-28-agent-runtime-phase-b-agent-run-state-plan.md
```

If the Phase B plan file has already been committed or staged by another worker, accept that state and do not rewrite history.

- [ ] **Step 2: Run Python focused baseline**

Run:

```powershell
python -m pytest -q python\tests\test_app.py python\tests\test_graph.py python\tests\test_execution.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run frontend event baseline**

Run:

```powershell
npm run frontend:test -- src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 4: Run a broad verification checkpoint before editing**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

If this fails before Phase B code changes, stop and record the exact failing command. Do not start Phase B implementation on a red baseline.

---

## Task 1: AgentRunState Contract

**Files:**
- Create: `python/agent_service/agent_run_state.py`
- Create: `python/tests/test_agent_run_state.py`

- [ ] **Step 1: Write failing tests for message request conversion**

Create `python/tests/test_agent_run_state.py` with this initial content:

```python
from __future__ import annotations

from agent_service.agent_run_state import AgentRunState
from agent_service.goal_spec import GoalSpec
from agent_service.schemas import (
    AgentMessageRequest,
    Attachment,
    GraphNode,
    RunGraph,
    RunGraphRequest,
    RunMode,
    UserMessage,
)


def test_from_message_request_preserves_request_context_without_alias_leaks() -> None:
    graph = _sample_graph()
    request = AgentMessageRequest(
        task_id="task-state",
        content="Research and compare current Python packaging tools",
        attachments=[
            Attachment(
                attachment_id="doc-1",
                name="notes.docx",
                path=r"C:\Users\Drew\Desktop\notes.docx",
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
        inquiry_choice="research_flow",
        current_graph=graph,
        has_run_history=True,
        artifact_refs=["artifact-1"],
        pending_choice={"id": "confirm_overwrite", "kind": "full_replan"},
        model_session_id="model-session-1",
    )

    state = AgentRunState.from_message_request(request)

    assert state.task_id == "task-state"
    assert state.run_id is None
    assert state.message == UserMessage(
        task_id="task-state",
        content="Research and compare current Python packaging tools",
        attachments=list(request.attachments),
        model_session_id="model-session-1",
    )
    assert state.inquiry_choice == "research_flow"
    assert state.current_graph == graph
    assert state.has_run_history is True
    assert state.artifact_refs == ["artifact-1"]
    assert state.pending_choice == {"id": "confirm_overwrite", "kind": "full_replan"}
    assert state.goal_spec is None
    assert state.route_decision is None
    assert state.intent is None
    assert state.project_path is None
    assert state.run_mode is None
    assert state.disabled_tool_ids == []
    assert state.approved_permissions == []


def test_from_message_request_copies_mutable_lists() -> None:
    request = AgentMessageRequest(
        task_id="task-state-copy",
        content="hello",
        attachments=[],
        artifact_refs=["artifact-1"],
    )

    state = AgentRunState.from_message_request(request)
    state.artifact_refs.append("artifact-2")

    assert request.artifactRefs == ["artifact-1"]
    assert state.artifact_refs == ["artifact-1", "artifact-2"]


def test_from_user_message_supports_existing_graph_wrappers() -> None:
    message = UserMessage(task_id="direct-message", content="hello")
    graph = _sample_graph()

    state = AgentRunState.from_user_message(
        message,
        inquiry_choice="quick_answer",
        current_graph=graph,
        has_run_history=True,
        artifact_refs=["artifact-1"],
        pending_choice={"id": "confirm_overwrite"},
    )

    assert state.task_id == "direct-message"
    assert state.message == message
    assert state.inquiry_choice == "quick_answer"
    assert state.current_graph == graph
    assert state.has_run_history is True
    assert state.artifact_refs == ["artifact-1"]
    assert state.pending_choice == {"id": "confirm_overwrite"}
```

- [ ] **Step 2: Add failing tests for graph-run conversion and routing metadata**

Append this content to `python/tests/test_agent_run_state.py`:

```python
def test_from_run_graph_request_preserves_execution_context() -> None:
    graph = _sample_graph(metadata={"question": "Research Python packaging"})
    request = RunGraphRequest(
        task_id="task-run",
        run_id="run-1",
        project_path=r"D:\Projects\demo.alita",
        attachments=[
            Attachment(
                attachment_id="doc-1",
                name="notes.md",
                path=r"D:\Projects\notes.md",
                size_bytes=64,
                mime_type="text/markdown",
            )
        ],
        graph=graph,
        mode=RunMode(type="from_node", node_id="node-1", source_run_id="run-0"),
        disabled_tool_ids=["document.disabled"],
        approved_permissions=["network"],
        model_session_id="model-session-2",
    )

    state = AgentRunState.from_run_graph_request(request)

    assert state.task_id == "task-run"
    assert state.run_id == "run-1"
    assert state.message == UserMessage(
        task_id="task-run",
        content="Research Python packaging",
        attachments=list(request.attachments),
        model_session_id="model-session-2",
    )
    assert state.current_graph == graph
    assert state.project_path == r"D:\Projects\demo.alita"
    assert state.run_mode == request.mode
    assert state.disabled_tool_ids == ["document.disabled"]
    assert state.approved_permissions == ["network"]


def test_from_run_graph_request_uses_empty_content_when_question_metadata_is_missing() -> None:
    request = RunGraphRequest(
        task_id="task-run-empty",
        run_id="run-empty",
        project_path=r"D:\Projects\demo.alita",
        attachments=[],
        graph=_sample_graph(),
    )

    state = AgentRunState.from_run_graph_request(request)

    assert state.message.content == ""


def test_with_routing_returns_updated_copy_without_mutating_original() -> None:
    state = AgentRunState.from_user_message(
        UserMessage(task_id="task-routing", content="hello")
    )
    goal_spec = GoalSpec(
        goal="hello",
        task_type="chat",
        deliverable="chat_answer",
        success_criteria=["回答用户的问题"],
        risk_level="read_only",
        confidence=0.7,
    )

    updated = state.with_routing(
        intent="chat",
        route_decision={
            "intent": {"kind": "chat"},
            "inquiry": None,
            "reason": "conversation",
            "missing_inputs": [],
        },
        goal_spec=goal_spec,
    )

    assert state.intent is None
    assert state.route_decision is None
    assert state.goal_spec is None
    assert updated.intent == "chat"
    assert updated.route_decision == {
        "intent": {"kind": "chat"},
        "inquiry": None,
        "reason": "conversation",
        "missing_inputs": [],
    }
    assert updated.goal_spec == goal_spec


def _sample_graph(metadata: dict | None = None) -> RunGraph:
    return RunGraph(
        graphId="graph-state",
        nodes=[
            GraphNode(
                nodeId="node-1",
                nodeType="planning",
                displayName="Plan",
                status="waiting",
                summary="Plan the task.",
                createdBy="agent",
                position={"x": 0, "y": 0},
            )
        ],
        edges=[],
        metadata=metadata or {},
    )
```

- [ ] **Step 3: Run the tests and verify the import failure**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.agent_run_state'
```

- [ ] **Step 4: Create the `AgentRunState` implementation**

Create `python/agent_service/agent_run_state.py` with:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec
from agent_service.schemas import (
    AgentMessageRequest,
    RunGraph,
    RunGraphRequest,
    RunMode,
    UserMessage,
)


InquiryChoice = Literal["quick_answer", "research_flow"]


class AgentRunState(BaseModel):
    task_id: str
    message: UserMessage
    run_id: str | None = None
    goal_spec: GoalSpec | None = None
    current_graph: RunGraph | None = None
    has_run_history: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    inquiry_choice: InquiryChoice | None = None
    route_decision: dict[str, Any] | None = None
    intent: str | None = None
    project_path: str | None = None
    run_mode: RunMode | None = None
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_message_request(cls, request: AgentMessageRequest) -> "AgentRunState":
        return cls(
            task_id=request.task_id,
            message=request.to_user_message(),
            inquiry_choice=request.inquiry_choice,
            current_graph=request.currentGraph,
            has_run_history=bool(request.hasRunHistory),
            artifact_refs=list(request.artifactRefs or []),
            pending_choice=request.pendingChoice,
        )

    @classmethod
    def from_user_message(
        cls,
        message: UserMessage,
        *,
        inquiry_choice: InquiryChoice | None = None,
        current_graph: RunGraph | None = None,
        has_run_history: bool = False,
        artifact_refs: list[str] | None = None,
        pending_choice: dict[str, Any] | None = None,
    ) -> "AgentRunState":
        return cls(
            task_id=message.task_id,
            message=message,
            inquiry_choice=inquiry_choice,
            current_graph=current_graph,
            has_run_history=has_run_history,
            artifact_refs=list(artifact_refs or []),
            pending_choice=pending_choice,
        )

    @classmethod
    def from_run_graph_request(cls, request: RunGraphRequest) -> "AgentRunState":
        question = request.graph.metadata.get("question", "")
        return cls(
            task_id=request.task_id,
            run_id=request.run_id,
            message=UserMessage(
                task_id=request.task_id,
                content=str(question),
                attachments=list(request.attachments),
                model_session_id=request.model_session_id,
            ),
            current_graph=request.graph,
            project_path=request.project_path,
            run_mode=request.mode,
            disabled_tool_ids=list(request.disabled_tool_ids),
            approved_permissions=list(request.approved_permissions),
        )

    def with_routing(
        self,
        *,
        intent: str,
        route_decision: dict[str, Any],
        goal_spec: GoalSpec,
    ) -> "AgentRunState":
        return self.model_copy(
            update={
                "intent": intent,
                "route_decision": route_decision,
                "goal_spec": goal_spec,
            }
        )
```

- [ ] **Step 5: Run contract tests**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py
```

Expected:

```text
6 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/agent_run_state.py python/tests/test_agent_run_state.py
git commit -m "feat: add agent run state contract"
```

Expected: one commit containing only the new state model and tests.

---

## Task 2: Graph Orchestration Uses AgentRunState Internally

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`
- Test: `python/tests/test_agent_run_state.py`

- [ ] **Step 1: Add failing graph tests for run-state propagation**

In `python/tests/test_graph.py`, update the imports:

```python
from agent_service.agent_run_state import AgentRunState
```

Change the graph import block to include the new helpers:

```python
from agent_service.graph import (
    _classify_message,
    _node,
    build_graph,
    run_agent,
    run_agent_from_state,
    stream_agent_events,
    stream_agent_events_from_state,
)
```

Add these tests after `test_graph_state_preserves_structured_route_decision_for_inquiries`:

```python
def test_graph_state_updates_agent_run_state_with_routing_metadata() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python release",
                    url="https://www.python.org/downloads/",
                    snippet="Latest Python release.",
                )
            ]
        )
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-run-state-route",
            content="What is the latest Python release?",
        )
    )
    app = build_graph(search_provider=provider)

    result = app.invoke(
        {
            "run_state": run_state,
            "message": run_state.message,
            "events": [],
        }
    )

    updated = result["run_state"]
    assert isinstance(updated, AgentRunState)
    assert updated.task_id == "task-run-state-route"
    assert updated.intent == "web_simple_inquiry"
    assert updated.goal_spec is not None
    assert updated.goal_spec.needs_web is True
    assert updated.route_decision == {
        "intent": {"kind": "inquiry"},
        "inquiry": {"mode": "web_simple", "requires_web": True},
        "reason": "question requests current or external factual data",
        "missing_inputs": [],
    }
    assert result["intent"] == "web_simple_inquiry"


def test_build_graph_still_accepts_legacy_state_without_run_state() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python release",
                    url="https://www.python.org/downloads/",
                    snippet="Latest Python release.",
                )
            ]
        )
    )
    app = build_graph(search_provider=provider)

    result = app.invoke(
        {
            "message": UserMessage(
                task_id="task-legacy-state",
                content="What is the latest Python release?",
            ),
            "events": [],
        }
    )

    assert isinstance(result["run_state"], AgentRunState)
    assert result["run_state"].task_id == "task-legacy-state"
    assert result["intent"] == "web_simple_inquiry"
```

- [ ] **Step 2: Add failing tests for internal orchestration helpers**

Append these tests near the existing public `run_agent()` and streaming tests:

```python
def test_run_agent_from_state_matches_public_research_choice_behavior() -> None:
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="complex-web-state",
            content="Research and compare current Python packaging tools",
        )
    )

    events = run_agent_from_state(run_state)

    assert [event.type for event in events] == ["research.choice_required"]
    assert events[0].payload["taskId"] == "complex-web-state"
    assert [choice["id"] for choice in events[0].payload["choices"]] == [
        "quick_answer",
        "research_flow",
    ]


def test_stream_agent_events_from_state_matches_public_stream_behavior() -> None:
    client = FakeModelClient()
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="stream-state", content="hello")
    )

    events = list(stream_agent_events_from_state(run_state, model_client=client))

    assert [event.type for event in events] == [
        "message.started",
        "message.delta",
        "message.delta",
        "message.completed",
    ]
    assert client.calls
```

- [ ] **Step 3: Run the new graph tests and verify failures**

Run:

```powershell
python -m pytest -q python\tests\test_graph.py::test_graph_state_updates_agent_run_state_with_routing_metadata python\tests\test_graph.py::test_build_graph_still_accepts_legacy_state_without_run_state python\tests\test_graph.py::test_run_agent_from_state_matches_public_research_choice_behavior python\tests\test_graph.py::test_stream_agent_events_from_state_matches_public_stream_behavior
```

Expected:

```text
FAILED ... ImportError: cannot import name 'run_agent_from_state'
```

- [ ] **Step 4: Import `AgentRunState` in `graph.py`**

In `python/agent_service/graph.py`, add:

```python
from agent_service.agent_run_state import AgentRunState
```

Add `run_state` to `AgentState`:

```python
class AgentState(TypedDict, total=False):
    run_state: AgentRunState
    message: UserMessage
    events: list[AgentEvent]
    intent: AgentIntent
    route_decision: dict
    inquiry_choice: InquiryChoice
    current_graph: RunGraph
    has_run_history: bool
    artifact_refs: list[str]
    pending_choice: dict
    goal_spec: GoalSpec
```

- [ ] **Step 5: Add graph state conversion helpers**

Add these helpers above `classify_intent()`:

```python
def _run_state_from_agent_state(state: AgentState) -> AgentRunState:
    if "run_state" in state:
        return state["run_state"]
    return AgentRunState.from_user_message(
        state["message"],
        inquiry_choice=state.get("inquiry_choice"),
        current_graph=state.get("current_graph"),
        has_run_history=bool(state.get("has_run_history")),
        artifact_refs=state.get("artifact_refs"),
        pending_choice=state.get("pending_choice"),
    )


def _agent_state_from_run_state(run_state: AgentRunState) -> AgentState:
    return {
        "run_state": run_state,
        "message": run_state.message,
        "events": [],
        "inquiry_choice": run_state.inquiry_choice,
        "current_graph": run_state.current_graph,
        "has_run_history": run_state.has_run_history,
        "artifact_refs": list(run_state.artifact_refs),
        "pending_choice": run_state.pending_choice,
    }
```

- [ ] **Step 6: Update `classify_intent()` to persist routing metadata on run-state**

Replace the first part of `classify_intent()` with:

```python
def classify_intent(state: AgentState) -> AgentState:
    run_state = _run_state_from_agent_state(state)
    message = run_state.message
    decision = classify_route(message)
    goal_spec = parse_goal_spec(message)
    intent = _compatible_intent(
        message,
        decision,
        inquiry_choice=run_state.inquiry_choice or state.get("inquiry_choice"),
        goal_spec=goal_spec,
    )
    updated_run_state = run_state.with_routing(
        intent=intent,
        route_decision=decision.to_payload(),
        goal_spec=goal_spec,
    )
    return {
        **state,
        "run_state": updated_run_state,
        "message": message,
        "intent": intent,
        "route_decision": decision.to_payload(),
        "goal_spec": goal_spec,
    }
```

- [ ] **Step 7: Add internal run-state orchestration wrappers**

Replace the body of `run_agent()` with a compatibility wrapper and add `run_agent_from_state()` above it:

```python
def run_agent_from_state(
    run_state: AgentRunState,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
) -> list[AgentEvent]:
    if _should_handle_graph_feedback(
        run_state.message,
        run_state.current_graph,
        pending_choice=run_state.pending_choice,
    ):
        return [
            apply_graph_feedback(
                run_state.message,
                run_state.current_graph,
                has_run_history=run_state.has_run_history,
                artifact_refs=run_state.artifact_refs,
                pending_choice=run_state.pending_choice,
            )
        ]

    app = build_graph(
        model_client=model_client,
        search_provider=search_provider,
        weather_provider=weather_provider,
        inquiry_choice=run_state.inquiry_choice,
    )
    result = app.invoke(_agent_state_from_run_state(run_state))
    return result["events"]
```

Then make `run_agent()`:

```python
def run_agent(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
    current_graph: RunGraph | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict | None = None,
) -> list[AgentEvent]:
    run_state = AgentRunState.from_user_message(
        message,
        inquiry_choice=inquiry_choice,
        current_graph=current_graph,
        has_run_history=has_run_history,
        artifact_refs=artifact_refs,
        pending_choice=pending_choice,
    )
    return run_agent_from_state(
        run_state,
        model_client=model_client,
        search_provider=search_provider,
        weather_provider=weather_provider,
    )
```

- [ ] **Step 8: Add internal streaming wrapper**

Add `stream_agent_events_from_state()` above `stream_agent_events()` and move the current body of `stream_agent_events()` into it, replacing parameter references with `run_state` fields:

```python
def stream_agent_events_from_state(
    run_state: AgentRunState,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
) -> Iterator[AgentEvent]:
    message = run_state.message
    if _should_handle_graph_feedback(
        message,
        run_state.current_graph,
        pending_choice=run_state.pending_choice,
    ):
        yield apply_graph_feedback(
            message,
            run_state.current_graph,
            has_run_history=run_state.has_run_history,
            artifact_refs=run_state.artifact_refs,
            pending_choice=run_state.pending_choice,
        )
        return

    decision = classify_route(message)
    goal_spec = parse_goal_spec(message)
    intent = _compatible_intent(
        message,
        decision,
        inquiry_choice=run_state.inquiry_choice,
        goal_spec=goal_spec,
    )
    if intent == "task":
        graph_payload = _graph_payload_for_task(
            message,
            goal_spec=goal_spec,
        )
        yield from _task_planning_progress_events(message, graph_payload)
        yield AgentEvent(
            type="node_graph.created",
            payload={"graph": graph_payload},
        )
        return

    if intent not in {"chat", "local_inquiry"}:
        yield from run_agent_from_state(
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        )
        return

    client = model_client or LlamaCppModelClient()
    policy = policy_for_agent_intent(intent)
    assistant_message = _assistant_message("")
    message_id = assistant_message["messageId"]
    yield AgentEvent(
        type="message.started",
        payload={"message": assistant_message},
    )

    try:
        for delta in client.stream_chat(
            _build_model_messages(message),
            policy=policy,
        ):
            yield AgentEvent(
                type="message.delta",
                payload={"messageId": message_id, "delta": delta},
            )
    except ModelRuntimeDisabled:
        yield AgentEvent(
            type="message.delta",
            payload={
                "messageId": message_id,
                "delta": "本地模型暂未启用。请在首选项里设置默认 GGUF 模型，并确认 llama.cpp 服务已启动。",
            },
        )
    except ModelRuntimeRequestFailed as error:
        yield AgentEvent(
            type="message.delta",
            payload={
                "messageId": message_id,
                "delta": f"本地模型暂时没有返回可用结果：{error}",
            },
        )

    yield AgentEvent(
        type="message.completed",
        payload={"messageId": message_id},
    )
```

Then replace `stream_agent_events()` with:

```python
def stream_agent_events(
    message: UserMessage,
    *,
    model_client: ModelClient | None = None,
    search_provider: SearchProvider | None = None,
    weather_provider: WeatherProvider | None = None,
    inquiry_choice: InquiryChoice | None = None,
    current_graph: RunGraph | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict | None = None,
) -> Iterator[AgentEvent]:
    run_state = AgentRunState.from_user_message(
        message,
        inquiry_choice=inquiry_choice,
        current_graph=current_graph,
        has_run_history=has_run_history,
        artifact_refs=artifact_refs,
        pending_choice=pending_choice,
    )
    yield from stream_agent_events_from_state(
        run_state,
        model_client=model_client,
        search_provider=search_provider,
        weather_provider=weather_provider,
    )
```

- [ ] **Step 9: Run graph and state tests**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py python\tests\test_graph.py
```

Expected:

```text
... passed
```

- [ ] **Step 10: Run integration regressions**

Run:

```powershell
python -m pytest -q python\tests\test_agent_routing_integration.py python\tests\test_app.py
```

Expected:

```text
... passed
```

- [ ] **Step 11: Commit**

Run:

```powershell
git add python/agent_service/graph.py python/tests/test_graph.py
git commit -m "refactor: route graph orchestration through agent run state"
```

Expected: one commit containing graph orchestration changes and graph tests.

---

## Task 3: FastAPI And Execution Boundaries Use AgentRunState

**Files:**
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_app.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add failing endpoint tests for message orchestration state**

In `python/tests/test_app.py`, add imports:

```python
from agent_service.agent_run_state import AgentRunState
from agent_service.schemas import AgentEvent
```

Add this test near the existing message endpoint tests:

```python
def test_agent_message_endpoint_passes_agent_run_state_to_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AgentRunState] = []

    def fake_run_agent_from_state(
        run_state: AgentRunState,
        *,
        model_client,
    ) -> list[AgentEvent]:
        del model_client
        captured.append(run_state)
        return [AgentEvent(type="message.created", payload={"message": {"content": "ok"}})]

    monkeypatch.setattr("agent_service.app.run_agent_from_state", fake_run_agent_from_state)
    client = TestClient(app)
    graph = _temporary_script_graph()

    response = client.post(
        "/agent/message",
        json={
            "task_id": "task-state-endpoint",
            "content": "Restart, the direction is wrong.",
            "attachments": [],
            "current_graph": graph,
            "has_run_history": True,
            "artifact_refs": ["artifact-1"],
            "pending_choice": {"id": "confirm_overwrite", "kind": "full_replan"},
            "inquiry_choice": "quick_answer",
        },
    )

    assert response.status_code == 200
    assert len(captured) == 1
    run_state = captured[0]
    assert run_state.task_id == "task-state-endpoint"
    assert run_state.message.content == "Restart, the direction is wrong."
    assert run_state.inquiry_choice == "quick_answer"
    assert run_state.current_graph is not None
    assert run_state.has_run_history is True
    assert run_state.artifact_refs == ["artifact-1"]
    assert run_state.pending_choice == {"id": "confirm_overwrite", "kind": "full_replan"}
```

- [ ] **Step 2: Add failing endpoint tests for research and SSE state**

Append these tests in `python/tests/test_app.py`:

```python
def test_research_choose_endpoint_passes_agent_run_state_to_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AgentRunState] = []

    def fake_run_agent_from_state(
        run_state: AgentRunState,
        *,
        model_client,
    ) -> list[AgentEvent]:
        del model_client
        captured.append(run_state)
        return [AgentEvent(type="research.choice_required", payload={"taskId": run_state.task_id})]

    monkeypatch.setattr("agent_service.app.run_agent_from_state", fake_run_agent_from_state)
    client = TestClient(app)

    response = client.post(
        "/agent/research/choose",
        json={
            "task_id": "research-state-endpoint",
            "content": "Research and compare current Python packaging tools",
            "attachments": [],
            "inquiry_choice": "research_flow",
        },
    )

    assert response.status_code == 200
    assert captured[0].task_id == "research-state-endpoint"
    assert captured[0].inquiry_choice == "research_flow"


def test_agent_message_stream_endpoint_passes_agent_run_state_to_streamer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AgentRunState] = []

    def fake_stream_agent_events_from_state(
        run_state: AgentRunState,
        *,
        model_client,
    ):
        del model_client
        captured.append(run_state)
        yield AgentEvent(
            type="message.completed",
            payload={"messageId": f"assistant-{run_state.task_id}"},
        )

    monkeypatch.setattr(
        "agent_service.app.stream_agent_events_from_state",
        fake_stream_agent_events_from_state,
    )
    client = TestClient(app)

    response = client.post(
        "/agent/message/stream",
        json={
            "task_id": "stream-state-endpoint",
            "content": "hello",
            "attachments": [],
        },
    )

    assert response.status_code == 200
    assert "stream-state-endpoint" in response.text
    assert captured[0].task_id == "stream-state-endpoint"
```

- [ ] **Step 3: Add failing execution boundary tests**

In `python/tests/test_execution.py`, add:

```python
from agent_service.agent_run_state import AgentRunState
```

Add these tests near existing `run_graph_events()` tests:

```python
def test_run_graph_events_accepts_matching_agent_run_state(tmp_path: Path) -> None:
    request = _single_output_run_request(tmp_path)
    run_state = AgentRunState.from_run_graph_request(request)

    events = list(run_graph_events(request, run_state=run_state))

    assert events[0].type == "run.started"
    assert events[-1].type == "task.completed"


def test_run_graph_events_rejects_mismatched_agent_run_state(tmp_path: Path) -> None:
    request = _single_output_run_request(tmp_path)
    run_state = AgentRunState.from_run_graph_request(request).model_copy(
        update={"task_id": "different-task"}
    )

    events = list(run_graph_events(request, run_state=run_state))

    assert events[0].type == "task.failed"
    assert events[0].payload["taskId"] == request.task_id
    assert events[0].payload["runId"] == request.run_id
    assert events[0].payload["error"]["code"] == "run_state_mismatch"
```

Add this helper at the bottom of `python/tests/test_execution.py`:

```python
def _single_output_run_request(tmp_path: Path) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="execution-state-task",
        run_id="execution-state-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph={
            "graphId": "execution-state-graph",
            "nodes": [
                {
                    "nodeId": "task-output",
                    "nodeType": "output",
                    "displayName": "Task output",
                    "status": "waiting",
                    "inputPorts": [],
                    "outputPorts": [],
                    "dependencies": [],
                    "summary": "Return final output.",
                    "createdBy": "agent",
                    "artifactRefs": [],
                    "retryCount": 0,
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )
```

- [ ] **Step 4: Run targeted tests and verify failures**

Run:

```powershell
python -m pytest -q python\tests\test_app.py::test_agent_message_endpoint_passes_agent_run_state_to_orchestrator python\tests\test_app.py::test_research_choose_endpoint_passes_agent_run_state_to_orchestrator python\tests\test_app.py::test_agent_message_stream_endpoint_passes_agent_run_state_to_streamer python\tests\test_execution.py::test_run_graph_events_accepts_matching_agent_run_state python\tests\test_execution.py::test_run_graph_events_rejects_mismatched_agent_run_state
```

Expected:

```text
FAILED ... AttributeError: module 'agent_service.app' has no attribute 'run_agent_from_state'
FAILED ... TypeError: run_graph_events() got an unexpected keyword argument 'run_state'
```

- [ ] **Step 5: Wire FastAPI message endpoints to run-state**

In `python/agent_service/app.py`, add:

```python
from agent_service.agent_run_state import AgentRunState
```

Change the graph import to:

```python
from agent_service.graph import (
    run_agent_from_state,
    stream_agent_events_from_state,
)
```

Replace `agent_message()` body with:

```python
def agent_message(
    request: AgentMessageRequest,
    _auth: None = Depends(require_sidecar_token),
) -> list[AgentEvent]:
    model_client = _model_client_for_session(request.model_session_id)
    return run_agent_from_state(
        AgentRunState.from_message_request(request),
        model_client=model_client,
    )
```

Replace `research_choose()` body with:

```python
def research_choose(
    request: ResearchChoiceRequest,
    _auth: None = Depends(require_sidecar_token),
) -> list[AgentEvent]:
    model_client = _model_client_for_session(request.model_session_id)
    return run_agent_from_state(
        AgentRunState.from_message_request(request),
        model_client=model_client,
    )
```

- [ ] **Step 6: Wire FastAPI stream serializers to run-state**

Replace `_serialize_sse_events()` with:

```python
def _serialize_sse_events(request: AgentMessageRequest, *, model_client):
    run_state = AgentRunState.from_message_request(request)
    for event in stream_agent_events_from_state(
        run_state,
        model_client=model_client,
    ):
        yield f"data: {event.model_dump_json()}\n\n"
```

Replace `_serialize_graph_sse_events()` with:

```python
def _serialize_graph_sse_events(request: RunGraphRequest, *, model_client):
    run_state = AgentRunState.from_run_graph_request(request)
    for event in run_graph_events(
        request,
        run_state=run_state,
        model_client=model_client,
        registry=DEFAULT_RUN_REGISTRY,
    ):
        yield f"data: {event.model_dump_json()}\n\n"
```

- [ ] **Step 7: Add optional run-state boundary to execution**

In `python/agent_service/execution.py`, add:

```python
from agent_service.agent_run_state import AgentRunState
```

Update `run_graph_events()` signature:

```python
def run_graph_events(
    request: RunGraphRequest,
    *,
    run_state: AgentRunState | None = None,
    executor: NodeExecutor | None = None,
    model_client: ModelClient | None = None,
    tool_executor: ToolExecutor | None = None,
    search_provider: SearchProvider | None = None,
    source_fetcher: SourceContentFetcher | None = None,
    registry: RunRegistry | None = None,
) -> Iterator[AgentEvent]:
```

At the start of `run_graph_events()`, before `run_registry = registry or DEFAULT_RUN_REGISTRY`, add:

```python
    run_state = run_state or AgentRunState.from_run_graph_request(request)
    mismatch = _run_state_mismatch(request, run_state)
    if mismatch is not None:
        yield AgentEvent(
            type="task.failed",
            payload={
                "taskId": request.task_id,
                "runId": request.run_id,
                "error": {
                    "code": "run_state_mismatch",
                    "message": mismatch,
                },
            },
        )
        return
```

Add this helper near the other run request helper functions:

```python
def _run_state_mismatch(
    request: RunGraphRequest,
    run_state: AgentRunState,
) -> str | None:
    if run_state.task_id != request.task_id:
        return (
            "AgentRunState task_id does not match RunGraphRequest task_id: "
            f"{run_state.task_id} != {request.task_id}"
        )
    if run_state.run_id != request.run_id:
        return (
            "AgentRunState run_id does not match RunGraphRequest run_id: "
            f"{run_state.run_id} != {request.run_id}"
        )
    return None
```

- [ ] **Step 8: Run endpoint and execution tests**

Run:

```powershell
python -m pytest -q python\tests\test_app.py python\tests\test_execution.py
```

Expected:

```text
... passed
```

- [ ] **Step 9: Run routing integration tests**

Run:

```powershell
python -m pytest -q python\tests\test_agent_routing_integration.py python\tests\test_graph.py python\tests\test_agent_run_state.py
```

Expected:

```text
... passed
```

- [ ] **Step 10: Commit**

Run:

```powershell
git add python/agent_service/app.py python/agent_service/execution.py python/tests/test_app.py python/tests/test_execution.py
git commit -m "refactor: pass agent run state through sidecar boundaries"
```

Expected: one commit containing FastAPI and execution boundary changes.

---

## Task 4: Behavior Preservation And Final Regression

**Files:**
- Read: `python/agent_service/agent_run_state.py`
- Read: `python/agent_service/graph.py`
- Read: `python/agent_service/app.py`
- Read: `python/agent_service/execution.py`
- Read: `src/features/task/useTaskEvents.ts`

- [ ] **Step 1: Run focused Python regression**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py python\tests\test_app.py python\tests\test_graph.py python\tests\test_execution.py python\tests\test_agent_routing_integration.py python\tests\test_tool_gateway.py python\tests\test_model_tool_adapter.py python\tests\test_planner_v2.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run frontend event regression**

Run:

```powershell
npm run frontend:test -- src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 3: Run full MVP verification**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

- [ ] **Step 4: Confirm public event payloads did not change**

Run:

```powershell
python -m pytest -q python\tests\test_agent_routing_integration.py::test_complex_web_inquiry_first_asks_quick_vs_research_choice python\tests\test_agent_routing_integration.py::test_task_message_creates_graph_with_planning_and_executable_nodes python\tests\test_agent_routing_integration.py::test_full_replan_asks_for_overwrite_confirmation_when_artifacts_exist
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Confirm worktree cleanliness**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
```

If the branch name changes for Phase B implementation, accept the actual `codex/...` branch name, but the working tree must be clean.

- [ ] **Step 6: Final code review**

Dispatch a final code review over the Phase B commit range. The review prompt must include:

```text
Review Phase B AgentRunState implementation. Prioritize public API compatibility, event payload preservation, graph feedback behavior, stream behavior, execution run-state mismatch handling, and whether AgentRunState is useful without overbuilding later phases.
```

Expected: reviewer returns no blocking findings. Fix any critical or important finding before finishing.

---

## Acceptance Criteria

Phase B is complete when all statements are true:

- `python/agent_service/agent_run_state.py` exists and is covered by `python/tests/test_agent_run_state.py`.
- `AgentRunState.from_message_request()` preserves message, inquiry choice, graph feedback context, artifacts, pending choice, and mutable list isolation.
- `AgentRunState.from_user_message()` keeps existing `run_agent()` and `stream_agent_events()` callers compatible.
- `AgentRunState.from_run_graph_request()` preserves run id, project path, graph, attachments, mode, disabled tools, approved permissions, and model session id.
- `graph.py` carries `run_state` through LangGraph and writes routing metadata back to `run_state`.
- `run_agent()` and `stream_agent_events()` still work with their old signatures.
- `run_agent_from_state()` and `stream_agent_events_from_state()` are available for internal callers.
- `app.py` message, research choice, message stream, and graph stream paths construct `AgentRunState`.
- `execution.py` accepts optional `run_state` and rejects task/run id mismatches before side effects.
- Existing route, task graph, research choice, graph feedback, and SSE event payload tests pass unchanged.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase C

Phase C can now move internal tool execution behind `UnifiedToolGateway` using `AgentRunState` instead of adding more loose parameters. Phase C should not alter public endpoint schemas; new tool execution metadata should attach to internal state or node run records first, then be exposed only after regression tests prove frontend compatibility.
